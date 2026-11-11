import json
from datetime import UTC

import httpx
import pytest

from gon_stock.kis import ConnectionFailure, Credentials, KisReadClient


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr('gon_stock.kis.time.sleep', lambda _: None)


def make(handler, environment='mock'):
    return KisReadClient(
        Credentials('key', 'secret', '12345678', '01'),
        environment,
        transport=httpx.MockTransport(handler),
    )


def token():
    return httpx.Response(
        200, json={'access_token': 'token', 'token_type': 'Bearer', 'expires_in': 86400}
    )


def test_domestic_bars_readonly_contract():
    def handler(r):
        if r.url.path == '/oauth2/tokenP':
            return token()
        assert r.method == 'GET'
        assert r.url.path == '/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice'
        assert r.headers['tr_id'] == 'FHKST03010200'
        assert dict(r.url.params) == {
            'FID_COND_MRKT_DIV_CODE': 'J',
            'FID_INPUT_ISCD': '005930',
            'FID_INPUT_HOUR_1': '155900',
            'FID_PW_DATA_INCU_YN': 'N',
            'FID_ETC_CLS_CODE': '',
        }
        return httpx.Response(
            200,
            json={
                'rt_cd': '0',
                'output1': {'stck_prpr': '71000'},
                'output2': [{'stck_bsop_date': '20261111', 'stck_cntg_hour': '153000'}],
            },
        )

    with make(handler) as client:
        result = client.fetch('kr_bars', symbol='005930')
    assert result.clock.status == 'dated_bar'
    assert result.clock.source_date == '2026-11-11'
    assert result.event_time is None


@pytest.mark.parametrize('rows', [None, {}, 'invalid'])
def test_domestic_bars_reject_non_list_rows(rows):
    def handler(r):
        return (
            token()
            if r.url.path == '/oauth2/tokenP'
            else httpx.Response(
                200,
                json={'rt_cd': '0', 'output1': {}, 'output2': rows},
            )
        )

    with make(handler) as client, pytest.raises(ConnectionFailure, match='invalid_response'):
        client.fetch('kr_bars', symbol='005930')


def test_empty_domestic_bars_do_not_claim_a_timestamp():
    def handler(r):
        return (
            token()
            if r.url.path == '/oauth2/tokenP'
            else httpx.Response(
                200,
                json={'rt_cd': '0', 'output1': {}, 'output2': []},
            )
        )

    with make(handler) as client:
        result = client.fetch('kr_bars', symbol='005930')
    assert result.clock.status == 'missing'
    assert result.event_time is None


def test_orders_and_invalid_parameters_never_send_credentials():
    calls = []
    with make(lambda r: calls.append(r)) as client:
        for op, params in [
            ('order', {}),
            ('kr_quote', {'symbol': '../bad'}),
            ('kr_quote', {'symbol': '005930', 'quantity': '1'}),
            ('us_quote', {'symbol': 'AAPL', 'exchange': 'BAD'}),
        ]:
            with pytest.raises(ConnectionFailure):
                client.fetch(op, **params)
    assert calls == []


def test_arbitrary_environment_is_rejected():
    with pytest.raises(ConnectionFailure, match='invalid_environment'):
        make(lambda r: token(), 'https://other.example')


