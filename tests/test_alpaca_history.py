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
