"""Public index notices, with deliberately conservative confirmation rules.

An effective date is not the trading date on which a tracking portfolio changes.
The former is retained; the latter is either explicitly published or derived from
a complete sequence of confirmed exchange sessions supplied by the market feed.
No absence-of-event claim is made for the finite public news pages we inspect.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, timedelta
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from ..http import HttpClient
from ..models import Event, Result, Session

MSCI_REVIEW = 'https://www.msci.com/eqb/gimi/stdindex/index_review.html'
MSCI_DATES = 'https://www.msci.com/eqb/pressreleases/archive/ir_dates.pdf'
NASDAQ_METHOD = 'https://indexes.nasdaq.com/docs/Methodology_NDX.pdf'
NASDAQ_NEWS = 'https://ir.nasdaq.com/news-and-events/press-releases'
NASDAQ_RSS = 'https://ir.nasdaq.com/rss/news-releases.xml'
SP_METHOD = 'https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-us-indices.pdf'
SP_NEWS = 'https://press.spglobal.com/'

MONTHS = {name.lower(): i for i, name in enumerate(
    ['January', 'February', 'March', 'April', 'May', 'June', 'July',
     'August', 'September', 'October', 'November', 'December'], 1)}
MONTHS.update({key[:3]: value for key, value in list(MONTHS.items())})
MONTHS['sept'] = 9
DATE = r'(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sept?\.?|Oct\.?|Nov\.?|Dec\.?)\s+\d{1,2}(?:st|nd|rd|th)?\s*,?\s+\d{4}'


def normalize(value: str) -> str:
    return re.sub(r'\s+', ' ', value.replace('\u00ad', '').replace('\u2011', '-').replace('\u2013', '-')).strip()


def parse_date(value: str) -> date:
    match = re.fullmatch(r'([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s+(\d{4})', normalize(value))
    if not match:
        raise ValueError('Unrecognized English date')
    return date(int(match[3]), MONTHS[match[1].lower()], int(match[2]))


def previous_session(day: date, market: str, sessions: list[Session]) -> Session | None:
    """Require every intervening calendar day to be known, including weekends."""
    by_day = {s.date: s for s in sessions if s.market == market}
    for offset in range(1, 15):
        item = by_day.get((day - timedelta(days=offset)).isoformat())
        if item is None or not item.confirmed or item.status == 'unknown':
            return None
        if item.status in ('open', 'early_close', 'changed'):
            return item
        if item.status != 'closed':
            return None
    return None


def weekday_before(day: date) -> date:
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _source_date(text: str) -> str | None:
    # Look next to the dateline, rather than the first date in page navigation.
    found = re.search(r'(?:NEW YORK|London)\s*[-,]\s*(' + DATE + ')', text, re.I)
    return parse_date(found[1]).isoformat() if found else None


def _event(category: str, market: str, implementation: date, effective: date | None,
           source: str, announcement: str | None, confirmed: bool,
           details: list[str], title: str, suffix: str = '') -> Event:
    return Event(
        id=f'{category}:{market}:{(effective or implementation).isoformat()}{suffix}',
        category=category, title=title, market=market,
        trade_date=implementation.isoformat(),
        slot='morning' if market == 'KR' else 'evening', phase='implementation',
        details=details, sources=[source], confirmed=confirmed,
        announcement_date=announcement, implementation_date=implementation.isoformat(),
        effective_date=effective.isoformat() if effective else None,
    )


def parse_msci_calendar(text: str, source: str = MSCI_DATES) -> list[Event]:
    """Published future effective dates alone do not confirm implementation dates."""
    text = normalize(text)
    pattern = (r'((?:February|May|August|November)\s+\d{4})\s+Index Review\s*'
               r'.*?Announcement date\s*:\s*(' + DATE + r')\s*'
               r'.*?Effective date\s*:\s*(' + DATE + ')')
    events = []
    for match in re.finditer(pattern, text, re.I):
        announcement, effective = parse_date(match[2]), parse_date(match[3])
        for market in ('KR', 'US'):
            events.append(_event(
                'msci', market, weekday_before(effective), effective, source,
                announcement.isoformat(), False,
                ['공식 발표일과 효력일은 확인됨. 종가 반영일은 개별 리뷰 발표문 확인 전 추정값입니다.',
                 f'리뷰: {match[1]} / 효력일: {effective.isoformat()}'],
                'MSCI 정기 리뷰 반영 예정 (미확정)',
            ))
    if not events:
        raise ValueError('MSCI future-review date table was not recognized')
    return events


def parse_msci_release(text: str, source: str, sessions: list[Session] | None = None) -> list[Event]:
    text = normalize(text)
    if not re.search(r'MSCI.*?Index Review', text, re.I):
        raise ValueError('Not an MSCI index-review announcement')
    match = re.search(r'(?:all changes|the.*?Index Review)\s+will be implemented\s+'
                      r'(?:as of|at)\s+the close(?:\s+of business)?(?:\s+on|\s+of)?\s+('
                      + DATE + ')', text, re.I)
    if not match:
        raise ValueError('MSCI explicit implementation date was not recognized')
    implementation = parse_date(match[1])
    effective_match = re.search(r'effective date\s*(?:of|:)?\s*(' + DATE + ')', text, re.I)
    effective = parse_date(effective_match[1]) if effective_match else None
    events = []
    sessions = sessions or []
    for market in ('KR', 'US'):
        item = next((s for s in sessions if s.market == market and s.date == implementation.isoformat()), None)
        details = ['MSCI 공식 발표문의 종가 반영일입니다. 개별 종목 편출입 내역은 원문에서 확인하세요.']
        trade_date = implementation
        if item and item.confirmed and item.status == 'closed':
            previous = previous_session(implementation, market, sessions)
            details.append('공식 반영일에 해당 시장은 휴장: 마지막 이용 가능한 종가가 적용됩니다.')
            if previous:
                trade_date = date.fromisoformat(previous.date)
                details.append(f'이 시장의 마지막 거래 가능일 {previous.date}에 알립니다. 공식 반영일: {implementation}.')
        event = _event('msci', market, trade_date, effective, source, _source_date(text), True,
                       details, 'MSCI 정기 리뷰 종가 반영')
        event.implementation_date = implementation.isoformat()
        if item and item.close_at and trade_date == implementation:
            event.occurs_at = item.close_at
        events.append(event)
    return events


def _article_text(soup: BeautifulSoup) -> str:
    for selector in ('.wd_body', '.field--name-body', '.node__content', 'article', 'main'):
        node = soup.select_one(selector)
        if node and len(node.get_text(' ', strip=True)) > 100:
            return normalize(node.get_text(' ', strip=True))
    return normalize(soup.get_text(' ', strip=True))


def parse_us_notice(text: str, category: str, source: str,
                    sessions: list[Session] | None = None) -> list[Event]:
    """Parse explicitly dated implementation clauses; never treat a dateline as an event.

    Ambiguous multi-date notices are rejected rather than assigning another
    index's effective date to S&P 500. This is reported by collect as a warning.
    """
    text = normalize(text)
    required = r'Nasdaq-100' if category == 'nasdaq' else r'S\s*&\s*P\s*500'
    # Exclude provider boilerplate, which often mentions S&P 500 in every release.
    body = re.split(r'ABOUT S&P DOW JONES INDICES|About Nasdaq|About S&P Dow Jones', text, flags=re.I)[0]
    if not re.search(required, body, re.I):
        raise ValueError('The target index is absent from the announcement body')
    clauses = []
    for match in re.finditer(r'(?:effective|implemented)\s+(.{0,130}?)(' + DATE + ')', body, re.I):
        prefix = match[1].lower()
        mode = 'close' if re.search(r'(?:after|as of|at)\s+(?:the\s+)?(?:market\s+)?close', prefix) else 'open' if re.search(r'(?:prior|before).*?open|at.*?open', prefix) else None
        if mode:
            clauses.append((mode, parse_date(match[2])))
    clauses = list(dict.fromkeys(clauses))
    if len(clauses) != 1:
        raise ValueError('No single unambiguous implementation/effective-date clause')
    mode, published_date = clauses[0]
    previous = previous_session(published_date, 'US', sessions or []) if mode == 'open' else None
    implementation = date.fromisoformat(previous.date) if previous else weekday_before(published_date) if mode == 'open' else published_date
    confirmed = mode == 'close' or previous is not None
    effective = published_date if mode == 'open' else None
    quarterly = bool(re.search(r'quarterly (?:rebalanc|changes)', body, re.I))
    annual = bool(re.search(r'annual (?:reconstitution|changes)', body, re.I))
    special = bool(re.search(r'special rebalance', body, re.I))
    kind = '특별 리밸런싱' if special else '연례 재구성·리밸런싱' if annual else '분기 리밸런싱' if quarterly else '수시 편출입'
    label = 'Nasdaq-100' if category == 'nasdaq' else 'S&P 500'
    details = [f'구분: {kind}. 종목 내역은 공식 공지 원문에서 확인하세요.']
    if mode == 'open':
        details.append(f'공식 효력일: {published_date.isoformat()} 미국 개장 전.')
        details.append('공식 효력일과 거래소 거래일에서 종가 반영일을 계산했습니다.' if confirmed
                       else '직전 미국 거래일 달력 확인 실패: 종가 반영일은 평일 기준 추정이며 기본 알림에서 제외됩니다.')
    else:
        details.append('공식 공지에 명시된 미국 종가 반영일입니다.')
    # Several notices can share one effective date; preserve separate ad hoc changes.
    suffix = '' if quarterly or annual else ':' + hashlib.sha256(source.encode()).hexdigest()[:10]
    event = _event(category, 'US', implementation, effective, source, _source_date(body), confirmed,
                   details, f'{label} {kind} 종가 반영', suffix)
    if previous:
        event.sources.extend(previous.sources)
        event.occurs_at = previous.close_at
    return [event]


def _allowed(url: str, domains: tuple[str, ...]) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == 'https' and any(parsed.hostname == d or (parsed.hostname or '').endswith('.' + d) for d in domains)


def discover_news(soup: BeautifulSoup, base: str, category: str) -> list[str]:
    target = re.compile(r'nasdaq[-\s]*100' if category == 'nasdaq' else r's(?:&|\s*-\s*|%26)\s*p(?:-|\s)*500', re.I)
    domains = ('nasdaq.com',) if category == 'nasdaq' else ('spglobal.com',)
    links = []
    for anchor in soup.find_all('a', href=True):
        href = urljoin(base, anchor['href'])
        context = anchor.get_text(' ', strip=True) + ' ' + href
        # Nasdaq's listing links are labelled simply "HTML" inside a release row.
        row = anchor.find_parent('tr')
        if row:
            context += ' ' + row.get_text(' ', strip=True)
        if target.search(normalize(context)) and _allowed(href, domains):
            if category == 'nasdaq' and not any(s in href for s in ('news-release', '/node/', '/press-release/')):
                continue
            if category == 'sp500' and not re.search(r'/\d{4}-\d{2}-\d{2}-|/indexnews/', href):
                continue
            links.append(href.split('#')[0])
    return list(dict.fromkeys(links))


def _rss_links(xml: str) -> list[str]:
    root = ElementTree.fromstring(xml)
    if root.tag not in ('rss', '{http://www.w3.org/2005/Atom}feed'):
        raise ValueError('Nasdaq RSS response is not RSS/Atom')
    links = []
    for item in root.findall('.//item'):
        title = item.findtext('title', '')
        href = item.findtext('link', '')
        if re.search(r'Nasdaq[-\s]*100', normalize(title), re.I) and _allowed(href, ('nasdaq.com',)):
            links.append(href)
    return list(dict.fromkeys(links))


def _rule_events(category: str, start: date, end: date, source: str, sessions: list[Session]) -> list[Event]:
    events = []
    for year in range(start.year, end.year + 1):
        for month in (3, 6, 9, 12):
            first = date(year, month, 1)
            third_friday = first + timedelta(days=(4 - first.weekday()) % 7 + 14)
            implementation = third_friday
            next_day = third_friday + timedelta(days=1)
            # Use supplied session calendar where possible, but this remains only
            # a rule-based prediction until a specific index notice is published.
            for _ in range(10):
                item = next((s for s in sessions if s.market == 'US' and s.date == next_day.isoformat()), None)
                if item and item.confirmed and item.status in ('open', 'early_close', 'changed'):
                    previous = previous_session(next_day, 'US', sessions)
                    if previous:
                        implementation = date.fromisoformat(previous.date)
                    break
                if item is None and next_day.weekday() < 5:
                    break
                next_day += timedelta(days=1)
            label = 'Nasdaq-100' if category == 'nasdaq' else 'S&P 500'
            events.append(_event(category, 'US', implementation, next_day, source, None, False,
                                 ['정기 규칙으로 계산한 예정일입니다. 해당 회차 공식 공지 확인 전에는 기본 알림에서 제외됩니다.'],
                                 f'{label} 분기 리밸런싱 예정 (미확정)'))
    return events


def collect(client: HttpClient, start: date, end: date,
            sessions: list[Session] | None = None) -> Result:
    if end < start:
        raise ValueError('end must not precede start')
    sessions = sessions or []
    result = Result(provider='rebalances')
    calendar_events = []
    candidates: list[Event] = []

    def failure(label: str, exc: Exception) -> None:
        result.warnings.append(f'{label}: 수집 또는 해석 실패 ({type(exc).__name__}). 일정 없음으로 판단할 수 없습니다.')

    try:
        calendar_events = parse_msci_calendar(client.pdf_text(MSCI_DATES))
        result.sources.append(MSCI_DATES)
    except Exception as exc:
        failure('MSCI 향후 리뷰 일정', exc)
    try:
        soup = client.get_soup(MSCI_REVIEW)
        result.sources.append(MSCI_REVIEW)
        links = []
        for anchor in soup.find_all('a', href=True):
            href = urljoin(MSCI_REVIEW, anchor['href'])
            marker = re.search(r'MSCI_(?:Feb|May|Aug|Nov)(\d{2})_(?:QIR|SAIR)PR\.pdf', href, re.I)
            if marker and start.year - 1 <= 2000 + int(marker[1]) <= end.year and _allowed(href, ('msci.com',)):
                links.append(href)
        links = list(dict.fromkeys(links))[:12]
        if not links:
            raise ValueError('MSCI review release links were not found')
        for href in links:
            try:
                events = parse_msci_release(client.pdf_text(href), href, sessions)
                # Join actual implementation notices to the separately published
                # calendar by release month (announcement), never by guessed date.
                for event in events:
                    for future in calendar_events:
                        if event.announcement_date and future.announcement_date == event.announcement_date and future.market == event.market:
                            event.effective_date = future.effective_date
                            event.id = future.id
                            event.sources.append(MSCI_DATES)
                            break
                candidates.extend(events)
                result.sources.append(href)
            except Exception as exc:
                failure('MSCI 리뷰 공지 ' + href.rsplit('/', 1)[-1], exc)
    except Exception as exc:
        failure('MSCI 리뷰 발표 목록', exc)
    candidates.extend(calendar_events)

    for category, method in (('nasdaq', NASDAQ_METHOD), ('sp500', SP_METHOD)):
        try:
            text = normalize(client.pdf_text(method))
            if category == 'nasdaq':
                valid = re.search(r'first trading day following the third Friday', text, re.I)
            else:
                valid = re.search(r'quarterly', text, re.I) and 'S&P 500' in text
            if not valid:
                raise ValueError('Index methodology schedule changed')
            candidates.extend(_rule_events(category, start, end, method, sessions))
            result.sources.append(method)
        except Exception as exc:
            failure(category + ' 방법론', exc)

    nasdaq_links = []
    try:
        nasdaq_links.extend(_rss_links(client.get_text(NASDAQ_RSS)))
        result.sources.append(NASDAQ_RSS)
    except Exception as exc:
        failure('Nasdaq 공식 뉴스 RSS', exc)
    for category, base in (('nasdaq', NASDAQ_NEWS), ('sp500', SP_NEWS)):
        links = nasdaq_links[:] if category == 'nasdaq' else []
        try:
            soup = client.get_soup(base)
            links.extend(discover_news(soup, base, category))
            result.sources.append(base)
            # Follow only same-site pagination URLs actually present in the page.
            pages = []
            for anchor in soup.find_all('a', href=True):
                href = urljoin(base, anchor['href'])
                if urlparse(href).hostname == urlparse(base).hostname and re.search(r'[?&](?:page|o)=\d+', href):
                    pages.append(href)
            for href in list(dict.fromkeys(pages))[:3]:
                try:
                    links.extend(discover_news(client.get_soup(href), href, category))
                    result.sources.append(href)
                except Exception as exc:
                    failure(category + ' 뉴스 추가 페이지', exc)
        except Exception as exc:
            failure(category + ' 공식 공지 목록', exc)
        for href in list(dict.fromkeys(links))[:30]:
            try:
                soup = client.get_soup(href)
                candidates.extend(parse_us_notice(_article_text(soup), category, href, sessions))
                result.sources.append(href)
            except Exception as exc:
                failure(category + ' 개별 공지 ' + href.rsplit('/', 1)[-1][:90], exc)
        if not links:
            result.warnings.append(f'{category}: 공개 뉴스 목록에서 대상 공지를 찾지 못했습니다. 수시 편출입·특별 리밸런싱 부재를 확인한 것은 아닙니다.')
    result.warnings.append('리밸런싱 확인범위: MSCI 공개 정기 리뷰 자료와 Nasdaq/S&P 공개 최신 뉴스 및 최대 3개 추가 페이지입니다. 향후 미발표 일정·수시 편출입·특별 변경 전체의 부재는 보장하지 않습니다.')

    # Confirmed explicit notices win over rule-generated placeholders; deduplicate
    # by stable index/effective-date ids so a corrected date can be detected upstream.
    chosen: dict[str, Event] = {}
    for event in sorted(candidates, key=lambda e: e.confirmed):
        if start.isoformat() <= event.trade_date <= end.isoformat():
            chosen[event.id] = event
    result.events = sorted(chosen.values(), key=lambda e: (e.trade_date, e.market, e.id))
    result.sources = list(dict.fromkeys(result.sources))
    warning_text = '\n'.join(result.warnings).lower()
    for scope, markers in {
        'msci': ('msci 향후', 'msci 리뷰 발표 목록'),
        'nasdaq': ('nasdaq 방법론', 'nasdaq 공식 뉴스 rss', 'nasdaq: 공개 뉴스'),
        'sp500': ('sp500 방법론', 'sp500 공식 공지 목록'),
    }.items():
        target = result.failed_scopes if any(marker in warning_text for marker in markers) else result.successful_scopes
        target.append(scope)
    # Coverage is intentionally unset: a finite public news feed is not a complete
    # calendar and must not be used to infer "no event" for an arbitrary date.
    return result
