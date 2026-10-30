"""Opt-in local-time CRM briefing scheduler with durable, deduplicated delivery."""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _time(value: str):
    try:
        parsed = datetime.strptime(value, '%H:%M').time()
    except (TypeError, ValueError):
        raise ValueError('Quiet hours must use HH:MM') from None
    return parsed


def in_quiet_hours(local: datetime, start: str, end: str) -> bool:
    begin, finish = _time(start), _time(end)
    if begin == finish:
        raise ValueError('Quiet-hours start and end must differ')
    current = local.timetz().replace(tzinfo=None)
    if begin < finish:
        return begin <= current < finish
    return current >= begin or current < finish


def format_briefing(db: sqlite3.Connection, user_id: str, local_now: datetime, stale_days: int) -> str:
    today = local_now.date().isoformat()
    cutoff = (local_now.date() - timedelta(days=stale_days)).isoformat()
    due = db.execute('''SELECT f.id,c.name,f.note,f.due_date FROM followups f
        JOIN contacts c ON c.id=f.contact_id AND c.user_id=f.user_id
        WHERE f.user_id=? AND f.done=0 AND f.due_date<=? ORDER BY f.due_date,f.id LIMIT 20''',
        (user_id, today)).fetchall()
    stale = db.execute('''SELECT c.id,c.name,COALESCE(MAX(i.occurred_at),c.created_at) last_contact
        FROM contacts c LEFT JOIN interactions i ON i.contact_id=c.id AND i.user_id=c.user_id
        WHERE c.user_id=? GROUP BY c.id HAVING substr(last_contact,1,10)<=?
        ORDER BY last_contact LIMIT 20''', (user_id, cutoff)).fetchall()
    due_lines = [f"#{r['id']} {r['due_date']} {r['name']}: {r['note']}" for r in due]
    stale_lines = [f"#{r['id']} {r['name']}: last interaction {r['last_contact'][:10]}" for r in stale]
    return (f"CRM daily briefing for {today}\nDue or overdue follow-ups:\n"+
            ('\n'.join(due_lines) if due_lines else 'None')+
            f"\n\nNo interaction for {stale_days}+ days:\n"+
            ('\n'.join(stale_lines) if stale_lines else 'None'))[:3900]


def enqueue_due_briefings(db: sqlite3.Connection, now_utc: datetime | None = None) -> int:
    """Queue each enabled user's local-date briefing at most once; never sends."""
    instant = now_utc or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError('Scheduler time must be timezone-aware')
    instant = instant.astimezone(timezone.utc)
    db.execute('BEGIN IMMEDIATE')
    try:
        settings = db.execute('SELECT * FROM briefing_settings WHERE enabled=1 ORDER BY user_id').fetchall()
        queued = 0
        for setting in settings:
            try:
                local = instant.astimezone(ZoneInfo(setting['timezone']))
            except (ZoneInfoNotFoundError, ValueError):
                continue
            if in_quiet_hours(local, setting['quiet_start'], setting['quiet_end']):
                continue
            notification_key = f"daily-briefing:{local.date().isoformat()}"
            dedupe_key = f"{setting['user_id']}:{notification_key}"
            if db.execute('SELECT 1 FROM notification_log WHERE user_id=? AND notification_key=?',
                          (setting['user_id'], notification_key)).fetchone():
                continue
            if db.execute('SELECT 1 FROM telegram_outbox WHERE dedupe_key=?', (dedupe_key,)).fetchone():
                continue
            message = format_briefing(db, setting['user_id'], local, setting['stale_days'])
            raw_key = hashlib.sha256(dedupe_key.encode()).digest()[:8]
            synthetic_update_id = -(int.from_bytes(raw_key, 'big') & 0x7FFFFFFFFFFFFFFF or 1)
            cursor = db.execute('''INSERT OR IGNORE INTO telegram_outbox
                (update_id,sequence,chat_id,text,status,created_at,dedupe_key,notification_key)
                VALUES(?,0,?,?,'queued',?,?,?)''',
                (synthetic_update_id, setting['user_id'], message, instant.isoformat(), dedupe_key, notification_key))
            queued += cursor.rowcount
        db.commit()
        return queued
    except Exception:
        db.rollback()
        raise
