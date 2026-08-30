import os
import time
import requests
import threading
from dotenv import load_dotenv
from db import init_db, upsert, all_projects

load_dotenv()

DEX_API = "https://api.dexscreener.com/token-profiles/latest/v1"
DEX_PAIRS_API = "https://api.dexscreener.com/latest/dex/tokens/{}"

TELEGRAM_API = "https://api.telegram.org/bot{}"
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))

known_alerts = set()


def telegram(method, data=None):
    if not BOT_TOKEN:
        return None

    try:
        url = TELEGRAM_API.format(BOT_TOKEN) + "/" + method
        response = requests.post(
            url,
            data=data or {},
            timeout=20
        )

        if response.status_code != 200:
            print("Telegram error:", response.status_code)

        return response.json()

    except Exception as e:
        print("Telegram error:", e)
        return None


def send_message(chat_id, text):
    return telegram(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True
        }
    )



def score_project(profile):
    score = 0
    links = profile.get("links") or []

    link_types = {
        (x.get("type") or "").lower()
        for x in links
    }

    description = profile.get("description") or ""

    # Project description
    if description:
        score += 10

    # Website
    if "website" in link_types or "web" in link_types:
        score += 15

    # X / Twitter
    if "twitter" in link_types or "x" in link_types:
        score += 15

    # Telegram
    if "telegram" in link_types:
        score += 15

    # Discord
    if "discord" in link_types:
        score += 10

    # GitHub
    if "github" in link_types:
        score += 10

    # Other community/social links
    if "medium" in link_types:
        score += 5

    # Determine project stage
    if score >= 70:
        stage = "🔥 HOT"
    elif score >= 45:
        stage = "🟡 WATCH"
    else:
        stage = "🔵 EARLY"

    return min(score, 100), stage, links


def get_market_data(address):
    try:
        url = DEX_PAIRS_API.format(address)
        response = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": "BSC-PreLaunch-Radar/1.0"}
        )

        if response.status_code != 200:
            return {}

        data = response.json()
        pairs = data.get("pairs") or []

        # Only use BSC pairs
        bsc_pairs = [
            p for p in pairs
            if (p.get("chainId") or "").lower() == "bsc"
        ]

        if not bsc_pairs:
            return {}

        # Select the pair with the highest liquidity
        pair = max(
            bsc_pairs,
            key=lambda p: (p.get("liquidity") or {}).get("usd") or 0
        )

        liquidity = (pair.get("liquidity") or {}).get("usd") or 0
        volume_24h = (pair.get("volume") or {}).get("h24") or 0

        txns = (pair.get("txns") or {}).get("h24") or {}
        buys = txns.get("buys") or 0
        sells = txns.get("sells") or 0

        return {
            "dex": pair.get("dexId") or "",
            "pair": pair.get("pairAddress") or "",
            "liquidity": liquidity,
            "volume_24h": volume_24h,
            "buys_24h": buys,
            "sells_24h": sells,
            "price_usd": pair.get("priceUsd") or "",
            "pair_created_at": pair.get("pairCreatedAt")
        }

    except Exception as e:
        print("⚠️ Market data error:", e)
        return {}
def scan():
    print("🔎 Scanning BSC projects...")

    try:
        response = requests.get(
            DEX_API,
            timeout=20,
            headers={
                "User-Agent": "BSC-PreLaunch-Radar/1.0"
            }
        )

        print("DexScreener status:", response.status_code)

        if response.status_code == 429:
            print("⚠️ DexScreener rate limit reached.")
            print("Waiting until next scan...")
            return

        response.raise_for_status()

        profiles = response.json()

        if not isinstance(profiles, list):
            print("⚠️ Unexpected API response.")
            return

    except requests.RequestException as e:
        print("⚠️ DexScreener API error:", e)
        return

    except Exception as e:
        print("⚠️ Scanner error:", e)
        return

    for profile in profiles:

        if profile.get("chainId", "").lower() != "bsc":
            continue

        address = profile.get("tokenAddress")

        if not address:
            continue

