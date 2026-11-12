import importlib
import threading

import httpx
import pytest


def api():
    try:
        return importlib.import_module('gon_stock.workbench')
    except ModuleNotFoundError:
        pytest.fail('P4 workbench is not implemented')


@pytest.fixture
def server(tmp_path):
    value = api().make_server(tmp_path / 'state.sqlite', tmp_path / 'settings.json', port=0)
    thread = threading.Thread(target=value.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{value.server_port}'
    with httpx.Client(base_url=url, trust_env=False) as client:
        yield client, url
    value.shutdown()
    value.server_close()
    thread.join()


def test_watchlist_real_http_roundtrip_and_safety_state(server):
    client, origin = server
    page = client.get('/')
    assert page.status_code == 200 and '연구 작업대' in page.text
    assert page.headers['cache-control'] == 'no-store'
    assert "default-src 'self'" in page.headers['content-security-policy']
    assert client.get('/api/state').json()['holdings_status'] == 'not_connected'
    target = {'exchange': 'XKRX', 'symbol': '005930', 'currency': 'KRW'}
    assert client.post('/api/watch', headers={'origin': origin}, json=target).status_code == 200
    state = client.get('/api/state').json()
    assert state['watchlist'] == [target] and state['order_allowed'] is False
    assert state['p3_status'] == 'pending'
    assert (
        client.post('/api/pause', headers={'origin': origin}, json={'paused': True}).status_code
        == 200
    )
    assert client.get('/api/state').json()['paused'] is True
    assert client.post('/api/unwatch', headers={'origin': origin}, json=target).status_code == 200
    assert client.get('/api/state').json()['watchlist'] == []


def test_cross_origin_dns_rebinding_and_arbitrary_file_routes_are_refused(server):
    client, _ = server
    target = {'exchange': 'XKRX', 'symbol': '005930', 'currency': 'KRW'}
    for origin in ('https://evil.example', 'null', ''):
        response = client.post('/api/watch', headers={'origin': origin}, json=target)
        assert response.status_code == 403
    assert client.get('/', headers={'host': 'evil.example'}).status_code == 403
    assert client.get('/.private/operator-settings.json').status_code == 404
    assert client.get('/api/state').json()['watchlist'] == []


def test_invalid_input_and_missing_credentials_emit_only_safe_error(server):
    client, origin = server
    response = client.post('/api/watch', headers={'origin': origin}, json={'secret': 'no-echo'})
    assert response.status_code == 400 and 'no-echo' not in response.text
    response = client.post('/api/discuss', headers={'origin': origin}, json={'secret': 'no-echo'})
    assert response.status_code == 400 and 'no-echo' not in response.text
    assert client.get('/api/state').json()['runs'] == []
