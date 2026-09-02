"""
BSC RADAR V3 - CONFIGURATION
============================

Central configuration for the pre-CA BSC intelligence radar.

IMPORTANT:
- Put secrets in Render Environment Variables, NOT in this file.
- Never commit real API keys or bot tokens to GitHub.
- scanner.py will import this module.
"""

import os
from typing import List


# ============================================================================
# ENVIRONMENT HELPERS
# ============================================================================

def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {
        "1", "true", "yes", "y", "on"
    }


# ============================================================================
# APPLICATION
# ============================================================================

APP_NAME = env("APP_NAME", "BSC Radar V3")
APP_ENV = env("APP_ENV", "production")
DEBUG = env_bool("DEBUG", False)

HOST = env("HOST", "0.0.0.0")
PORT = env_int("PORT", 10000)

TIMEZONE = env("TIMEZONE", "UTC")


# ============================================================================
# DATABASE
# ============================================================================

DB_PATH = env("DB_PATH", "bsc_radar_v3.db")

DATABASE_TIMEOUT = env_int(
    "DATABASE_TIMEOUT",
    30,
)


# ============================================================================
# BSC / BNB CHAIN
# ============================================================================

BSC_CHAIN_ID = 56

BSC_RPC_URL = env(
    "BSC_RPC_URL",
    "https://bsc-dataseed.bnbchain.org",
)

# Optional backup RPCs. scanner.py can rotate through them if the primary
# endpoint fails or becomes rate limited.
BSC_RPC_URL_2 = env("BSC_RPC_URL_2", "")
BSC_RPC_URL_3 = env("BSC_RPC_URL_3", "")

BSC_RPC_URLS: List[str] = [
    url for url in (
        BSC_RPC_URL,
        BSC_RPC_URL_2,
        BSC_RPC_URL_3,
    )
    if url
]

# BSC is fast. Keep this reasonably low to avoid falling behind and hitting
# public RPC rate limits.
SCAN_INTERVAL = env_int(
    "SCAN_INTERVAL",
    60,
)

# Maximum number of blocks the on-chain scanner should catch up per cycle.
MAX_BLOCKS = env_int(
    "MAX_BLOCKS",
    25,
)

# Number of blocks to inspect on the first run.
FIRST_SCAN_BLOCKS = env_int(
    "FIRST_SCAN_BLOCKS",
    10,
)

# Delay between expensive RPC requests.
RPC_REQUEST_DELAY = env_float(
    "RPC_REQUEST_DELAY",
    0.05,
)

RPC_TIMEOUT = env_int(
    "RPC_TIMEOUT",
    20,
)

RPC_RETRIES = env_int(
    "RPC_RETRIES",
    3,
)


# ============================================================================
# PRE-CA DISCOVERY
# ============================================================================

PRE_CA_ENABLED = env_bool(
    "PRE_CA_ENABLED",
    True,
)

# Minimum score before a discovered signal is stored as a project.
MIN_PRECA_SCORE = env_int(
    "MIN_PRECA_SCORE",
    35,
)

# Telegram alert threshold.
PRE_CA_ALERT_SCORE = env_int(
    "PRE_CA_ALERT_SCORE",
    75,
)

# "HOT" project threshold.
PRE_CA_HOT_SCORE = env_int(
    "PRE_CA_HOT_SCORE",
    85,
)

# Do not alert on the same project repeatedly unless its score increases by
# at least this amount.
ALERT_SCORE_INCREASE = env_int(
    "ALERT_SCORE_INCREASE",
    10,
)


# ============================================================================
# PRE-CA SCORING WEIGHTS
# ============================================================================

# Chain evidence
SCORE_BSC_SIGNAL = env_int(
    "SCORE_BSC_SIGNAL",
    15,
)

# Launch intent
SCORE_LAUNCH_INTENT = env_int(
    "SCORE_LAUNCH_INTENT",
    15,
)

# Strong phrases such as "CA soon", "launching soon", "fair launch".
SCORE_STRONG_LAUNCH_SIGNAL = env_int(
    "SCORE_STRONG_LAUNCH_SIGNAL",
    5,
)

# Identity
SCORE_TICKER = env_int(
    "SCORE_TICKER",
    10,
)

SCORE_PROJECT_NAME = env_int(
    "SCORE_PROJECT_NAME",
    5,
)

# Public infrastructure
SCORE_WEBSITE = env_int(
    "SCORE_WEBSITE",
    10,
)

SCORE_TELEGRAM = env_int(
    "SCORE_TELEGRAM",
    5,
)

