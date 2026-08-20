import os
import time
import requests
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

    if description:
        score += 10

    if "website" in link_types or "web" in link_types:
        score += 10

    if "twitter" in link_types or "x" in link_types:
        score += 15

    if "telegram" in link_types:
        score += 15

    if score >= 60:
        stage = "🔥 HOT"
    elif score >= 45:
        stage = "🟡 WATCH"
    else:
        stage = "🔵 EARLY"

    return min(score, 100), stage, links


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


def run():
    init_db()

    print("🚀 BSC Pre-Launch Radar started")
    print(f"⏱ Scanner interval: {SCAN_INTERVAL} seconds")

    while True:
        scan()

        try:
            time.sleep(SCAN_INTERVAL)
        except KeyboardInterrupt:
            print("🛑 Scanner stopped.")
            break
