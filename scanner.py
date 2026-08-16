import os
import time
import requests
from dotenv import load_dotenv
from db import init_db, upsert, all_projects

load_dotenv()

DEX_API = "https://api.dexscreener.com/token-profiles/latest/v1"
TELEGRAM_API = "https://api.telegram.org/bot{}"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL_SECONDS", "120"))

known_alerts = set()


def telegram(method, data=None):
    if not BOT_TOKEN:
        return None

    try:
        url = TELEGRAM_API.format(BOT_TOKEN) + "/" + method
        response = requests.post(url, data=data or {}, timeout=20)
        return response.json()
    except Exception as e:
        print("Telegram error:", e)
        return None


def send_message(chat_id, text):
    return telegram("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True
    })


def get_updates():
    return telegram("getUpdates", {"timeout": 5})


def handle_telegram():
    """Learn the user's chat ID and respond to commands."""
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

            os.environ["TELEGRAM_CHAT_ID"] = str(chat_id)

        elif text.startswith("/id"):
            send_message(
                chat_id,
                f"🆔 Your Telegram Chat ID:\n{chat_id}"
            )

            os.environ["TELEGRAM_CHAT_ID"] = str(chat_id)

        elif text.startswith("/status"):
            projects = all_projects()

            send_message(
                chat_id,
                f"📡 BSC Radar Status\n\n"
                f"Projects tracked: {len(projects)}\n"
                f"Scanner interval: {SCAN_INTERVAL} seconds"
            )


def score_project(profile):
    score = 10
    links = profile.get("links") or []

    link_types = {
        (x.get("type") or "").lower(): x.get("url", "")
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

    return min(score, 100), stage, link_types


def scan():
    print("🔎 Scanning BSC projects...")

    try:
    response = requests.get(
        DEX_API,
        timeout=20
    )

    if response.status_code == 429:
        print("⚠️ DEX Screener rate limit reached.")
        print("Waiting before next scan...")
        return

    response.raise_for_status()

    profiles = response.json()

except requests.RequestException as e:
    print("⚠️ DEX Screener API error:", e)
    return

except Exception as e:
    print("⚠️ Scanner error:", e)
    return

    for profile in profiles:

        if profile.get("chainId") != "bsc":
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
            "x_url": links.get("twitter") or links.get("x") or "",
            "telegram_url": links.get("telegram") or "",
            "score": score,
            "stage": stage
        }

        upsert(project)

        # Alert only high-scoring new projects.
        if score >= 60 and address not in known_alerts:

            known_alerts.add(address)

            chat_id = os.getenv("TELEGRAM_CHAT_ID")

            if chat_id:

                message = (
                    "🚨 NEW BSC PROJECT DETECTED\n\n"
                    f"Project: {project['name']}\n"
                    f"Stage: {stage}\n"
                    f"Score: {score}/100\n\n"
                    f"Website: {project['url'] or 'Not available'}\n"
                    f"X: {project['x_url'] or 'Not available'}\n"
                    f"Telegram: {project['telegram_url'] or 'Not available'}\n\n"
                    f"Contract:\n{address}\n\n"
                    "⚠️ Research before interacting."
                )

                send_message(chat_id, message)

    print("✅ Scan completed.")


def run():

    init_db()

    print("🚀 BSC Pre-Launch Radar started")

    while True:

        try:
            handle_telegram()
            scan()

        except Exception as e:
            print("Scanner error:", e)

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    run()
