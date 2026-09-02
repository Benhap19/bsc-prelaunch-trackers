"""
BSC RADAR V3 - Complete Core Source
===================================

Purpose:
    Pre-CA intelligence for discovering BSC/BNB Chain projects BEFORE
    their token contract address is deployed.

This file is the core data/logic layer. Network-specific collectors
(X, Telegram, RSS, websites, mempool/RPC) should feed normalized
PreCASignal objects into this engine.

Pipeline:
    Public signal
        -> normalize
        -> detect BSC + launch intent
        -> extract project identity
        -> deduplicate
        -> calculate PRE-CA score
        -> rank
        -> store/export
        -> hand off to on-chain scanner when CA appears

IMPORTANT:
    This is an intelligence/scoring engine, not proof that a project is
    legitimate. A high score means "strong pre-launch signals", not "safe
    investment".
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse


# ============================================================================
# CONFIGURATION
# ============================================================================

DB_PATH = "bsc_radar_v3.db"

# Minimum evidence required before a signal becomes a project candidate.
MIN_PRECA_SCORE = 35

# Scores used by scanner.py later.
ALERT_SCORE = 75
HOT_SCORE = 85

# Maximum stored text to avoid bloating SQLite.
MAX_TEXT_LENGTH = 6000

# BSC identifiers.
BSC_CHAIN_IDS = {"56", "0x38"}
BSC_NAMES = {
    "bsc",
    "bnb",
    "bnb chain",
    "bnb smart chain",
    "binance smart chain",
}


# ============================================================================
# KEYWORDS
# ============================================================================

BSC_KEYWORDS = [
    "bsc",
    "bnb chain",
    "bnbchain",
    "bnb smart chain",
    "binance smart chain",
]

LAUNCH_KEYWORDS = [
    "launching soon",
    "launch soon",
    "launching",
    "launch date",
    "fair launch",
    "stealth launch",
    "stealth",
    "presale",
    "presale soon",
    "presale live",
    "token launch",
    "tge",
    "ido",
    "ico",
    "ca soon",
    "contract soon",
    "contract address soon",
    "liquidity soon",
    "liquidity will be added",
    "lp will be added",
    "listing soon",
    "dex launch",
    "dex listing",
]

HIGH_SIGNAL_KEYWORDS = [
    "ca soon",
    "contract soon",
    "contract address soon",
    "launch date",
    "launching soon",
    "fair launch",
    "stealth launch",
    "liquidity soon",
    "lp will be added",
]

NOISE_KEYWORDS = [
    "casino",
    "sports betting",
    "adult",
    "free money",
    "guaranteed profit",
]

SOCIAL_HOSTS = {
    "x.com",
    "twitter.com",
    "t.me",
    "telegram.me",
    "discord.com",
    "discord.gg",
    "github.com",
}

# Common words that should not accidentally become token tickers.
TICKER_STOPWORDS = {
    "THE", "AND", "FOR", "NEW", "NOW", "BUY", "SELL", "LIVE",
    "JOIN", "BSC", "BNB", "CHAIN", "CA", "SOON", "TOKEN",
    "COIN", "LAUNCH", "PRESALE", "TG", "X", "USD", "USDT",
}


# ============================================================================
# UTILITIES
# ============================================================================

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(value: Any, limit: int = MAX_TEXT_LENGTH) -> str:
    if value is None:
        return ""

    text = str(value)
    text = text.replace("\x00", " ")
    text = re.sub(r"\s+", " ", text).strip()

    return text[:limit]


def normalize_url(url: Any) -> str:
    url = clean_text(url, 1000)

    if not url:
        return ""

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)

    if not parsed.netloc:
        return ""

    return url.rstrip("/")


def domain(url: str) -> str:
    try:
        host = urlparse(normalize_url(url)).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def normalize_handle(handle: Any) -> str:
    value = clean_text(handle, 100)

    value = value.replace("https://x.com/", "")
    value = value.replace("https://twitter.com/", "")
    value = value.replace("@", "")
    value = value.strip("/ ")

    return value.lower()


def normalize_ticker(value: Any) -> str:
    value = clean_text(value, 50)
    value = value.replace("$", "").upper()

    value = re.sub(r"[^A-Z0-9_]", "", value)

    if not value or value in TICKER_STOPWORDS:
        return ""

    return value[:30]


def normalize_project_name(value: Any) -> str:
    value = clean_text(value, 200)

    if not value:
        return ""

    # Avoid turning URLs into project names.
    if value.startswith(("http://", "https://")):
        return ""

    return value


def stable_hash(*parts: Any) -> str:
    raw = "|".join(clean_text(x).lower() for x in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def contains_any(text: str, terms: Iterable[str]) -> List[str]:
    text = clean_text(text).lower()
    return [term for term in terms if term.lower() in text]


def is_bsc_text(text: str) -> bool:
    return bool(contains_any(text, BSC_KEYWORDS))


def has_launch_intent(text: str) -> bool:
    return bool(contains_any(text, LAUNCH_KEYWORDS))


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class PreCASignal:
    source_type: str
    source_name: str

    text: str = ""
    url: str = ""

    project_name: str = ""
    ticker: str = ""

    network: str = ""
    launch_text: str = ""
    launch_timestamp: Optional[str] = None

    website: str = ""
    telegram: str = ""
    x_handle: str = ""

    engagement: int = 0
    followers: int = 0
    community_members: int = 0

    author: str = ""
    author_followers: int = 0

    signals: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    observed_at: str = field(default_factory=utc_now)

    def normalize(self) -> "PreCASignal":
        self.source_type = clean_text(self.source_type, 50).lower()
        self.source_name = clean_text(self.source_name, 200)

        self.text = clean_text(self.text)
        self.url = normalize_url(self.url)

        self.project_name = normalize_project_name(self.project_name)
        self.ticker = normalize_ticker(self.ticker)

        self.network = clean_text(self.network, 50).upper()
        self.launch_text = clean_text(self.launch_text, 1000)

        self.website = normalize_url(self.website)
        self.telegram = normalize_url(self.telegram)
        self.x_handle = normalize_handle(self.x_handle)

        self.engagement = max(0, int(self.engagement or 0))
        self.followers = max(0, int(self.followers or 0))
        self.community_members = max(0, int(self.community_members or 0))
        self.author_followers = max(0, int(self.author_followers or 0))

        self.signals = list(dict.fromkeys(
            clean_text(x, 200) for x in self.signals if clean_text(x)
        ))

        return self


@dataclass
class ProjectCandidate:
    project_id: str

    project_name: str = ""
    ticker: str = ""

    network: str = "BSC"

    website: str = ""
    telegram: str = ""
    x_handle: str = ""

    launch_text: str = ""
    launch_timestamp: Optional[str] = None

    pre_ca_score: int = 0
    confidence: int = 0
    stage: str = "PRE-CA"

    signal_count: int = 0
    source_count: int = 0

    engagement: int = 0
    followers: int = 0
    community_members: int = 0

    has_website: bool = False
    has_telegram: bool = False
    has_x: bool = False
    has_launch_date: bool = False
    has_bsc_signal: bool = False
    has_token_identity: bool = False

    ca: str = ""

    first_seen: str = field(default_factory=utc_now)
    last_seen: str = field(default_factory=utc_now)

    signals: List[str] = field(default_factory=list)
    source_urls: List[str] = field(default_factory=list)

    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)

        data["has_website"] = bool(self.has_website)
        data["has_telegram"] = bool(self.has_telegram)
        data["has_x"] = bool(self.has_x)
        data["has_launch_date"] = bool(self.has_launch_date)
        data["has_bsc_signal"] = bool(self.has_bsc_signal)
        data["has_token_identity"] = bool(self.has_token_identity)

        return data


# ============================================================================
# TEXT EXTRACTION
# ============================================================================

def extract_tickers(text: str) -> List[str]:
    """
    Extract $TICKER candidates.

    We deliberately do not treat a ticker as proof of a project.
    """
    text = clean_text(text)

    matches = re.findall(r"\$([A-Za-z][A-Za-z0-9_]{1,29})", text)

    result = []

    for match in matches:
        ticker = normalize_ticker(match)

        if ticker and ticker not in result:
            result.append(ticker)

    return result


def extract_urls(text: str) -> List[str]:
    text = clean_text(text)

    raw_urls = re.findall(
        r"(?:https?://|www\.)[^\s<>()]+",
        text,
        flags=re.IGNORECASE,
    )

    result = []

    for raw in raw_urls:
        raw = raw.rstrip(".,!?;:'\"")

        url = normalize_url(raw)

        if url and url not in result:
            result.append(url)

    return result


def classify_urls(urls: Iterable[str]) -> Dict[str, List[str]]:
    classified = {
        "x": [],
        "telegram": [],
        "website": [],
        "github": [],
        "other": [],
    }

    for url in urls:
        d = domain(url)

        if d in {"x.com", "twitter.com"}:
            classified["x"].append(url)
        elif d in {"t.me", "telegram.me"}:
            classified["telegram"].append(url)
        elif d == "github.com" or d.endswith(".github.com"):
            classified["github"].append(url)
        elif d:
            classified["website"].append(url)
        else:
            classified["other"].append(url)

    return classified


def extract_launch_text(text: str) -> str:
    text = clean_text(text)

    matches = contains_any(text, LAUNCH_KEYWORDS)

    if not matches:
        return ""

    # Keep the complete text rather than trying to over-interpret dates.
    return text[:1000]


def extract_project_identity(signal: PreCASignal) -> Tuple[str, str]:
    """
    Determine a likely project name/ticker from explicit fields or text.

    This is intentionally conservative.
    """
    ticker = normalize_ticker(signal.ticker)

    if not ticker:
        tickers = extract_tickers(signal.text)
        if tickers:
            ticker = tickers[0]

    name = normalize_project_name(signal.project_name)

    if not name and ticker:
        # Do not invent a name; ticker alone is acceptable.
        name = ""

    return name, ticker


# ============================================================================
# SIGNAL ANALYSIS
# ============================================================================

def analyze_signal(signal: PreCASignal) -> Dict[str, Any]:
    signal.normalize()

    text = signal.text.lower()

    bsc_hits = contains_any(text, BSC_KEYWORDS)
    launch_hits = contains_any(text, LAUNCH_KEYWORDS)
    high_hits = contains_any(text, HIGH_SIGNAL_KEYWORDS)
    noise_hits = contains_any(text, NOISE_KEYWORDS)

    urls = extract_urls(signal.text)
    classified = classify_urls(urls)

    name, ticker = extract_project_identity(signal)

    if not signal.website and classified["website"]:
        signal.website = classified["website"][0]

    if not signal.telegram and classified["telegram"]:
        signal.telegram = classified["telegram"][0]

    if not signal.x_handle and classified["x"]:
        parsed = urlparse(classified["x"][0])
        signal.x_handle = normalize_handle(parsed.path.strip("/").split("/")[0])

    if not signal.launch_text:
        signal.launch_text = extract_launch_text(signal.text)

    if not signal.network and bsc_hits:
        signal.network = "BSC"

    # Signal-level confidence. This is not project legitimacy.
    confidence = 0

    if bsc_hits:
        confidence += 30

    if launch_hits:
        confidence += 30

    if high_hits:
        confidence += 20

    if ticker:
        confidence += 10

    if signal.website:
        confidence += 5

    if signal.telegram:
        confidence += 5

    if signal.x_handle:
        confidence += 5

    confidence = min(100, confidence)

    return {
        "bsc_hits": bsc_hits,
        "launch_hits": launch_hits,
        "high_signal_hits": high_hits,
        "noise_hits": noise_hits,
        "urls": urls,
        "classified_urls": classified,
        "project_name": name,
        "ticker": ticker,
        "confidence": confidence,
    }


# ============================================================================
# PRE-CA SCORING
# ============================================================================

def calculate_pre_ca_score(
    signal: PreCASignal,
    analysis: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Calculate an explainable 0-100 pre-CA score.

    The score measures strength of public launch signals.

    It DOES NOT mean:
        - the project is safe
        - the project is genuine
        - the token will pump
        - the developer is trustworthy
    """
    signal.normalize()

    analysis = analysis or analyze_signal(signal)

    score = 0
    reasons: List[str] = []

    # Chain identification ---------------------------------------------------
    if analysis["bsc_hits"] or signal.network.upper() == "BSC":
        score += 15
        reasons.append("BSC/BNB Chain signal")

    # Launch intent ----------------------------------------------------------
    if analysis["launch_hits"]:
        score += 15
        reasons.append("Launch intent detected")

    high_signal_hits = analysis["high_signal_hits"]

    if high_signal_hits:
        bonus = min(15, len(high_signal_hits) * 5)
        score += bonus
        reasons.append("Strong launch language")

    # Identity ---------------------------------------------------------------
    if analysis["ticker"]:
        score += 10
        reasons.append("Token ticker identified")

    if analysis["project_name"]:
        score += 5
        reasons.append("Project name identified")

    # Public infrastructure --------------------------------------------------
    if signal.website:
        score += 10
        reasons.append("Website detected")

    if signal.telegram:
        score += 5
        reasons.append("Telegram detected")

    if signal.x_handle:
        score += 5
        reasons.append("X account detected")

    # Launch timing ----------------------------------------------------------
    if signal.launch_timestamp or signal.launch_text:
        score += 5
        reasons.append("Launch timing information")

    # Engagement -------------------------------------------------------------
    engagement = max(
        signal.engagement,
        signal.community_members,
        signal.followers,
    )

    if engagement >= 10000:
        score += 10
        reasons.append("Very strong public/community activity")
    elif engagement >= 3000:
        score += 7
        reasons.append("Strong public/community activity")
    elif engagement >= 500:
        score += 4
        reasons.append("Meaningful public/community activity")

    # Noise penalty ----------------------------------------------------------
    if analysis["noise_hits"]:
        score -= min(15, len(analysis["noise_hits"]) * 5)
        reasons.append("Potential noise/risk keywords")

    score = max(0, min(100, score))

    # Confidence is evidence quality, not safety.
    confidence = analysis["confidence"]

    if len(analysis["urls"]) >= 2:
        confidence = min(100, confidence + 5)

    if signal.engagement > 0:
        confidence = min(100, confidence + 5)

    if score >= HOT_SCORE:
        stage = "🔥 HOT PRE-CA"
    elif score >= ALERT_SCORE:
        stage = "🟣 HIGH POTENTIAL"
    elif score >= 60:
        stage = "🟡 WATCH"
    elif score >= MIN_PRECA_SCORE:
        stage = "⚪ EARLY SIGNAL"
    else:
        stage = "⚫ WEAK SIGNAL"

    return {
        "score": score,
        "confidence": confidence,
        "stage": stage,
        "reasons": list(dict.fromkeys(reasons)),
    }


