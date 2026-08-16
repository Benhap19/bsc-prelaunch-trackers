# BSC Pre-Launch Tracker — MVP

Starter BSC discovery dashboard using public token-profile signals.

## Run
python -m venv .venv
pip install -r requirements.txt
python -m app.main

Open http://127.0.0.1:8000

## Scanner
Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID if you later add alerts.
Then run:
python -m app.scanner