SCORE_X = env_int(
    "SCORE_X",
    5,
)

# Timing
SCORE_LAUNCH_TIMING = env_int(
    "SCORE_LAUNCH_TIMING",
    5,
)

# Community/engagement tiers
ENGAGEMENT_SCORE_500 = env_int(
    "ENGAGEMENT_SCORE_500",
    4,
)

ENGAGEMENT_SCORE_3000 = env_int(
    "ENGAGEMENT_SCORE_3000",
    7,
)

ENGAGEMENT_SCORE_10000 = env_int(
    "ENGAGEMENT_SCORE_10000",
    10,
)


# ============================================================================
# X / TWITTER
# ============================================================================

# Disabled by default because API access/credits may not be available.
X_ENABLED = env_bool(
    "X_ENABLED",
    False,
)

X_BEARER_TOKEN = env(
    "X_BEARER_TOKEN",
)

X_API_BASE = env(
    "X_API_BASE",
    "https://api.x.com/2",
)

X_RECENT_SEARCH_ENDPOINT = (
    f"{X_API_BASE.rstrip('/')}/tweets/search/recent"
)

X_SEARCH_INTERVAL = env_int(
    "X_SEARCH_INTERVAL",
    120,
)

X_MAX_RESULTS = max(
    10,
    min(100, env_int("X_MAX_RESULTS", 100)),
)

# Search terms are intentionally configurable so scanner.py does not need
# hard-coded API queries.
X_SEARCH_QUERIES = [
    q.strip()
    for q in env(
        "X_SEARCH_QUERIES",
        (
            '"BSC launch" OR "BSC launching" OR '
            '"BSC project" OR "BSC token"'
        ),
    ).split("|")
    if q.strip()
]


# ============================================================================
# TELEGRAM DISCOVERY
# ============================================================================

# This is for SOURCE monitoring, not outbound bot alerts.
#
# Bot API bots cannot automatically read arbitrary Telegram channels. The
# scanner should only monitor sources the configured integration is actually
# authorized to access.
TELEGRAM_DISCOVERY_ENABLED = env_bool(
    "TELEGRAM_DISCOVERY_ENABLED",
    False,
)

TELEGRAM_API_ID = env_int(
    "TELEGRAM_API_ID",
    0,
)

TELEGRAM_API_HASH = env(
    "TELEGRAM_API_HASH",
)

TELEGRAM_SESSION = env(
    "TELEGRAM_SESSION",
)

# Comma-separated public usernames/channel names.
# Example:
# TELEGRAM_SOURCE_CHANNELS=channel_one,channel_two
TELEGRAM_SOURCE_CHANNELS = [
    x.strip().lstrip("@")
    for x in env(
        "TELEGRAM_SOURCE_CHANNELS",
        "",
    ).split(",")
    if x.strip()
]

TELEGRAM_SEARCH_INTERVAL = env_int(
    "TELEGRAM_SEARCH_INTERVAL",
    60,
)


# ============================================================================
# TELEGRAM ALERT BOT
# ============================================================================

TELEGRAM_ALERTS_ENABLED = env_bool(
    "TELEGRAM_ALERTS_ENABLED",
    True,
)

TELEGRAM_BOT_TOKEN = env(
    "TELEGRAM_BOT_TOKEN",
)

TELEGRAM_CHAT_ID = env(
    "TELEGRAM_CHAT_ID",
)

TELEGRAM_ALERT_MIN_SCORE = env_int(
    "TELEGRAM_ALERT_MIN_SCORE",
    PRE_CA_ALERT_SCORE,
)

TELEGRAM_SEND_TIMEOUT = env_int(
    "TELEGRAM_SEND_TIMEOUT",
    15,
)

# Do not use getUpdates in this radar. This prevents the multiple-poller
# 409 conflict that can happen when more than one process consumes updates.
TELEGRAM_POLLING_ENABLED = False


# ============================================================================
# WEBSITE DISCOVERY
# ============================================================================

WEBSITE_DISCOVERY_ENABLED = env_bool(
    "WEBSITE_DISCOVERY_ENABLED",
    True,
)

WEBSITE_REQUEST_TIMEOUT = env_int(
    "WEBSITE_REQUEST_TIMEOUT",
    15,
)

WEBSITE_MAX_BYTES = env_int(
    "WEBSITE_MAX_BYTES",
    2_000_000,
)

WEBSITE_SCAN_INTERVAL = env_int(
    "WEBSITE_SCAN_INTERVAL",
    300,
)

# Only inspect these common project pages when discovered.
WEBSITE_PATHS = [
    "/",
    "/whitepaper",
    "/tokenomics",
    "/roadmap",
    "/docs",
]


