"""
BSC RADAR V3 - SCANNER
======================

Pre-CA discovery scanner.

Pipeline:
    X / Telegram / RSS / websites
        -> normalized PreCASignal
        -> PreCARadar
        -> SQLite
        -> Telegram alert

Optional second pipeline:
    BSC mined contract deployments
        -> ERC20 check
        -> CA handoff
        -> Telegram notification

IMPORTANT:
- This scanner does not claim a project is legitimate or safe.
- Pre-CA discovery depends on the source adapters that are enabled.
- X requires a valid API token and available credits.
- Telegram discovery requires an authorized Telegram integration/source.
- Mempool monitoring is intentionally separate and disabled by default.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

import config
from bsc_radar_v3_core import (
    PreCARadar,
    PreCASignal,
    ProjectCandidate,
    format_pre_ca_alert,
    handle_signal,
    should_alert,
    get_domain,
    normalize_url,
    extract_tickers,
    utc_now,
    clean_text,
    detect_network,
)

from db import init_db, upsert_prelaunch


# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=getattr(config, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s",
)

log = logging.getLogger("bsc-radar-v3")


# ============================================================================
# GLOBAL STATE
# ============================================================================

radar = PreCARadar()
alerted_candidates = set()
init_db()

stop_event = threading.Event()

rpc_index = 0
last_scanned_block: Optional[int] = None
last_x_search_at = 0.0
telegram_webhook_registered = False

# Cache live DEX verification so broad discovery does not hammer the public API.
dex_verify_cache: Dict[str, Dict[str, Any]] = {}

http_session = requests.Session()

http_session.headers.update({
    "User-Agent": "BSC-Radar-V3/1.0",
    "Accept": "application/json,text/html,application/xhtml+xml",
})


# ============================================================================
# GENERIC HTTP
# ============================================================================

def http_get(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: Optional[int] = None,
) -> Optional[requests.Response]:
    """GET with retries and basic backoff."""
    if not url:
        return None

    timeout = timeout or config.WEBSITE_REQUEST_TIMEOUT

    for attempt in range(max(1, config.RPC_RETRIES)):
        try:
            response = http_session.get(
                url,
                headers=headers,
                params=params,
                timeout=timeout,
            )

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")

                try:
                    delay = min(
                        60,
                        max(1, int(retry_after)),
                    )
                except (TypeError, ValueError):
                    delay = config.ERROR_BACKOFF_SECONDS

                log.warning(
                    "Rate limited by %s; waiting %ss",
                    url,
                    delay,
                )

                time.sleep(delay)
                continue

            if response.status_code >= 500:
                time.sleep(config.ERROR_BACKOFF_SECONDS)
                continue

            return response

        except requests.RequestException as exc:
            if attempt == config.RPC_RETRIES - 1:
                log.warning("HTTP error: %s", exc)
                return None

            time.sleep(min(
                config.ERROR_BACKOFF_SECONDS,
                2 ** attempt,
            ))

    return None


# ============================================================================
# TELEGRAM ALERTS
# ============================================================================

def send_telegram_message(text: str) -> bool:
    if not config.TELEGRAM_ALERTS_ENABLED:
        return False

    if not config.TELEGRAM_BOT_TOKEN:
        log.warning("Telegram alerts enabled but bot token is missing.")
        return False

    if not config.TELEGRAM_CHAT_ID:
        log.warning("Telegram alerts enabled but chat ID is missing.")
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text[:4096],
        "disable_web_page_preview": True,
    }

    try:
        response = http_session.post(
            url,
            json=payload,
            timeout=config.TELEGRAM_SEND_TIMEOUT,
        )

        if response.status_code != 200:
            log.warning(
                "Telegram send failed: %s %s",
                response.status_code,
                response.text[:500],
            )
            return False

        return True

    except requests.RequestException as exc:
        log.warning("Telegram error: %s", exc)
        return False


# ============================================================================
# X / TWITTER
# ============================================================================

def search_x() -> int:
    """Search recent X posts for supported-chain pre-launch signals."""
    global last_x_search_at

    if not config.X_ENABLED:
        return 0

    if not config.X_BEARER_TOKEN:
        log.warning("X discovery enabled but X_BEARER_TOKEN is missing.")
        return 0

    now = time.time()
    interval = max(60, int(getattr(config, "X_SEARCH_INTERVAL", 300)))
    if last_x_search_at and now - last_x_search_at < interval:
        return 0
    last_x_search_at = now

    headers = {"Authorization": f"Bearer {config.X_BEARER_TOKEN}"}
    processed = 0

    for query in config.X_SEARCH_QUERIES:
        response = http_get(
            config.X_RECENT_SEARCH_ENDPOINT,
            headers=headers,
            params={
                "query": query,
                "max_results": config.X_MAX_RESULTS,
                "tweet.fields": (
                    "created_at,author_id,public_metrics,entities,lang,"
                    "conversation_id"
                ),
                "expansions": "author_id",
                "user.fields": "username,name,public_metrics,verified",
            },
            timeout=20,
        )

        if response is None:
            continue

        if response.status_code == 402:
            log.warning(
                "X API returned 402 credits depleted. X discovery will be skipped."
            )
            return processed

        if response.status_code != 200:
            log.warning(
                "X API returned %s: %s",
                response.status_code,
                response.text[:500],
            )
            continue

        try:
            data = response.json()
        except ValueError:
            continue

        users = {
            str(user.get("id")): user
            for user in data.get("includes", {}).get("users", [])
        }

        for tweet in data.get("data", []):
            if process_x_post(tweet, users.get(str(tweet.get("author_id")), {})):
                processed += 1

    log.info("X discovery processed=%s queries=%s", processed, len(config.X_SEARCH_QUERIES))
    return processed


def process_x_post(
    tweet: Dict[str, Any],
    author: Dict[str, Any],
) -> Optional[ProjectCandidate]:
    text = tweet.get("text", "")
    metrics = tweet.get("public_metrics") or {}
    author_metrics = author.get("public_metrics") or {}

    # Pre-CA means we should not promote posts that publish a contract address.
    # Catch both labelled CAs and bare 0x addresses.
    if contains_explicit_contract_address(text):
        return None

    # Strong post-launch language is also excluded even when the CA is not
    # repeated in the post.
    if contains_post_launch_language(text):
        return None

    urls = extract_urls(text)
    website = ""
    telegram = ""
    x_handle = ""

    for url in urls:
        host = get_domain(url)
        if host in {"t.me", "telegram.me"}:
            telegram = url
        elif host in {"x.com", "twitter.com"}:
            parts = urlparse(url).path.strip("/").split("/")
            if parts:
                x_handle = parts[0]
        elif not website and host:
            website = url

    tickers = extract_tickers(text)
    hashtags = [
        item.get("tag", "")
        for item in (tweet.get("entities") or {}).get("hashtags", [])
        if item.get("tag")
    ]

    signal = PreCASignal(
        source_type="x",
        source_family="x",
        source_name=f"X:{author.get('username', 'unknown')}",
        text=text,
        url=f"https://x.com/i/web/status/{tweet.get('id')}" if tweet.get("id") else "",
        website_url=website,
        project_name=hashtags[0] if hashtags else "",
        ticker=tickers[0] if tickers else "",
        network=detect_network(text),
        raw={
            "public_metrics": metrics,
            "author_metrics": author_metrics,
            "author": author.get("username", ""),
            "followers": author_metrics.get("followers_count", 0),
            "username": author.get("username", ""),
        },
    )
    return handle_candidate_signal(signal)


# ============================================================================
# TELEGRAM SOURCE DISCOVERY (WEBHOOK)
# ============================================================================

def _telegram_source_allowed(chat: Dict[str, Any]) -> bool:
    chat_id = str(chat.get("id", ""))
    username = str(chat.get("username", "")).lstrip("@").lower()

    allowed_usernames = {
        str(x).lstrip("@").lower()
        for x in getattr(config, "TELEGRAM_SOURCE_CHANNELS", [])
        if str(x).strip()
    }
    allowed_ids = {
        str(x).strip()
        for x in getattr(config, "TELEGRAM_SOURCE_CHAT_IDS", [])
        if str(x).strip()
    }

    return bool(
        (username and username in allowed_usernames)
        or (chat_id and chat_id in allowed_ids)
    )


def _telegram_secret() -> str:
    token = config.TELEGRAM_BOT_TOKEN or ""
    return hashlib.sha256(("bsc-radar-telegram:" + token).encode()).hexdigest()[:32]


def register_telegram_webhook() -> bool:
    """Register the Render webhook with Telegram; never uses getUpdates."""
    global telegram_webhook_registered

    if telegram_webhook_registered:
        return True
    if not getattr(config, "TELEGRAM_DISCOVERY_ENABLED", False):
        return False
    if not getattr(config, "TELEGRAM_WEBHOOK_ENABLED", False):
        return False
    if not config.TELEGRAM_BOT_TOKEN:
        log.warning("Telegram webhook discovery enabled but bot token is missing.")
        return False
    if not getattr(config, "TELEGRAM_SOURCE_CHANNELS", []) and not getattr(config, "TELEGRAM_SOURCE_CHAT_IDS", []):
        log.warning("Telegram discovery enabled but no source channels/chat IDs are configured.")
        return False

    base_url = (getattr(config, "RENDER_EXTERNAL_URL", "") or "").rstrip("/")
    if not base_url:
        import os
        base_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    if not base_url:
        log.warning("Telegram webhook cannot register: RENDER_EXTERNAL_URL is unavailable.")
        return False

    webhook_url = base_url + "/telegram/webhook"
    api_url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/setWebhook"
    payload = {
        "url": webhook_url,
        "secret_token": _telegram_secret(),
        "allowed_updates": ["channel_post", "edited_channel_post", "message", "edited_message"],
        "drop_pending_updates": False,
    }

    try:
        response = http_session.post(api_url, json=payload, timeout=15)
        if response.status_code != 200 or not response.json().get("ok"):
            log.warning("Telegram webhook registration failed: %s %s", response.status_code, response.text[:500])
            return False
        telegram_webhook_registered = True
        log.info("Telegram source webhook registered | sources=%s", len(getattr(config, "TELEGRAM_SOURCE_CHANNELS", [])) + len(getattr(config, "TELEGRAM_SOURCE_CHAT_IDS", [])))
        return True
    except (requests.RequestException, ValueError) as exc:
        log.warning("Telegram webhook registration error: %s", exc)
        return False


def handle_telegram_update(update: Dict[str, Any]) -> int:
    """Process one authorized Telegram channel/group update."""
    if not getattr(config, "TELEGRAM_DISCOVERY_ENABLED", False):
        return 0

    message = (
        update.get("channel_post")
        or update.get("edited_channel_post")
        or update.get("message")
        or update.get("edited_message")
        or {}
    )
    chat = message.get("chat") or {}

    if not _telegram_source_allowed(chat):
        return 0

    text = str(message.get("text") or message.get("caption") or "").strip()
    if not text:
        return 0

    # Reject explicit published CAs and obvious post-launch announcements.
    if contains_explicit_contract_address(text) or contains_post_launch_language(text):
        return 0

    username = str(chat.get("username") or "").lstrip("@")
    source_name = f"TG:@{username}" if username else f"TG:{chat.get('id', 'unknown')}"
    message_id = message.get("message_id", "")
    chat_id = chat.get("id", "")

    signal = PreCASignal(
        source_type="telegram",
        source_family="telegram",
        source_name=source_name,
        text=text,
        url=(
            f"https://t.me/{username}/{message_id}"
            if username and message_id else ""
        ),
        network=detect_network(text),
        observed_at=utc_now(),
        raw={
            "chat_id": chat_id,
            "chat_title": chat.get("title", ""),
            "username": username,
            "message_id": message_id,
        },
    )

    candidate = handle_candidate_signal(signal)
    return 1 if candidate else 0


# ============================================================================
# RSS / PUBLIC FEEDS
# ============================================================================

def search_rss_feeds() -> int:
    if not config.RSS_ENABLED:
        return 0

    processed = 0
    feeds_ok = 0
    feeds_failed = 0
    articles = 0
    candidates = 0

    for feed_url in config.RSS_FEEDS:
        response = http_get(
            feed_url,
            headers={"Accept": "application/rss+xml,application/atom+xml,application/xml,text/xml"},
            timeout=20,
        )
        if response is None or response.status_code != 200:
            feeds_failed += 1
            log.warning("RSS unavailable: %s", feed_url)
            continue

        feeds_ok += 1

        try:
            body = response.content[:config.WEBSITE_MAX_BYTES]
            xml_text = body.decode(response.encoding or "utf-8", errors="ignore")
        except Exception:
            continue

        entries = parse_feed_entries(xml_text)
        articles += len(entries)

        feed_context = rss_bsc_context(feed_url)

        for entry in entries:
            raw_text = f"{entry.get('title', '')}\n{entry.get('description', '')}"

            # BNB/BSC-specific feeds provide trusted network context even when
            # an individual headline omits the chain name. Still require a
            # concrete pre-launch signal so ordinary crypto news is rejected.
            entry_text = raw_text
            if feed_context and rss_has_prelaunch_intent(raw_text):
                entry_text = f"{feed_context}\n{raw_text}"
            elif feed_context:
                continue

            signal = PreCASignal(
                source_type="rss",
                source_name=get_domain(feed_url) or feed_url,
                text=entry_text,
                url=entry.get("link", feed_url),
                launch_text=entry.get("title", ""),
                observed_at=entry.get("published", "") or utc_now(),
                raw={**entry, "feed_context": feed_context},
            )
            candidate = handle_candidate_signal(signal)
            if candidate:
                processed += 1
                candidates += 1

            # Inspect explicit project links and a small number of outbound
            # links from qualifying article pages. This adds a second evidence
            # channel without indiscriminate web crawling.
            links = []
            for link in extract_urls(entry_text)[:3]:
                if is_probable_project_website(link):
                    links.append(link)

            article_link = entry.get("link", "")
            if (
                config.WEBSITE_DISCOVERY_ENABLED
                and article_link
                and rss_has_prelaunch_intent(raw_text)
            ):
                links.extend(discover_project_links_from_article(article_link))

            seen_hosts = set()
            for link in links:
                link = normalize_url(link)
                host = get_domain(link)
                if not host or host in seen_hosts:
                    continue
                seen_hosts.add(host)
                website_candidate = inspect_website(
                    link,
                    context_text=entry_text,
                )
                if website_candidate:
                    processed += 1
                if len(seen_hosts) >= getattr(
                    config, "MAX_PROJECT_LINKS_PER_ARTICLE", 2
                ):
                    break

    log.info(
        "RSS diagnostics | feeds_ok=%s feeds_failed=%s articles=%s qualifying=%s",
        feeds_ok,
        feeds_failed,
        articles,
        candidates,
    )

    return processed



def rss_bsc_context(feed_url: str) -> str:
    """Return trusted supported-chain context encoded by a feed URL."""
    value = (feed_url or "").lower()
    if any(token in value for token in (
        "rssfeeds-bnb",
        "bnb+chain",
        "bnb%20chain",
        "bsc+crypto",
        "bsc%20crypto",
    )):
        return "BSC / BNB Chain"
    return ""


def rss_has_prelaunch_intent(text: str) -> bool:
    """Keep RSS discovery focused on projects before/around launch."""
    value = (text or "").lower()
    indicators = (
        "launching soon", "launch soon", "coming soon",
        "upcoming launch", "set to launch", "will launch",
        "plans to launch", "presale", "pre-sale", "pre sale",
        "fair launch", "fairlaunch", "stealth launch",
        "contract soon", "ca soon", "ca coming",
        "contract coming", "contract address soon",
        "liquidity soon", "liquidity coming",
    )
    return any(item in value for item in indicators)

def parse_feed_entries(xml_text: str) -> List[Dict[str, str]]:
    """
    Lightweight RSS/Atom parser using the standard library.
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    entries = []

    # RSS <item>
    for item in root.findall(".//item"):
        title = get_xml_text(item, "title")
        description = get_xml_text(item, "description")
        link = get_xml_text(item, "link")
        published = (
            get_xml_text(item, "pubDate")
            or get_xml_text(item, "published")
        )

        entries.append({
            "title": clean_xml(title),
            "description": clean_xml(description),
            "link": clean_xml(link),
            "published": normalize_date(published),
        })

    # Atom <entry>
    ns_entries = root.findall(
        ".//{http://www.w3.org/2005/Atom}entry"
    )

    for item in ns_entries:
        title = get_xml_text(
            item,
            "{http://www.w3.org/2005/Atom}title",
        )

        summary = (
            get_xml_text(
                item,
                "{http://www.w3.org/2005/Atom}summary",
            )
            or get_xml_text(
                item,
                "{http://www.w3.org/2005/Atom}content",
            )
        )

        link = ""

        for child in item.findall(
            "{http://www.w3.org/2005/Atom}link"
        ):
            href = child.attrib.get("href", "")

            if href:
                link = href
                break

        published = (
            get_xml_text(
                item,
                "{http://www.w3.org/2005/Atom}published",
            )
            or get_xml_text(
                item,
                "{http://www.w3.org/2005/Atom}updated",
            )
        )

        entries.append({
            "title": clean_xml(title),
            "description": clean_xml(summary),
            "link": normalize_url(link),
            "published": normalize_date(published),
        })

    return entries


