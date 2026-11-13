import importlib
import json

import httpx
import pytest


def api():
    try:
        return importlib.import_module('gon_stock.alpaca_history')
    except ModuleNotFoundError:
        pytest.fail('Alpaca SIP acquisition boundary missing')


def bar():
    return {
        't': '2026-10-30T13:30:00Z',
        'o': 189.31,
        'h': 189.5,
        'l': 189.2,
        'c': 189.44,
        'v': 1234,
        'n': 37,
        'vw': 189.3712,
    }


def test_pages_keep_sip_raw_and_actual_receipt(tmp_path):
    calls = []

    def serve(request):
        calls.append(request)
        assert request.method == 'GET'
        assert request.url.host == 'data.alpaca.markets'
        assert request.url.path == '/v2/stocks/bars'
        assert request.url.params['feed'] == 'sip'
        assert request.url.params['adjustment'] == 'raw'
        assert request.url.params['asof'] == '-'
        assert request.headers['APCA-API-KEY-ID'] == 'test-key'
        symbol = 'AAPL' if len(calls) == 1 else 'QQQ'
        return httpx.Response(
            200,
            json={
                'bars': {symbol: [bar()]},
                'next_page_token': 'next' if len(calls) == 1 else None,
            },
        )

    result = api().download(
        {'key_id': 'test-key', 'secret_key': 'test-secret'},
        ['AAPL', 'QQQ'],
        '2026-05-22T13:30:00Z',
        '2026-11-11T20:59:59Z',
        tmp_path / 'pages',
        transport=httpx.MockTransport(serve),
    )
    assert result['counts'] == {'AAPL': 1, 'QQQ': 1}
    assert calls[1].url.params['page_token'] == 'next'
    saved = json.loads((tmp_path / 'pages/0000.json').read_text())
    assert saved['received_at'] > '2026-11-12'
    assert saved['payload']['bars']['AAPL'][0]['t'] == '2026-10-30T13:30:00Z'
    assert 'test-secret' not in (tmp_path / 'pages/0000.json').read_text()
    assert saved['payload'] == {'bars': {'AAPL': [bar()]}, 'next_page_token': 'next'}
    assert saved['payload_sha256'] == api().digest(api().canonical(saved['payload']))
    assert result['acceptance'] == 'NOT_EVALUATED'


def test_auth_failure_has_no_iex_fallback(tmp_path):
    calls = []

    def serve(request):
        calls.append(request)
        return httpx.Response(403, json={'message': 'do not expose response or key'})

    with pytest.raises(ValueError, match='alpaca_http_403'):
        api().download(
            {'key_id': 'x', 'secret_key': 'y'},
            ['AAPL', 'QQQ'],
            '2026-05-22T13:30:00Z',
            '2026-11-11T20:59:59Z',
            tmp_path / 'pages',
            transport=httpx.MockTransport(serve),
        )
    assert len(calls) == 1


def test_repeated_cursor_and_missing_symbol_fail(tmp_path):
    for token, error in [('same', 'repeated_page_token'), (None, 'missing_requested_symbol')]:
        with pytest.raises(ValueError, match=error):
            api().download(
                {'key_id': 'x', 'secret_key': 'y'},
                ['AAPL', 'QQQ'],
                '2026-05-22T13:30:00Z',
                '2026-11-11T20:59:59Z',
                tmp_path / str(token),
                transport=httpx.MockTransport(
                    lambda _, token=token: httpx.Response(
                        200, json={'bars': {'AAPL': [bar()]}, 'next_page_token': token}
                    )
                ),
            )


@pytest.mark.parametrize(
    'payload',
    [
        {'bars': {'AAPL': [bar()], 'QQQ': [bar()]}},
        {'bars': {'SPY': [bar()]}, 'next_page_token': None},
        {'bars': {'AAPL': [{**bar(), 't': '2020-01-01T00:00:00Z'}]}, 'next_page_token': None},
    ],
)
def test_malformed_response_is_not_marked_complete(tmp_path, payload):
    with pytest.raises(ValueError):
        api().download(
            {'key_id': 'x', 'secret_key': 'y'},
            ['AAPL', 'QQQ'],
            '2026-05-22T13:30:00Z',
            '2026-11-11T20:59:59Z',
            tmp_path / 'pages',
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
        )
    assert not (tmp_path / 'pages/manifest.json').exists()


