"""Small SQLite schema migration runner; migrations are additive and versioned."""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone


def _v1(db: sqlite3.Connection) -> None:
    db.executescript('''
    CREATE TABLE IF NOT EXISTS contacts(id INTEGER PRIMARY KEY,user_id TEXT NOT NULL,name TEXT NOT NULL,email TEXT,organization TEXT,notes TEXT DEFAULT '',created_at TEXT NOT NULL, UNIQUE(user_id,email));
    CREATE TABLE IF NOT EXISTS interactions(id INTEGER PRIMARY KEY,user_id TEXT NOT NULL,contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,note TEXT NOT NULL,occurred_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS followups(id INTEGER PRIMARY KEY,user_id TEXT NOT NULL,contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,note TEXT NOT NULL,due_date TEXT NOT NULL,done INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,user_id TEXT NOT NULL,event TEXT NOT NULL,entity_id INTEGER,created_at TEXT NOT NULL);
    ''')


def _v2(db: sqlite3.Connection) -> None:
    db.executescript('''
    CREATE TABLE IF NOT EXISTS tags(id INTEGER PRIMARY KEY,user_id TEXT NOT NULL,name TEXT NOT NULL,UNIQUE(user_id,name));
    CREATE TABLE IF NOT EXISTS contact_tags(contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,PRIMARY KEY(contact_id,tag_id));
    CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY,user_id TEXT NOT NULL,name TEXT NOT NULL,description TEXT DEFAULT '',UNIQUE(user_id,name));
    CREATE TABLE IF NOT EXISTS contact_projects(contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,PRIMARY KEY(contact_id,project_id));
    CREATE TABLE IF NOT EXISTS organizations(id INTEGER PRIMARY KEY,user_id TEXT NOT NULL,name TEXT NOT NULL,notes TEXT DEFAULT '',UNIQUE(user_id,name));
    CREATE TABLE IF NOT EXISTS pending_actions(user_id TEXT PRIMARY KEY,action_json TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS telegram_updates(update_id INTEGER PRIMARY KEY,processed_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS notification_log(user_id TEXT NOT NULL,notification_key TEXT NOT NULL,sent_at TEXT NOT NULL,PRIMARY KEY(user_id,notification_key));
    ''')


def _v3(db: sqlite3.Connection) -> None:
    db.executescript('''CREATE TABLE IF NOT EXISTS bot_updates(update_id INTEGER PRIMARY KEY,processed_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS telegram_outbox(id INTEGER PRIMARY KEY,update_id INTEGER NOT NULL,sequence INTEGER NOT NULL,chat_id TEXT NOT NULL,text TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',created_at TEXT NOT NULL,sent_at TEXT,UNIQUE(update_id,sequence));''')


def _v4(db: sqlite3.Connection) -> None:
    columns = {row[1] for row in db.execute('PRAGMA table_info(telegram_outbox)')}
    for name, declaration in (
        ('attempt_count', 'INTEGER NOT NULL DEFAULT 0'),
        ('dedupe_key', 'TEXT'),
        ('notification_key', 'TEXT'),
    ):
        if name not in columns:
            db.execute(f'ALTER TABLE telegram_outbox ADD COLUMN {name} {declaration}')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS telegram_outbox_dedupe_key ON telegram_outbox(dedupe_key)')
    db.execute('''CREATE TABLE IF NOT EXISTS briefing_settings(
        user_id TEXT PRIMARY KEY,timezone TEXT NOT NULL,quiet_start TEXT NOT NULL DEFAULT '22:00',
        quiet_end TEXT NOT NULL DEFAULT '08:00',stale_days INTEGER NOT NULL DEFAULT 90,
        enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)))''')

def connect(path) -> sqlite3.Connection:
    db=sqlite3.connect(path); db.row_factory=sqlite3.Row; db.execute('PRAGMA foreign_keys=ON'); db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA busy_timeout=5000')
    db.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL)')
    current=db.execute('SELECT COALESCE(MAX(version),0) FROM schema_migrations').fetchone()[0]
    for version,migration in enumerate((_v1,_v2,_v3,_v4),1):
        if version>current:
            migration(db); db.execute('INSERT INTO schema_migrations VALUES(?,?)',(version,datetime.now(timezone.utc).isoformat())); db.commit()
    return db