@pytest.mark.parametrize(
    ('env', 'host', 'port'),
    [
        ('mock', 'openapivts.koreainvestment.com', 29443),
        ('real', 'openapi.koreainvestment.com', 9443),
    ],
)
def test_quote_contract_and_token_reuse(env, host, port):
    calls = []

    def handler(r):
        calls.append(r)
        assert r.url.host == host and r.url.port == port
        if r.url.path == '/oauth2/tokenP':
            assert json.loads(r.content) == {
                'grant_type': 'client_credentials',
                'appkey': 'key',
                'appsecret': 'secret',
            }
            return token()
        assert r.method == 'GET'
        assert r.url.path == '/uapi/domestic-stock/v1/quotations/inquire-price'
        assert r.headers['tr_id'] == 'FHKST01010100'
        assert r.headers['content-type'] == 'application/json; charset=utf-8'
        assert r.headers['authorization'] == 'Bearer token'
        assert dict(r.url.params) == {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': '005930'}
        return httpx.Response(200, json={'rt_cd': '0', 'output': {'stck_prpr': '71000'}})

    with make(handler, env) as client:
        result = client.fetch('kr_quote', symbol='005930')
        client.fetch('kr_quote', symbol='005930')
    assert len(calls) == 3
    assert result.payload['output']['stck_prpr'] == '71000'
    assert result.received_at.tzinfo == UTC
    assert result.event_time is None
    assert '71000' not in repr(result)


@pytest.mark.parametrize(
    ('response', 'code'),
    [
        (httpx.Response(200, json={'rt_cd': '1', 'msg1': 'secret'}), 'broker_rejected'),
        (httpx.Response(200, json={'rt_cd': False}), 'invalid_response'),
        (httpx.Response(200, json={'rt_cd': '0'}), 'invalid_response'),
        (httpx.Response(200, content=b'secret'), 'invalid_response'),
        (httpx.Response(429), 'rate_limited'),
        (httpx.Response(401), 'authentication_failed'),
        (httpx.Response(302, headers={'location': 'https://other.example'}), 'http_error'),
    ],
)
def test_fail_closed_and_redacted(response, code):
    with make(lambda r: token() if r.url.path == '/oauth2/tokenP' else response) as client:
        with pytest.raises(ConnectionFailure) as exc:
            client.fetch('kr_quote', symbol='005930')
    assert exc.value.code == code
    assert 'secret' not in str(exc.value)
    assert exc.value.__cause__ is None


def test_timeout_is_not_retried():
    calls = []

    def handler(r):
        calls.append(r)
        raise httpx.ReadTimeout('secret', request=r)

    with make(handler) as client:
        with pytest.raises(ConnectionFailure, match='timeout'):
            client.fetch('kr_quote', symbol='005930')
    assert len(calls) == 1


@pytest.mark.parametrize('expiry', [0, -1, True, '86400'])
def test_invalid_token_never_queries(expiry):
    calls = []

    def handler(r):
        calls.append(r)
        return httpx.Response(
            200, json={'access_token': 'token', 'token_type': 'Bearer', 'expires_in': expiry}
        )

    with make(handler) as client:
        with pytest.raises(ConnectionFailure, match='invalid_response'):
            client.fetch('kr_quote', symbol='005930')
    assert len(calls) == 1


@pytest.mark.parametrize(
    ('operation', 'tr_id', 'path', 'params', 'outputs'),
    [
        (
            'us_quote',
            'HHDFS00000300',
            '/uapi/overseas-price/v1/quotations/price',
            {'symbol': 'AAPL', 'exchange': 'NAS'},
            {'output': {'last': '200'}},
        ),
        (
            'kr_orderbook',
            'FHKST01010200',
            '/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn',
            {'symbol': '005930'},
            {'output1': {'askp1': '71000'}, 'output2': {}},
        ),
        (
            'us_orderbook',
            'HHDFS76200100',
            '/uapi/overseas-price/v1/quotations/inquire-asking-price',
            {'symbol': 'AAPL', 'exchange': 'NAS'},
            {'output1': {'rsym': 'DNAAPL'}, 'output2': {}},
        ),
        (
            'us_holdings',
            'VTTS3012R',
            '/uapi/overseas-stock/v1/trading/inquire-balance',
            {'exchange': 'NASD'},
            {'output1': [], 'output2': {}},
        ),
    ],
)
def test_other_read_contracts(operation, tr_id, path, params, outputs):
    def handler(r):
        if r.url.path == '/oauth2/tokenP':
            return token()
        assert r.method == 'GET' and r.url.path == path
        assert r.headers['tr_id'] == tr_id
        if operation.startswith('us_') and operation != 'us_holdings':
            assert dict(r.url.params) == {'AUTH': '', 'EXCD': 'NAS', 'SYMB': 'AAPL'}
        if operation == 'us_holdings':
            assert r.url.params['OVRS_EXCG_CD'] == 'NASD'
            assert r.url.params['CANO'] == '12345678'
        return httpx.Response(200, json={'rt_cd': '0', **outputs})

    with make(handler) as client:
        assert client.fetch(operation, **params).payload['rt_cd'] == '0'


@pytest.mark.parametrize('mode', ['complete', 'cycle', 'missing'])
def test_holdings_pagination(mode):
    calls = []

    def handler(r):
        if r.url.path == '/oauth2/tokenP':
            return token()
        calls.append(r)
        assert r.headers['tr_id'] == 'VTTC8434R'
        if len(calls) > 1:
            assert r.headers['tr_cont'] == 'N'
            assert r.url.params['CTX_AREA_NK100'] == 'next'
        more = len(calls) == 1 or mode == 'cycle'
        return httpx.Response(
            200,
            headers={'tr_cont': 'M' if more else 'D'},
            json={
                'rt_cd': '0',
                'output1': [],
                'output2': [],
                'ctx_area_fk100': 'fk',
                'ctx_area_nk100': '' if mode == 'missing' else 'next',
            },
        )

    with make(handler) as client:
        if mode == 'complete':
            assert len(client.fetch_pages('kr_holdings')) == 2
        else:
            with pytest.raises(ConnectionFailure):
                client.fetch_pages('kr_holdings')
    assert len(calls) <= 2


@pytest.mark.parametrize(
    ('status', 'field', 'code', 'expected'),
    [
        (500, 'msg_cd', 'EGW00201', 'rate_limited'),
        (403, 'error_code', 'EGW00133', 'rate_limited'),
        (500, 'msg_cd', 'EGW00121', 'authentication_failed'),
        (500, 'msg_cd', 'EGW00123', 'authentication_failed'),
        (200, 'msg_cd', 'EGW00201', 'rate_limited'),
    ],
)
def test_kis_error_codes_override_http_status(status, field, code, expected):
    def handler(r):
        if r.url.path == '/oauth2/tokenP':
            return token()
        return httpx.Response(status, json={'rt_cd': '1', field: code, 'msg1': 'secret'})

    with make(handler) as client:
        with pytest.raises(ConnectionFailure) as exc:
            client.fetch('kr_quote', symbol='005930')
    assert exc.value.code == expected


def test_network_error_does_not_retain_secret_request_context():
    def handler(r):
        raise httpx.ConnectError('secret', request=r)

    with make(handler) as client:
        with pytest.raises(ConnectionFailure) as exc:
            client.fetch('kr_quote', symbol='005930')
    assert exc.value.__context__ is None


def test_real_key_on_mock_account_reports_environment_mismatch():
    def handler(r):
        if r.url.path == '/oauth2/tokenP':
            return token()
        return httpx.Response(
            500,
            json={
                'rt_cd': '1',
                'msg_cd': 'EGW02007',
                'msg1': '해당 앱키는 모의투자용 앱키가 아닙니다',
            },
        )

    with make(handler) as client:
        with pytest.raises(ConnectionFailure, match='environment_mismatch'):
            client.fetch('kr_holdings')


@pytest.mark.parametrize('mode', ['complete', 'cycle', 'missing', 'limit'])
def test_us_holdings_continuation_and_page_limit(mode):
    calls = []

    def handler(r):
        if r.url.path == '/oauth2/tokenP':
            return token()
        calls.append(r)
        assert r.url.params['OVRS_EXCG_CD'] == 'NASD'
        assert r.headers['tr_id'] == 'VTTS3012R'
        if len(calls) > 1:
            assert r.headers['tr_cont'] == 'N'
            assert r.url.params['CTX_AREA_FK200'] == 'fk'
            assert r.url.params['CTX_AREA_NK200'] == (
                '1' if mode != 'limit' else str(len(calls) - 1)
            )
        more = len(calls) == 1 or mode != 'complete'
        next_key = str(len(calls)) if mode == 'limit' else '1'
        return httpx.Response(
            200,
            headers={'tr_cont': 'F' if more else 'D'},
            json={
                'rt_cd': '0',
                'output1': [],
                'output2': {},
                'ctx_area_fk200': 'fk',
                'ctx_area_nk200': '' if mode == 'missing' else next_key,
            },
        )

    with make(handler) as client:
        if mode == 'complete':
            assert len(client.fetch_pages('us_holdings', exchange='NASD')) == 2
        else:
            with pytest.raises(ConnectionFailure) as exc:
                client.fetch_pages('us_holdings', exchange='NASD')
            assert (
                exc.value.code
                == {
                    'cycle': 'pagination_cycle',
                    'missing': 'invalid_response',
                    'limit': 'pagination_limit',
                }[mode]
            )
    assert len(calls) == {'complete': 2, 'cycle': 2, 'missing': 1, 'limit': 100}[mode]
