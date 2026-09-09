"""GitHub Actions처럼 실행마다 디스크가 초기화되는 환경을 위한 상태 스냅샷.

sqlite 파일 자체를 저장소에 커밋하면 바이너리라 이력이 커진다.
그래서 사람이 읽을 수 있는 JSON 한 개로 내보내고, 다음 실행에서 되읽는다.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SESSION_PAST_DAYS = 30
SESSION_FUTURE_DAYS = 400
SENT_KEEP_DAYS = 120
CHANGE_KEEP_DAYS = 120


def _trim(payload: dict, today: date) -> dict:
    """개장·휴장 세션은 알림에 필요한 구간만 남긴다. 나머지는 갱신 때 다시 만든다."""
    left = (today - timedelta(days=SESSION_PAST_DAYS)).isoformat()
    right = (today + timedelta(days=SESSION_FUTURE_DAYS)).isoformat()
    trimmed = dict(payload)
    trimmed['sessions'] = [s for s in payload.get('sessions', [])
                           if left <= str(s.get('date', '')) <= right]
    return trimmed


def export_state(db: sqlite3.Connection, path: str | Path,
                 today: date | None = None) -> Path:
    today = today or datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc)
    sent_cutoff = (now - timedelta(days=SENT_KEEP_DAYS)).isoformat()
    change_cutoff = (now - timedelta(days=CHANGE_KEEP_DAYS)).isoformat()

    state = {
        'version': 1,
        'exported_at': now.isoformat(),
        'provider_cache': [
            {'provider': provider, 'updated_at': updated_at,
             'payload': _trim(json.loads(payload), today)}
            for provider, payload, updated_at in db.execute(
                'SELECT provider,payload,updated_at FROM provider_cache ORDER BY provider')
        ],
        'sent_messages': [
            {'idempotency_key': key, 'sent_at': sent_at}
            for key, sent_at in db.execute(
                'SELECT idempotency_key,sent_at FROM sent_messages '
                'WHERE sent_at>=? ORDER BY sent_at', (sent_cutoff,))
        ],
        'changes': [
            {'id': row[0], 'provider': row[1], 'event_id': row[2],
             'old_payload': row[3], 'new_payload': row[4],
             'changed_at': row[5], 'notified_at': row[6]}
            for row in db.execute(
                'SELECT id,provider,event_id,old_payload,new_payload,changed_at,notified_at '
                'FROM changes WHERE notified_at IS NULL OR changed_at>=? ORDER BY id',
                (change_cutoff,))
        ],
    }
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(state, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return file


def import_state(db: sqlite3.Connection, path: str | Path) -> bool:
    file = Path(path)
    if not file.exists() or not file.read_text(encoding='utf-8').strip():
        return False
    state = json.loads(file.read_text(encoding='utf-8'))

    for item in state.get('provider_cache', []):
        db.execute('''INSERT INTO provider_cache(provider,payload,updated_at) VALUES(?,?,?)
                      ON CONFLICT(provider) DO UPDATE SET payload=excluded.payload,
                      updated_at=excluded.updated_at''',
                   (item['provider'], json.dumps(item['payload'], ensure_ascii=False),
                    item['updated_at']))
    for item in state.get('sent_messages', []):
        db.execute('INSERT OR IGNORE INTO sent_messages VALUES(?,?,?)',
                   (item['idempotency_key'], item['sent_at'], '(본문 보관 생략)'))
    for item in state.get('changes', []):
        db.execute('''INSERT INTO changes(id,provider,event_id,old_payload,new_payload,
                      changed_at,notified_at) VALUES(?,?,?,?,?,?,?)
                      ON CONFLICT(id) DO NOTHING''',
                   (item['id'], item['provider'], item['event_id'], item['old_payload'],
                    item['new_payload'], item['changed_at'], item['notified_at']))
    db.commit()
    return True
