import threading

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from db import init_db, all_prelaunch
from scanner import run


app = FastAPI(
    title="BSC Pre-Launch Radar V3",
    description="BSC pre-contract project discovery and intelligence radar",
)


init_db()


def start_scanner():
    thread = threading.Thread(
        target=run,
        daemon=True,
    )
    thread.start()


@app.on_event("startup")
def startup_event():
    start_scanner()


@app.get("/api/projects")
def projects():
    return all_prelaunch()


@app.get("/", response_class=HTMLResponse)
def dashboard():
    projects = all_prelaunch()

    rows = ""

    for project in projects:
        website = project.get("website", "")
        telegram = project.get("telegram_url", "")
        x_url = project.get("x_url", "")
        symbol = project.get("symbol", "")
        score = project.get("prelaunch_score", 0)
        stage = project.get("stage", "EARLY")

        website_html = (
            f'<a href="{website}" target="_blank">Website</a>'
            if website else "-"
        )
        telegram_html = (
            f'<a href="{telegram}" target="_blank">Telegram</a>'
            if telegram else "-"
        )
        x_html = (
            f'<a href="{x_url}" target="_blank">{x_url}</a>'
            if x_url.startswith("http") else (x_url or "-")
        )

        rows += f"""
        <tr>
            <td><strong>{project.get('name') or 'Unknown BSC Project'}</strong></td>
            <td>${symbol or 'N/A'}</td>
            <td><strong>{stage}</strong></td>
            <td><strong>{score}/100</strong></td>
            <td>{project.get('mentions', 1)}</td>
            <td>{website_html}</td>
            <td>{telegram_html}</td>
            <td>{x_html}</td>
            <td><strong>NOT DEPLOYED</strong></td>
        </tr>
        """

    if not rows:
        rows = """
        <tr>
            <td colspan="9" class="empty">
                No qualifying pre-CA projects detected yet.
            </td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta http-equiv="refresh" content="60">
        <title>BSC Pre-Launch Radar V3</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 0;
                background: #0b1020;
                color: #e8ecf3;
            }}
            .container {{
                max-width: 1500px;
                margin: auto;
                padding: 20px;
            }}
            .card {{
                background: #121a2d;
                padding: 20px;
                border-radius: 14px;
                margin-bottom: 20px;
            }}
            h1 {{ margin: 0 0 8px; }}
            .sub {{ color: #aeb8ca; }}
            .table-wrap {{ overflow-x: auto; }}
            table {{
                width: 100%;
                min-width: 1050px;
                border-collapse: collapse;
            }}
            th, td {{
                padding: 12px;
                border-bottom: 1px solid #27324a;
                text-align: left;
            }}
            th {{ background: #1a243b; }}
            a {{ color: #8ec5ff; text-decoration: none; }}
            .empty {{ text-align: center; padding: 30px; color: #aeb8ca; }}
            .badge {{
                display: inline-block;
                padding: 6px 10px;
                border-radius: 999px;
                background: #1d2a46;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>🚨 BSC Pre-Launch Radar V3</h1>
                <div class="sub">
                    Pre-contract-address intelligence and project discovery.
                    The dashboard refreshes every 60 seconds.
                </div>
                <p>
                    Projects tracked:
                    <strong>{len(projects)}</strong>
                </p>
            </div>

            <div class="card table-wrap">
                <table>
                    <tr>
                        <th>Project</th>
                        <th>Ticker</th>
                        <th>Stage</th>
                        <th>Score</th>
                        <th>Signals</th>
                        <th>Website</th>
                        <th>Telegram</th>
                        <th>X</th>
                        <th>CA Status</th>
                    </tr>
                    {rows}
                </table>
            </div>
        </div>
    </body>
    </html>
    """

    return html
