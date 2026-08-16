from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from db import init_db,all_projects

app=FastAPI(title="BSC Pre-Launch Tracker")
init_db()

@app.get("/api/projects")
def projects():
    return all_projects()

@app.get("/",response_class=HTMLResponse)
def dashboard():
    rows=all_projects()
    body=""
    for p in rows:
        body += f"<tr><td>{p['name']}</td><td>{p['stage']}</td><td>{p['score']}</td>"
        body += f"<td><a href='{p['url']}' target='_blank'>DexScreener</a></td>"
        body += f"<td><a href='https://bscscan.com/token/{p['address']}' target='_blank'>BscScan</a></td></tr>"
    html='''<!doctype html><html><head><meta charset="utf-8"><title>BSC Tracker</title>
<style>body{font-family:Arial;max-width:1100px;margin:40px auto}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #ddd}</style>
</head><body><h1>BSC Pre-Launch Tracker</h1>
<p>Public-signal discovery dashboard. Not an investment signal.</p>
<table><tr><th>Project</th><th>Stage</th><th>Score</th><th>Market</th><th>Explorer</th></tr>''' + body + '''</table></body></html>'''
    return html
