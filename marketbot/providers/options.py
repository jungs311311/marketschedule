"""Standard monthly option-expiration alerts.

The default scope intentionally excludes weekly/daily/EOM series.  Standard
AM-settled SPX/NDX and single-stock equity options are described separately.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ..http import HttpClient
from ..models import Event, Result, Session

KRX_URL = 'https://global.krx.co.kr/contents/GLB/02/0201/0201040202/GLB0201040202.jsp'
KRX_GUIDE = 'https://www.krx.co.kr/contents/OPN/01/01041401/Guide_to_Night_Session_in_KRX_Derivatives_Market.pdf'
OIC_BASICS = 'https://www.optionseducation.org/optionsoverview/options-basics'
OIC_EXERCISE = 'https://www.optionseducation.org/referencelibrary/faq/options-exercise'
OIC_INDEX = 'https://www.optionseducation.org/advancedconcepts/equity-vs-index-options'
CBOE_SPEC = 'https://www.cboe.com/tradable-products/sp-500/spx-options/spx-specifications'
CBOE_CALENDAR = 'https://cdn.cboe.com/resources/options/Cboe{year}OPTIONSCalendar.pdf'
NDX_FACT = 'https://www.nasdaq.com/NDX_NDXP_Factsheet'

KST = ZoneInfo('Asia/Seoul')
NY = ZoneInfo('America/New_York')


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (nth - 1))


def _by_day(sessions: list[Session], market: str) -> dict[date, Session]:
    return {date.fromisoformat(s.date): s for s in sessions if s.market == market}


def _adjust_prior(day: date, sessions: dict[date, Session]) -> tuple[date, bool]:
    item = sessions.get(day)
    if item and item.confirmed and item.status in ('open', 'early_close', 'changed'):
        return day, True
    if not item or not item.confirmed:
        return day, False
    for offset in range(1, 8):
        prior = sessions.get(day - timedelta(days=offset))
        if not prior or not prior.confirmed:
            return day, False
        if prior.status in ('open', 'early_close', 'changed'):
            return day - timedelta(days=offset), True
    return day, False


def _fmt_kst(day: date, value: time) -> str:
    return datetime.combine(day, value, NY).astimezone(KST).strftime('%Y-%m-%d %H:%M KST')


def validate_krx(text: str) -> None:
    normalized = ' '.join(text.split())
    if not re.search(r'Last Trading Day\s+Second Thursday of the contract month', normalized, re.I):
        raise ValueError('KRX KOSPI 200 월간 옵션 최종거래일 규칙 미확인')
    if not re.search(r'Final Settlement\s+Cash', normalized, re.I):
        raise ValueError('KRX 현금결제 명세 미확인')


def validate_us(oic_basics: str, oic_exercise: str, oic_index: str,
                ndx_fact: str, spx_spec: str, cboe_calendar: str, year: int) -> None:
    combined = ' '.join((oic_basics + ' ' + oic_exercise).split())
    if not re.search(r'third Friday', combined, re.I):
        raise ValueError('미국 표준 월간 옵션 셋째 금요일 규칙 미확인')
    if not re.search(r'equity options.*American-style|standardized equity options use American-style', combined, re.I):
        raise ValueError('미국 개별주식옵션 행사 방식 미확인')
    if not re.search(r'opening prices', ' '.join(oic_index.split()), re.I):
        raise ValueError('AM 결제 지수옵션 개장가격 기준 미확인')
    fact = ' '.join(ndx_fact.split())
    if not (re.search(r'NDX.*third Friday', fact, re.I) and
            re.search(r'calculated at the open of trading', fact, re.I)):
        raise ValueError('NDX 월간 AM 결제 명세 미확인')
    if not re.search(r'preceding the day.*exercise-settlement value', ' '.join(spx_spec.split()), re.I):
        raise ValueError('SPX AM 결제 최종거래일 명세 미확인')
    if str(year) not in cboe_calendar or 'Standard Expiration' not in cboe_calendar:
        raise ValueError(f'Cboe {year}년 만기 캘린더 확인 실패')


def collect(client: HttpClient, start: date, end: date,
            sessions: list[Session] | None = None) -> Result:
    if end < start:
        raise ValueError('end must not precede start')
    sessions = sessions or []
    result = Result(provider='options', coverage_start=start.isoformat(), coverage_end=end.isoformat())
    kr_sessions, us_sessions = _by_day(sessions, 'KR'), _by_day(sessions, 'US')

    kr_rules = False
    try:
        text = client.get_soup(KRX_URL).get_text(' ', strip=True)
        validate_krx(text)
        kr_rules = True
        result.sources.append(KRX_URL)
    except Exception as exc:
        result.warnings.append(f'KRX 옵션 명세 수집 실패: {type(exc).__name__}: {exc}')
    for year in range(start.year, end.year + 1):
        for month in range(1, 13):
            nominal = _nth_weekday(year, month, calendar.THURSDAY, 2)
            actual, session_ok = _adjust_prior(nominal, kr_sessions)
            if not start <= actual <= end:
                continue
            confirmed = kr_rules and session_ok
            details = [
                'KOSPI 200 월간 정기 옵션 최종거래일',
                '최종거래일 거래시간 08:45–15:20 KST · 현금결제',
                '위클리 옵션은 기본 알림에서 제외',
            ]
            if actual != nominal:
                details.append(f'휴장 조정: 원래 둘째 목요일 {nominal.isoformat()} → {actual.isoformat()}')
            if not confirmed:
                details.append('공식 상품 명세 또는 해당 거래일 달력 확인 실패 · 기본 발송 제외')
            result.events.append(Event(
                id=f'kr_options:{actual}', category='kr_options', title='국장 옵션 만기',
                market='KR', trade_date=actual.isoformat(), slot='morning', phase='last_trading_day',
                occurs_at=datetime.combine(actual, time(15, 20), KST).isoformat(),
                details=details, sources=[KRX_URL], confirmed=confirmed,
            ))
    (result.successful_scopes if kr_rules and kr_sessions else result.failed_scopes).append('kr_options')

    try:
        oic_basics = client.get_soup(OIC_BASICS).get_text(' ', strip=True)
        oic_exercise = client.get_soup(OIC_EXERCISE).get_text(' ', strip=True)
        oic_index = client.get_soup(OIC_INDEX).get_text(' ', strip=True)
        ndx_fact = client.pdf_text(NDX_FACT)
        spx_spec = client.get_soup(CBOE_SPEC).get_text(' ', strip=True)
        result.sources.extend([OIC_BASICS, OIC_EXERCISE, OIC_INDEX, NDX_FACT, CBOE_SPEC])
    except Exception as exc:
        oic_basics = oic_exercise = oic_index = ndx_fact = spx_spec = ''
        result.warnings.append(f'미국 옵션 상품 명세 수집 실패: {type(exc).__name__}: {exc}')

    us_all_ok = True
    for year in range(start.year, end.year + 1):
        calendar_url = CBOE_CALENDAR.format(year=year)
        rules_ok = False
        try:
            calendar_text = client.pdf_text(calendar_url)
            validate_us(oic_basics, oic_exercise, oic_index, ndx_fact, spx_spec, calendar_text, year)
            rules_ok = True
            result.sources.append(calendar_url)
        except Exception as exc:
            us_all_ok = False
            result.warnings.append(f'미국 옵션 {year}년 일정 검증 실패: {type(exc).__name__}: {exc}')
        for month in range(1, 13):
            nominal = _nth_weekday(year, month, calendar.FRIDAY, 3)
            actual, session_ok = _adjust_prior(nominal, us_sessions)
            if not start <= actual <= end:
                continue
            confirmed = rules_ok and session_ok
            open_kst = _fmt_kst(actual, time(9, 30))
            close = us_sessions.get(actual).close_at if us_sessions.get(actual) else None
            close_kst = (datetime.fromisoformat(close).astimezone(KST).strftime('%Y-%m-%d %H:%M KST')
                         if close else _fmt_kst(actual, time(16)))
            details = [
                f'[지수 AM] SPX·NDX 표준 월물: 구성종목 개장가격 기준 결제 ({open_kst})',
                f'[개별주식] 표준 월물: 장 마감 종가 기준 자동행사 판단 ({close_kst})',
                'SPX·NDX AM의 결제시점과 최종거래시점은 다름: 상품별 최신 명세 확인',
                'SPXW·NDXP 같은 PM 결제 지수옵션과 위클리·일일 옵션은 기본 알림에서 제외',
            ]
            if actual != nominal:
                details.append(f'거래소 휴장 조정: 원래 셋째 금요일 {nominal.isoformat()} → {actual.isoformat()}')
            if not confirmed:
                details.append('공식 연간 만기 캘린더 또는 거래일 확인 실패 · 기본 발송 제외')
            result.events.append(Event(
                id=f'us_options:{actual}', category='us_options', title='미장 월간 옵션 만기',
                market='US', trade_date=actual.isoformat(), slot='evening', phase='expiration',
                occurs_at=datetime.combine(actual, time(9, 30), NY).isoformat(),
                details=details,
                sources=[OIC_BASICS, OIC_EXERCISE, OIC_INDEX, CBOE_SPEC, NDX_FACT, calendar_url],
                confirmed=confirmed,
            ))
    (result.successful_scopes if us_all_ok and us_sessions else result.failed_scopes).append('us_options')
    result.events.sort(key=lambda e: (e.trade_date, e.market))
    result.sources = list(dict.fromkeys(result.sources))
    return result