def normalized_page(rows=None):
    payload = {'bars': {'AAPL': rows if rows is not None else [bar()]}, 'next_page_token': None}
    return {
        'source': 'alpaca_sip',
        'params': {
            'symbols': 'AAPL,QQQ',
            'timeframe': '1Min',
            'feed': 'sip',
            'adjustment': 'raw',
            'asof': '-',
            'start': '2026-05-22T13:30:00Z',
            'end': '2026-11-11T20:59:59Z',
        },
        'received_at': '2026-11-13T00:00:00Z',
        'payload': payload,
        'payload_sha256': api().digest(api().canonical(payload)),
    }


def normalize(page, target=None):
    assert hasattr(api(), 'history_events'), 'Alpaca normalization is missing'
    return api().history_events(
        page, target or {'exchange': 'XNAS', 'symbol': 'AAPL', 'currency': 'USD'}
    )


def test_normalization_keeps_alpaca_provenance_and_actual_receipts():
    page = normalized_page()
    event = normalize(page)[0]
    assert event['source'] == 'alpaca_sip'
    assert event['endpoint'] == 'alpaca_history'
    assert event['received_at'] == '2026-11-13T00:00:00+00:00'
    assert event['event_time'] == '2026-10-30T13:30:00+00:00'
    assert event['data']['open'] == '189.31'
    assert event['raw_sha256'] == api().digest(api().canonical(bar()))
    assert event['clock_status'] == 'verified'
    assert normalize(page, {'exchange': 'XNAS', 'symbol': 'QQQ', 'currency': 'USD'}) == []


@pytest.mark.parametrize('change', ['hash', 'feed', 'ohlc', 'time', 'volume', 'target'])
def test_normalization_rejects_invalid_external_data(change):
    page = normalized_page()
    target = {'exchange': 'XNAS', 'symbol': 'AAPL', 'currency': 'USD'}
    if change == 'hash':
        page['payload_sha256'] = '0' * 64
    elif change == 'feed':
        page['params']['feed'] = 'iex'
    elif change == 'target':
        target = {'exchange': 'XKRX', 'symbol': '005930', 'currency': 'KRW'}
    else:
        page['payload']['bars']['AAPL'][0][{'ohlc': 'h', 'time': 't', 'volume': 'v'}[change]] = {
            'ohlc': 1,
            'time': '2026-10-30T13:30:01Z',
            'volume': 1.5,
        }[change]
        page['payload_sha256'] = api().digest(api().canonical(page['payload']))
    with pytest.raises(ValueError):
        normalize(page, target)


def test_alpaca_history_simulation_preserves_receipt_and_stays_blocked():
    from copy import deepcopy

    from test_backtest import ASSET, BENCHMARK, COSTS, fixture_rows

    from gon_stock.backtest import backtest
    from gon_stock.evaluation import VERIFICATIONS, evaluate
    from gon_stock.event_store import validate_event

    rows, calendar = fixture_rows()
    for row in rows:
        row['source'] = 'alpaca_sip'
        row['environment'] = 'real'
        row['endpoint'] = 'alpaca_history'
        row['received_at'] = '2026-11-13T00:00:00+00:00'
    before = deepcopy(rows)
    result = backtest(rows, calendar, [ASSET], BENCHMARK, COSTS, historical_delay_seconds=80)
    assert rows == before
    assert len(result['trades']) == 1
    assert result['trades'][0]['entry_at'] == '2026-11-12T14:52:00+00:00'
    manifest = {
        'source_kind': 'vendor_history',
        'environment': 'real',
        'train_end': '2026-09-01',
        'calibration_end': '2026-10-01',
        'test_end': '2026-11-12',
        'verified': dict.fromkeys(VERIFICATIONS, True),
    }
    assessment = evaluate(result, ['2026-11-10', '2026-11-11', '2026-11-12'], manifest)
    assert assessment['status'] == 'BLOCKED'
    assert 'assumed_historical_availability' in assessment['blockers']
    assert assessment['probabilities'] == {}
    invalid = {k: v for k, v in rows[0].items() if k != 'receipt_seq'}
    invalid['source'] = 'kis'
    with pytest.raises(ValueError):
        validate_event(invalid)