# ============================================================================
# RSS / PUBLIC FEEDS
# ============================================================================

RSS_ENABLED = env_bool(
    "RSS_ENABLED",
    True,
)

RSS_SCAN_INTERVAL = env_int(
    "RSS_SCAN_INTERVAL",
    300,
)

# Add feeds using:
# RSS_FEEDS=https://example.com/feed.xml|https://example.org/rss
RSS_FEEDS = [
    url.strip()
    for url in env(
        "RSS_FEEDS",
        "",
    ).split("|")
    if url.strip()
]


# ============================================================================
# LAUNCHPAD / PRESALE DISCOVERY
# ============================================================================

LAUNCHPAD_DISCOVERY_ENABLED = env_bool(
    "LAUNCHPAD_DISCOVERY_ENABLED",
    True,
)

# These URLs are placeholders for configuration. scanner.py should implement
# adapters only for sources that expose accessible public data/APIs.
LAUNCHPAD_URLS = [
    url.strip()
    for url in env(
        "LAUNCHPAD_URLS",
        "",
    ).split("|")
    if url.strip()
]


# ============================================================================
# MEMPOOL / PENDING DEPLOYMENT
# ============================================================================

# This is separate from pre-CA social discovery.
#
# A pending transaction may reveal a contract deployment before the
# transaction is mined, but availability depends on the RPC/provider.
MEMPOOL_ENABLED = env_bool(
    "MEMPOOL_ENABLED",
    False,
)

MEMPOOL_SCAN_INTERVAL = env_int(
    "MEMPOOL_SCAN_INTERVAL",
    5,
)

# Public BSC RPC endpoints generally should NOT be assumed to expose a
# complete pending transaction stream. Use a provider that explicitly
# supports pending transactions/WebSockets when enabling this.
BSC_WS_URL = env(
    "BSC_WS_URL",
)


# ============================================================================
# ON-CHAIN HANDOFF
# ============================================================================

ONCHAIN_HANDOFF_ENABLED = env_bool(
    "ONCHAIN_HANDOFF_ENABLED",
    True,
)

# Once a CA is found, scanner.py can hand the project to the on-chain
# analyzer for security/liquidity/tax/holder checks.
ONCHAIN_MIN_SCORE_FOR_DEEP_SCAN = env_int(
    "ONCHAIN_MIN_SCORE_FOR_DEEP_SCAN",
    60,
)


# ============================================================================
# DEXSCREENER
# ============================================================================

DEXSCREENER_ENABLED = env_bool(
    "DEXSCREENER_ENABLED",
    True,
)

DEXSCREENER_BASE_URL = env(
    "DEXSCREENER_BASE_URL",
    "https://api.dexscreener.com",
)

DEXSCREENER_TOKEN_ENDPOINT = (
    DEXSCREENER_BASE_URL.rstrip("/") +
    "/tokens/v1/bsc/"
)

DEXSCREENER_REQUEST_TIMEOUT = env_int(
    "DEXSCREENER_REQUEST_TIMEOUT",
    15,
)

DEXSCREENER_INTERVAL = env_int(
    "DEXSCREENER_INTERVAL",
    60,
)


# ============================================================================
# BSCSCAN / ETHERSCAN API V2
# ============================================================================

BSCSCAN_ENABLED = env_bool(
    "BSCSCAN_ENABLED",
    True,
)

BSCSCAN_API_KEY = env(
    "BSCSCAN_API_KEY",
)

ETHERSCAN_V2_BASE_URL = env(
    "ETHERSCAN_V2_BASE_URL",
    "https://api.etherscan.io/v2/api",
)

ETHERSCAN_CHAIN_ID = 56

BSCSCAN_REQUEST_TIMEOUT = env_int(
    "BSCSCAN_REQUEST_TIMEOUT",
    20,
)

BSCSCAN_INTERVAL = env_int(
    "BSCSCAN_INTERVAL",
    120,
)


# ============================================================================
# SECURITY SCANNING
# ============================================================================

SECURITY_SCAN_ENABLED = env_bool(
    "SECURITY_SCAN_ENABLED",
    True,
)

# Function selectors used as HEURISTICS.
#
# These are not a substitute for source-code review, simulation, or a
# professional audit.
OWNER_SELECTOR = "0x8da5cb5b"

BLACKLIST_SELECTORS = [
    "443e5e04",
    "5c60da1b",
    "f9f92be4",
]

PAUSE_SELECTOR = "0x8456cb59"

MINT_SELECTORS = [
    "40c10f19",
    "a0712d68",
]

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


