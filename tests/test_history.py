import json
from datetime import UTC, datetime

import httpx
import pytest

from gon_stock.kis import ConnectionFailure, Credentials, KisReadClient


def test_history_route_keeps_real_receipt_and_uses_past_cursor():
    calls = []

    def serve(request):
        calls.append(request)
        if request.url.path == '/oauth2/tokenP':
            return httpx.Response(
                200,
                json={'access_token': 'test-token', 'expires_in': 86400, 'token_type': 'Bearer'},
            )
        return httpx.Response(200, json={'rt_cd': '0', 'output1': {'ok': '1'}, 'output2': []})

    with KisReadClient(
        Credentials('key', 'secret', '12345678', '01'), 'real', transport=httpx.MockTransport(serve)
    ) as client:
        page = client.fetch('kr_history', symbol='005930', before='20260601153000')
        assert page.received_at > datetime(2026, 6, 1, tzinfo=UTC)
        assert calls[-1].url.path.endswith('inquire-time-dailychartprice')
        assert calls[-1].url.params['FID_INPUT_DATE_1'] == '20260601'
        client.fetch('us_history', symbol='AAPL', exchange='NAS', before='20260601160000')
        assert calls[-1].url.params['KEYB'] == '20260601160000'
        assert calls[-1].url.params['NREC'] == '120'
        client.fetch('us_bars', symbol='AAPL', exchange='NAS')
        assert calls[-1].url.params['NREC'] == '2'
        assert all(c.method == 'GET' for c in calls[1:])


@pytest.mark.parametrize('before', ['20260230100000', '20990101100000', '20260601100001', 'bad'])
def test_history_invalid_cursor_fails_before_network(before):
    with KisReadClient(
        Credentials('key', 'secret', '12345678', '01'),
        'real',
        transport=httpx.MockTransport(lambda _: pytest.fail('network')),
    ) as client:
        with pytest.raises(ConnectionFailure):
            client.fetch('kr_history', symbol='005930', before=before)


def test_history_mock_environment_is_not_allowed():
    with KisReadClient(
        Credentials('key', 'secret', '12345678', '01'),
        'mock',
        transport=httpx.MockTransport(lambda _: pytest.fail('network')),
    ) as client:
        with pytest.raises(ConnectionFailure, match='unsupported_environment'):
            client.fetch('kr_history', symbol='005930', before='20260601153000')


def history_api():
    import importlib

    try:
        return importlib.import_module('gon_stock.history')
    except ModuleNotFoundError:
        pytest.fail('historical data boundary missing')


def test_download_pages_past_false_more_and_keeps_receipts(tmp_path):
    from gon_stock.event_store import utc

    calls = []
    target = {'exchange': 'XNAS', 'symbol': 'AAPL', 'currency': 'USD'}
    session = {
        'date': '2026-06-01',
        'open': '2026-06-01T13:30:00Z',
        'close': '2026-06-01T20:00:00Z',
    }

    def serve(request):
        if request.url.path == '/oauth2/tokenP':
            return httpx.Response(
                200,
                json={'access_token': 'test-token', 'expires_in': 86400, 'token_type': 'Bearer'},
            )
        key = request.url.params['KEYB']
        calls.append(key)
        times = [('155900', '045900')] if key.endswith('160000') else [('093000', '223000')]
        rows = [
            {
                'xymd': '20260601',
                'xhms': x,
                'kymd': '20260602' if x.startswith('15') else '20260601',
                'khms': k,
                'open': '100',
                'high': '101',
                'low': '99',
                'last': '100',
                'evol': '10',
            }
            for x, k in times
        ]
        return httpx.Response(200, json={'rt_cd': '0', 'output1': {'ok': '1'}, 'output2': rows})

    with KisReadClient(
        Credentials('key', 'secret', '12345678', '01'), 'real', transport=httpx.MockTransport(serve)
    ) as client:
        pages = history_api().download_day(client, target, session, tmp_path)
        assert calls == ['20260601160000', '20260601155800']
        assert len(pages) == 2
        assert all(utc(p['received_at']) > utc(session['close']) for p in pages)
        assert history_api().download_day(client, target, session, tmp_path) == pages
        assert len(calls) == 2
        saved = json.loads(next(tmp_path.glob('*.json')).read_text())
        saved['payload']['output2'] = []
        next(tmp_path.glob('*.json')).write_text(json.dumps(saved))
        with pytest.raises(ValueError, match='page_hash_mismatch'):
            history_api().download_day(client, target, session, tmp_path)


