from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from marketbot.models import Event, Result, Session
from marketbot.snapshot import export_state, import_state
from marketbot.storage import Store
from marketbot.__main__ import resolve_slot

TODAY = date(2026, 9, 9)


def _sample() -> Result:
    return Result(
        provider='markets',
        events=[Event(id='fomc-2026-09-16', category='fomc', title='FOMC 금리 결정',
                      market='US', trade_date='2026-09-16', slot='evening')],
        sessions=[
            Session('KR', TODAY.isoformat(), 'open', '정상 개장'),
            Session('KR', (TODAY + timedelta(days=900)).isoformat(), 'open', '정상 개장'),
        ],
    )


def test_export_import_roundtrip(tmp_path):
    path = tmp_path / 'state.json'
    first = Store(tmp_path / 'a.sqlite3')
    first.put(_sample())
    first.mark_sent('2026-09-09:morning', '보낸 메시지')
    export_state(first.db, path, TODAY)
    first.close()

    second = Store(tmp_path / 'b.sqlite3')
    assert import_state(second.db, path) is True
    restored = second.get('markets')
    assert restored is not None
    assert [e.id for e in restored.events] == ['fomc-2026-09-16']
    # 발송 이력이 살아 있어야 재시작 후 중복 발송을 막는다.
    assert second.was_sent('2026-09-09:morning') is True
    assert second.was_sent('2026-09-09:evening') is False
    # 알림에 쓰이지 않는 먼 미래 세션은 잘라내 파일 크기를 줄인다.
    dates = {s.date for s in restored.sessions}
    assert TODAY.isoformat() in dates
    assert (TODAY + timedelta(days=900)).isoformat() not in dates
    second.close()


def test_import_without_file(tmp_path):
    store = Store(tmp_path / 'c.sqlite3')
    assert import_state(store.db, tmp_path / 'missing.json') is False
    store.close()


def test_resolve_slot_uses_korean_hour():
    kst = timezone(timedelta(hours=9))
    assert resolve_slot('auto', datetime(2026, 9, 9, 8, 5, tzinfo=kst)) == 'morning'
    assert resolve_slot('auto', datetime(2026, 9, 9, 21, 5, tzinfo=kst)) == 'evening'
    # 실행이 늦어져도 지정한 슬롯은 그대로 유지한다.
    assert resolve_slot('morning', datetime(2026, 9, 9, 21, 5, tzinfo=kst)) == 'morning'