def get_xml_text(element: Any, tag: str) -> str:
    child = element.find(tag)

    if child is None:
        return ""

    return "".join(
        child.itertext()
    )


def clean_xml(value: str) -> str:
    value = unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_date(value: str) -> str:
    value = clean_xml(value)

    if not value:
        return ""

    try:
        dt = parsedate_to_datetime(value)
        return dt.isoformat()
    except (TypeError, ValueError, OverflowError):
        return value


# ============================================================================
# LIVE MARKET / PRE-LAUNCH VERIFICATION
# ============================================================================

POST_LAUNCH_PHRASES = (
    "trading now",
    "trading live",
    "now trading",
    "live trading",
    "token is live",
    "token live",
    "coin is live",
    "coin live",
    "launched today",
    "launched now",
    "already launched",
    "launch complete",
    "listed on",
    "listing is live",
    "liquidity added",
    "liquidity is live",
    "pair is live",
    "buy now",
    "chart is live",
    "dexscreener",
)


def contains_explicit_contract_address(text: str) -> bool:
    """Reject any post containing a 40-hex-character EVM contract address."""
    return bool(re.search(r"\b0x[a-fA-F0-9]{40}\b", text or ""))


def contains_post_launch_language(text: str) -> bool:
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in POST_LAUNCH_PHRASES)


