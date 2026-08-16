import sqlite3
from pathlib import Path
DB=Path(__file__).resolve().parent.parent/"tracker.db"

def connect():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def init_db():
    c=connect()
    c.execute('''CREATE TABLE IF NOT EXISTS projects(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      address TEXT UNIQUE NOT NULL, name TEXT, description TEXT, url TEXT,
      x_url TEXT, telegram_url TEXT, score INTEGER DEFAULT 0,
      stage TEXT DEFAULT 'EARLY', first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
      last_seen TEXT DEFAULT CURRENT_TIMESTAMP)''')
    c.commit(); c.close()

def upsert(p):
    c=connect()
    c.execute('''INSERT INTO projects(address,name,description,url,x_url,telegram_url,score,stage)
    VALUES(?,?,?,?,?,?,?,?)
    ON CONFLICT(address) DO UPDATE SET name=excluded.name,
    description=excluded.description,url=excluded.url,x_url=excluded.x_url,
    telegram_url=excluded.telegram_url,score=excluded.score,
    stage=excluded.stage,last_seen=CURRENT_TIMESTAMP''',
    (p["address"],p["name"],p["description"],p["url"],p["x_url"],p["telegram_url"],p["score"],p["stage"]))
    c.commit(); c.close()

def all_projects():
    c=connect()
    rows=c.execute("SELECT * FROM projects ORDER BY score DESC,last_seen DESC").fetchall()
    c.close(); return [dict(x) for x in rows]
