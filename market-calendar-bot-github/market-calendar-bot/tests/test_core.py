import tempfile
import unittest
from datetime import date
from pathlib import Path

from marketbot.models import Event, Result, Session
from marketbot.providers.markets import parse_jpx, parse_nasdaq, parse_nyse
from marketbot.providers.monetary import dst_events, parse_bok, parse_fomc
from marketbot.providers.options import _adjust_prior, _nth_weekday
from marketbot.render import render
from marketbot.storage import Store, merge_with_confirmed_cache


class MarketParsingTests(unittest.TestCase):
    def test_nyse_closed_and_early_close(self):
        html = '''<table><tr><th>Holiday</th><th>2026</th></tr>
        <tr><td>Thanksgiving</td><td>Thursday, November 26</td></tr></table>
        <p>Each market will close early at 1:00 p.m. on Friday, November 27, 2026.</p>'''
        values, years = parse_nyse(html)
        self.assertEqual(years, {2026})
        self.assertEqual(values[2026][date(2026, 11, 26)][0], 'closed')
        self.assertEqual(values[2026][date(2026, 11, 27)][0], 'early_close')

    def test_nasdaq_status(self):
        values = parse_nasdaq('''<table><tr><td>November 27, 2026</td>
        <td>Early Close</td><td>1:00 p.m.</td></tr></table>''')
        self.assertEqual(values[date(2026, 11, 27)][0], 'early_close')

    def test_jpx_year_is_scoped_to_heading(self):
        rows = ''.join(f'<tr><td>Jan. {i} (Mon.)</td><td>Holiday {i}</td></tr>' for i in range(1, 11))
        values, years = parse_jpx(f'<div><h2>2026</h2></div><div><table>{rows}</table></div>')
        self.assertEqual(years, {2026})
        self.assertIn(date(2026, 1, 1), values[2026])


class MonetaryTests(unittest.TestCase):
    def test_fomc_ignores_one_day_notation_vote(self):
        meetings = ''.join(f'''<div class="row fomc-meeting"><div class="fomc-meeting__month">January</div>
        <div class="fomc-meeting__date">{i}-{i+1}</div></div>''' for i in range(1, 8))
        html = f'<div class="panel"><h4>2026 FOMC Meetings</h4>{meetings}<div class="fomc-meeting"><div class="fomc-meeting__month">August</div><div class="fomc-meeting__date">22 (notation vote)</div></div></div>'
        self.assertEqual(len(parse_fomc(html)[2026]), 7)

    def test_bok_requires_policy_table(self):
        rows = ''.join(f'<tr><td>{m}월 1일 (목)</td></tr>' for m in range(1, 7))
        html = f'<h2>2026년</h2><table><caption>통화정책방향</caption>{rows}</table>'
        self.assertEqual(len(parse_bok(html, 2026)), 6)

    def test_dst_korean_transition_times(self):
        text = 'second Sunday in March at 2 a.m. first Sunday in November at 2 a.m.'
        events = dst_events(2026, text)
        self.assertEqual(events[0].occurs_at, '2026-03-08T16:00:00+09:00')
        self.assertEqual(events[1].occurs_at, '2026-11-01T15:00:00+09:00')


class OptionsAndStateTests(unittest.TestCase):
    def test_second_thursday_and_holiday_adjustment(self):
        nominal = _nth_weekday(2026, 9, 3, 2)
        self.assertEqual(nominal, date(2026, 9, 10))
        sessions = {
            date(2026, 9, 10): Session('KR', '2026-09-10', 'closed', '휴장'),
            date(2026, 9, 9): Session('KR', '2026-09-09', 'open', '정상'),
        }
        self.assertEqual(_adjust_prior(nominal, sessions), (date(2026, 9, 9), True))

    def test_unknown_refresh_keeps_confirmed_session(self):
        old = Result('markets', sessions=[Session('US', '2026-01-02', 'open', '정상')])
        new = Result('markets', sessions=[Session('US', '2026-01-02', 'unknown', '실패', confirmed=False)])
        merged = merge_with_confirmed_cache(old, new)
        self.assertEqual(merged.sessions[0].status, 'open')

    def test_store_idempotency(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'test.sqlite3')
            store.mark_sent('2026-01-01:morning', 'message')
            self.assertTrue(store.was_sent('2026-01-01:morning'))
            store.close()

    def test_render_states_index_open_and_equity_close(self):
        event = Event('us_options:2026-09-18', 'us_options', '미장 월간 옵션 만기', 'US',
                      '2026-09-18', 'evening', details=[
                          '[지수 AM] SPX·NDX: 구성종목 개장가격 기준 결제',
                          '[개별주식] 장 마감 종가 기준 자동행사 판단'])
        session = Session('US', '2026-09-18', 'open', '정상 개장',
                          '2026-09-18T09:30:00-04:00', '2026-09-18T16:00:00-04:00')
        message = render([Result('x', events=[event], sessions=[session])], date(2026, 9, 18), 'evening')
        self.assertIn('개장가격', message)
        self.assertIn('장 마감 종가', message)


if __name__ == '__main__':
    unittest.main()
