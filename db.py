hereimport sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "tracker.db"


def connect():
    c = sqlite3.connect(DB)
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

    # Safely add new columns to an existing database
    columns = {
        "liquidity": "REAL DEFAULT 0",
        "volume_24h": "REAL DEFAULT 0",
        "buys": "INTEGER DEFAULT 0",
        "sells": "INTEGER DEFAULT 0",
        "pair_age_minutes": "REAL DEFAULT 0",
        "dex_url": "TEXT DEFAULT ''"
    }

    existing = {
        row["name"]
        for row in c.execute("PRAGMA table_info(projects)").fetchall()
    }

    for name, definition in columns.items():
        if name not in existing:
            c.execute(
                f"ALTER TABLE projects ADD COLUMN {name} {definition}"
            )

    c.commit()
    c.close()


def upsert(p):
    c = connect()

    c.execute("""
        INSERT INTO projects(
            address,
            name,
            description,
            url,
            x_url,
            telegram_url,
            score,
            stage,
            liquidity,
            volume_24h,
            buys,
            sells,
            pair_age_minutes,
            dex_url
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)

        ON CONFLICT(address) DO UPDATE SET
            name=excluded.name,
            description=excluded.description,
            url=excluded.url,
            x_url=excluded.x_url,
            telegram_url=excluded.telegram_url,
            score=excluded.score,
            stage=excluded.stage,
            liquidity=excluded.liquidity,
            volume_24h=excluded.volume_24h,
            buys=excluded.buys,
            sells=excluded.sells,
            pair_age_minutes=excluded.pair_age_minutes,
            dex_url=excluded.dex_url,
            last_seen=CURRENT_TIMESTAMP
    """, (
        p["address"],
        p.get("name", ""),
        p.get("description", ""),
        p.get("url", ""),
        p.get("x_url", ""),
        p.get("telegram_url", ""),
        p.get("score", 0),
        p.get("stage", "EARLY"),
        p.get("liquidity", 0),
        p.get("volume_24h", 0),
        p.get("buys", 0),
        p.get("sells", 0),
        p.get("pair_age_minutes", 0),
        p.get("dex_url", "")
    ))

    c.commit()
    c.close()


def all_projects():
    c = connect()

    rows = c.execute("""
        SELECT *
        FROM projects
        ORDER BY score DESC, last_seen DESC
    """).fetchall()

    c.close()

    return [dict(x) for x in rows]
