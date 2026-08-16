import os,time,requests
from dotenv import load_dotenv
from .db import init_db,upsert
load_dotenv()
API="https://api.dexscreener.com/token-profiles/latest/v1"

def score_profile(p):
    score=10
    if p.get("description"): score+=10
    links=p.get("links") or []
    types={(x.get("type") or "").lower():x.get("url","") for x in links}
    if "website" in types or "web" in types: score+=10
    if "twitter" in types or "x" in types: score+=15
    if "telegram" in types: score+=15
    stage="HOT" if score>=60 else ("WATCH" if score>=45 else "EARLY")
    return min(score,100),stage,types

def scan():
    r=requests.get(API,timeout=20); r.raise_for_status()
    for p in r.json():
        if p.get("chainId")!="bsc" or not p.get("tokenAddress"): continue
        score,stage,links=score_profile(p)
        upsert({
          "address":p["tokenAddress"],
          "name":p.get("description") or p["tokenAddress"][:10],
          "description":p.get("description") or "",
          "url":p.get("url") or "",
          "x_url":links.get("twitter") or links.get("x") or "",
          "telegram_url":links.get("telegram") or "",
          "score":score,"stage":stage
        })

if __name__=="__main__":
    init_db()
    while True:
        try: scan()
        except Exception as e: print("scanner error:",e)
        time.sleep(int(os.getenv("SCAN_INTERVAL_SECONDS","120")))