# ============================================================================
# PROJECT IDENTITY / DEDUPLICATION
# ============================================================================

def make_project_id(
    project_name: str = "",
    ticker: str = "",
    website: str = "",
    x_handle: str = "",
    telegram: str = "",
) -> str:
    """
    Build a deterministic identity.

    Priority:
        ticker + website
        ticker
        website
        X
        Telegram
        project name
    """
    ticker = normalize_ticker(ticker)
    website_domain = domain(website)
    x_handle = normalize_handle(x_handle)
    telegram = normalize_url(telegram)
    name = normalize_project_name(project_name).lower()

    if ticker and website_domain:
        return "proj_" + stable_hash("ticker", ticker, "domain", website_domain)[:20]

    if ticker:
        return "proj_" + stable_hash("ticker", ticker)[:20]

    if website_domain:
        return "proj_" + stable_hash("domain", website_domain)[:20]

    if x_handle:
        return "proj_" + stable_hash("x", x_handle)[:20]

    if telegram:
        return "proj_" + stable_hash("telegram", telegram)[:20]

    if name:
        return "proj_" + stable_hash("name", name)[:20]

    return "proj_" + stable_hash("unknown", utc_now())[:20]


# ============================================================================
# SQLITE DATABASE
# ============================================================================

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,

    project_name TEXT,
    ticker TEXT,
    network TEXT DEFAULT 'BSC',

    website TEXT,
    telegram TEXT,
    x_handle TEXT,

    launch_text TEXT,
    launch_timestamp TEXT,

    pre_ca_score INTEGER DEFAULT 0,
    confidence INTEGER DEFAULT 0,
    stage TEXT DEFAULT 'PRE-CA',

    signal_count INTEGER DEFAULT 0,
    source_count INTEGER DEFAULT 0,

    engagement INTEGER DEFAULT 0,
    followers INTEGER DEFAULT 0,
    community_members INTEGER DEFAULT 0,

    has_website INTEGER DEFAULT 0,
    has_telegram INTEGER DEFAULT 0,
    has_x INTEGER DEFAULT 0,
    has_launch_date INTEGER DEFAULT 0,
    has_bsc_signal INTEGER DEFAULT 0,
    has_token_identity INTEGER DEFAULT 0,

    ca TEXT DEFAULT '',

    first_seen TEXT,
    last_seen TEXT,

    signals_json TEXT DEFAULT '[]',
    source_urls_json TEXT DEFAULT '[]',
    metadata_json TEXT DEFAULT '{}',

    alerted INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS signals (
    signal_id TEXT PRIMARY KEY,
    project_id TEXT,

    source_type TEXT,
    source_name TEXT,

    text TEXT,
    url TEXT,

    observed_at TEXT,

    analysis_json TEXT DEFAULT '{}',
    raw_json TEXT DEFAULT '{}',

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(project_id) REFERENCES projects(project_id)
);

