import threading

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from db import init_db, all_projects
from scanner import run


app = FastAPI(
    title="BSC Pre-Launch Radar",
    description="BSC project discovery and alert system"
)


init_db()


def start_scanner():
    thread = threading.Thread(
        target=run,
        daemon=True
    )

    thread.start()


@app.on_event("startup")
def startup_event():
    start_scanner()


@app.get("/api/projects")
def projects():
    return all_projects()


@app.get("/", response_class=HTMLResponse)
def dashboard():

    projects = all_projects()

    body = ""

    for project in projects:

        body += f"""
        <tr>
            <td>{project['name']}</td>

            <td>
                <strong>{project['stage']}</strong>
            </td>

            <td>
                <strong>{project['score']}/100</strong>
            </td>

            <td>
                <a href="{project['url']}" target="_blank">
                    DexScreener
                </a>
            </td>

            <td>
                <a href="https://bscscan.com/token/{project['address']}"
                   target="_blank">
                    BscScan
                </a>
            </td>

            <td>
                {project['x_url'] or '-'}
            </td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>

    <html>

    <head>

        <meta charset="UTF-8">

        <meta name="viewport"
              content="width=device-width, initial-scale=1">

        <title>BSC Pre-Launch Radar</title>

        <style>

            body {{
                font-family: Arial, sans-serif;
                margin: 20px;
                background: #f5f5f5;
            }}

            .container {{
                max-width: 1200px;
                margin: auto;
            }}

            h1 {{
                margin-bottom: 5px;
            }}

            .card {{
                background: white;
                padding: 20px;
                border-radius: 12px;
                margin-bottom: 20px;
            }}

            table {{
                width: 100%;
                border-collapse: collapse;
                background: white;
            }}

            th, td {{
                padding: 12px;
                border-bottom: 1px solid #ddd;
                text-align: left;
            }}

            th {{
                background: #111;
                color: white;
            }}

            a {{
                text-decoration: none;
            }}

        </style>

    </head>

    <body>

        <div class="container">

            <div class="card">

                <h1>🚀 BSC Pre-Launch Radar</h1>

                <p>
                    Automated BSC project discovery and scoring.
                </p>

                <p>
                    Projects tracked:
                    <strong>{len(projects)}</strong>
                </p>

            </div>


            <div class="card">

                <table>

                    <tr>
                        <th>Project</th>
                        <th>Stage</th>
                        <th>Score</th>
                        <th>DEX</th>
                        <th>Contract</th>
                        <th>X</th>
                    </tr>

                    {body}

                </table>

            </div>

        </div>

    </body>

    </html>
    """

    return html
