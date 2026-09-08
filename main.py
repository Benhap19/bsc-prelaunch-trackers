import html
import threading

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from db import all_prelaunch, init_db
from scanner import handle_telegram_update, run, _telegram_secret


app = FastAPI(
    title="Multi-Chain Pre-Launch Radar",
    description="BSC, Base and Solana pre-launch discovery and scoring system",
)

init_db()


def start_scanner():
    thread = threading.Thread(target=run, daemon=True)
    thread.start()


@app.on_event("startup")
def startup_event():
    start_scanner()


@app.get("/api/projects")
def projects():
    return all_prelaunch()


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not secret or secret != _telegram_secret():
        return {"ok": False, "error": "unauthorized"}

    update = await request.json()
    handle_telegram_update(update)
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def dashboard():
    projects = all_prelaunch()
    # Only show genuine pre-launch rows. Deployed/trading candidates are
    # retained in SQLite for traceability but removed from the radar view.
    projects = [
        project for project in projects
        if not project.get("contract_address")
        and (project.get("stage") or "").upper() != "DEPLOYED"
    ]
    rows = ""

    for project in projects:
        name = html.escape(project.get("name") or "Unknown BSC Project")
        symbol = html.escape(project.get("symbol") or "-")
        if symbol.startswith("BSC:") or symbol.startswith("BASE:") or symbol.startswith("SOLANA:"):
            symbol = html.escape(symbol.split(":", 1)[1])
        network = html.escape(project.get("network") or "-")
        stage = html.escape(project.get("stage") or "EARLY")
        score = int(project.get("prelaunch_score") or 0)
        website = html.escape(project.get("website") or "")
        telegram = html.escape(project.get("telegram_url") or "")
        x_url = html.escape(project.get("x_url") or "")
        source = html.escape(project.get("source") or "-")
        mentions = int(project.get("mentions") or 1)
        evidence = html.escape(project.get("source_types") or "-")
        confidence = int(project.get("confidence") or score)

        links = []
        if website:
            links.append(f'<a href="{website}" target="_blank">Website</a>')
        if telegram:
            links.append(f'<a href="{telegram}" target="_blank">Telegram</a>')
        if x_url.startswith("http"):
            links.append(f'<a href="{x_url}" target="_blank">X</a>')

        rows += f"""
        <tr>
            <td><strong>{name}</strong><br><small>${symbol}</small></td>
            <td>{network}</td>
            <td>{stage}</td>
            <td><strong>{score}/100</strong></td>
            <td>{confidence}/100</td>
            <td>{mentions}</td>
            <td>{evidence}</td>
            <td>{source}</td>
            <td>{" · ".join(links) if links else "-"}</td>
            <td>VERIFIED PRE-CA</td>
        </tr>
        """

    if not rows:
        rows = '<tr><td colspan="10" class="empty">No qualifying pre-CA projects discovered yet.</td></tr>'

    return f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BSC Pre-Launch Radar</title>
<style>
body{{font-family:Arial,sans-serif;margin:0;background:#f4f6f8;color:#111}}
.container{{max-width:1200px;margin:auto;padding:18px}}
.card{{background:#fff;border-radius:14px;padding:20px;margin-bottom:18px;box-shadow:0 2px 10px rgba(0,0,0,.06)}}
h1{{margin:0 0 8px;font-size:28px}}
.badge{{display:inline-block;padding:6px 10px;border-radius:999px;background:#111;color:#fff}}
.table-wrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;min-width:1020px}}
th,td{{padding:12px;border-bottom:1px solid #e5e7eb;text-align:left}}
th{{background:#111;color:#fff}}
.empty{{text-align:center;padding:30px;color:#666}}
a{{color:#0645ad;text-decoration:none}}
small{{color:#666}}
</style>
</head>
<body>
<div class="container">
<div class="card">
<h1>🚀 Multi-Chain Pre-Launch Radar</h1>
<p>Automated discovery of potential BSC, Base and Solana projects before contract deployment.</p>
<p><span class="badge">Pre-CA intelligence</span></p>
<h2>{len(projects)} project(s) tracked</h2>
</div>
<div class="card table-wrap">
<table>
<tr>
<th>Project</th><th>Network</th><th>Stage</th><th>Score</th><th>Confidence</th><th>Signals</th>
<th>Evidence</th><th>Source</th><th>Links</th><th>Contract</th>
</tr>
{rows}
</table>
</div>
</div>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