# ============================================================================
# HOLDER / CONCENTRATION ANALYSIS
# ============================================================================

HOLDER_ANALYSIS_ENABLED = env_bool(
    "HOLDER_ANALYSIS_ENABLED",
    True,
)

TOP_HOLDER_COUNT = env_int(
    "TOP_HOLDER_COUNT",
    10,
)

# Alert/review thresholds.
TOP10_WARNING_PERCENT = env_float(
    "TOP10_WARNING_PERCENT",
    40.0,
)

TOP10_HIGH_RISK_PERCENT = env_float(
    "TOP10_HIGH_RISK_PERCENT",
    60.0,
)


# ============================================================================
# LIQUIDITY / MARKET SIGNALS
# ============================================================================

LIQUIDITY_ANALYSIS_ENABLED = env_bool(
    "LIQUIDITY_ANALYSIS_ENABLED",
    True,
)

LIQUIDITY_STRONG_USD = env_float(
    "LIQUIDITY_STRONG_USD",
    50_000,
)

LIQUIDITY_GOOD_USD = env_float(
    "LIQUIDITY_GOOD_USD",
    10_000,
)

LIQUIDITY_LOW_USD = env_float(
    "LIQUIDITY_LOW_USD",
    5_000,
)


# ============================================================================
# DEPLOYER REPUTATION
# ============================================================================

DEPLOYER_ANALYSIS_ENABLED = env_bool(
    "DEPLOYER_ANALYSIS_ENABLED",
    True,
)

DEPLOYER_HISTORY_LIMIT = env_int(
    "DEPLOYER_HISTORY_LIMIT",
    20,
)

# Number of contracts created by a deployer before we flag unusually high
# deployment activity.
DEPLOYER_HIGH_ACTIVITY = env_int(
    "DEPLOYER_HIGH_ACTIVITY",
    20,
)


# ============================================================================
# TAX / HONEYPOT / TRADE SIMULATION
# ============================================================================

TRADE_SIMULATION_ENABLED = env_bool(
    "TRADE_SIMULATION_ENABLED",
    False,
)

# This will require a compatible simulation/RPC provider or execution
# environment. It is deliberately disabled until scanner.py implements the
# safe simulation adapter.
HONEYPOT_CHECK_ENABLED = env_bool(
    "HONEYPOT_CHECK_ENABLED",
    False,
)

TAX_ANALYSIS_ENABLED = env_bool(
    "TAX_ANALYSIS_ENABLED",
    False,
)


# ============================================================================
# DEDUPLICATION
# ============================================================================

DEDUP_ENABLED = env_bool(
    "DEDUP_ENABLED",
    True,
)

# A candidate can be merged using ticker, website domain, X handle,
# Telegram URL, or project name depending on available evidence.
DEDUP_WINDOW_SECONDS = env_int(
    "DEDUP_WINDOW_SECONDS",
    86_400,
)


# ============================================================================
# RATE LIMIT / SAFETY CONTROLS
# ============================================================================

REQUEST_DELAY = env_float(
    "REQUEST_DELAY",
    0.25,
)

MAX_REQUESTS_PER_CYCLE = env_int(
    "MAX_REQUESTS_PER_CYCLE",
    100,
)

ERROR_BACKOFF_SECONDS = env_int(
    "ERROR_BACKOFF_SECONDS",
    30,
)

MAX_CONSECUTIVE_ERRORS = env_int(
    "MAX_CONSECUTIVE_ERRORS",
    10,
)


# ============================================================================
# LOGGING
# ============================================================================

LOG_LEVEL = env(
    "LOG_LEVEL",
    "INFO",
).upper()

LOG_JSON = env_bool(
    "LOG_JSON",
    False,
)


# ============================================================================
# DASHBOARD
# ============================================================================

DASHBOARD_ENABLED = env_bool(
    "DASHBOARD_ENABLED",
    True,
)

DASHBOARD_PAGE_SIZE = env_int(
    "DASHBOARD_PAGE_SIZE",
    50,
)

DASHBOARD_REFRESH_SECONDS = env_int(
    "DASHBOARD_REFRESH_SECONDS",
    15,
)


# ============================================================================
# RENDER / PRODUCTION
# ============================================================================

RENDER_SERVICE_NAME = env(
    "RENDER_SERVICE_NAME",
    "bsc-radar-v3",
)

HEALTH_PATH = env(
    "HEALTH_PATH",
    "/health",
)


# ============================================================================
# SOURCE PRIORITIES
# ============================================================================

