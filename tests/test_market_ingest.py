import importlib

import pytest
from test_event_store import stamp

from gon_stock.kis import ReadResult


def api():
    try:
        return importlib.import_module('gon_stock.market_ingest')
    except ModuleNotFoundError:
        pytest.fail('P2 KIS normalization is not implemented')


def test_domestic_completed_bar_retains_source_clock_and_precision():
    row = {
        'stck_bsop_date': '20261112',
        'stck_cntg_hour': '093000',
        'stck_oprc': '100',
        'stck_hgpr': '102',
        'stck_lwpr': '99',
        'stck_prpr': '101',
        'cntg_vol': '12',
        'unexpected': 'not-stored',
    }
    result = ReadResult({'output2': [row]}, stamp('2026-11-12T00:32:01Z'), False)
    records = api().normalize_bars(
        result,
        'kr_bars',
        {'exchange': 'KRX', 'symbol': '123456', 'currency': 'KRW'},
        'mock',
        requested_at=stamp('2026-11-12T00:32:00Z'),
        request_id='fixture',
    )
    assert records[0]['event_time'] == '2026-11-12T00:30:00+00:00'
    assert records[0]['data']['close'] == '101'
    assert records[0]['clock_status'] == 'verified'
    assert records[0]['source_clock']['source_time'] == '09:30:00'
    assert 'not-stored' not in str(records)


def test_ongoing_and_zero_volume_domestic_bars_remain_unverified():
    row = {
        'stck_bsop_date': '20261112',
        'stck_cntg_hour': '093200',
        'stck_oprc': '100',
        'stck_hgpr': '102',
        'stck_lwpr': '99',
        'stck_prpr': '101',
        'cntg_vol': '0',
    }
    result = ReadResult({'output2': [row]}, stamp('2026-11-12T00:32:01Z'), False)
    record = api().normalize_bars(
        result,
        'kr_bars',
        {'exchange': 'KRX', 'symbol': '123456', 'currency': 'KRW'},
        'mock',
        requested_at=stamp('2026-11-12T00:32:00Z'),
        request_id='fixture',
    )[0]
    assert record['event_time'] is None
    assert record['clock_status'] == 'unverified'


def test_us_bar_timezone_mismatch_is_preserved_as_ineligible():
    row = {
        'kymd': '20261112',
        'khms': '233000',
        'xymd': '20261112',
        'xhms': '083000',
        'open': '100.1234',
        'high': '102',
        'low': '99',
        'last': '101',
        'evol': '12',
    }
    result = ReadResult({'output2': [row]}, stamp('2026-11-12T14:32:01Z'), False)
    record = api().normalize_bars(
        result,
        'us_bars',
        {'exchange': 'NAS', 'symbol': 'TEST', 'currency': 'USD'},
        'real',
        requested_at=stamp('2026-11-12T14:32:00Z'),
        request_id='fixture',
    )[0]
    assert record['clock_status'] == 'invalid'
    assert record['event_time'] is None
    assert record['data']['open'] == '100.1234'


def test_ingest_refuses_holdings_and_wrong_market():
    result = ReadResult({'output2': []}, stamp('2026-11-12T00:32:01Z'), False)
    for op, target in [
        ('kr_holdings', {'exchange': 'KRX', 'symbol': '123456', 'currency': 'KRW'}),
        ('kr_bars', {'exchange': 'NAS', 'symbol': 'TEST', 'currency': 'USD'}),
    ]:
        with pytest.raises(ValueError):
            api().normalize_bars(
                result,
                op,
                target,
                'mock',
                requested_at=stamp('2026-11-12T00:32:00Z'),
                request_id='fixture',
            )


@pytest.mark.parametrize(
    ('hour', 'local', 'status', 'expected'),
    [
        ('233000', '093000', 'verified', '2026-11-12T14:30:00+00:00'),
        ('233200', '093200', 'unverified', '2026-11-12T14:32:00+00:00'),
        ('233300', '093300', 'future', '2026-11-12T14:33:00+00:00'),
    ],
)
def test_us_clock_branches(hour, local, status, expected):
    row = {
        'kymd': '20261112',
        'khms': hour,
        'xymd': '20261112',
        'xhms': local,
        'open': '100',
        'high': '102',
        'low': '99',
        'last': '101',
        'evol': '12',
    }
    result = ReadResult({'output2': [row]}, stamp('2026-11-12T14:32:01Z'), False)
    record = api().normalize_bars(
        result,
        'us_bars',
        {'exchange': 'NAS', 'symbol': 'TEST', 'currency': 'USD'},
        'real',
        requested_at=stamp('2026-11-12T14:32:00Z'),
        request_id='fixture',
    )[0]
    assert record['clock_status'] == status
    assert record['event_time'] == expected