score, stage, links = score_project(profile)

market = get_market_data(address)

# Market/activity scoring
liquidity = market.get("liquidity", 0)
volume_24h = market.get("volume_24h", 0)
buys_24h = market.get("buys_24h", 0)
sells_24h = market.get("sells_24h", 0)

if liquidity >= 10000:
    score += 10
elif liquidity >= 5000:
    score += 7
elif liquidity >= 1000:
    score += 4

if volume_24h >= 25000:
    score += 10
elif volume_24h >= 10000:
    score += 7
elif volume_24h >= 1000:
    score += 4

if buys_24h > sells_24h and buys_24h >= 10:
    score += 5

score = min(score, 100)

if score >= 70:
    stage = "🔥 HOT"
elif score >= 45:
    stage = "🟡 WATCH"
else:
    stage = "🔵 EARLY"

project = {
    "address": address,
    "name": profile.get("description") or address[:10],
    "description": profile.get("description") or "",
    "url": profile.get("url") or "",
    "x_url": "",
    "telegram_url": "",
    "score": score,
    "stage": stage
}

for link in links:
    link_type = (link.get("type") or "").lower()
    link_url = link.get("url") or ""

    if link_type in ("twitter", "x"):
        project["x_url"] = link_url

    if link_type == "telegram":
        project["telegram_url"] = link_url

        try:
            upsert(project)
        except Exception as e:
            print("⚠️ Database error:", e)
            continue

        if score >= 60 and address not in known_alerts:

            known_alerts.add(address)

            chat_id = os.getenv("TELEGRAM_CHAT_ID")

            if chat_id:

                message = (
                    "🚨 NEW BSC PROJECT DETECTED!\n\n"
                    f"Project: {project['name']}\n"
                    f"Stage: {stage}\n"
                    f"Score: {score}/100\n"
                    f"Contract: {address}\n"
                    f"Website: {project['url'] or 'Not available'}\n"
                    f"X: {project['x_url'] or 'Not available'}\n"
                    f"Telegram: {project['telegram_url'] or 'Not available'}"
                )

                send_message(chat_id, message)

    print("✅ Scan completed.")

def get_updates():
    return telegram("getUpdates", {"timeout": 5})
    
def telegram_loop():
    while True:
        try:
            handle_telegram()
            time.sleep(2)
        except Exception as e:
            print("⚠️ Telegram loop error:", e)
            time.sleep(5)

def handle_telegram():
    result = get_updates()

    if not result or not result.get("ok"):
        return

    for update in result.get("result", []):
        message = update.get("message")

        if not message:
            continue

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        text = message.get("text", "")

        if not chat_id:
            continue

        if text.startswith("/start"):
            send_message(
                chat_id,
                "🚀 BSC Pre-Launch Radar is connected!\n\n"
                "Your Chat ID has been detected.\n\n"
                "Commands:\n"
                "/id - show your Chat ID\n"
                "/status - show tracker status"
            )

        elif text.startswith("/id"):
            send_message(
                chat_id,
                f"🆔 Your Telegram Chat ID:\n{chat_id}"
            )

        elif text.startswith("/status"):
            projects = all_projects()

            send_message(
                chat_id,
                "📡 BSC Radar Status\n\n"
                f"Projects tracked: {len(projects)}\n"
                f"Scanner interval: {SCAN_INTERVAL} seconds"
            )
def run():
    init_db()

    print("🚀 BSC Pre-Launch Radar started")
    print(f"⏱ Scanner interval: {SCAN_INTERVAL} seconds")

    telegram_thread = threading.Thread(
        target=telegram_loop,
        daemon=True
    )
    telegram_thread.start()

    while True:
        scan()

        try:
            time.sleep(SCAN_INTERVAL)
        except KeyboardInterrupt:
            print("🛑 Scanner stopped.")
            break
