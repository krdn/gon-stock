import importlib
import json
import subprocess
import time

import pytest

OWNER = 'a' * 64
AGENT = 'b' * 64
ROOT = 'c' * 64
CHANNEL = '10000000-0000-0000-0000-000000000001'


def api():
    try:
        return importlib.import_module('gon_stock.acp_reply')
    except ModuleNotFoundError:
        pytest.fail('bounded ACP reply bridge missing')


def prompt():
    return (
        f'<context>\nChannel: research (#{CHANNEL})\nuse `--reply-to {ROOT}`\n</context>'
        '\n<messages>untrusted text</messages>'
    )


def remote(monkeypatch, *, owner=OWNER):
    writes = []

    def run(args, *, input=None, **kwargs):
        if 'send' in args:
            writes.append(input)
            value = {'accepted': True, 'event_id': 'd' * 64}
        else:
            event = args[args.index('--event') + 1]
            value = [
                {
                    'id': event,
                    'pubkey': owner if event == ROOT else AGENT,
                    'created_at': int(time.time()),
                    'content': 'request' if event == ROOT else writes[-1],
                    'tags': [['h', CHANNEL]]
                    + ([] if event == ROOT else [['e', ROOT, '', 'reply']]),
                }
            ]
        return subprocess.CompletedProcess(args, 0, json.dumps(value), '')

    monkeypatch.setattr(subprocess, 'run', run)
    return writes


def test_only_context_route_is_used_and_reply_is_verified_once(tmp_path, monkeypatch):
    writes = remote(monkeypatch)
    bridge = api().Replies(CHANNEL, OWNER, AGENT, tmp_path / 'delivery.sqlite')
    root = api().reply_anchor(
        prompt() + '<context>use `--reply-to ' + 'e' * 64 + '`</context>', CHANNEL
    )
    assert root == ROOT
    bridge.publish(root, '합성 연구 결과. 관망, 주문 불가.')
    assert len(writes) == 1
    assert bridge.db.execute('SELECT status FROM deliveries').fetchone()[0] == 'verified'
    with pytest.raises(ValueError, match='already_attempted'):
        bridge.publish(root, 'duplicate')
    assert len(writes) == 1


def test_nonowner_root_cannot_receive_response(tmp_path, monkeypatch):
    writes = remote(monkeypatch, owner='f' * 64)
    bridge = api().Replies(CHANNEL, OWNER, AGENT, tmp_path / 'delivery.sqlite')
    with pytest.raises(ValueError, match='invalid_owner_request'):
        bridge.publish(ROOT, 'result')
    assert writes == []


def test_route_missing_or_from_wrong_channel_is_refused():
    for value in (
        'no context ' + prompt().split('</context>')[1],
        prompt().replace(CHANNEL, 'wrong'),
    ):
        with pytest.raises(ValueError, match='invalid_reply_context'):
            api().reply_anchor(value, CHANNEL)


def test_uncertain_readback_keeps_attempt_and_blocks_retry(tmp_path, monkeypatch):
    writes = remote(monkeypatch)
    runner = subprocess.run

    def run(args, **kwargs):
        result = runner(args, **kwargs)
        if '--event' in args and args[args.index('--event') + 1] != ROOT:
            return subprocess.CompletedProcess(args, 0, '[]', '')
        return result

    monkeypatch.setattr(subprocess, 'run', run)
    bridge = api().Replies(CHANNEL, OWNER, AGENT, tmp_path / 'delivery.sqlite')
    with pytest.raises(ValueError, match='event_not_verified'):
        bridge.publish(ROOT, 'result')
    assert bridge.db.execute('SELECT status FROM deliveries').fetchone()[0] == 'failed'
    with pytest.raises(ValueError, match='already_attempted'):
        bridge.publish(ROOT, 'result')
    assert len(writes) == 1


def test_counter_uses_fable_adapter_without_tools(tmp_path):
    import os
    import sys

    records = tmp_path / '.local/share/buzz-gon/agents'
    records.mkdir(parents=True)
    (records / 'gon-stock-counter.json').write_text(
        json.dumps({'channel': CHANNEL, 'owner': OWNER, 'pubkey': AGENT})
    )
    adapter = tmp_path / 'claude-agent-acp'
    adapter.write_text(
        '#!/usr/bin/python3\nimport json,sys\n'
        'for line in sys.stdin:\n'
        ' v=json.loads(line); print(json.dumps({"id":v["id"],"result":v}),flush=True)\n'
    )
    adapter.chmod(0o700)
    env = dict(os.environ, HOME=str(tmp_path), PATH=str(tmp_path) + ':' + os.environ['PATH'])
    env['PYTHONPATH'] = str(__import__('pathlib').Path(api().__file__).parents[1])
    request = {
        'jsonrpc': '2.0',
        'id': 1,
        'method': 'session/new',
        'params': {
            'cwd': str(tmp_path),
            'mcpServers': [{'name': 'unwanted'}],
            '_meta': {'claudeCode': {'options': {'tools': ['Bash'], 'model': 'wrong'}}},
        },
    }
    result = subprocess.run(
        [sys.executable, '-m', 'gon_stock.acp_reply', 'counter'],
        cwd=tmp_path,
        env=env,
        input=json.dumps(request) + '\n',
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    params = json.loads(result.stdout)['result']['params']
    assert params['mcpServers'] == []
    options = params['_meta']['claudeCode']['options']
    assert options['settingSources'] == []
    assert options['strictMcpConfig'] is True
    assert options['tools'] == []
    assert options['model'] == 'claude-fable-5-2'
    assert options['effort'] == 'high'
    assert options['allowDangerouslySkipPermissions'] is False


def test_counter_rejects_resume_and_model_changes():
    for method, params in [
        ('session/load', {}),
        ('session/resume', {}),
        ('session/fork', {}),
        ('session/set_model', {'modelId': 'wrong'}),
        ('session/set_config_option', {'configId': 'model', 'value': 'wrong'}),
        ('session/set_mode', {'modeId': 'bypassPermissions'}),
    ]:
        with pytest.raises(ValueError, match='counter_method_denied'):
            api().restrict_counter({'method': method, 'params': params})


def test_counter_preserves_custom_prompt_only():
    value = {
        'method': 'session/new',
        'params': {
            '_meta': {
                'systemPrompt': 'dedicated counter rules',
                'other': 'untrusted',
                'claudeCode': {'options': {'tools': ['Bash']}},
            }
        },
    }
    api().restrict_counter(value)
    assert value['params']['_meta']['systemPrompt'] == 'dedicated counter rules'
    assert 'other' not in value['params']['_meta']
