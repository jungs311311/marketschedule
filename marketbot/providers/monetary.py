"""Official monetary-policy calendars and New York DST transitions.

Dates are discovered afresh. Annual meetings, minutes and financial-stability
meetings are deliberately not interchangeable with interest-rate decisions.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from ..http import HttpClient
from ..models import Event, Result

BOK_URL = 'https://www.bok.or.kr/portal/singl/crncyPolicyDrcMtg/listYear.do?menuNo=200755&mtgSe=A'
FED_URL = 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm'
NIST_URL = 'https://www.nist.gov/pml/time-and-frequency-division/popular-links/daylight-saving-time-dst'
MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_name) if name}
KST = ZoneInfo('Asia/Seoul')
NY = ZoneInfo('America/New_York')


def parse_fomc(html: str) -> dict[int, list[date]]:
    """Parse year panels, never infer a year from unrelated footer text."""
    soup = BeautifulSoup(html, 'html.parser')
    found: dict[int, list[date]] = {}
    for heading in soup.find_all(re.compile(r'^h[1-6]$')):
        match = re.fullmatch(r'(20\d{2})\s+FOMC Meetings', heading.get_text(' ', strip=True))
        if not match:
            continue
        year = int(match[1])
        panel = heading.find_parent(class_='panel')
        if panel is None:
            panel = heading.parent.parent
        dates: list[date] = []
        for row in panel.select('.fomc-meeting'):
            month_node = row.select_one('.fomc-meeting__month')
            days_node = row.select_one('.fomc-meeting__date')
            if month_node is None or days_node is None:
                continue
            month_text = month_node.get_text(' ', strip=True).lower()
            month = MONTHS.get(month_text)
            days_text = days_node.get_text(' ', strip=True).replace('*', '').strip()
            # Unscheduled conferences and notation changes are not silently
            # treated as regular policy decisions.
            days_match = re.fullmatch(r'(\d{1,2})\s*[-–]\s*(\d{1,2})', days_text)
            if month and days_match:
                dates.append(date(year, month, int(days_match[2])))
        if len(set(dates)) >= 6:
            found[year] = sorted(set(dates))
    if not found:
        raise ValueError('FOMC 연도별 정례회의 표를 찾지 못했습니다')
    return found


def parse_bok(html: str, requested_year: int) -> list[date]:
    soup = BeautifulSoup(html, 'html.parser')
    year_headings = [h for h in soup.find_all(re.compile(r'^h[1-6]$'))
                     if re.fullmatch(fr'{requested_year}\s*년', h.get_text(' ', strip=True))]
    if not year_headings:
        raise ValueError(f'한국은행 {requested_year}년 일정 제목을 확인할 수 없습니다')
    dates: set[date] = set()
    for table in soup.find_all('table'):
        caption = table.find('caption')
        label = caption.get_text(' ', strip=True) if caption else ''
        text = table.get_text(' ', strip=True)
        if '통화정책방향' not in label and not ('회의일자' in text and '결정문' in text):
            continue
        for row in table.find_all('tr'):
            cell = row.find(['td', 'th'])
            if not cell:
                continue
            match = re.fullmatch(r'(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*\([월화수목금토일]\)',
                                 cell.get_text(' ', strip=True))
            if match:
                dates.add(date(requested_year, int(match[1]), int(match[2])))
    if len(dates) < 6:
        raise ValueError(f'한국은행 {requested_year}년 통화정책방향 표 파싱 실패')
    return sorted(dates)


def fomc_event(day: date, time_verified: bool, time_source: str | None = None) -> Event:
    when = datetime.combine(day, time(14), NY).astimezone(KST) if time_verified else None
    details = [f'미국 결정일 {day.isoformat()} · 정례회의 마지막 날']
    if when:
        details.append(f'내일 새벽 금리 결정 {when:%Y-%m-%d %H:%M} KST (14:00 ET)')
        details.append(f'기자회견 {when + timedelta(minutes=30):%Y-%m-%d %H:%M} KST (14:30 ET)')
    else:
        details.append('회의일 확인 완료 · 해당 월 공식 발표 시각은 확인하지 못했습니다')
    return Event(id=f'fomc:{day}', category='fomc', title='FOMC 금리 결정', market='US',
                 trade_date=day.isoformat(), slot='evening', phase='rate_decision',
                 occurs_at=when.isoformat() if when else None, details=details,
                 sources=[FED_URL] + ([time_source] if time_source else []))


def dst_events(year: int, rule_text: str) -> list[Event]:
    text = ' '.join(rule_text.lower().split())
    if not ('second sunday' in text and 'march' in text and
            'first sunday' in text and 'november' in text):
        raise ValueError('NIST 서머타임 시작·종료 규칙 검증 실패')
    events = []
    for month, nth, start in [(3, 2, True), (11, 1, False)]:
        day = date(year, month, 1)
        day += timedelta(days=(6 - day.weekday()) % 7 + 7 * (nth - 1))
        # DST starts at 02:00 EST (a nonexistent local wall time); using UTC
        # from the instant just before transition avoids ambiguous attachment.
        before = datetime.combine(day, time(1, 59, 59), NY)
        if not start:
            before = before.replace(fold=0)
        utc_transition = before.astimezone(ZoneInfo('UTC')) + timedelta(seconds=1)
        after = utc_transition.astimezone(NY)
        if (start and after.hour != 3) or (not start and after.hour != 1):
            raise ValueError('NIST 규칙과 설치된 시간대 데이터가 일치하지 않습니다')
        when = utc_transition.astimezone(KST)
        title = '미국 서머타임 시작' if start else '미국 서머타임 종료'
        hours = ('23:30–다음 날 06:00 → 22:30–다음 날 05:00' if start else
                 '22:30–다음 날 05:00 → 23:30–다음 날 06:00')
        events.append(Event(id=f'dst:{year}:{"start" if start else "end"}', category='dst',
                            title=title, market='US', trade_date=when.date().isoformat(),
                            slot='morning', occurs_at=when.isoformat(),
                            details=[f'오늘 {when:%H:%M} KST 뉴욕 시계 변경 예정',
                                     f'다음 미국 정규 거래일부터 한국시간 {hours}',
                                     '조기폐장·임시 거래시간 변경은 해당일 시장 안내 우선'],
                            sources=[NIST_URL, 'https://www.nyse.com/trade/hours-calendars']))
    return events


def collect(client: HttpClient, start: date, end: date) -> Result:
    result = Result(provider='monetary', coverage_start=start.isoformat(), coverage_end=end.isoformat())
    try:
        schedule = parse_fomc(client.get_text(FED_URL))
        absent = set(range(start.year, end.year + 1)) - schedule.keys()
        for year, days in schedule.items():
            for day in days:
                if not start <= day <= end:
                    continue
                url = f'https://www.federalreserve.gov/newsevents/{year}-{calendar.month_name[day.month].lower()}.htm'
                verified = False
                try:
                    text = client.get_soup(url).get_text(' ', strip=True)
                    verified = bool(re.search(r'2:00\s*p\.m\.\s*FOMC Meeting', text) and
                                    re.search(r'2:30\s*p\.m\.\s*FOMC Press Conference', text))
                except Exception:
                    pass
                if not verified:
                    result.warnings.append(f'FOMC {day}: 공식 발표 시각 미확인')
                result.events.append(fomc_event(day, verified, url if verified else None))
        result.sources.append(FED_URL)
        if absent:
            result.warnings.append(f'FOMC 아직 확인되지 않은 연도: {sorted(absent)}')
            result.failed_scopes.append('fomc')
        else:
            result.successful_scopes.append('fomc')
    except Exception as exc:
        result.failed_scopes.append('fomc')
        result.warnings.append(f'FOMC 수집 실패: {type(exc).__name__}: {exc}')

    bok_ok = True
    for year in range(start.year, end.year + 1):
        url = BOK_URL + f'&year={year}'
        try:
            days = parse_bok(client.get_text(url), year)
            result.sources.append(url)
            for day in days:
                if start <= day <= end:
                    result.events.append(Event(id=f'bok:{day}', category='bok',
                                               title='한국은행 기준금리 결정회의', market='KR',
                                               trade_date=day.isoformat(), slot='morning', phase='rate_decision',
                                               details=['통화정책방향 결정회의 · 발표 시각은 당일 한국은행 공지 확인'],
                                               sources=[url]))
        except Exception as exc:
            bok_ok = False
            result.warnings.append(f'한국은행 {year}년 수집 실패: {type(exc).__name__}: {exc}')
    (result.successful_scopes if bok_ok else result.failed_scopes).append('bok')

    try:
        rule_text = client.get_soup(NIST_URL).get_text(' ', strip=True)
        for year in range(start.year, end.year + 1):
            result.events.extend(e for e in dst_events(year, rule_text)
                                 if start.isoformat() <= e.trade_date <= end.isoformat())
        result.sources.append(NIST_URL)
        result.successful_scopes.append('dst')
    except Exception as exc:
        result.failed_scopes.append('dst')
        result.warnings.append(f'서머타임 수집 실패: {type(exc).__name__}: {exc}')
    return result