CREATE INDEX IF NOT EXISTS idx_projects_score
ON projects(pre_ca_score DESC);

CREATE INDEX IF NOT EXISTS idx_projects_stage
ON projects(stage);

CREATE INDEX IF NOT EXISTS idx_projects_ca
ON projects(ca);

CREATE INDEX IF NOT EXISTS idx_signals_project
ON signals(project_id);
"""


class RadarDB:
    """Thread-safe SQLite persistence for the pre-CA radar."""

    def __init__(self, path: str = DB_PATH):
        self.path = path
        self.lock = threading.RLock()

        Path(path).parent.mkdir(parents=True, exist_ok=True)

        self.init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.path,
            timeout=30,
            check_same_thread=False,
        )

        conn.row_factory = sqlite3.Row

        return conn

    def init(self) -> None:
        with self.lock:
            conn = self.connect()

            try:
                conn.executescript(DB_SCHEMA)
                conn.commit()
            finally:
                conn.close()

    def upsert_project(self, project: ProjectCandidate) -> None:
        data = project.to_dict()

        with self.lock:
            conn = self.connect()

            try:
                conn.execute(
                    """
                    INSERT INTO projects (
                        project_id,
                        project_name,
                        ticker,
                        network,
                        website,
                        telegram,
                        x_handle,
                        launch_text,
                        launch_timestamp,
                        pre_ca_score,
                        confidence,
                        stage,
                        signal_count,
                        source_count,
                        engagement,
                        followers,
                        community_members,
                        has_website,
                        has_telegram,
                        has_x,
                        has_launch_date,
                        has_bsc_signal,
                        has_token_identity,
                        ca,
                        first_seen,
                        last_seen,
                        signals_json,
                        source_urls_json,
                        metadata_json
                    )
                    VALUES (
                        :project_id,
                        :project_name,
                        :ticker,
                        :network,
                        :website,
                        :telegram,
                        :x_handle,
                        :launch_text,
                        :launch_timestamp,
                        :pre_ca_score,
                        :confidence,
                        :stage,
                        :signal_count,
                        :source_count,
                        :engagement,
                        :followers,
                        :community_members,
                        :has_website,
                        :has_telegram,
                        :has_x,
                        :has_launch_date,
                        :has_bsc_signal,
                        :has_token_identity,
                        :ca,
                        :first_seen,
                        :last_seen,
                        :signals_json,
                        :source_urls_json,
                        :metadata_json
                    )
                    ON CONFLICT(project_id) DO UPDATE SET
                        project_name = excluded.project_name,
                        ticker = excluded.ticker,
                        network = excluded.network,
                        website = excluded.website,
                        telegram = excluded.telegram,
                        x_handle = excluded.x_handle,
                        launch_text = excluded.launch_text,
                        launch_timestamp = excluded.launch_timestamp,
                        pre_ca_score = excluded.pre_ca_score,
                        confidence = excluded.confidence,
                        stage = excluded.stage,
                        signal_count = excluded.signal_count,
                        source_count = excluded.source_count,
                        engagement = excluded.engagement,
                        followers = excluded.followers,
                        community_members = excluded.community_members,
                        has_website = excluded.has_website,
                        has_telegram = excluded.has_telegram,
                        has_x = excluded.has_x,
                        has_launch_date = excluded.has_launch_date,
                        has_bsc_signal = excluded.has_bsc_signal,
                        has_token_identity = excluded.has_token_identity,
                        ca = excluded.ca,
                        last_seen = excluded.last_seen,
                        signals_json = excluded.signals_json,
                        source_urls_json = excluded.source_urls_json,
                        metadata_json = excluded.metadata_json,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    {
                        **data,
                        "signals_json": json.dumps(
                            project.signals,
                            ensure_ascii=False,
                        ),
                        "source_urls_json": json.dumps(
                            project.source_urls,
                            ensure_ascii=False,
                        ),
                        "metadata_json": json.dumps(
                            project.metadata,
                            ensure_ascii=False,
                        ),
                    },
                )

                conn.commit()

            finally:
                conn.close()

    def add_signal(
        self,
        project_id: str,
        signal: PreCASignal,
        analysis: Dict[str, Any],
    ) -> str:
        signal_id = stable_hash(
            project_id,
            signal.source_type,
            signal.source_name,
            signal.url,
            signal.text,
        )

        with self.lock:
            conn = self.connect()

            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO signals (
                        signal_id,
                        project_id,
                        source_type,
                        source_name,
                        text,
                        url,
                        observed_at,
                        analysis_json,
                        raw_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        signal_id,
                        project_id,
                        signal.source_type,
                        signal.source_name,
                        signal.text,
                        signal.url,
                        signal.observed_at,
                        json.dumps(analysis, ensure_ascii=False),
                        json.dumps(signal.raw or {}, ensure_ascii=False),
                    ),
                )

                conn.commit()

            finally:
                conn.close()

        return signal_id

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            conn = self.connect()

            try:
                row = conn.execute(
                    "SELECT * FROM projects WHERE project_id = ?",
                    (project_id,),
                ).fetchone()

                return self._row_to_project(row) if row else None

            finally:
                conn.close()

    def list_projects(
        self,
        min_score: int = 0,
        stage: str = "",
        limit: int = 100,
        pre_ca_only: bool = True,
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT *
            FROM projects
            WHERE pre_ca_score >= ?
        """

        params: List[Any] = [min_score]

        if pre_ca_only:
            query += " AND (ca IS NULL OR ca = '')"

        if stage:
            query += " AND stage = ?"
            params.append(stage)

        query += """
            ORDER BY pre_ca_score DESC, last_seen DESC
            LIMIT ?
        """

        params.append(max(1, min(1000, int(limit))))

        with self.lock:
            conn = self.connect()

            try:
                rows = conn.execute(query, params).fetchall()

                return [
                    self._row_to_project(row)
                    for row in rows
                ]

            finally:
                conn.close()

    def search_projects(
        self,
        query_text: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        q = f"%{clean_text(query_text).lower()}%"

        with self.lock:
            conn = self.connect()

            try:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM projects
                    WHERE LOWER(project_name) LIKE ?
                       OR LOWER(ticker) LIKE ?
                       OR LOWER(website) LIKE ?
                       OR LOWER(x_handle) LIKE ?
                       OR LOWER(telegram) LIKE ?
                    ORDER BY pre_ca_score DESC
                    LIMIT ?
                    """,
                    (q, q, q, q, q, max(1, min(500, limit))),
                ).fetchall()

                return [
                    self._row_to_project(row)
                    for row in rows
                ]

            finally:
                conn.close()

    def mark_alerted(self, project_id: str) -> None:
        with self.lock:
            conn = self.connect()

            try:
                conn.execute(
                    """
                    UPDATE projects
                    SET alerted = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE project_id = ?
                    """,
                    (project_id,),
                )

                conn.commit()

            finally:
                conn.close()

    def was_alerted(self, project_id: str) -> bool:
        with self.lock:
            conn = self.connect()

            try:
                row = conn.execute(
                    "SELECT alerted FROM projects WHERE project_id = ?",
                    (project_id,),
                ).fetchone()

                return bool(row["alerted"]) if row else False

            finally:
                conn.close()

    def stats(self) -> Dict[str, int]:
        with self.lock:
            conn = self.connect()

            try:
                total = conn.execute(
                    "SELECT COUNT(*) AS c FROM projects"
                ).fetchone()["c"]

                pre_ca = conn.execute(
                    """
                    SELECT COUNT(*) AS c
                    FROM projects
                    WHERE ca IS NULL OR ca = ''
                    """
                ).fetchone()["c"]

                hot = conn.execute(
                    """
                    SELECT COUNT(*) AS c
                    FROM projects
                    WHERE pre_ca_score >= ?
                      AND (ca IS NULL OR ca = '')
                    """,
                    (HOT_SCORE,),
                ).fetchone()["c"]

                high = conn.execute(
                    """
                    SELECT COUNT(*) AS c
                    FROM projects
                    WHERE pre_ca_score >= ?
                      AND (ca IS NULL OR ca = '')
                    """,
                    (ALERT_SCORE,),
                ).fetchone()["c"]

                deployed = conn.execute(
                    """
                    SELECT COUNT(*) AS c
                    FROM projects
                    WHERE ca IS NOT NULL AND ca != ''
                    """
                ).fetchone()["c"]

                signals = conn.execute(
                    "SELECT COUNT(*) AS c FROM signals"
                ).fetchone()["c"]

                return {
                    "projects": int(total),
                    "pre_ca": int(pre_ca),
                    "hot_pre_ca": int(hot),
                    "high_potential": int(high),
                    "deployed": int(deployed),
                    "signals": int(signals),
                }

            finally:
                conn.close()

    @staticmethod
    def _row_to_project(row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)

        for key in (
            "signals_json",
            "source_urls_json",
            "metadata_json",
        ):
            raw = data.pop(key, "{}")

            try:
                data[key.replace("_json", "")] = json.loads(raw or "{}")
            except json.JSONDecodeError:
                data[key.replace("_json", "")] = {}

        for key in (
            "has_website",
            "has_telegram",
            "has_x",
            "has_launch_date",
            "has_bsc_signal",
            "has_token_identity",
            "alerted",
        ):
            data[key] = bool(data.get(key))

        return data


