"""
BSC RADAR V3 - CORE INTELLIGENCE ENGINE
=======================================

Pre-CA project discovery and signal intelligence.

Purpose:
    Detect potential BSC projects BEFORE a contract address exists.

Signal sources:
    - X / Twitter
    - Telegram
    - RSS / Atom feeds
    - Project websites

This module:
    - Normalizes discovery signals
    - Extracts project names
    - Extracts possible tickers
    - Detects BSC / BNB Chain intent
    - Detects launch / presale intent
    - Scores pre-CA signals
    - Groups related signals
    - Creates project candidates
    - Prevents weak/noisy signals from becoming alerts
    - Formats Telegram alerts

IMPORTANT:
This system does NOT claim that a project is legitimate,
safe, or guaranteed to launch.

A high score means:
    "This signal contains characteristics commonly associated
     with an upcoming BSC project."

It does NOT mean:
    "This project is safe to buy."
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


# ============================================================
# OPTIONAL CONFIG
# ============================================================

try:
    import config
except Exception:
    config = None


# ============================================================
# CONSTANTS
# ============================================================

DEFAULT_MIN_SCORE = 45
DEFAULT_ALERT_SCORE = 60

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


# ============================================================
# KEYWORD GROUPS
# ============================================================

BSC_KEYWORDS = [
    "bsc",
    "bnb chain",
    "bnbchain",
    "binance smart chain",
    "bnb smart chain",
    "binance chain",
]

LAUNCH_KEYWORDS = [
    "launch",
    "launching",
    "launch soon",
    "launching soon",
    "coming soon",
    "presale",
    "pre-sale",
    "pre sale",
    "fair launch",
    "fairlaunch",
    "stealth launch",
    "stealthlaunch",
    "contract soon",
    "ca soon",
    "ca coming",
    "contract coming",
    "contract address soon",
    "contract address coming",
    "liquidity soon",
    "liquidity coming",
    "listing soon",
    "listing coming",
]

STRONG_PRE_CA_KEYWORDS = [
    "contract soon",
    "ca soon",
    "ca coming",
    "contract coming",
    "contract address soon",
    "contract address coming",
    "stealth launch",
    "stealthlaunch",
    "launching soon",
    "launch soon",
]

PRESALE_KEYWORDS = [
    "presale",
    "pre-sale",
    "pre sale",
    "presale live",
    "presale soon",
    "private sale",
    "public sale",
]

LIQUIDITY_KEYWORDS = [
    "liquidity",
    "lp",
    "liquidity soon",
    "liquidity coming",
    "add liquidity",
    "liquidity locked",
]

SOCIAL_KEYWORDS = [
    "telegram",
    "t.me",
    "discord",
    "twitter",
    "x.com",
    "website",
    "community",
]


# ============================================================
# DATACLASSES
# ============================================================

@dataclass
class PreCASignal:
    """
    A single piece of evidence suggesting that a project
    may be preparing for a BSC launch.
    """

    source_type: str
    source_name: str
    text: str

    url: str = ""
    website_url: str = ""

    launch_text: str = ""

    observed_at: str = ""

    raw: Dict[str, Any] = field(default_factory=dict)

    score: int = 0
    project_name: str = ""
    ticker: str = ""

    network: str = "BSC"

    signal_id: str = ""

    def __post_init__(self) -> None:
        if not self.observed_at:
            self.observed_at = utc_now()

        if not self.launch_text:
            self.launch_text = self.text

        if not self.signal_id:
            self.signal_id = make_signal_id(
                self.source_type,
                self.source_name,
                self.url,
                self.text,
            )


@dataclass
class ProjectCandidate:
    """
    Normalized pre-CA project candidate.

    This object deliberately does not require a contract address.
    """

    project_name: str

    ticker: str = ""

    network: str = "BSC"

    website: str = ""
    telegram_url: str = ""
    x_handle: str = ""

    engagement: int = 0
    followers: int = 0

    author: str = ""
    author_followers: int = 0

    score: int = 0

    stage: str = "EARLY"

    signal_count: int = 1

    first_seen: str = ""
    last_seen: str = ""

    source: str = ""

    contract_address: str = ""

    raw: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.first_seen:
            self.first_seen = utc_now()

        if not self.last_seen:
            self.last_seen = self.first_seen


# ============================================================
# TIME HELPERS
# ============================================================

def utc_now() -> str:
    """Return the current UTC time in ISO format."""

    return datetime.now(timezone.utc).isoformat()


# ============================================================
# TEXT HELPERS
# ============================================================

def clean_text(value: Any) -> str:
    """
    Normalize arbitrary text into a compact string.
    """

    if value is None:
        return ""

    text = str(value)

    text = text.replace("\x00", " ")

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def lower_text(value: Any) -> str:
    return clean_text(value).lower()


def contains_any(text: str, keywords: List[str]) -> bool:
    """
    Check whether any keyword exists in text.
    """

    text = lower_text(text)

    return any(
        keyword.lower() in text
        for keyword in keywords
    )


def count_matches(text: str, keywords: List[str]) -> int:
    """
    Count unique keyword matches.
    """

    text = lower_text(text)

    return sum(
        1
        for keyword in keywords
        if keyword.lower() in text
    )


# ============================================================
# URL HELPERS
# ============================================================

def get_domain(url: str) -> str:
    """
    Return a normalized hostname.
    """

    url = clean_text(url)

    if not url:
        return ""

    try:
        parsed = urlparse(url)

        host = parsed.netloc.lower()

        if host.startswith("www."):
            host = host[4:]

        return host

    except Exception:
        return ""


def normalize_url(url: str) -> str:
    """
    Normalize a URL while avoiding aggressive transformations.
    """

    url = clean_text(url)

    if not url:
        return ""

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed = urlparse(url)

        scheme = parsed.scheme.lower()
        host = parsed.netloc.lower()

        path = parsed.path or ""

        return f"{scheme}://{host}{path}"

    except Exception:
        return url


def is_telegram_url(url: str) -> bool:
    host = get_domain(url)

    return host in {
        "t.me",
        "telegram.me",
        "telegram.dog",
    }


def is_x_url(url: str) -> bool:
    host = get_domain(url)

    return host in {
        "x.com",
        "twitter.com",
    }


# ============================================================
# TICKER EXTRACTION
# ============================================================

def extract_tickers(text: str) -> List[str]:
    """
    Extract possible crypto tickers.

    Examples:
        $DOGE
        $PEPE
        $VELLY

    Returns:
        Unique uppercase tickers.
    """

    text = clean_text(text)

    found = re.findall(
        r"\$([A-Za-z][A-Za-z0-9]{1,14})\b",
        text,
    )

    results: List[str] = []

    seen = set()

    for ticker in found:
        ticker = ticker.upper()

        if ticker in seen:
            continue

        seen.add(ticker)

        results.append(ticker)

    return results


def extract_first_ticker(text: str) -> str:
    tickers = extract_tickers(text)

    if not tickers:
        return ""

    return tickers[0]


# ============================================================
# HASHTAG EXTRACTION
# ============================================================

def extract_hashtags(text: str) -> List[str]:
    """
    Extract hashtags from text.
    """

    text = clean_text(text)

    found = re.findall(
        r"#([A-Za-z0-9_]{2,50})",
        text,
    )

    results = []

    seen = set()

    for tag in found:

        tag = tag.strip()

        if not tag:
            continue

        key = tag.lower()

        if key in seen:
            continue

        seen.add(key)

        results.append(tag)

    return results


# ============================================================
# PROJECT NAME EXTRACTION
# ============================================================

def clean_project_name(name: str) -> str:
    """
    Clean a possible project name.
    """

    name = clean_text(name)

    name = re.sub(
        r"^[#@$]+",
        "",
        name,
    )

    name = re.sub(
        r"\s+",
        " ",
        name,
    )

    return name.strip(" -_|:;,.")


def extract_project_name(
    text: str,
    ticker: str = "",
) -> str:
    """
    Try to identify a project name from a signal.

    Priority:
        1. Explicit phrases
        2. Hashtags
        3. Ticker
        4. First meaningful line
    """

    text = clean_text(text)

    if not text:
        return ""

    # --------------------------------------------------------
    # Explicit project-name patterns
    # --------------------------------------------------------

    patterns = [
        r"(?:project|token|coin)\s*(?:name)?\s*[:\-]\s*([A-Za-z0-9][A-Za-z0-9 _.-]{1,60})",
        r"(?:introducing|meet|welcome)\s+([A-Za-z0-9][A-Za-z0-9 _.-]{1,60})",
        r"(?:our project is|we are building)\s+([A-Za-z0-9][A-Za-z0-9 _.-]{1,60})",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:

            candidate = clean_project_name(
                match.group(1)
            )

            if candidate:
                return candidate[:80]

    # --------------------------------------------------------
    # Hashtag fallback
    # --------------------------------------------------------

    hashtags = extract_hashtags(text)

    if hashtags:

        tag = hashtags[0]

        if len(tag) >= 3:

            return clean_project_name(tag)[:80]

    # --------------------------------------------------------
    # Ticker fallback
    # --------------------------------------------------------

    if ticker:

        return ticker.replace(
            "$",
            "",
        ).strip()

    # --------------------------------------------------------
    # First meaningful line
    # --------------------------------------------------------

    lines = [
        clean_text(line)
        for line in text.splitlines()
        if clean_text(line)
    ]

    if lines:

        first = lines[0]

        first = re.sub(
            r"^(breaking|announcement|update|new)\s*[:\-]?\s*",
            "",
            first,
            flags=re.IGNORECASE,
        )

        first = clean_project_name(first)

        if len(first) >= 3:

            return first[:80]

    return ""


# ============================================================
# NETWORK DETECTION
# ============================================================

def detect_bsc(text: str) -> bool:
    """
    Detect explicit BSC / BNB Chain references.
    """

    return contains_any(
        text,
        BSC_KEYWORDS,
    )


def detect_network(text: str) -> str:
    """
    Return the most likely network.

    This radar is focused on BSC, so unknown signals
    are not automatically treated as BSC.
    """

    if detect_bsc(text):
        return "BSC"

    return ""


# ============================================================
# PRE-CA INTENT DETECTION
# ============================================================

def detect_launch_intent(text: str) -> bool:
    return contains_any(
        text,
        LAUNCH_KEYWORDS,
    )


def detect_strong_pre_ca_intent(text: str) -> bool:
    return contains_any(
        text,
        STRONG_PRE_CA_KEYWORDS,
    )


def detect_presale(text: str) -> bool:
    return contains_any(
        text,
        PRESALE_KEYWORDS,
    )


def detect_liquidity_intent(text: str) -> bool:
    return contains_any(
        text,
        LIQUIDITY_KEYWORDS,
    )


# ============================================================
# SIGNAL SCORING
# ============================================================

def score_pre_ca_signal(signal: PreCASignal) -> int:
    """
    Score a discovery signal from 0-100.

    Higher score:
        Stronger evidence that an upcoming BSC project exists.

    This is NOT an investment score.
    """

    text = lower_text(signal.text)

    score = 0

    # --------------------------------------------------------
    # BSC / BNB Chain
    # --------------------------------------------------------

    if contains_any(text, BSC_KEYWORDS):
        score += 25

    # --------------------------------------------------------
    # Launch intent
    # --------------------------------------------------------

    if "launch" in text or "launching" in text:
        score += 20

    # --------------------------------------------------------
    # Presale
    # --------------------------------------------------------

    if contains_any(text, PRESALE_KEYWORDS):
        score += 15

    # --------------------------------------------------------
    # Fair launch
    # --------------------------------------------------------

    if (
        "fair launch" in text
        or "fairlaunch" in text
    ):
        score += 15

    # --------------------------------------------------------
    # Contract / CA coming
    # --------------------------------------------------------

    if contains_any(
        text,
        STRONG_PRE_CA_KEYWORDS,
    ):
        score += 25

    # --------------------------------------------------------
    # Liquidity
    # --------------------------------------------------------

    if contains_any(
        text,
        LIQUIDITY_KEYWORDS,
    ):
        score += 5

    # --------------------------------------------------------
    # Ticker
    # --------------------------------------------------------

    if signal.ticker:
        score += 10

    # --------------------------------------------------------
    # Website
    # --------------------------------------------------------

    if signal.website_url:
        score += 10

    # --------------------------------------------------------
    # Telegram
    # --------------------------------------------------------

    if (
        signal.url
        and is_telegram_url(signal.url)
    ):
        score += 5

    # --------------------------------------------------------
    # X source
    # --------------------------------------------------------

    if signal.source_type.lower() in {
        "x",
        "twitter",
    }:
        score += 5

    # --------------------------------------------------------
    # Multiple launch indicators
    # --------------------------------------------------------

    indicator_count = count_matches(
        text,
        LAUNCH_KEYWORDS,
    )

    if indicator_count >= 3:
        score += 5

    if indicator_count >= 5:
        score += 5

    # --------------------------------------------------------
    # Cap
    # --------------------------------------------------------

    return max(
        0,
        min(
            score,
            100,
        ),
    )


# ============================================================
# STAGE CLASSIFICATION
# ============================================================

def classify_stage(score: int) -> str:
    """
    Convert a pre-CA score into a radar stage.
    """

    if score >= 80:
        return "🔥 HOT"

    if score >= 60:
        return "🟡 WATCH"

    if score >= 45:
        return "🔵 EARLY"

    return "⚪ WEAK"


# ============================================================
# SIGNAL VALIDATION
# ============================================================

def is_valid_signal(signal: PreCASignal) -> bool:
    """
    Reject obviously unusable signals.
    """

    if not signal:
        return False

    if not clean_text(signal.text):
        return False

    return True


# ============================================================
# SIGNAL ID
# ============================================================

def make_signal_id(
    source_type: str,
    source_name: str,
    url: str,
    text: str,
) -> str:
    """
    Create a deterministic ID for duplicate detection.
    """

    raw = "|".join(
        [
            clean_text(source_type).lower(),
            clean_text(source_name).lower(),
            normalize_url(url),
            clean_text(text).lower(),
        ]
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:32]


# ============================================================
# CANDIDATE IDENTITY
# ============================================================

def candidate_key(
    project_name: str,
    ticker: str = "",
    website: str = "",
) -> str:
    """
    Create a stable identity key for a project.

    Preference:
        ticker + website
        ticker
        project name
    """

    ticker = clean_text(ticker).lower()

    website = get_domain(
        website
    ).lower()

    project_name = clean_text(
        project_name
    ).lower()

    if ticker and website:
        value = f"{ticker}|{website}"

    elif ticker:
        value = ticker

    else:
        value = project_name

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()[:24]


# ============================================================
# EXTRACT SOCIAL LINKS
# ============================================================

def extract_social_links(
    text: str,
) -> Dict[str, str]:
    """
    Extract common X / Telegram / website links.
    """

    text = clean_text(text)

    urls = re.findall(
        r"https?://[^\s<>\"]+",
        text,
        flags=re.IGNORECASE,
    )

    result = {
        "website": "",
        "telegram": "",
        "x": "",
    }

    for raw_url in urls:

        url = raw_url.rstrip(
            ".,!?);]}>"
        )

        host = get_domain(url)

        if not host:
            continue

        if is_telegram_url(url):

            if not result["telegram"]:
                result["telegram"] = url

        elif is_x_url(url):

            if not result["x"]:
                result["x"] = url

        elif host not in {
            "t.co",
            "bit.ly",
            "tinyurl.com",
        }:

            if not result["website"]:
                result["website"] = url

    return result


# ============================================================
# X HANDLE EXTRACTION
# ============================================================

def extract_x_handle(
    text: str,
) -> str:
    """
    Extract a possible X/Twitter handle.
    """

    text = clean_text(text)

    patterns = [
        r"(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,30})",
        r"@([A-Za-z0-9_]{2,30})",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:

            handle = match.group(1)

            if handle.lower() in {
                "here",
                "everyone",
                "channel",
                "telegram",
            }:
                continue

            return "@" + handle

    return ""


# ============================================================
# ENGAGEMENT HELPERS
# ============================================================

def safe_int(value: Any) -> int:
    """
    Safely convert a value to int.
    """

    try:

        if value is None:
            return 0

        return int(
            float(
                str(value).replace(",", "")
            )
        )

    except Exception:

        return 0


def calculate_engagement(
    metrics: Optional[Dict[str, Any]],
) -> int:
    """
    Calculate a simple engagement value.

    Supported fields:
        like_count
        reply_count
        retweet_count
        quote_count
    """

    metrics = metrics or {}

    return (
        safe_int(
            metrics.get("like_count")
        )
        +
        safe_int(
            metrics.get("reply_count")
        )
        +
        safe_int(
            metrics.get("retweet_count")
        )
        +
        safe_int(
            metrics.get("quote_count")
        )
    )


# ============================================================
# SIGNAL -> CANDIDATE
# ============================================================

def signal_to_candidate(
    signal: PreCASignal,
) -> Optional[ProjectCandidate]:
    """
    Convert a normalized signal into a project candidate.
    """

    if not is_valid_signal(signal):
        return None

    text = clean_text(signal.text)

    # --------------------------------------------------------
    # Ticker
    # --------------------------------------------------------

    ticker = (
        signal.ticker
        or extract_first_ticker(text)
    )

    # --------------------------------------------------------
    # Project name
    # --------------------------------------------------------

    project_name = (
        signal.project_name
        or extract_project_name(
            text,
            ticker,
        )
    )

    if not project_name:

        project_name = (
            "Unknown BSC Project"
        )

    # --------------------------------------------------------
    # Social links
    # --------------------------------------------------------

    links = extract_social_links(
        text
    )

    website = (
        signal.website_url
        or links.get("website", "")
    )

    telegram_url = (
        links.get("telegram", "")
    )

    x_handle = extract_x_handle(
        text
    )

    # --------------------------------------------------------
    # Metrics from raw source
    # --------------------------------------------------------

    raw = signal.raw or {}

    metrics = (
        raw.get("public_metrics")
        or raw.get("metrics")
        or {}
    )

    author_metrics = (
        raw.get("author_metrics")
        or {}
    )

    engagement = calculate_engagement(
        metrics
    )

    followers = safe_int(
        raw.get("followers")
    )

    author_followers = safe_int(
        raw.get("author_followers")
        or author_metrics.get(
            "followers_count"
        )
    )

    # --------------------------------------------------------
    # Score
    # --------------------------------------------------------

    score = signal.score

    if score <= 0:

        score = score_pre_ca_signal(
            signal
        )

    # --------------------------------------------------------
    # Stage
    # --------------------------------------------------------

    stage = classify_stage(
        score
    )

    # --------------------------------------------------------
    # Candidate
    # --------------------------------------------------------

    candidate = ProjectCandidate(
        project_name=project_name[:100],
        ticker=ticker[:20],
        network=(
            signal.network
            or "BSC"
        ),
        website=website,
        telegram_url=telegram_url,
        x_handle=x_handle,
        engagement=engagement,
        followers=followers,
        author=clean_text(
            raw.get("author")
            or raw.get("username")
            or ""
        ),
        author_followers=author_followers,
        score=score,
        stage=stage,
        signal_count=1,
        first_seen=signal.observed_at,
        last_seen=signal.observed_at,
        source=signal.source_name,
        contract_address="",
        raw={
            "signal": signal.raw,
            "signal_id": signal.signal_id,
            "source_type": signal.source_type,
            "source_name": signal.source_name,
            "url": signal.url,
            "text": text,
        },
    )

    return candidate


# ============================================================
# PROJECT MERGING
# ============================================================

def merge_candidates(
    existing: ProjectCandidate,
    incoming: ProjectCandidate,
) -> ProjectCandidate:
    """
    Merge two observations that appear to belong to
    the same project.

    The highest score wins.
    """

    if not existing:
        return incoming

    if not incoming:
        return existing

    existing.score = max(
        existing.score,
        incoming.score,
    )

    existing.stage = classify_stage(
        existing.score
    )

    existing.signal_count += (
        incoming.signal_count
    )

    existing.last_seen = max(
        existing.last_seen,
        incoming.last_seen,
    )

    # Prefer known values.

    if not existing.ticker:
        existing.ticker = incoming.ticker

    if not existing.website:
        existing.website = incoming.website

    if not existing.telegram_url:
        existing.telegram_url = (
            incoming.telegram_url
        )

    if not existing.x_handle:
        existing.x_handle = (
            incoming.x_handle
        )

    if not existing.author:
        existing.author = incoming.author

    if incoming.engagement > existing.engagement:
        existing.engagement = (
            incoming.engagement
        )

    if incoming.followers > existing.followers:
        existing.followers = (
            incoming.followers
        )

    if (
        incoming.author_followers
        > existing.author_followers
    ):
        existing.author_followers = (
            incoming.author_followers
        )

    if incoming.raw:

        existing.raw.setdefault(
            "signals",
            [],
        )

        existing.raw["signals"].append(
            incoming.raw
        )

    return existing


# ============================================================
# IN-MEMORY RADAR
# ============================================================

class PreCARadar:
    """
    Lightweight in-memory pre-CA radar.

    This class intentionally does not depend on SQLite.
    The scanner can persist candidates through db.py.
    """

    def __init__(
        self,
        min_score: Optional[int] = None,
    ) -> None:

        if min_score is None:

            if config is not None:

                min_score = getattr(
                    config,
                    "PRE_CA_MIN_SCORE",
                    DEFAULT_MIN_SCORE,
                )

            else:

                min_score = DEFAULT_MIN_SCORE

        self.min_score = int(
            min_score
        )

        self.signals: Dict[
            str,
            PreCASignal,
        ] = {}

        self.projects: Dict[
            str,
            ProjectCandidate,
        ] = {}

    # --------------------------------------------------------
    # Add signal
    # --------------------------------------------------------

    def add_signal(
        self,
        signal: PreCASignal,
    ) -> Optional[ProjectCandidate]:
        """
        Process and store one signal.
        """

        if not is_valid_signal(signal):
            return None

        # ----------------------------------------------------
        # Network check
        # ----------------------------------------------------

        if not signal.network:

            signal.network = detect_network(
                signal.text
            )

        if signal.network != "BSC":

            return None

        # ----------------------------------------------------
        # Project information
        # ----------------------------------------------------

        if not signal.ticker:

            signal.ticker = extract_first_ticker(
                signal.text
            )

        if not signal.project_name:

            signal.project_name = (
                extract_project_name(
                    signal.text,
                    signal.ticker,
                )
            )

        # ----------------------------------------------------
        # Score
        # ----------------------------------------------------

        signal.score = score_pre_ca_signal(
            signal
        )

        # ----------------------------------------------------
        # Weak signal filter
        # ----------------------------------------------------

        if signal.score < self.min_score:

            return None

        # ----------------------------------------------------
        # Duplicate signal
        # ----------------------------------------------------

        self.signals[
            signal.signal_id
        ] = signal

        # ----------------------------------------------------
        # Candidate
        # ----------------------------------------------------

        candidate = signal_to_candidate(
            signal
        )

        if candidate is None:

            return None

        key = candidate_key(
            candidate.project_name,
            candidate.ticker,
            candidate.website,
        )

        existing = self.projects.get(
            key
        )

        if existing:

            candidate = merge_candidates(
                existing,
                candidate,
            )

        self.projects[
            key
        ] = candidate

        return candidate

    # --------------------------------------------------------
    # Process raw signal
    # --------------------------------------------------------

    def process(
        self,
        signal: PreCASignal,
    ) -> Optional[ProjectCandidate]:

        return self.add_signal(
            signal
        )

    # --------------------------------------------------------
    # Get projects
    # --------------------------------------------------------

    def get_projects(
        self,
    ) -> List[ProjectCandidate]:

        return sorted(
            self.projects.values(),
            key=lambda project: (
                project.score,
                project.signal_count,
                project.engagement,
            ),
            reverse=True,
        )

    # --------------------------------------------------------
    # Get hot projects
    # --------------------------------------------------------

    def get_hot_projects(
        self,
    ) -> List[ProjectCandidate]:

        return [
            project
            for project in self.get_projects()
            if project.score >= 70
        ]

    # --------------------------------------------------------
    # Get statistics
    # --------------------------------------------------------

    def stats(self) -> Dict[str, int]:

        return {
            "signals": len(
                self.signals
            ),
            "projects": len(
                self.projects
            ),
            "hot": len(
                self.get_hot_projects()
            ),
        }


# ============================================================
# GLOBAL RADAR INSTANCE
# ============================================================

_default_radar = PreCARadar()


# ============================================================
# PUBLIC SIGNAL HANDLER
# ============================================================

def handle_signal(
    signal: PreCASignal,
) -> Optional[ProjectCandidate]:
    """
    Main entry point used by scanner.py.

    Example:

        signal = PreCASignal(
            source_type="x",
            source_name="X",
            text="New BSC project launching soon $ABC",
            url="https://x.com/example",
        )

        candidate = handle_signal(signal)
    """

    candidate = _default_radar.process(
        signal
    )

    if candidate is None:
        return None

    return candidate


# ============================================================
# ALERT DECISION
# ============================================================

def should_alert(
    candidate: Optional[ProjectCandidate],
) -> bool:
    """
    Decide whether a candidate is strong enough for
    a Telegram alert.
    """

    if candidate is None:
        return False

    threshold = DEFAULT_ALERT_SCORE

    if config is not None:

        threshold = getattr(
            config,
            "PRE_CA_ALERT_SCORE",
            DEFAULT_ALERT_SCORE,
        )

    return (
        candidate.score
        >= int(threshold)
    )


# ============================================================
# FORMAT TELEGRAM ALERT
# ============================================================

def format_pre_ca_alert(
    candidate: ProjectCandidate,
) -> str:
    """
    Format a candidate into a Telegram-friendly alert.
    """

    stage = candidate.stage

    project_name = (
        candidate.project_name
        or "Unknown BSC Project"
    )

    ticker = (
        candidate.ticker
        or "N/A"
    )

    source = (
        candidate.source
        or "Unknown"
    )

    lines = [
        "🚨 BSC PRE-CA SIGNAL",
        "",
        f"🔥 Project: {project_name}",
        f"💎 Ticker: ${ticker}",
        f"⛓ Network: {candidate.network}",
        f"📊 Score: {candidate.score}/100",
        f"🎯 Stage: {stage}",
        "",
        "⚡ STATUS",
        "Contract Address: NOT DEPLOYED",
        "This is a pre-CA discovery signal.",
    ]

    if candidate.signal_count > 1:

        lines.extend(
            [
                "",
                f"📡 Signals: {candidate.signal_count}",
            ]
        )

    if candidate.engagement > 0:

        lines.append(
            f"💬 Engagement: {candidate.engagement:,}"
        )

    if candidate.followers > 0:

        lines.append(
            f"👥 Followers: {candidate.followers:,}"
        )

    if candidate.website:

        lines.extend(
            [
                "",
                f"🌐 Website: {candidate.website}",
            ]
        )

    if candidate.telegram_url:

        lines.append(
            f"📢 Telegram: {candidate.telegram_url}"
        )

    if candidate.x_handle:

        lines.append(
            f"🐦 X: {candidate.x_handle}"
        )

    lines.extend(
        [
            "",
            f"📡 Source: {source}",
            f"🕐 First seen: {candidate.first_seen}",
            "",
            "⚠️ DYOR — early signal only.",
            "The radar does not confirm legitimacy or safety.",
        ]
    )

    return "\n".join(
        lines
    )


# ============================================================
# DEBUG / DESCRIPTION
# ============================================================

def explain_signal(
    signal: PreCASignal,
) -> Dict[str, Any]:
    """
    Return scoring information useful for debugging.
    """

    text = lower_text(
        signal.text
    )

    return {
        "bsc_detected": contains_any(
            text,
            BSC_KEYWORDS,
        ),
        "launch_detected": detect_launch_intent(
            text
        ),
        "strong_pre_ca_detected": detect_strong_pre_ca_intent(
            text
        ),
        "presale_detected": detect_presale(
            text
        ),
        "liquidity_detected": detect_liquidity_intent(
            text
        ),
        "ticker": (
            signal.ticker
            or extract_first_ticker(text)
        ),
        "hashtags": extract_hashtags(
            text
        ),
        "score": score_pre_ca_signal(
            signal
        ),
        "stage": classify_stage(
            score_pre_ca_signal(
                signal
            )
        ),
    }


# ============================================================
# TEST HELPERS
# ============================================================

def test_signal(
    text: str,
    source_type: str = "test",
    source_name: str = "Test",
    url: str = "",
) -> Optional[ProjectCandidate]:
    """
    Convenience function for testing the engine.
    """

    signal = PreCASignal(
        source_type=source_type,
        source_name=source_name,
        text=text,
        url=url,
    )

    return handle_signal(
        signal
    )


# ============================================================
# LOCAL TEST
# ============================================================

if __name__ == "__main__":

    print("=" * 65)
    print("BSC RADAR V3 CORE TEST")
    print("=" * 65)

    examples = [
        (
            "New BSC project launching soon "
            "$TESTX. Contract soon. "
            "Join our Telegram.",
            "x",
        ),
        (
            "BSC fair launch coming soon. "
            "$MOONX presale starts Friday. "
            "CA will be released shortly.",
            "telegram",
        ),
        (
            "We are building something new "
            "for BNB Chain. Website coming soon.",
            "website",
        ),
    ]

    for text, source_type in examples:

        signal = PreCASignal(
            source_type=source_type,
            source_name=source_type.title(),
            text=text,
        )

        print()
        print("-" * 65)
        print("TEXT:")
        print(text)

        print()
        print("ANALYSIS:")

        print(
            json_safe(
                explain_signal(
                    signal
                )
            )
        )

        candidate = handle_signal(
            signal
        )

        print()
        print("CANDIDATE:")

        if candidate:

            print(
                format_pre_ca_alert(
                    candidate
                )
            )

        else:

            print(
                "Signal rejected."
            )


def json_safe(
    value: Any,
) -> str:
    """
    Small JSON formatter for local testing.
    """

    import json

    return json.dumps(
        value,
        indent=2,
        ensure_ascii=False,
    )
