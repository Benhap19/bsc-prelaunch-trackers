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
    """
    Search recent X posts for BSC pre-launch signals.

    X is disabled by default until the API credentials/credits are available.
    """
    if not config.X_ENABLED:
        return 0

    if not config.X_BEARER_TOKEN:
        log.warning("X discovery enabled but X_BEARER_TOKEN is missing.")
        return 0

    headers = {
        "Authorization": f"Bearer {config.X_BEARER_TOKEN}",
    }

    processed = 0

    for query in config.X_SEARCH_QUERIES:
        response = http_get(
            config.X_RECENT_SEARCH_ENDPOINT,
            headers=headers,
            params={
                "query": query,
                "max_results": config.X_MAX_RESULTS,
                "tweet.fields": (
                    "created_at,author_id,public_metrics,"
                    "entities,lang,conversation_id"
                ),
                "expansions": "author_id",
                "user.fields": (
                    "username,name,public_metrics,verified"
                ),
            },
            timeout=20,
        )

        if response is None:
            continue

        if response.status_code == 402:
            log.warning(
                "X API returned 402 credits depleted. "
                "X discovery will be skipped."
            )
            continue

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
            process_x_post(
                tweet,
                users.get(str(tweet.get("author_id")), {}),
            )
            processed += 1

    return processed


def process_x_post(
    tweet: Dict[str, Any],
    author: Dict[str, Any],
) -> Optional[ProjectCandidate]:
    text = tweet.get("text", "")
    metrics = tweet.get("public_metrics") or {}
    author_metrics = author.get("public_metrics") or {}

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
        source_name="X",
        text=text,
        url=f"https://x.com/i/web/status/{tweet.get('id')}" if tweet.get("id") else "",
        website_url=website,
        project_name=hashtags[0] if hashtags else "",
        ticker=tickers[0] if tickers else "",
        network="BSC",
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
    """Return trusted network context encoded by a BSC/BNB-focused feed URL."""
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


def handle_candidate_signal(
    signal: PreCASignal,
) -> Optional[ProjectCandidate]:
    candidate = handle_signal(signal)
    if candidate is None:
        return None

    try:
        upsert_prelaunch({
            "name": candidate.project_name,
            "symbol": candidate.ticker or candidate.project_name,
            "website": candidate.website,
            "x_url": candidate.x_handle,
            "telegram_url": candidate.telegram_url,
            "score": candidate.score,
            "stage": candidate.stage,
            "source": candidate.source,
            "signal_count": candidate.signal_count,
            "contract_address": candidate.contract_address,
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
    }
    return host not in blocked


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

    signal = PreCASignal(
        source_type="website",
        source_name=get_domain(url) or "Website",
        text=combined_text[:config.MAX_TEXT_LENGTH],
        url=url,
        website_url=url,
        raw={
            "title": extract_html_title(html),
            "source_url": url,
            "project_link_discovered": bool(context_text),
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
