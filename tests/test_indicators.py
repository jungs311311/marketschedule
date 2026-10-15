from __future__ import annotations

from datetime import date, time

from marketbot.providers import indicators as I

BLS = '''<table><tr><th>Reference Month</th><th>Release Date</th><th>Release Time</th></tr>
<tr><td>October 2026</td><td>Nov. 10, 2026</td><td>08:30 AM</td></tr>
<tr><td>November 2026</td><td>Dec. 10, 2026</td><td>08:30 AM</td></tr>
<tr><td>August 2027</td><td>Sept. 14, 2027</td><td>08:30 AM</td></tr></table>'''

BEA = '''<table><tr><th>Year 2026</th><th></th><th>Release</th></tr>
<tr><td>October 29 8:30 AM</td><td>News</td><td>GDP (Advance Estimate), 3rd Quarter 2026</td></tr>
<tr><td>October 29 8:30 AM</td><td>News</td><td>Personal Income and Outlays, September 2026</td></tr>
<tr><td>To Be Announced 2026</td><td>News</td><td>Personal Income and Outlays, December 2026</td></tr></table>'''

BOJ = '<table><caption>Table : 2026</caption>' + ''.join(
    f'<tr><td>{d}</td><td>{o}</td></tr>' for d, o in [
        ('Jan. 22 (Thurs.), 23 (Fri.) [PDF 171KB]', 'Jan. 23 (Fri.)'), ('Mar. 18 (Wed.), 19 (Thurs.)', '-'),
        ('Apr. 30 (Thurs.), May 1 (Fri.)', 'May 1 (Fri.)'), ('June 15 (Mon.), 16 (Tues.)', '-'),
        ('July 30 (Thurs.), 31 (Fri.)', 'July 31 (Fri.)'), ('Oct. 28\n (Thurs.), 29 (Fri.)', 'Oct. 29 (Fri.)')]) + '</table>'


def test_bls_dates_and_time():
    rows = I.parse_bls(BLS)
    assert rows[0] == (date(2026, 11, 10), time(8, 30), '10월분')
    assert rows[-1][0] == date(2027, 9, 14)          # 'Sept.' 표기도 읽는다


def test_bea_only_pce_rows():
    assert I.parse_bea_pce(BEA) == [(date(2026, 10, 29), time(8, 30), '9월분')]


def test_boj_last_day_and_month_change():
    rows = dict(I.parse_boj(BOJ))
    assert rows[date(2026, 5, 1)] is True               # 달이 바뀌는 회의
    assert rows[date(2026, 10, 29)] is True             # 줄바꿈이 섞인 표기
    assert rows[date(2026, 3, 19)] is False             # 전망보고서 없는 회의


def test_us_event_converts_dst():
    before = I._us_event('us_pce', 'PCE', I.BEA_SCHEDULE, date(2026, 10, 29), time(8, 30), '9월분')
    after = I._us_event('us_cpi', 'CPI', I.BLS_CPI, date(2026, 11, 10), time(8, 30), '10월분')
    assert '21:30 KST' in before.details[0]             # 서머타임 중
    assert '22:30 KST' in after.details[0]              # 서머타임 종료 후
    assert before.slot == after.slot == 'evening'