# Higher number = more important.
SOURCE_PRIORITY = {
    "x": 100,
    "telegram": 100,
    "website": 80,
    "launchpad": 75,
    "rss": 60,
    "mempool": 95,
    "manual": 50,
}


# ============================================================================
# PRE-CA KEYWORDS
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


# ============================================================================
# VALIDATION
# ============================================================================

def validate_config() -> List[str]:
    """
    Return configuration warnings/errors.

    scanner.py can call this during startup.
    """
    issues: List[str] = []

    if not BSC_RPC_URLS:
        issues.append("No BSC RPC URL configured.")

    if SCAN_INTERVAL < 15:
        issues.append(
            "SCAN_INTERVAL is below 15 seconds; this may overload an RPC."
        )

    if MAX_BLOCKS < 1:
        issues.append("MAX_BLOCKS must be at least 1.")

    if not 0 <= MIN_PRECA_SCORE <= 100:
        issues.append("MIN_PRECA_SCORE must be between 0 and 100.")

    if not 0 <= PRE_CA_ALERT_SCORE <= 100:
        issues.append("PRE_CA_ALERT_SCORE must be between 0 and 100.")

    if not 0 <= PRE_CA_HOT_SCORE <= 100:
        issues.append("PRE_CA_HOT_SCORE must be between 0 and 100.")

    if PRE_CA_ALERT_SCORE > PRE_CA_HOT_SCORE:
        issues.append(
            "PRE_CA_ALERT_SCORE should not exceed PRE_CA_HOT_SCORE."
        )

    if X_ENABLED and not X_BEARER_TOKEN:
        issues.append(
            "X_ENABLED=true but X_BEARER_TOKEN is missing."
        )

    if TELEGRAM_ALERTS_ENABLED:
        if not TELEGRAM_BOT_TOKEN:
            issues.append(
                "Telegram alerts enabled but TELEGRAM_BOT_TOKEN is missing."
            )

        if not TELEGRAM_CHAT_ID:
            issues.append(
                "Telegram alerts enabled but TELEGRAM_CHAT_ID is missing."
            )

    if TELEGRAM_DISCOVERY_ENABLED:
        if not TELEGRAM_API_ID:
            issues.append(
                "Telegram discovery enabled but TELEGRAM_API_ID is missing."
            )

        if not TELEGRAM_API_HASH:
            issues.append(
                "Telegram discovery enabled but TELEGRAM_API_HASH is missing."
            )

    if MEMPOOL_ENABLED and not BSC_WS_URL:
        issues.append(
            "MEMPOOL_ENABLED=true but BSC_WS_URL is missing."
        )

    return issues


def print_config_summary() -> None:
    """Safe startup summary. Secrets are never printed."""
    print("=" * 70)
    print(APP_NAME)
    print("=" * 70)
    print(f"Environment:              {APP_ENV}")
    print(f"BSC RPCs configured:      {len(BSC_RPC_URLS)}")
    print(f"Scan interval:            {SCAN_INTERVAL}s")
    print(f"Max blocks/cycle:         {MAX_BLOCKS}")
    print(f"Pre-CA discovery:         {PRE_CA_ENABLED}")
    print(f"Minimum pre-CA score:     {MIN_PRECA_SCORE}")
    print(f"Pre-CA alert score:       {PRE_CA_ALERT_SCORE}")
    print(f"Pre-CA hot score:         {PRE_CA_HOT_SCORE}")
    print(f"X discovery:              {X_ENABLED}")
    print(f"Telegram discovery:       {TELEGRAM_DISCOVERY_ENABLED}")
    print(f"Website discovery:        {WEBSITE_DISCOVERY_ENABLED}")
    print(f"RSS discovery:            {RSS_ENABLED}")
    print(f"Mempool monitoring:       {MEMPOOL_ENABLED}")
    print(f"On-chain handoff:         {ONCHAIN_HANDOFF_ENABLED}")
    print(f"Security scanning:        {SECURITY_SCAN_ENABLED}")
    print(f"Holder analysis:          {HOLDER_ANALYSIS_ENABLED}")
    print(f"Liquidity analysis:       {LIQUIDITY_ANALYSIS_ENABLED}")
    print(f"Trade simulation:         {TRADE_SIMULATION_ENABLED}")
    print(f"Dashboard:                {DASHBOARD_ENABLED}")
    print("=" * 70)


if __name__ == "__main__":
    print_config_summary()

    problems = validate_config()

    if problems:
        print("\nConfiguration warnings:")
        for problem in problems:
            print(f"- {problem}")
    else:
        print("\nConfiguration validation: PASSED")