# ============================================================================
# RADAR ENGINE
# ============================================================================

class PreCARadar:
    """
    Converts incoming public signals into ranked pre-CA project candidates.
    """

    def __init__(self, db: Optional[RadarDB] = None):
        self.db = db or RadarDB()

        self.lock = threading.RLock()

    def process_signal(
        self,
        signal: PreCASignal,
    ) -> Optional[ProjectCandidate]:
        """
        Process one observation.

        Returns:
            ProjectCandidate if the signal is strong enough to become a
            project candidate, otherwise None.
        """
        signal.normalize()

        analysis = analyze_signal(signal)

        # Require both chain evidence and launch intent for true pre-CA
        # discovery. This avoids turning every crypto post into a candidate.
        if not analysis["bsc_hits"]:
            return None

        if not analysis["launch_hits"]:
            return None

        name = analysis["project_name"]
        ticker = analysis["ticker"]

        project_id = make_project_id(
            project_name=name,
            ticker=ticker,
            website=signal.website,
            x_handle=signal.x_handle,
            telegram=signal.telegram,
        )

        score_data = calculate_pre_ca_score(
            signal,
            analysis,
        )

        if score_data["score"] < MIN_PRECA_SCORE:
            return None

        existing = self.db.get_project(project_id)

        now = utc_now()

        project = self._merge_project(
            existing,
            project_id,
            signal,
            analysis,
            score_data,
            now,
        )

        self.db.upsert_project(project)
        self.db.add_signal(
            project_id,
            signal,
            {
                **analysis,
                **score_data,
            },
        )

        return project

    def _merge_project(
        self,
        existing: Optional[Dict[str, Any]],
        project_id: str,
        signal: PreCASignal,
        analysis: Dict[str, Any],
        score_data: Dict[str, Any],
        now: str,
    ) -> ProjectCandidate:
        if existing:
            project = ProjectCandidate(
                project_id=project_id,
                project_name=existing.get("project_name", ""),
                ticker=existing.get("ticker", ""),
                network=existing.get("network", "BSC"),

                website=existing.get("website", ""),
                telegram=existing.get("telegram", ""),
                x_handle=existing.get("x_handle", ""),

                launch_text=existing.get("launch_text", ""),
                launch_timestamp=existing.get("launch_timestamp"),

                pre_ca_score=int(existing.get("pre_ca_score", 0)),
                confidence=int(existing.get("confidence", 0)),
                stage=existing.get("stage", "PRE-CA"),

                signal_count=int(existing.get("signal_count", 0)),
                source_count=int(existing.get("source_count", 0)),

                engagement=int(existing.get("engagement", 0)),
                followers=int(existing.get("followers", 0)),
                community_members=int(
                    existing.get("community_members", 0)
                ),

                has_website=bool(existing.get("has_website")),
                has_telegram=bool(existing.get("has_telegram")),
                has_x=bool(existing.get("has_x")),
                has_launch_date=bool(existing.get("has_launch_date")),
                has_bsc_signal=bool(existing.get("has_bsc_signal")),
                has_token_identity=bool(
                    existing.get("has_token_identity")
                ),

                ca=existing.get("ca", ""),

                first_seen=existing.get("first_seen") or now,
                last_seen=now,

                signals=list(existing.get("signals") or []),
                source_urls=list(existing.get("source_urls") or []),
                metadata=dict(existing.get("metadata") or {}),
            )
        else:
            project = ProjectCandidate(
                project_id=project_id,
                first_seen=now,
                last_seen=now,
            )

        # Merge identity -----------------------------------------------------
        if analysis["project_name"]:
            project.project_name = analysis["project_name"]

        if analysis["ticker"]:
            project.ticker = analysis["ticker"]

        if signal.network:
            project.network = signal.network

        if signal.website:
            project.website = signal.website

        if signal.telegram:
            project.telegram = signal.telegram

        if signal.x_handle:
            project.x_handle = signal.x_handle

        if signal.launch_text:
            project.launch_text = signal.launch_text

        if signal.launch_timestamp:
            project.launch_timestamp = signal.launch_timestamp

        # Aggregate metrics --------------------------------------------------
        project.signal_count += 1

        project.engagement = max(
            project.engagement,
            signal.engagement,
        )

        project.followers = max(
            project.followers,
            signal.followers,
        )

        project.community_members = max(
            project.community_members,
            signal.community_members,
        )

        # Boolean evidence ---------------------------------------------------
        project.has_website = bool(project.website)
        project.has_telegram = bool(project.telegram)
        project.has_x = bool(project.x_handle)
        project.has_launch_date = bool(project.launch_timestamp or project.launch_text)
        project.has_bsc_signal = True
        project.has_token_identity = bool(
            project.project_name or project.ticker
        )

        # Aggregate reasons -------------------------------------------------
        project.signals.extend(score_data["reasons"])
        project.signals.extend(signal.signals)

        project.signals = list(dict.fromkeys(
            clean_text(x, 200)
            for x in project.signals
            if clean_text(x)
        ))[-100:]

        # Source URLs --------------------------------------------------------
        if signal.url:
            project.source_urls.append(signal.url)

        project.source_urls = list(dict.fromkeys(
            x for x in project.source_urls if x
        ))[-100:]

        # Score is recalculated as evidence grows.
        project.pre_ca_score = max(
            project.pre_ca_score,
            int(score_data["score"]),
        )

        project.confidence = max(
            project.confidence,
            int(score_data["confidence"]),
        )

        project.stage = score_data["stage"]

        # Unique source count.
        source_names = set(
            project.metadata.get("sources", [])
        )

        source_names.add(signal.source_name)

        project.metadata["sources"] = sorted(
            x for x in source_names if x
        )

        project.source_count = len(
            project.metadata["sources"]
        )

        project.metadata["last_signal_type"] = signal.source_type
        project.metadata["last_signal_at"] = now

        return project

    def rank(
        self,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        return self.db.list_projects(
            min_score=MIN_PRECA_SCORE,
            limit=limit,
            pre_ca_only=True,
        )


# ============================================================================
# ALERT FORMATTER
# ============================================================================

def format_pre_ca_alert(project: ProjectCandidate) -> str:
    """
    Produce a Telegram-ready alert.

    scanner.py can send this through Telegram Bot API.
    """
    ticker = f"${project.ticker}" if project.ticker else "Unknown"

    lines = [
        "🚨 NEW BSC PROJECT — PRE-CA",
        "",
        f"📌 Project: {project.project_name or 'Unknown'}",
        f"🪙 Ticker: {ticker}",
        f"⛓ Network: {project.network or 'BSC'}",
        f"📊 Pre-CA Score: {project.pre_ca_score}/100",
        f"🎯 Confidence: {project.confidence}/100",
        f"🚦 Stage: {project.stage}",
        "",
        f"🌐 Website: {'YES' if project.has_website else 'NO'}",
        f"💬 Telegram: {'YES' if project.has_telegram else 'NO'}",
        f"🐦 X: {'YES' if project.has_x else 'NO'}",
        f"📅 Launch info: {'YES' if project.has_launch_date else 'NO'}",
        "",
        "🔐 CA: NOT DEPLOYED",
    ]

    if project.launch_text:
        lines.extend([
            "",
            f"📅 Launch signal: {project.launch_text[:500]}",
        ])

    if project.website:
        lines.extend([
            "",
            f"🌐 {project.website}",
        ])

    if project.telegram:
        lines.append(f"💬 {project.telegram}")

    if project.x_handle:
        lines.append(f"🐦 @{project.x_handle}")

    if project.signals:
        lines.extend([
            "",
            "📡 Signals:",
        ])

        for reason in project.signals[-8:]:
            lines.append(f"• {reason}")

    return "\n".join(lines)


# ============================================================================
# EXPORT
# ============================================================================

def export_projects_csv(
    projects: List[Dict[str, Any]],
    filepath: str = "pre_ca_projects.csv",
) -> str:
    """Export ranked projects for offline review."""
    if not projects:
        return filepath

    fields = [
        "project_id",
        "project_name",
        "ticker",
        "network",
        "website",
        "telegram",
        "x_handle",
        "pre_ca_score",
        "confidence",
        "stage",
        "signal_count",
        "source_count",
        "engagement",
        "followers",
        "community_members",
        "has_website",
        "has_telegram",
        "has_x",
        "has_launch_date",
        "ca",
        "first_seen",
        "last_seen",
    ]

    with open(
        filepath,
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore",
        )

        writer.writeheader()

        for project in projects:
            writer.writerow(project)

    return filepath


# ============================================================================
# TEST / DEMO
# ============================================================================

def demo() -> None:
    """
    Local self-test.

    No internet requests are made.
    """
    print("=" * 70)
    print("BSC RADAR V3 - PRE-CA CORE SELF TEST")
    print("=" * 70)

    db = RadarDB(":memory:")
    radar = PreCARadar(db)

    sample = PreCASignal(
        source_type="demo",
        source_name="Demo Source",
        text=(
            "🚀 New BSC project launching soon! "
            "$NOVA fair launch Friday at 7PM UTC. "
            "Community is growing fast. "
            "Website: https://nova-example.com "
            "Telegram: https://t.me/nova_example"
        ),
        engagement=4200,
        community_members=1800,
    )

    project = radar.process_signal(sample)

    if not project:
        raise RuntimeError("Self-test failed: project was not detected.")

    print(format_pre_ca_alert(project))
    print()
    print("Database stats:")
    print(json.dumps(db.stats(), indent=2))

    print()
    print("Ranked projects:")
    print(json.dumps(radar.rank(), indent=2, default=str))

    print()
    print("SELF TEST PASSED")


if __name__ == "__main__":
    demo()
