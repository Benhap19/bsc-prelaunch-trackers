"""SQLite persistence for BSC pre-launch and deployed projects."""

import sqlite3
from pathlib import Path

try:
    import config
except Exception:
    config = None


def _db_path() -> Path:
    raw = getattr(config, "DB_PATH", "radar_v3.db") if config else "radar_v3.db"
    path = Path(raw)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


DB = _db_path()


def connect():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = connect()
    c.execute("""
        CREATE TABLE IF NOT EXISTS projects(
            id INTEGER PRIMARY KEY,
            address TEXT UNIQUE NOT NULL,
            name TEXT,
            description TEXT,
            url TEXT,
            x_url TEXT,
            telegram_url TEXT,
            score INTEGER DEFAULT 0,
            stage TEXT DEFAULT 'EARLY',
            liquidity REAL DEFAULT 0,
            volume_24h REAL DEFAULT 0,
            buys INTEGER DEFAULT 0,
            sells INTEGER DEFAULT 0,
            pair_age_minutes REAL DEFAULT 0,
            dex_url TEXT DEFAULT '',
            first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
            last_seen TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS prelaunch_projects(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            symbol TEXT UNIQUE,
            description TEXT,
            website TEXT,
            x_url TEXT,
            telegram_url TEXT,
            launch_date TEXT,
            bsc_intent INTEGER DEFAULT 0,
            prelaunch_score INTEGER DEFAULT 0,
            stage TEXT DEFAULT 'EARLY',
            source TEXT,
            mentions INTEGER DEFAULT 1,
            contract_address TEXT DEFAULT '',
            deployer TEXT DEFAULT '',
            source_types TEXT DEFAULT '',
            confidence INTEGER DEFAULT 0,
            first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
            last_seen TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Safe migrations for databases created by earlier V3-V6 builds.
    for column, definition in (
        ("source_types", "TEXT DEFAULT ''"),
        ("confidence", "INTEGER DEFAULT 0"),
    ):
        try:
            c.execute(
                f"ALTER TABLE prelaunch_projects ADD COLUMN {column} {definition}"
            )
        except sqlite3.OperationalError:
            pass

    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_prelaunch_score
        ON prelaunch_projects(prelaunch_score)
    """)
    c.commit()
    c.close()


def upsert_prelaunch(p):
    symbol = (p.get("symbol") or p.get("name") or "UNKNOWN").strip().upper()[:64]
    c = connect()
    c.execute("""
        INSERT INTO prelaunch_projects(
            name, symbol, description, website, x_url, telegram_url,
            launch_date, bsc_intent, prelaunch_score, stage, source,
            mentions, contract_address, deployer, source_types, confidence
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE SET
            name=excluded.name,
            description=excluded.description,
            website=excluded.website,
            x_url=excluded.x_url,
            telegram_url=excluded.telegram_url,
            launch_date=excluded.launch_date,
            bsc_intent=excluded.bsc_intent,
            prelaunch_score=excluded.prelaunch_score,
            stage=excluded.stage,
            source=excluded.source,
            mentions=excluded.mentions,
            contract_address=excluded.contract_address,
            deployer=excluded.deployer,
            source_types=excluded.source_types,
            confidence=excluded.confidence,
            last_seen=CURRENT_TIMESTAMP
    """, (
        p.get("name", ""),
        symbol,
        p.get("description", ""),
        p.get("website", ""),
        p.get("x_url", ""),
        p.get("telegram_url", ""),
        p.get("launch_date", ""),
        1 if str(p.get("network", "BSC")).upper() == "BSC" else 0,
        int(p.get("score", p.get("prelaunch_score", 0)) or 0),
        p.get("stage", "EARLY"),
        p.get("source", ""),
        int(p.get("signal_count", p.get("mentions", 1)) or 1),
        p.get("contract_address", ""),
        p.get("deployer", ""),
        p.get("source_types", ""),
        int(p.get("confidence", p.get("score", 0)) or 0),
    ))
    c.commit()
    c.close()


def all_prelaunch():
    c = connect()
    rows = c.execute("""
        SELECT * FROM prelaunch_projects
        ORDER BY prelaunch_score DESC, last_seen DESC
    """).fetchall()
    c.close()
    return [dict(x) for x in rows]


def upsert(p):
    c = connect()
    c.execute("""
        INSERT INTO projects(
            address,name,description,url,x_url,telegram_url,score,stage,
            liquidity,volume_24h,buys,sells,pair_age_minutes,dex_url
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(address) DO UPDATE SET
            name=excluded.name, description=excluded.description,
            url=excluded.url, x_url=excluded.x_url,
            telegram_url=excluded.telegram_url, score=excluded.score,
            stage=excluded.stage, liquidity=excluded.liquidity,
            volume_24h=excluded.volume_24h, buys=excluded.buys,
            sells=excluded.sells, pair_age_minutes=excluded.pair_age_minutes,
            dex_url=excluded.dex_url, last_seen=CURRENT_TIMESTAMP
    """, (
        p["address"], p.get("name",""), p.get("description",""),
        p.get("url",""), p.get("x_url",""), p.get("telegram_url",""),
        p.get("score",0), p.get("stage","EARLY"), p.get("liquidity",0),
        p.get("volume_24h",0), p.get("buys",0), p.get("sells",0),
        p.get("pair_age_minutes",0), p.get("dex_url","")
    ))
    c.commit()
    c.close()


def all_projects():
    c = connect()
    rows = c.execute("SELECT * FROM projects ORDER BY score DESC, last_seen DESC").fetchall()
    c.close()
    return [dict(x) for x in rows]