def _normalise_host(value: str) -> str:
    try:
        host = get_domain(value) if value else ""
        return host.lower().lstrip("www.")
    except Exception:
        return ""


def _pair_socials(pair: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    info = pair.get("info") or {}
    for item in info.get("websites") or []:
        if item.get("url"):
            values.append(str(item["url"]))
    for item in info.get("socials") or []:
        if item.get("url"):
            values.append(str(item["url"]))
    return values


def _pair_matches_candidate(candidate: ProjectCandidate, pair: Dict[str, Any]) -> bool:
    expected = {"BSC": "bsc", "BASE": "base", "SOLANA": "solana"}.get(candidate.network)
    if not expected or str(pair.get("chainId", "")).lower() != expected:
        return False

    base = pair.get("baseToken") or {}
    pair_name = clean_text(base.get("name", ""))
    pair_symbol = clean_text(base.get("symbol", "")).upper()
    cand_name = clean_text(candidate.project_name)
    cand_symbol = clean_text(candidate.ticker).upper().lstrip("$")

    if not pair.get("pairAddress") or not base.get("address"):
        return False

    cand_site = _normalise_host(candidate.website)
    pair_hosts = {_normalise_host(x) for x in _pair_socials(pair)}
    if cand_site and cand_site in pair_hosts:
        return True

    author = clean_text(candidate.author).lower().lstrip("@")
    for url in _pair_socials(pair):
        if "x.com/" in url.lower() or "twitter.com/" in url.lower():
            handle = url.rstrip("/").split("/")[-1].lower().lstrip("@")
            if author and handle == author:
                return True
            if candidate.x_handle and handle == candidate.x_handle.lower().lstrip("@"):
                return True

    name_l = pair_name.lower()
    cand_name_l = cand_name.lower()
    symbol_match = bool(cand_symbol and pair_symbol == cand_symbol)
    name_match = bool(
        cand_name_l
        and cand_name_l != cand_symbol.lower()
        and (cand_name_l == name_l or cand_name_l in name_l or name_l in cand_name_l)
    )
    if symbol_match and name_match:
        return True
    if cand_name_l and cand_name_l != cand_symbol.lower() and cand_name_l == name_l:
        return True
    if symbol_match and cand_name_l == cand_symbol.lower():
        liquidity = ((pair.get("liquidity") or {}).get("usd") or 0) or 0
        volume = ((pair.get("volume") or {}).get("h24") or 0) or 0
        try:
            return float(liquidity) > 0 or float(volume) > 0
        except (TypeError, ValueError):
            return False
    return False


def verify_live_market(candidate: ProjectCandidate) -> Dict[str, Any]:
    """Check DexScreener for an already-trading market on the candidate chain."""
    if not getattr(config, "DEXSCREENER_VERIFY_ENABLED", True):
        return {"deployed": False, "reason": "disabled"}
    key = f"{candidate.network}:{(candidate.ticker or candidate.project_name or '').strip().lower()}"
    if not key or key.endswith(":"):
        return {"deployed": False, "reason": "no_identity"}
    now = time.time()
    cached = dex_verify_cache.get(key)
    interval = max(60, int(getattr(config, "DEXSCREENER_VERIFY_INTERVAL", 600)))
    if cached and now - cached.get("checked_at", 0) < interval:
        return cached
    queries: List[str] = []
    ticker = clean_text(candidate.ticker).lstrip("$")
    name = clean_text(candidate.project_name)
    if ticker and ticker.lower() not in {"bsc", "bnb", "base", "solana", "chain", "token", "coin"}:
        queries.append(ticker)
    if name and "lead" not in name.lower() and name not in queries:
        queries.append(name)
    result: Dict[str, Any] = {"deployed": False, "checked_at": now}
    for query in queries[:2]:
        try:
            response = http_get(getattr(config, "DEXSCREENER_API_URL", "https://api.dexscreener.com/latest/dex/search"), params={"q": query}, timeout=getattr(config, "DEXSCREENER_REQUEST_TIMEOUT", 10))
            if response is None or response.status_code != 200:
                continue
            pairs = response.json().get("pairs") or []
            matches = [p for p in pairs if _pair_matches_candidate(candidate, p)]
            if not matches:
                continue
            matches.sort(key=lambda p: (float(((p.get("liquidity") or {}).get("usd") or 0) or 0), float(((p.get("volume") or {}).get("h24") or 0) or 0)), reverse=True)
            pair = matches[0]
            result = {"deployed": True, "checked_at": now, "contract_address": (pair.get("baseToken") or {}).get("address", ""), "pair_address": pair.get("pairAddress", ""), "pair_url": pair.get("url", ""), "liquidity_usd": ((pair.get("liquidity") or {}).get("usd") or 0), "volume_24h": ((pair.get("volume") or {}).get("h24") or 0)}
            break
        except Exception as exc:
            log.debug("DexScreener verification failed for %s/%s: %s", candidate.network, query, exc)
    dex_verify_cache[key] = result
    return result


def verify_live_bsc_market(candidate: ProjectCandidate) -> Dict[str, Any]:
    """Backward-compatible alias for the generalized market verifier."""
    return verify_live_market(candidate)

def handle_candidate_signal(
    signal: PreCASignal,
) -> Optional[ProjectCandidate]:
    candidate = handle_signal(signal)
    if candidate is None:
        return None

    # Live-market gate: a broad discovery lead is useful only while it is
    # still pre-launch. If a matching BSC pair is already trading, mark the
    # candidate as deployed and do not keep it in the pre-launch table.
    verification = verify_live_market(candidate)
    if verification.get("deployed"):
        candidate.contract_address = verification.get("contract_address", "")
        candidate.raw["live_market"] = verification
        log.info(
            "Pre-CA rejected as already trading | project=%s symbol=%s ca=%s",
            candidate.project_name,
            candidate.ticker,
            candidate.contract_address or "unknown",
        )
        # Persist the deployed status so the dashboard can hide it on the
        # next render, while preventing any Telegram pre-launch alert.
        try:
            upsert_prelaunch({
                "name": candidate.project_name,
                "symbol": f"{candidate.network}:{candidate.ticker or candidate.project_name}",
                "website": candidate.website,
                "x_url": candidate.x_handle,
                "telegram_url": candidate.telegram_url,
                "score": candidate.score,
                "stage": "DEPLOYED",
                "source": candidate.source,
                "signal_count": candidate.signal_count,
                "contract_address": candidate.contract_address,
                "network": candidate.network,
                "source_types": ",".join(candidate.source_types or []),
                "confidence": candidate.confidence or candidate.score,
            })
        except Exception:
            log.exception("Failed to persist deployed candidate status")
        return None

    try:
        upsert_prelaunch({
            "name": candidate.project_name,
            "symbol": f"{candidate.network}:{candidate.ticker or candidate.project_name}",
            "website": candidate.website,
            "x_url": candidate.x_handle,
            "telegram_url": candidate.telegram_url,
            "score": candidate.score,
            "stage": candidate.stage,
            "source": candidate.source,
            "signal_count": candidate.signal_count,
            "contract_address": "",
            "network": candidate.network,
            "source_types": ",".join(candidate.source_types or []),
            "confidence": candidate.confidence or candidate.score,
        })
    except Exception:
        log.exception("Failed to persist pre-CA candidate")

    if should_alert(candidate):
        key = (
            candidate.ticker
            or candidate.website
            or candidate.project_name
        ).lower()
        if key not in alerted_candidates:
            alerted_candidates.add(key)
            send_telegram_message(format_pre_ca_alert(candidate))

    return candidate


def extract_urls(text: str) -> List[str]:
    return re.findall(r'https?://[^\s<>()\[\]\"\']+', text or '')


def is_probable_project_website(url: str) -> bool:
    host = get_domain(url)
    if not host:
        return False
    blocked = {
        "news.google.com", "x.com", "twitter.com", "t.me",
        "telegram.me", "youtube.com", "youtu.be",
        "facebook.com", "instagram.com", "linkedin.com",
        "google.com", "google-analytics.com", "googletagmanager.com",
        "googlesyndication.com", "doubleclick.net", "gstatic.com",
        "googleapis.com", "googleusercontent.com",
    }
    blocked_suffixes = (
        ".googleusercontent.com",
        ".googleapis.com",
        ".gstatic.com",
        ".google-analytics.com",
        ".googletagmanager.com",
        ".googlesyndication.com",
        ".doubleclick.net",
    )
    return host not in blocked and not host.endswith(blocked_suffixes)


# ============================================================================
# WEBSITE DISCOVERY
# ============================================================================

def discover_project_links_from_article(article_url: str) -> List[str]:
    """Extract a small set of likely project sites from a news article."""
    response = http_get(
        article_url,
        headers={"Accept": "text/html,application/xhtml+xml"},
        timeout=config.WEBSITE_REQUEST_TIMEOUT,
    )
    if response is None or response.status_code >= 400:
        return []

    try:
        html = response.content[:config.WEBSITE_MAX_BYTES].decode(
            response.encoding or "utf-8", errors="ignore"
        )
    except Exception:
        return []

    article_host = get_domain(article_url)
    found = []
    seen = set()

    # Capture absolute URLs from href attributes and plain page text.
    raw_links = re.findall(
        r"https?://[^\s\"'<>]+",
        html,
        flags=re.IGNORECASE,
    )

    for raw in raw_links:
        url = normalize_url(raw.rstrip(".,!?);]}>"))
        host = get_domain(url)
        if not host or host == article_host:
            continue
        if not is_probable_project_website(url):
            continue
        if host in seen:
            continue
        seen.add(host)
        found.append(url)
        if len(found) >= getattr(
            config, "MAX_PROJECT_LINKS_PER_ARTICLE", 2
        ):
            break

    return found


def extract_html_title(html: str) -> str:
    """Extract a concise HTML <title> for website evidence."""
    if not html:
        return ""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    title = unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    return title[:300]

def inspect_website(
    url: str,
    context_text: str = "",
) -> Optional[ProjectCandidate]:
    if not config.WEBSITE_DISCOVERY_ENABLED:
        return None

    url = normalize_url(url)

    if not url:
        return None

    response = http_get(
        url,
        headers={
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
        },
        timeout=config.WEBSITE_REQUEST_TIMEOUT,
    )

    if response is None or response.status_code >= 400:
        return None

    content = response.content[:config.WEBSITE_MAX_BYTES]

    try:
        html = content.decode(
            response.encoding or "utf-8",
            errors="ignore",
        )
    except Exception:
        return None

    text = html_to_text(html)

    combined_text = " ".join(
        part for part in (context_text, text) if part
    )

    # A project website reached through an RSS article is derived from that
    # RSS evidence and must not count as an independent source family.
    source_family = "rss" if context_text else "website"

    signal = PreCASignal(
        source_type="website",
        source_family=source_family,
        source_name=get_domain(url) or "Website",
        text=combined_text[:config.MAX_TEXT_LENGTH],
        url=url,
        website_url=url,
        raw={
            "title": extract_html_title(html),
            "source_url": url,
            "project_link_discovered": bool(context_text),
            "source_family": source_family,
        },
    )

    return handle_candidate_signal(signal)


def html_to_text(html: str) -> str:
    html = re.sub(
        r"<(script|style|noscript)[^>]*>.*?</\1>",
        " ",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    html = re.sub(
        r"<[^>]+>",
        " ",
        html,
    )

    return re.sub(
        r"\s+",
        " ",

               html,
           ).strip()

# ============================================================
# SCAN CYCLE
# ============================================================

def scan_once() -> Dict[str, int]:
    """
    Run one complete pre-CA discovery cycle.
    """

    stats = {
        "x": 0,
        "rss": 0,
        "websites": 0,
    }

    register_telegram_webhook()

    log.info("Starting BSC Radar V3 scan cycle")

    # --------------------------------------------------------
    # X / TWITTER
    # --------------------------------------------------------
    try:
        stats["x"] = search_x()
    except Exception:
        log.exception("X discovery failed")

    # --------------------------------------------------------
    # RSS / PUBLIC FEEDS
    # --------------------------------------------------------
    try:
        stats["rss"] = search_rss_feeds()
    except Exception:
        log.exception("RSS discovery failed")

    # --------------------------------------------------------
    # EXPLICIT WEBSITE SEEDS
    # --------------------------------------------------------
    if getattr(config, "WEBSITE_SEEDS", None):
        for seed in config.WEBSITE_SEEDS:
            try:
                if inspect_website(seed):
                    stats["websites"] += 1
            except Exception:
                log.exception("Website discovery failed for %s", seed)

    log.info(
        "Scan cycle complete | X=%s RSS=%s Websites=%s",
        stats["x"],
        stats["rss"],
        stats["websites"],
    )

    return stats


# ============================================================
# MAIN LOOP
# ============================================================

def run() -> None:
    """
    Continuously run the pre-CA intelligence scanner.
    """

    log.info("==============================================")
    log.info("BSC RADAR V3 STARTING")
    log.info("Pre-CA intelligence mode enabled")
    log.info("Broad discovery mode: %s", getattr(config, "BROAD_DISCOVERY_MODE", True))
    log.info("Live DEX verification: %s", getattr(config, "DEXSCREENER_VERIFY_ENABLED", True))
    log.info("X discovery enabled: %s", getattr(config, "X_ENABLED", False))
    log.info("Telegram webhook discovery: %s", getattr(config, "TELEGRAM_WEBHOOK_ENABLED", False))
    log.info("Telegram sources configured: %s", len(getattr(config, "TELEGRAM_SOURCE_CHANNELS", [])) + len(getattr(config, "TELEGRAM_SOURCE_CHAT_IDS", [])))
    log.info("RSS feeds configured: %s", len(getattr(config, "RSS_FEEDS", [])))
    log.info("Website seeds configured: %s", len(getattr(config, "WEBSITE_SEEDS", [])))
    log.info("==============================================")

    while not stop_event.is_set():
        try:
            scan_once()

        except Exception:
            log.exception("Unexpected error in scan cycle")

        interval = max(
            30,
            int(getattr(config, "SCAN_INTERVAL_SECONDS", 60))
        )

        log.info(
            "Next scan in %s seconds",
            interval
        )

        stop_event.wait(interval)

    log.info("BSC Radar V3 stopped")


def main() -> None:
    """
    Application entry point.
    """
    try:
        run()
    except KeyboardInterrupt:
        log.info("Shutdown requested")
    finally:
        stop_event.set()


if __name__ == "__main__":
    main()
