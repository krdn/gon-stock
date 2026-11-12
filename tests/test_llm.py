import json

import httpx
import pytest

from gon_stock.llm import ProxyClient, ProxyFailure


def make(handler, base='https://proxy.example'):
    return ProxyClient(base, 'synthetic-key', transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    'base',
    [
        'http://public.example',
        'https://user:pass@proxy.example',
        'https://proxy.example?key=value',
        'file:///tmp/a',
    ],
)
def test_unsafe_proxy_urls_are_rejected(base):
    with pytest.raises(ProxyFailure):
        make(lambda r: None, base)


def test_probe_proves_request_response_model_and_usage_without_echoing_content():
    calls = []

    def handler(r):
        calls.append(r)
        assert r.headers['authorization'] == 'Bearer synthetic-key'
        if r.url.path == '/v1/models':
            return httpx.Response(200, json={'data': [{'id': 'candidate-model'}]})
        assert r.method == 'POST' and r.url.path == '/v1/chat/completions'
        body = json.loads(r.content)
        assert body['model'] == 'candidate-model'
        assert body['messages'] == [{'role': 'user', 'content': 'Reply with OK only.'}]
        assert 'tools' not in body and body['stream'] is False
        return httpx.Response(
            200,
            json={
                'model': 'candidate-model',
                'choices': [{'message': {'content': 'private response'}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 8, 'completion_tokens': 1, 'total_tokens': 9},
            },
        )

    with make(handler) as client:
        result = client.probe('candidate-model')
    assert result.model_matches and result.returned_model == 'candidate-model'
    assert result.total_tokens == 9
    assert result.elapsed_seconds >= 0
    assert 'private response' not in repr(result)
    assert len(calls) == 2


def test_unlisted_model_never_sends_completion():
    calls = []

    def handler(r):
        calls.append(r)
        return httpx.Response(200, json={'data': [{'id': 'known'}]})

    with make(handler) as client:
        with pytest.raises(ProxyFailure, match='model_not_listed'):
            client.probe('unknown')
    assert len(calls) == 1


def test_alias_mismatch_is_reported_and_not_silently_accepted():
    def handler(r):
        if r.url.path == '/v1/models':
            return httpx.Response(200, json={'data': [{'id': 'requested'}]})
        return httpx.Response(
            200,
            json={
                'model': 'different',
                'choices': [{'message': {'content': 'OK'}, 'finish_reason': 'stop'}],
            },
        )

    with make(handler) as client:
        result = client.probe('requested')
    assert not result.model_matches
    assert result.requested_model == 'requested' and result.returned_model == 'different'


def test_completion_returns_content_and_trace_without_tools_or_response_repr():
    messages = [
        {'role': 'system', 'content': 'Return JSON.'},
        {'role': 'user', 'content': 'fixture'},
    ]

    def handler(request):
        if request.url.path == '/v1/models':
            return httpx.Response(200, json={'data': [{'id': 'candidate-model'}]})
        body = json.loads(request.content)
        assert body['messages'] == messages
        assert body['max_tokens'] == 2048
        assert 'tools' not in body and body['stream'] is False
        return httpx.Response(
            200,
            json={
                'model': 'candidate-model',
                'choices': [
                    {'message': {'content': '{"private":"fixture"}'}, 'finish_reason': 'stop'}
                ],
            },
        )

    with make(handler) as client:
        result = client.complete('candidate-model', messages)
    assert result.content == '{"private":"fixture"}'
    assert result.model_matches
    assert 'private' not in repr(result)


def test_completion_rejects_invalid_messages_before_network():
    with make(lambda _: pytest.fail('unexpected network')) as client:
        for messages in (
            [],
            [{'role': 'tool', 'content': 'x'}],
            [{'role': 'user', 'content': 'x', 'tools': ['order']}],
            [{'role': 'user', 'content': 'x' * 64001}],
        ):
            with pytest.raises(ProxyFailure):
                client.complete('candidate-model', messages)


@pytest.mark.parametrize(
    ('response', 'code'),
    [
        (httpx.Response(401, text='synthetic-key'), 'authentication_failed'),
        (httpx.Response(429, text='synthetic-key'), 'rate_limited'),
        (httpx.Response(503, text='synthetic-key'), 'provider_unavailable'),
        (httpx.Response(302, headers={'location': 'https://elsewhere.example'}), 'http_error'),
        (httpx.Response(200, content=b'synthetic-key'), 'invalid_response'),
        (httpx.Response(200, json={'data': [{}]}), 'invalid_response'),
    ],
)
def test_proxy_errors_are_redacted(response, code):
    with make(lambda r: response) as client:
        with pytest.raises(ProxyFailure) as exc:
            client.models()
    assert exc.value.code == code
    assert 'synthetic-key' not in str(exc.value)
    assert exc.value.__context__ is None


def test_timeout_is_not_retried_and_retains_no_secret_context():
    calls = []

    def handler(r):
        calls.append(r)
        raise httpx.ReadTimeout('synthetic-key', request=r)

    with make(handler) as client:
        with pytest.raises(ProxyFailure, match='timeout') as exc:
            client.models()
    assert len(calls) == 1 and exc.value.__context__ is None


@pytest.mark.parametrize(
    'body',
    [
        {'model': 'm', 'choices': []},
        {'model': 'm', 'choices': [{'message': {'content': ''}, 'finish_reason': 'stop'}]},
        {'model': 'm', 'choices': [{'message': {'content': 'OK'}, 'finish_reason': 'length'}]},
        {
            'model': 'm',
            'choices': [
                {'message': {'content': 'OK', 'tool_calls': [{}]}, 'finish_reason': 'stop'}
            ],
        },
        {
            'model': 'm',
            'choices': [{'message': {'content': 'OK'}, 'finish_reason': 'stop'}],
            'usage': {'total_tokens': True},
        },
    ],
)
def test_incomplete_or_invalid_completion_is_not_success(body):
    def handler(r):
        return httpx.Response(
            200, json={'data': [{'id': 'm'}]} if r.url.path.endswith('models') else body
        )

    with make(handler) as client:
        with pytest.raises(ProxyFailure):
            client.probe('m')


def test_cli_does_not_echo_key_or_private_endpoint(tmp_path, monkeypatch, capsys):
    import subprocess

    from gon_stock.llm_cli import main

    settings = tmp_path / 'settings.json'
    settings.write_text(json.dumps({'llm_proxy_base_url': 'https://private.example'}))
    monkeypatch.setattr('sys.argv', ['gon-stock-llm', 'models', '--settings', str(settings)])

    def run(argv, **kwargs):
        assert argv == ['secret-tool', 'lookup', 'service', 'gon-stock-llm-proxy']
        return subprocess.CompletedProcess(argv, 0, 'synthetic-key\n')

    monkeypatch.setattr('gon_stock.llm_cli.subprocess.run', run)
    monkeypatch.setattr(
        httpx.Client,
        'request',
        lambda *a, **k: httpx.Response(200, json={'data': [{'id': 'approved-model'}]}),
    )
    main()
    text = capsys.readouterr().out
    assert 'approved-model' in text
    assert 'synthetic-key' not in text and 'private.example' not in text
