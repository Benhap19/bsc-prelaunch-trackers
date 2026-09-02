
"""
BSC RADAR V3 - CONFIGURATION
============================

Central configuration for the BSC Pre-Launch Radar.

IMPORTANT:
Do not put private API keys directly in this file.
Use Render Environment Variables instead.
"""

import os


# ============================================================
# GENERAL
# ============================================================

APP_NAME = "BSC Pre-Launch Radar V3"

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

SCAN_INTERVAL_SECONDS = int(
    os.getenv("SCAN_INTERVAL_SECONDS", "60")
)


# ============================================================
# BSC RPC
# ============================================================

BSC_RPC_URLS = [
    os.getenv(
        "BSC_RPC_URL",
        "https://bsc-dataseed.bnbchain.org"
    )
]

RPC_TIMEOUT = int(
    os.getenv("RPC_TIMEOUT", "20")
)

RPC_RETRIES = int(
    os.getenv("RPC_RETRIES", "3")
)

ERROR_BACKOFF_SECONDS = int(
    os.getenv("ERROR_BACKOFF_SECONDS", "3")
)


# ============================================================
# BSC BLOCK SCANNER
# ============================================================

# Number of blocks processed during one catch-up cycle.
MAX_BLOCKS_PER_SCAN = int(
    os.getenv("MAX_BLOCKS_PER_SCAN", "25")
)

# Number of blocks scanned when the radar starts for the
# first time.
FIRST_SCAN_BLOCKS = int(
    os.getenv("FIRST_SCAN_BLOCKS", "20")
)


# ============================================================
# TELEGRAM ALERTS
# ============================================================

TELEGRAM_ALERTS_ENABLED = (
    os.getenv(
        "TELEGRAM_ALERTS_ENABLED",
        "true"
    ).lower()
    in ("1", "true", "yes", "on")
)

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()

TELEGRAM_SEND_TIMEOUT = int(
    os.getenv("TELEGRAM_SEND_TIMEOUT", "15")
)


# ============================================================
# X / TWITTER DISCOVERY
# ============================================================

# Keep disabled until X API credentials/credits are available.
X_ENABLED = (
    os.getenv(
        "X_ENABLED",
        "false"
    ).lower()
    in ("1", "true", "yes", "on")
)

X_BEARER_TOKEN = os.getenv(
    "X_BEARER_TOKEN",
    ""
).strip()

X_RECENT_SEARCH_ENDPOINT = (
    "https://api.x.com/2/tweets/search/recent"
)

X_MAX_RESULTS = int(
    os.getenv("X_MAX_RESULTS", "10")
)

X_SEARCH_QUERIES = [
    '(BSC OR "BNB Chain") '
    '(launch OR launching OR presale OR "fair launch") '
    "-is:retweet",

    '(BSC OR "BNB Chain") '
    '("contract soon" OR "CA soon" OR "contract address soon") '
    "-is:retweet",

    '(BSC OR "BNB Chain") '
    '("stealth launch" OR "launching soon") '
    "-is:retweet",
]


# ============================================================
# TELEGRAM SOURCE DISCOVERY
# ============================================================

# IMPORTANT:
#
# This is for authorized Telegram sources only.
#
# The radar does NOT magically read private Telegram groups.
# Add public/authorized source usernames or chat IDs here.
#
# Example:
# TELEGRAM_SOURCE_CHATS=@projectlaunches,-1001234567890
#

TELEGRAM_SOURCE_CHATS = os.getenv(
    "TELEGRAM_SOURCE_CHATS",
    ""
).strip()


# ============================================================
# RSS / PUBLIC FEED DISCOVERY
# ============================================================

RSS_ENABLED = (
    os.getenv(
        "RSS_ENABLED",
        "true"
    ).lower()
    in ("1", "true", "yes", "on")
)

RSS_FEEDS = [
    item.strip()
    for item in os.getenv(
        "RSS_FEEDS",
        ""
    ).split(",")
    if item.strip()
]


# ============================================================
# WEBSITE DISCOVERY
# ============================================================

WEBSITE_DISCOVERY_ENABLED = (
    os.getenv(
        "WEBSITE_DISCOVERY_ENABLED",
        "true"
    ).lower()
    in ("1", "true", "yes", "on")
)

WEBSITE_REQUEST_TIMEOUT = int(
    os.getenv("WEBSITE_REQUEST_TIMEOUT", "15")
)

WEBSITE_MAX_BYTES = int(
    os.getenv("WEBSITE_MAX_BYTES", "500000")
)

MAX_TEXT_LENGTH = int(
    os.getenv("MAX_TEXT_LENGTH", "3000")
)


# ============================================================
# PRE-CA SIGNAL SCORING
# ============================================================

# Minimum score before a discovered signal is stored.
PRE_CA_MIN_SCORE = int(
    os.getenv("PRE_CA_MIN_SCORE", "45")
)

# Score required before sending a Telegram alert.
PRE_CA_ALERT_SCORE = int(
    os.getenv("PRE_CA_ALERT_SCORE", "60")
)


# ============================================================
# SIGNAL KEYWORDS
# ============================================================

BSC_KEYWORDS = [
    "bsc",
    "bnb chain",
    "bnbchain",
    "binance smart chain",
]

LAUNCH_KEYWORDS = [
    "launch",
    "launching",
    "launch soon",
    "launching soon",
    "presale",
    "pre-sale",
    "fair launch",
    "fairlaunch",
    "stealth launch",
    "contract soon",
    "ca soon",
    "contract address",
    "contract address soon",
    "liquidity soon",
    "listing soon",
]


# ============================================================
# DATABASE
# ============================================================

DB_PATH = os.getenv(
    "DB_PATH",
    "radar_v3.db"
)


# ============================================================
# USER AGENT
# ============================================================

USER_AGENT = os.getenv(
    "USER_AGENT",
    "BSC-PreLaunch-Radar-V3/1.0"
)


# ============================================================
# DEBUG
# ============================================================

DEBUG = (
    os.getenv(
        "DEBUG",
        "false"
    ).lower()
    in ("1", "true", "yes", "on")
)


# ============================================================
# CONFIGURATION SUMMARY
# ============================================================

def print_config():
    """
    Print safe configuration information.

    API keys/tokens are deliberately NOT printed.
    """

    print("=" * 60)
    print("BSC PRE-LAUNCH RADAR V3")
    print("=" * 60)

    print(f"Scan interval: {SCAN_INTERVAL_SECONDS}s")
    print(f"Max blocks/scan: {MAX_BLOCKS_PER_SCAN}")
    print(f"First scan blocks: {FIRST_SCAN_BLOCKS}")

    print(f"Telegram alerts: {TELEGRAM_ALERTS_ENABLED}")
    print(f"X discovery: {X_ENABLED}")
    print(f"RSS discovery: {RSS_ENABLED}")
    print(
        f"Website discovery: "
        f"{WEBSITE_DISCOVERY_ENABLED}"
    )

    print(
        f"Pre-CA minimum score: "
        f"{PRE_CA_MIN_SCORE}"
    )

    print(
        f"Pre-CA alert score: "
        f"{PRE_CA_ALERT_SCORE}"
    )

    print(f"Database: {DB_PATH}")

    print("=" * 60)


if __name__ == "__main__":
    print_config()
