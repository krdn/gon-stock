from contextlib import nullcontext
from datetime import datetime, timedelta

import pytest

from gon_stock.collector import capture, next_poll, recent_rows
from gon_stock.event_store import utc
from gon_stock.kis import ConnectionFailure, ReadResult


def test_schedule_waits_for_completed_minute_and_stops_after_close():
    calendar = {'sessions': [{'open': '2026-11-12T00:00:00Z', 'close': '2026-11-12T06:30:00Z'}]}
    assert next_poll(calendar, utc('2026-11-11T23:00:00Z')) == utc('2026-11-12T00:01:20Z')
    assert next_poll(calendar, utc('2026-11-12T01:10:21Z')) == utc('2026-11-12T01:11:20Z')
    end = utc('2026-11-12T06:31:20Z')
    assert next_poll(calendar, end) == end
    assert next_poll(calendar, end + timedelta(microseconds=1)) is None


def test_recent_rows_are_chosen_by_clock_not_response_order():
    def row(time):
        return {'source_clock': {'source_date': '2026-11-12', 'source_time': time}}

    rows = [row('09:30:00'), row('09:32:00'), row('09:31:00')]
    assert recent_rows(rows) == rows[1:]
    with pytest.raises(ValueError):
        recent_rows([{'source_clock': {'source_date': None, 'source_time': None}}])


def test_capture_only_fetches_market_bars_and_preserves_actual_receipt():
    class Client:
        def fetch(self, operation, **params):
            assert operation == 'kr_bars'
            assert params == {'symbol': '005930'}
            return ReadResult(
                {
                    'output2': [
                        {
                            'stck_bsop_date': '20261112',
                            'stck_cntg_hour': hour,
                            'stck_oprc': '100',
                            'stck_hgpr': '102',
                            'stck_lwpr': '99',
                            'stck_prpr': '101',
                            'cntg_vol': '100',
                        }
                        for hour in ('093000', '093200', '093100')
                    ]
                },
                utc('2026-11-12T00:32:21Z'),
                False,
            )

    rows = []

    class Store:
        def append(self, row):
            rows.append(row)

    target = {'exchange': 'XKRX', 'symbol': '005930', 'currency': 'KRW'}
    result = capture(Client(), Store(), target, now=lambda: utc('2026-11-12T00:32:20Z'))
    assert result['stored'] == 2
    assert result['verified'] == 1
    assert all(row['received_at'] == '2026-11-12T00:32:21+00:00' for row in rows)
    assert {row['source_clock']['source_time'] for row in rows} == {'09:31:00', '09:32:00'}

    class FailedClient:
        def fetch(self, *args, **kwargs):
            raise ConnectionFailure('network_failure')

    with pytest.raises(ConnectionFailure):
        capture(FailedClient(), Store(), target)
    assert len(rows) == 2


def test_resume_after_close_does_not_fetch_off_session(monkeypatch, tmp_path):
    import gon_stock.collector as module

    current = [utc('2026-11-12T00:00:00Z')]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current[0]

    def sleep(_):
        current[0] = utc('2026-11-12T10:00:00Z')

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, 'datetime', Clock)
    monkeypatch.setattr(module.time, 'sleep', sleep)
    monkeypatch.setattr(module, 'credentials', lambda _: None)
    monkeypatch.setattr(module, 'KisReadClient', lambda *args: nullcontext(None))
    monkeypatch.setattr(
        module,
        'calendar_snapshot',
        lambda *args: {
            'sha256': 'fixture',
            'sessions': [{'open': '2026-11-12T00:00:00Z', 'close': '2026-11-12T06:30:00Z'}],
        },
    )
    monkeypatch.setattr(module, 'capture', lambda *args: pytest.fail('off-session GET'))
    monkeypatch.setattr(
        'sys.argv',
        [
            'collect',
            '--exchange',
            'XKRX',
            '--symbols',
            '005930',
            '--db',
            '.private/test.duckdb',
            '--until',
            '2026-11-13T00:00:00Z',
        ],
    )
    module.main()