def test_history_normalization_preserves_actual_receipt_and_endpoint():
    target = {'exchange': 'XKRX', 'symbol': '005930', 'currency': 'KRW'}
    page = {
        'operation': 'kr_history',
        'received_at': '2026-11-13T00:00:00Z',
        'payload': {
            'output2': [
                {
                    'stck_bsop_date': '20260601',
                    'stck_cntg_hour': '093000',
                    'stck_oprc': '100',
                    'stck_hgpr': '101',
                    'stck_lwpr': '99',
                    'stck_prpr': '100',
                    'cntg_vol': '10',
                }
            ]
        },
    }
    event = history_api().history_events(page, target)[0]
    assert event['endpoint'] == 'kr_history'
    assert event['received_at'] == '2026-11-13T00:00:00+00:00'
    assert event['event_time'] == '2026-06-01T00:30:00+00:00'


def test_historical_simulation_keeps_original_receipts_and_cannot_pass_acceptance():
    from copy import deepcopy

    from test_backtest import ASSET, BENCHMARK, COSTS, fixture_rows

    from gon_stock.backtest import backtest
    from gon_stock.evaluation import VERIFICATIONS, evaluate

    rows, calendar = fixture_rows()
    for row in rows:
        row['endpoint'] = 'us_history'
        row['received_at'] = '2026-11-13T00:00:00+00:00'
    before = deepcopy(rows)
    live = backtest(rows, calendar, [ASSET], BENCHMARK, COSTS)
    assert live['trades'] == []
    simulated = backtest(rows, calendar, [ASSET], BENCHMARK, COSTS, historical_delay_seconds=80)
    assert rows == before
    assert len(simulated['trades']) == 1
    assert simulated['trades'][0]['decision_at'] == '2026-11-12T14:51:20+00:00'
    assert simulated['trades'][0]['entry_at'] == '2026-11-12T14:52:00+00:00'
    assert simulated['availability_mode'] == 'historical_assumption'
    manifest = {
        'source_kind': 'observed',
        'environment': 'real',
        'train_end': '2026-09-01',
        'calibration_end': '2026-10-01',
        'test_end': '2026-11-12',
        'verified': dict.fromkeys(VERIFICATIONS, True),
    }
    result = evaluate(simulated, ['2026-11-10', '2026-11-11', '2026-11-12'], manifest)
    assert result['status'] == 'BLOCKED'
    assert 'assumed_historical_availability' in result['blockers']
    assert result['probabilities'] == {}


def test_history_delay_must_be_explicit_and_history_only():
    from test_backtest import ASSET, BENCHMARK, COSTS, fixture_rows

    from gon_stock.backtest import backtest

    rows, calendar = fixture_rows()
    with pytest.raises(ValueError, match='history_only'):
        backtest(rows, calendar, [ASSET], BENCHMARK, COSTS, historical_delay_seconds=80)
    for delay in [0, 59, 121, True, 80.5]:
        with pytest.raises(ValueError, match='invalid_history_delay'):
            backtest(rows, calendar, [ASSET], BENCHMARK, COSTS, historical_delay_seconds=delay)


def test_reconciliation_does_not_fill_missing_bars_or_hide_conflicts():
    from copy import deepcopy

    from test_backtest import fixture_rows

    rows, calendar = fixture_rows()
    for r in rows:
        r['endpoint'] = 'us_history'
    duplicated = deepcopy(rows[0])
    duplicated['id'] = 'duplicate'
    duplicated['received_at'] = '2026-11-13T00:00:00Z'
    selected, quality = history_api().reconcile([*rows, duplicated], calendar)
    assert len(selected) == len(rows)
    assert quality['duplicates'] == 1
    assert quality['conflicts'] == 0
    assert sum(d['missing_minutes_assuming_start_label'] for d in quality['coverage']) == 0
    selected, quality = history_api().reconcile(rows[1:], calendar)
    assert sum(d['missing_minutes_assuming_start_label'] for d in quality['coverage']) == 1
    duplicated['data']['volume'] = '999'
    _, quality = history_api().reconcile([*rows, duplicated], calendar)
    assert quality['conflicts'] == 1
