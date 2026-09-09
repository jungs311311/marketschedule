from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Result


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS provider_cache (
          provider TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sent_messages (
          idempotency_key TEXT PRIMARY KEY, sent_at TEXT NOT NULL, message TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS changes (
          id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL,
          event_id TEXT NOT NULL, old_payload TEXT, new_payload TEXT NOT NULL,
          changed_at TEXT NOT NULL, notified_at TEXT
        );
        ''')
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(changes)')}
        if 'notified_at' not in columns:
            self.db.execute('ALTER TABLE changes ADD COLUMN notified_at TEXT')
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def get(self, provider: str) -> Result | None:
        row = self.db.execute('SELECT payload FROM provider_cache WHERE provider=?', (provider,)).fetchone()
        return Result.from_dict(json.loads(row[0])) if row else None

    def all(self) -> list[Result]:
        return [Result.from_dict(json.loads(r[0])) for r in
                self.db.execute('SELECT payload FROM provider_cache ORDER BY provider')]

    def put(self, result: Result) -> None:
        old = self.get(result.provider)
        old_events = {e.id: e.__dict__ for e in old.events} if old else {}
        now = datetime.now(timezone.utc).isoformat()
        for event in result.events:
            new_value = event.__dict__
            old_value = old_events.get(event.id)
            material = ('trade_date', 'slot', 'title', 'occurs_at', 'implementation_date',
                        'effective_date', 'confirmed')
            if old_value is not None and any(old_value.get(k) != new_value.get(k) for k in material):
                self.db.execute(
                    'INSERT INTO changes(provider,event_id,old_payload,new_payload,changed_at) VALUES(?,?,?,?,?)',
                    (result.provider, event.id, json.dumps(old_value, ensure_ascii=False),
                     json.dumps(new_value, ensure_ascii=False), now))
        self.db.execute('''INSERT INTO provider_cache(provider,payload,updated_at) VALUES(?,?,?)
                           ON CONFLICT(provider) DO UPDATE SET payload=excluded.payload,
                           updated_at=excluded.updated_at''',
                        (result.provider, json.dumps(result.to_dict(), ensure_ascii=False), now))
        self.db.commit()

    def was_sent(self, key: str) -> bool:
        return self.db.execute('SELECT 1 FROM sent_messages WHERE idempotency_key=?', (key,)).fetchone() is not None

    def mark_sent(self, key: str, message: str) -> None:
        self.db.execute('INSERT OR IGNORE INTO sent_messages VALUES(?,?,?)',
                        (key, datetime.now(timezone.utc).isoformat(), message))
        self.db.commit()

    def pending_corrections(self) -> list[tuple[int, dict, dict]]:
        rows = self.db.execute(
            'SELECT id,old_payload,new_payload FROM changes WHERE notified_at IS NULL ORDER BY id').fetchall()
        return [(row[0], json.loads(row[1]), json.loads(row[2])) for row in rows if row[1]]

    def mark_change_notified(self, change_id: int) -> None:
        self.db.execute('UPDATE changes SET notified_at=? WHERE id=?',
                        (datetime.now(timezone.utc).isoformat(), change_id))
        self.db.commit()


def merge_with_confirmed_cache(previous: Result | None, current: Result) -> Result:
    """Retain prior confirmed items when a current source returns unknown data."""
    if previous is None:
        return current
    current_sessions = {(s.market, s.date): s for s in current.sessions}
    reused = 0
    for old in previous.sessions:
        key = (old.market, old.date)
        new = current_sessions.get(key)
        if old.confirmed and (new is None or not new.confirmed):
            current_sessions[key] = old
            reused += 1
    current.sessions = sorted(current_sessions.values(), key=lambda s: (s.date, s.market))

    current_events = {e.id: e for e in current.events}
    for old in previous.events:
        new = current_events.get(old.id)
        scope_failed = old.category in current.failed_scopes
        if old.confirmed and ((new is not None and not new.confirmed) or (new is None and scope_failed)):
            current_events[old.id] = old
            reused += 1
    current.events = sorted(current_events.values(), key=lambda e: (e.trade_date, e.market, e.id))
    if reused:
        current.warnings.append(f'현재 확인 실패 항목 {reused}개에 이전의 공식 확인값을 유지했습니다.')
    return current
