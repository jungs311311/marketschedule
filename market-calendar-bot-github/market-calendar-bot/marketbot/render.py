from __future__ import annotations

from datetime import date, datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .models import Event, Result, Session

KST = ZoneInfo('Asia/Seoul')
STATUS = {'open': '정상 개장', 'closed': '휴장', 'early_close': '조기 폐장',
          'changed': '거래시간 변경', 'unknown': '확인 불가'}


def _time_range(session: Session) -> str:
    if not session.open_at or not session.close_at:
        return ''
    opened = datetime.fromisoformat(session.open_at).astimezone(KST)
    closed = datetime.fromisoformat(session.close_at).astimezone(KST)
    next_day = '다음 날 ' if closed.date() > opened.date() else ''
    return f' · {opened:%H:%M}–{next_day}{closed:%H:%M} KST'


def _session_line(label: str, session: Session | None) -> str:
    if session is None:
        return f'{label}: 확인 불가 · 저장된 일정 없음'
    reason = '' if session.reason in ('정상 개장', STATUS.get(session.status)) else f' · {session.reason}'
    return f'{label}: {STATUS.get(session.status, session.status)}{reason}{_time_range(session)}'


def _event_lines(event: Event) -> list[str]:
    lines = ['', f'📌 {event.title}']
    lines.extend('• ' + detail for detail in event.details)
    return lines


def render(results: list[Result], day: date, slot: str) -> str:
    if slot not in ('morning', 'evening'):
        raise ValueError('slot은 morning 또는 evening이어야 합니다')
    sessions = {(s.market, s.date): s for r in results for s in r.sessions}
    events = [e for r in results for e in r.events
              if e.confirmed and e.trade_date == day.isoformat() and e.slot == slot]
    lines = ([f'[증시 일정 | {day.isoformat()} 08:00 KST]',
              _session_line('한국', sessions.get(('KR', day.isoformat()))),
              _session_line('일본', sessions.get(('JP', day.isoformat()))),
              _session_line(f'오늘 밤 미국 ({day.isoformat()} 현지)', sessions.get(('US', day.isoformat())))]
             if slot == 'morning' else
             [f'[미국장 일정 | {day.isoformat()} 21:00 KST]',
              f'대상 미국 거래일: {day.isoformat()}',
              _session_line('미국', sessions.get(('US', day.isoformat())))])
    for event in sorted(events, key=lambda e: (e.category, e.id)):
        lines.extend(_event_lines(event))

    sources = []
    relevant_sessions = [sessions.get((m, day.isoformat())) for m in (('KR', 'JP', 'US') if slot == 'morning' else ('US',))]
    for item in [x for x in relevant_sessions if x] + events:
        sources.extend(item.sources)
    unique = list(dict.fromkeys(sources))
    domains = list(dict.fromkeys((urlparse(u).hostname or u).removeprefix('www.') for u in unique))
    if domains:
        lines.extend(['', '출처: ' + ', '.join(domains[:8])])
    fetched = [datetime.fromisoformat(r.fetched_at).astimezone(KST) for r in results if r.fetched_at]
    if fetched:
        lines.append(f'마지막 갱신: {max(fetched):%Y-%m-%d %H:%M} KST')
    return '\n'.join(lines)[:4096]
