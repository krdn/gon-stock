import json
import subprocess
from unittest.mock import patch

import pytest

from gon_stock.cli import credentials
from gon_stock.kis import ConnectionFailure


def test_secret_lookup_is_environment_scoped_and_repr_is_redacted():
    def run(argv, **kwargs):
        assert argv == ['secret-tool', 'lookup', 'service', 'gon-stock-kis', 'environment', 'mock']
        assert kwargs['capture_output']
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps(
                {
                    'app_key': 'secret-app',
                    'secret_key': 'secret-key',
                    'account': '12345678',
                    'product': '01',
                }
            ),
        )

    with patch('gon_stock.cli.subprocess.run', run):
        value = credentials('mock')
    assert value.account == '12345678'
    assert 'secret' not in repr(value) and '12345678' not in repr(value)


@pytest.mark.parametrize('output', ['', 'not-json', '{}', '[]'])
def test_invalid_or_missing_secret_fails_without_echo(output):
    with patch(
        'gon_stock.cli.subprocess.run', return_value=subprocess.CompletedProcess([], 0, output)
    ):
        with pytest.raises(ConnectionFailure):
            credentials('mock')


def test_registration_requires_real_terminal():
    with patch('gon_stock.cli.sys.stdin.isatty', return_value=False):
        with pytest.raises(ConnectionFailure, match='terminal_required'):
            credentials('mock', register=True)


def test_probe_reuses_token_and_only_emits_summaries(monkeypatch, capsys):
    import httpx

    from gon_stock.cli import main

    calls = []

    def request(self, method, path, **kwargs):
        calls.append((method, path))
        if path == '/oauth2/tokenP':
            return httpx.Response(
                200,
                json={'access_token': 'secret-token', 'token_type': 'Bearer', 'expires_in': 86400},
            )
        output = {
            'rt_cd': '0',
            'output': {'price': 'private-value'},
            'output1': {'price': 'private-value'},
            'output2': {},
        }
        if path.endswith('inquire-balance'):
            output['output1'] = []
        return httpx.Response(200, json=output)

    monkeypatch.setattr('sys.argv', ['gon-stock', 'probe', '--environment', 'mock'])
    monkeypatch.setattr('gon_stock.kis.time.sleep', lambda _: None)
    monkeypatch.setattr(httpx.Client, 'request', request)
    with patch(
        'gon_stock.cli.subprocess.run',
        return_value=subprocess.CompletedProcess(
            [],
            0,
            json.dumps(
                {'app_key': 'key', 'secret_key': 'secret', 'account': '12345678', 'product': '01'}
            ),
        ),
    ):
        main()
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 6
    assert len(calls) == 7
    assert 'private-value' not in output and 'secret' not in output


def test_corrupt_secret_does_not_retain_json_context():
    with patch(
        'gon_stock.cli.subprocess.run',
        return_value=subprocess.CompletedProcess([], 0, '{"secret_key": "secret",'),
    ):
        with pytest.raises(ConnectionFailure) as exc:
            credentials('mock')
    assert exc.value.__context__ is None


def test_probe_stops_after_token_timeout(monkeypatch, capsys):
    import httpx

    from gon_stock.cli import main

    calls = []

    def request(self, method, path, **kwargs):
        calls.append(path)
        raise httpx.ReadTimeout('secret')

    monkeypatch.setattr('sys.argv', ['gon-stock', 'probe', '--environment', 'mock'])
    monkeypatch.setattr('gon_stock.kis.time.sleep', lambda _: None)
    monkeypatch.setattr(httpx.Client, 'request', request)
    with patch(
        'gon_stock.cli.subprocess.run',
        return_value=subprocess.CompletedProcess(
            [],
            0,
            json.dumps(
                {'app_key': 'key', 'secret_key': 'secret', 'account': '12345678', 'product': '01'}
            ),
        ),
    ):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    assert calls == ['/oauth2/tokenP']
    assert len(capsys.readouterr().out.splitlines()) == 1
