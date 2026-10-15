"""주요 경제지표 발표 일정: 미국 CPI·고용보고서·PCE, 일본은행 금리 결정, 한국 소비자물가.

모든 날짜는 각 기관의 공식 발표 일정표에서 가져온다. 공식적으로 발표 시각이
명시된 미국 지표만 한국시간을 표시하고, 시각이 고정되지 않은 일본은행과
통계청은 시각을 지어내지 않는다.
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from pypdf import PdfReader

from ..http import HttpClient
from ..models import Event, Result

BLS_CPI = 'https://www.bls.gov/schedule/news_release/cpi.htm'
BLS_JOBS = 'https://www.bls.gov/schedule/news_release/empsit.htm'
BEA_SCHEDULE = 'https://www.bea.gov/news/schedule'
BOJ_SCHEDULE = 'https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm'
KOSTAT_SCHEDULE = 'https://kostat.go.kr/ansk/file/schedule_{year}.pdf'

KST = ZoneInfo('Asia/Seoul')
NY = ZoneInfo('America/New_York')
MONTH = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6, 'jul': 7,
         'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}
MONTH_KO = {m: f'{m}월' for m in range(1, 13)}


def _month(word: str) -> int:
    return MONTH[word[:3].lower()]


def _clock(text: str) -> time:
    match = re.fullmatch(r'(\d{1,2}):(\d{2})\s*([AP])M', text.strip(), re.I)
    if not match:
        raise ValueError(f'발표 시각 형식 불일치: {text}')
    hour = int(match[1]) % 12 + (12 if match[3].upper() == 'P' else 0)
    return time(hour, int(match[2]))


def _ref_month(text: str) -> str:
    """'September 2026' → '9월분'."""
    match = re.search(r'([A-Za-z]+)\s+(20\d{2})', text)
    return f'{_month(match[1])}월분' if match else ''


def parse_bls(html: str) -> list[tuple[date, time, str]]:
    """BLS 지표별 일정표: [기준월, 'Nov. 10, 2026', '08:30 AM']."""
    soup = BeautifulSoup(html, 'html.parser')
    found: dict[date, tuple[date, time, str]] = {}
    for row in soup.find_all('tr'):
        cells = [c.get_text(' ', strip=True) for c in row.find_all(['td', 'th'])]
        if len(cells) != 3:
            continue
        match = re.fullmatch(r'([A-Za-z]{3,5})\.?\s+(\d{1,2}),\s*(20\d{2})', cells[1])
        if not match or not re.fullmatch(r'[A-Za-z]+\s+20\d{2}', cells[0]):
            continue
        day = date(int(match[3]), _month(match[1]), int(match[2]))
        found[day] = (day, _clock(cells[2]), _ref_month(cells[0]))
    if len(found) < 3:
        raise ValueError('BLS 발표 일정표를 찾지 못했습니다')
    return sorted(found.values())


def parse_bea_pce(html: str) -> list[tuple[date, time, str]]:
    """BEA 전체 일정표에서 'Personal Income and Outlays' 행만 고른다."""
    soup = BeautifulSoup(html, 'html.parser')
    found: dict[date, tuple[date, time, str]] = {}
    for table in soup.find_all('table'):
        first = table.find('tr')
        year_match = re.search(r'Year\s+(20\d{2})', first.get_text(' ', strip=True)) if first else None
        if not year_match:
            continue
        year = int(year_match[1])
        for row in table.find_all('tr')[1:]:
            cells = [c.get_text(' ', strip=True) for c in row.find_all(['td', 'th'])]
            if len(cells) < 3 or not cells[-1].startswith('Personal Income and Outlays'):
                continue
            match = re.fullmatch(r'([A-Za-z]+)\s+(\d{1,2})\s+(\d{1,2}:\d{2}\s*[AP]M)', cells[0])
            if not match:
                continue  # 'To Be Announced' 등 날짜 미정 행은 건너뛴다
            day = date(year, _month(match[1]), int(match[2]))
            found[day] = (day, _clock(match[3]), _ref_month(cells[-1]))
    if not found:
        raise ValueError('BEA 일정표에서 PCE(개인소득·지출) 발표를 찾지 못했습니다')
    return sorted(found.values())


def parse_boj(html: str) -> list[tuple[date, bool]]:
    """일본은행 연도별 표. 결정일은 회의 마지막 날. (결정일, 전망보고서 발표 여부)."""
    soup = BeautifulSoup(html, 'html.parser')
    found: dict[date, bool] = {}
    for table in soup.find_all('table'):
        caption = table.find('caption')
        year_match = re.search(r'(20\d{2})', caption.get_text(' ', strip=True)) if caption else None
        if not year_match:
            continue
        year = int(year_match[1])
        for row in table.find_all('tr'):
            cells = [c.get_text(' ', strip=True) for c in row.find_all('td')]
            if not cells:
                continue
            text = re.sub(r'\[PDF[^\]]*\]', '', cells[0])
            pieces = re.findall(r'(?:([A-Z][a-z]{2,4})\.?\s+)?(\d{1,2})\s*\(', text)
            if len(pieces) < 2 or not pieces[0][0]:
                continue
            month = _month(pieces[0][0])
            for name, _ in pieces[1:]:
                if name:
                    month = _month(name)
            last_day = int(pieces[-1][1])
            outlook = len(cells) > 1 and cells[1].strip() not in ('-', '–', '')
            found[date(year, month, last_day)] = outlook
    if len(found) < 6:
        raise ValueError('일본은행 금융정책결정회의 일정표를 찾지 못했습니다')
    return sorted(found.items())


def parse_kostat_cpi(pdf: bytes, year: int) -> list[tuple[date, str]]:
    """통계청 연간 공표일정 PDF: '2026년 9월 소비자물가동향 10.2.(금)'."""
    text = '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(pdf)).pages)
    found: dict[date, str] = {}
    for line in text.splitlines():
        if '소비자물가동향' not in line:
            continue
        ref = re.search(r'(20\d{2})년\s*(\d{1,2})월', line)
        when = re.search(r'(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*\([월화수목금토일]\)', line)
        if ref and when:
            day = date(year, int(when[1]), int(when[2]))
            label = f'{int(ref[2])}월분' + (' · 연간' if '연간' in line else '')
            found[day] = label
    if len(found) < 10:
        raise ValueError(f'통계청 {year}년 소비자물가동향 공표일정을 찾지 못했습니다')
    return sorted(found.items())


def _us_event(kind: str, title: str, source: str, day: date, clock: time, ref: str) -> Event:
    when = datetime.combine(day, clock, NY).astimezone(KST)
    details = [f'오늘 {when:%H:%M} KST ({clock:%H:%M} ET) 발표' + (f' · {ref}' if ref else '')]
    return Event(id=f'{kind}:{day}', category=kind, title=title, market='US',
                 trade_date=day.isoformat(), slot='evening', phase='release',
                 occurs_at=when.isoformat(), details=details, sources=[source])


def collect(client: HttpClient, start: date, end: date) -> Result:
    result = Result(provider='indicators', coverage_start=start.isoformat(), coverage_end=end.isoformat())

    for kind, title, url, parse in (
        ('us_cpi', '미국 CPI(소비자물가) 발표', BLS_CPI, parse_bls),
        ('us_jobs', '미국 고용보고서 발표', BLS_JOBS, parse_bls),
        ('us_pce', '미국 PCE(개인소비지출 물가) 발표', BEA_SCHEDULE, parse_bea_pce),
    ):
        try:
            for day, clock, ref in parse(client.get_text(url)):
                if start <= day <= end:
                    result.events.append(_us_event(kind, title, url, day, clock, ref))
            result.sources.append(url)
            result.successful_scopes.append(kind)
        except Exception as exc:
            result.failed_scopes.append(kind)
            result.warnings.append(f'{title} 일정 수집 실패: {type(exc).__name__}: {exc}')

    try:
        for day, outlook in parse_boj(client.get_text(BOJ_SCHEDULE)):
            if not start <= day <= end:
                continue
            details = ['금융정책결정회의 마지막 날 · 결정문은 회의 종료 직후 발표(시각 고정 아님)']
            if outlook:
                details.append('경제·물가 전망보고서 함께 발표되는 회의')
            result.events.append(Event(id=f'boj:{day}', category='boj', title='일본은행(BOJ) 금리 결정',
                                       market='JP', trade_date=day.isoformat(), slot='morning',
                                       phase='rate_decision', details=details, sources=[BOJ_SCHEDULE]))
        result.sources.append(BOJ_SCHEDULE)
        result.successful_scopes.append('boj')
    except Exception as exc:
        result.failed_scopes.append('boj')
        result.warnings.append(f'일본은행 일정 수집 실패: {type(exc).__name__}: {exc}')

    kr_ok = True
    for year in range(start.year, end.year + 1):
        url = KOSTAT_SCHEDULE.format(year=year)
        try:
            for day, label in parse_kostat_cpi(client.get_bytes(url), year):
                if start <= day <= end:
                    result.events.append(Event(id=f'kr_cpi:{day}', category='kr_cpi',
                                               title='한국 소비자물가 발표', market='KR',
                                               trade_date=day.isoformat(), slot='morning', phase='release',
                                               details=[f'통계청 소비자물가동향 · {label} · 발표 시각은 당일 공지 확인'],
                                               sources=[url]))
            result.sources.append(url)
        except Exception as exc:
            if year > start.year:
                # 다음 해 일정은 보통 연말에야 공개된다. 미공개를 장애로 보지 않는다.
                result.warnings.append(f'통계청 {year}년 공표일정 아직 확인 안 됨 ({type(exc).__name__})')
            else:
                kr_ok = False
                result.warnings.append(f'통계청 {year}년 공표일정 수집 실패: {type(exc).__name__}: {exc}')
    (result.successful_scopes if kr_ok else result.failed_scopes).append('kr_cpi')
    return result
