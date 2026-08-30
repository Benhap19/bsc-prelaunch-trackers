import os
import time
import requests
import threading
import json
from dotenv import load_dotenv
from db import init_db, upsert, all_projects

load_dotenv()

DEX_API = "https://api.dexscreener.com/token-profiles/latest/v1"
DEX_PAIRS_API = "https://api.dexscreener.com/latest/dex/tokens/{}"

TELEGRAM_API = "https://api.telegram.org/bot{}"
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL_SECONDS", "60"))
BSC_RPC = os.getenv(
    "BSC_RPC_URL",
    "https://bsc-dataseed.bnbchain.org"
)

last_scanned_block = None
seen_contracts = set()
known_alerts = set()

def rpc_call(method, params=None):
    try:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or [],
            "id": 1
        }

        response = requests.post(
            BSC_RPC,
            json=payload,
            timeout=20
        )

        response.raise_for_status()
        data = response.json()

        if "error" in data:
            print("⚠️ BSC RPC error:", data["error"])
            return None

        return data.get("result")

    except Exception as e:
        print("⚠️ BSC RPC request error:", e)
        return None


def get_latest_block():
    result = rpc_call("eth_blockNumber")

    if not result:
        return None

    return int(result, 16)


def get_block(block_number):
    return rpc_call(
        "eth_getBlockByNumber",
        [hex(block_number), True]
    )


def get_contract_address(tx_hash):
    receipt = rpc_call(
        "eth_getTransactionReceipt",
        [tx_hash]
    )

    if not receipt:
        return None

    return receipt.get("contractAddress")


def eth_call(to, data):
    return rpc_call(
        "eth_call",
        [
            {
                "to": to,
                "data": data
            },
            "latest"
        ]
    )


def read_token_string(address, selector):
    result = eth_call(address, selector)

    if not result or result == "0x":
        return ""

    try:
        raw = bytes.fromhex(result[2:])

        # Standard ABI dynamic string
        if len(raw) >= 64:
            offset = int.from_bytes(raw[:32], "big")

            if offset + 32 <= len(raw):
                length = int.from_bytes(
                    raw[offset:offset + 32],
                    "big"
                )

                start = offset + 32
                end = start + length

                if end <= len(raw):
                    return raw[start:end].decode(
                        "utf-8",
                        errors="ignore"
                    ).strip()

        # bytes32 fallback
        return raw.rstrip(b"\x00").decode(
            "utf-8",
            errors="ignore"
        ).strip()

    except Exception:
        return ""


def is_bep20_token(address):
    try:
        name = read_token_string(
            address,
            "0x06fdde03"
        )

        symbol = read_token_string(
            address,
            "0x95d89b41"
        )

        decimals = eth_call(
            address,
            "0x313ce567"
        )

        total_supply = eth_call(
            address,
            "0x18160ddd"
        )

        if not symbol:
            return None

        if not decimals:
            return None

        if not total_supply:
            return None

        return {
            "name": name or "Unknown Token",
            "symbol": symbol,
            "decimals": int(decimals, 16),
            "total_supply": int(total_supply, 16)
        }

    except Exception:
        return None


def discover_new_contracts(block_number):
    block = get_block(block_number)

    if not block:
        return []

    contracts = []

    for tx in block.get("transactions", []):
        # Contract deployment transaction
        if tx.get("to") is not None:
            continue

        tx_hash = tx.get("hash")
        deployer = tx.get("from")

        if not tx_hash:
            continue

        contract = get_contract_address(tx_hash)

        if not contract:
            continue

        if contract.lower() in seen_contracts:
            continue

        seen_contracts.add(contract.lower())

        token = is_bep20_token(contract)

        if not token:
            continue

        contracts.append({
            "address": contract,
            "deployer": deployer,
            "tx_hash": tx_hash,
            "block": block_number,
            "token": token
        })

    return contracts

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
    global last_scanned_block

    print("🔎 Scanning BSC blockchain...")

    latest_block = get_latest_block()

    if latest_block is None:
        print("⚠️ Could not get latest BSC block.")
        return

    # First scan: start close to the current chain tip.
    if last_scanned_block is None:
        last_scanned_block = max(0, latest_block - 20)

    start_block = last_scanned_block + 1

    # Protect the RPC from an excessively large catch-up scan.
    max_blocks = 100

    if latest_block - start_block + 1 > max_blocks:
        start_block = latest_block - max_blocks + 1

    print(
        f"📦 Checking BSC blocks "
        f"{start_block} → {latest_block}"
    )

    total_tokens = 0

    for block_number in range(start_block, latest_block + 1):

        contracts = discover_new_contracts(block_number)

        if not contracts:
            continue

        print(
            f"🆕 Block {block_number}: "
            f"{len(contracts)} token contract(s) found"
        )

        for item in contracts:

            address = item["address"]
            deployer = item["deployer"]
            tx_hash = item["tx_hash"]
            token = item["token"]

            project = {
                "address": address,
                "name": token.get("name") or "Unknown Token",
                "description": (
                    f"New BSC token detected before "
                    f"market discovery. "
                    f"Deployer: {deployer}"
                ),
                "url": "",
                "x_url": "",
                "telegram_url": "",
                "score": 50,
                "stage": "🟢 PRE-LAUNCH",
            }

            try:
                upsert(project)
                total_tokens += 1

            except Exception as e:
                print("⚠️ Database error:", e)
                continue

            if address.lower() not in known_alerts:

                known_alerts.add(address.lower())

                chat_id = os.getenv("TELEGRAM_CHAT_ID")

                if chat_id:

                    message = (
                        "🚨 NEW BSC TOKEN DETECTED\n\n"
                        f"🪙 Name: {project['name']}\n"
                        f"🔤 Symbol: {token.get('symbol', 'Unknown')}\n"
                        f"📍 Stage: PRE-LAUNCH\n"
                        f"📊 Score: {project['score']}/100\n\n"
                        f"📄 Contract:\n{address}\n\n"
                        f"👤 Deployer:\n{deployer}\n\n"
                        f"🔗 TX:\n"
                        f"https://bscscan.com/tx/{tx_hash}"
                    )

                    send_message(chat_id, message)

    last_scanned_block = latest_block

    print(
        f"✅ BSC scan completed. "
        f"New tokens found: {total_tokens}"
    )                

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
