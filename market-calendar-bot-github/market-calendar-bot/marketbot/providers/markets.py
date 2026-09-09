"""Official cash-equity market sessions for Korea, the U.S. and Japan."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from ..http import HttpClient
from ..models import Result, Session

NYSE_URL = 'https://www.nyse.com/trade/hours-calendars'
NASDAQ_URL = 'https://www.nasdaqtrader.com/Trader.aspx?id=Calendar'
JPX_URL = 'https://www.jpx.co.jp/english/corporate/about-jpx/calendar/'
KRX_PAGE = 'https://open.krx.co.kr/contents/MKD/01/0110/01100305/MKD01100305.jsp'
KRX_OTP = 'https://open.krx.co.kr/contents/COM/GenerateOTP.jspx'
KRX_DATA = 'https://open.krx.co.kr/contents/OPN/99/OPN99000001.jspx'

KST = ZoneInfo('Asia/Seoul')
NY = ZoneInfo('America/New_York')
TOKYO = ZoneInfo('Asia/Tokyo')
EN_MONTHS = {name[:3].lower(): i for i, name in enumerate(
             ('', 'January', 'February', 'March', 'April', 'May', 'June',
              'July', 'August', 'September', 'October', 'November', 'December')) if name}


def _aware(day: date, value: time, zone: ZoneInfo) -> str:
    return datetime.combine(day, value, zone).isoformat()


def _english_date(value: str, year: int | None = None) -> date:
    value = re.sub(r'\([^)]*\)|[*†‡]+', '', value).strip().replace(',', '')
    match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z.]*\s+(\d{1,2})(?:\s+(20\d{2}))?', value, re.I)
    if not match or (not year and not match[3]):
        raise ValueError('영문 날짜 형식 불일치')
    return date(int(match[3]) if match[3] else int(year), EN_MONTHS[match[1][:3].lower()], int(match[2]))


def parse_nyse(html: str) -> tuple[dict[int, dict[date, tuple[str, str]]], set[int]]:
    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table')
    if not tables:
        raise ValueError('NYSE 휴장 표 없음')
    rows = tables[0].find_all('tr')
    headers = [c.get_text(' ', strip=True) for c in rows[0].find_all(['th', 'td'])]
    years = [int(x) for x in headers[1:] if re.fullmatch(r'20\d{2}', x)]
    if not years:
        raise ValueError('NYSE 휴장 연도 없음')
    result = {year: {} for year in years}
    for row in rows[1:]:
        cells = [c.get_text(' ', strip=True) for c in row.find_all(['th', 'td'])]
        if len(cells) < len(years) + 1:
            continue
        reason = cells[0]
        for year, value in zip(years, cells[1:]):
            try:
                day = _english_date(value, year)
            except ValueError:
                continue
            result[year][day] = ('closed', reason)

    # Early-close dates are maintained in official footnotes outside the table.
    for node in soup.find_all(['p', 'li']):
        text_value = node.get_text(' ', strip=True)
        if not re.search(r'close early at 1:00 p\.m\.', text_value, re.I):
            continue
        for raw in re.findall(r'(?:Monday|Tuesday|Wednesday|Thursday|Friday),\s+[A-Z][a-z]+\s+\d{1,2},\s+20\d{2}', text_value):
            day = _english_date(raw)
            if day.year in result:
                result[day.year][day] = ('early_close', '미국 주식시장 조기폐장(13:00 ET)')
    return result, set(years)


def parse_nasdaq(html: str) -> dict[date, tuple[str, str]]:
    soup = BeautifulSoup(html, 'html.parser')
    found: dict[date, tuple[str, str]] = {}
    for row in soup.find_all('tr'):
        cells = [c.get_text(' ', strip=True) for c in row.find_all(['th', 'td'])]
        if len(cells) != 3:
            continue
        try:
            day = _english_date(cells[0])
        except ValueError:
            continue
        status = 'closed' if cells[2].lower() == 'closed' else 'early_close' if '1:00' in cells[2] else None
        if status:
            found[day] = (status, cells[1])
    if not found:
        raise ValueError('Nasdaq 휴장 표 없음')
    return found


def parse_jpx(html: str) -> tuple[dict[int, dict[date, str]], set[int]]:
    soup = BeautifulSoup(html, 'html.parser')
    result: dict[int, dict[date, str]] = {}
    for heading in soup.find_all('h2'):
        label = heading.get_text(' ', strip=True)
        if not re.fullmatch(r'20\d{2}', label):
            continue
        year = int(label)
        container = heading.parent.find_next_sibling()
        if not container:
            continue
        days: dict[date, str] = {}
        for row in container.find_all('tr'):
            cells = [c.get_text(' ', strip=True) for c in row.find_all(['th', 'td'])]
            if len(cells) < 2:
                continue
            try:
                day = _english_date(cells[0], year)
            except ValueError:
                continue
            days[day] = cells[1]
        if len(days) >= 10:
            result[year] = days
    if not result:
        raise ValueError('JPX 연도별 휴장 표 없음')
    return result, set(result)


def fetch_krx(client: HttpClient, year: int) -> dict[date, str]:
    headers = {'Referer': KRX_PAGE}
    query = ('?bld=MKD%2F01%2F0110%2F01100305%2Fmkd01100305_01&name=form')
    code = client.get_text(KRX_OTP + query, headers=headers).strip()
    if not code or len(code) > 500 or not re.fullmatch(r'[A-Za-z0-9+/=]+', code):
        raise ValueError('KRX OTP 응답 불일치')
    raw = client.post_form(KRX_DATA, {
        'search_bas_yy': str(year), 'gridTp': 'KRX',
        'pagePath': '/contents/MKD/01/0110/01100305/MKD01100305.jsp',
        'code': code, 'pageFirstCall': 'Y',
    }, headers=headers)
    data = json.loads(raw).get('block1')
    if not isinstance(data, list) or len(data) < 8:
        raise ValueError(f'KRX {year}년 공식 휴장 자료 미발표 또는 형식 변경')
    found = {}
    for item in data:
        day = date.fromisoformat(item['calnd_dd'])
        if day.year == year:
            found[day] = item.get('holdy_nm') or '휴장'
    return found


def _make_sessions(market: str, start: date, end: date, available: bool,
                   holidays: dict[date, tuple[str, str]] | dict[date, str],
                   source: str) -> list[Session]:
    zone, open_time, close_time = {
        'KR': (KST, time(9), time(15, 30)),
        'US': (NY, time(9, 30), time(16)),
        'JP': (TOKYO, time(9), time(15, 30)),
    }[market]
    sessions = []
    day = start
    while day <= end:
        if not available:
            sessions.append(Session(market, day.isoformat(), 'unknown', '공식 연간 일정 미발표 또는 수집 실패', sources=[source], confirmed=False))
        elif day.weekday() >= 5:
            sessions.append(Session(market, day.isoformat(), 'closed', '주말', sources=[source]))
        elif day in holidays:
            value = holidays[day]
            status, reason = value if isinstance(value, tuple) else ('closed', value)
            close = time(13) if status == 'early_close' else close_time
            sessions.append(Session(market, day.isoformat(), status, reason,
                                    _aware(day, open_time, zone) if status != 'closed' else None,
                                    _aware(day, close, zone) if status != 'closed' else None,
                                    [source]))
        else:
            sessions.append(Session(market, day.isoformat(), 'open', '정상 개장',
                                    _aware(day, open_time, zone), _aware(day, close_time, zone), [source]))
        day += timedelta(days=1)
    return sessions


def collect(client: HttpClient, start: date, end: date) -> Result:
    if end < start:
        raise ValueError('end must not precede start')
    result = Result(provider='markets', coverage_start=start.isoformat(), coverage_end=end.isoformat())

    try:
        nyse, years = parse_nyse(client.get_text(NYSE_URL))
        result.sources.append(NYSE_URL)
        try:
            nasdaq = parse_nasdaq(client.get_text(NASDAQ_URL))
            result.sources.append(NASDAQ_URL)
            for day, status in nasdaq.items():
                if day.year in years and nyse[day.year].get(day) and nyse[day.year][day][0] != status[0]:
                    raise ValueError(f'NYSE/Nasdaq 상태 불일치: {day}')
        except Exception as exc:
            result.warnings.append(f'Nasdaq 교차검증 실패: {type(exc).__name__}: {exc}')
        for year in range(start.year, end.year + 1):
            left, right = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
            result.sessions.extend(_make_sessions('US', left, right, year in years, nyse.get(year, {}), NYSE_URL))
        (result.successful_scopes if set(range(start.year, end.year + 1)) <= years else result.failed_scopes).append('US')
    except Exception as exc:
        result.failed_scopes.append('US')
        result.warnings.append(f'미국시장 일정 수집 실패: {type(exc).__name__}: {exc}')
        result.sessions.extend(_make_sessions('US', start, end, False, {}, NYSE_URL))

    try:
        jpx, years = parse_jpx(client.get_text(JPX_URL))
        result.sources.append(JPX_URL)
        for year in range(start.year, end.year + 1):
            left, right = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
            result.sessions.extend(_make_sessions('JP', left, right, year in years, jpx.get(year, {}), JPX_URL))
        (result.successful_scopes if set(range(start.year, end.year + 1)) <= years else result.failed_scopes).append('JP')
    except Exception as exc:
        result.failed_scopes.append('JP')
        result.warnings.append(f'일본시장 일정 수집 실패: {type(exc).__name__}: {exc}')
        result.sessions.extend(_make_sessions('JP', start, end, False, {}, JPX_URL))

    krx_ok = True
    for year in range(start.year, end.year + 1):
        left, right = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
        try:
            holidays = fetch_krx(client, year)
            result.sessions.extend(_make_sessions('KR', left, right, True, holidays, KRX_PAGE))
            result.sources.append(KRX_PAGE)
        except Exception as exc:
            krx_ok = False
            result.warnings.append(f'한국시장 {year}년 일정 수집 실패: {type(exc).__name__}: {exc}')
            result.sessions.extend(_make_sessions('KR', left, right, False, {}, KRX_PAGE))
    (result.successful_scopes if krx_ok else result.failed_scopes).append('KR')
    result.sessions.sort(key=lambda s: (s.date, s.market))
    result.sources = list(dict.fromkeys(result.sources))
    return result
