import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from gon_stock.buzz import _hex, _plain
from gon_stock.data_cli import private_path


def reply_anchor(prompt, channel):
    block = re.search(r'<context>\s*(.*?)</context>', prompt, re.S)
    if not block or not re.search(
        r'^Channel: (?:[^\n]*\(#)?' + re.escape(channel) + r'\)?$', block[1], re.M
    ):
        raise ValueError('invalid_reply_context')
    roots = re.findall(r'use `--reply-to ([0-9a-f]{64})`', block[1])
    if len(roots) != 1:
        raise ValueError('invalid_reply_context')
    return roots[0]


class Replies:
    def __init__(self, channel, owner, agent, path):
        self.channel, self.owner, self.agent = channel, owner, agent
        self.db = sqlite3.connect(path)
        Path(path).chmod(0o600)
        self.db.execute(
            'CREATE TABLE IF NOT EXISTS deliveries (root TEXT PRIMARY KEY, status TEXT)'
        )

    def call(self, args, content=None):
        result = subprocess.run(
            ['buzz', '--relay', 'https://buzz.krdn.kr', *args],
            input=content,
            capture_output=True,
            text=True,
            timeout=45,
        )
        if result.returncode:
            raise ValueError('buzz_command_failed')
        return json.loads(result.stdout)

    def event(self, event_id):
        rows = self.call(['social', 'event', '--event', event_id])
        if not isinstance(rows, list) or len(rows) != 1 or rows[0].get('id') != event_id:
            raise ValueError('event_not_verified')
        return rows[0]

    def publish(self, root, text):
        if not _hex(root) or not isinstance(text, str) or not 1 <= len(text.strip()) <= 16000:
            raise ValueError('invalid_reply')
        if self.db.execute('SELECT 1 FROM deliveries WHERE root = ?', [root]).fetchone():
            raise ValueError('already_attempted')
        request = self.event(root)
        if (
            request.get('pubkey') != self.owner
            or ['h', self.channel] not in request.get('tags', [])
            or not isinstance(request.get('created_at'), int)
            or not 0 <= time.time() - request['created_at'] < 900
        ):
            raise ValueError('invalid_owner_request')
        with self.db:
            self.db.execute('INSERT INTO deliveries VALUES (?, ?)', [root, 'attempted'])
        text = '연구 전용 · 관망 · 주문 불가 · 성과 검증 대기\n' + _plain(text)
        try:
            sent = self.call(
                [
                    'messages',
                    'send',
                    '--channel',
                    self.channel,
                    '--reply-to',
                    root,
                    '--content',
                    '-',
                ],
                text,
            )
            if sent.get('accepted') is not True or not _hex(sent.get('event_id')):
                raise ValueError('reply_not_accepted')
            event = self.event(sent['event_id'])
            if (
                event.get('pubkey') != self.agent
                or event.get('content') != text
                or ['h', self.channel] not in event.get('tags', [])
                or not any(
                    len(t) >= 4 and t[:2] == ['e', root] and t[3] in ('root', 'reply')
                    for t in event.get('tags', [])
                )
            ):
                raise ValueError('reply_not_verified')
            with self.db:
                self.db.execute(
                    'UPDATE deliveries SET status = ? WHERE root = ?', ['verified', root]
                )
        except (ValueError, TypeError, KeyError, OSError, subprocess.TimeoutExpired):
            with self.db:
                self.db.execute('UPDATE deliveries SET status = ? WHERE root = ?', ['failed', root])
            raise


def restrict_counter(value):
    method = value.get('method')
    params = value.get('params', {})
    if method == 'session/new':
        custom_prompt = params.get('_meta', {}).get('systemPrompt')
        params['mcpServers'] = []
        params['_meta'] = {
            'claudeCode': {
                'options': {
                    'tools': [],
                    'model': 'claude-fable-5-2',
                    'effort': 'high',
                    'settingSources': [],
                    'strictMcpConfig': True,
                    'allowDangerouslySkipPermissions': False,
                }
            }
        }
        if isinstance(custom_prompt, str):
            params['_meta']['systemPrompt'] = custom_prompt
    elif method == 'session/set_model' and params.get('modelId') == 'claude-fable-5-2':
        return
    elif method == 'session/set_mode' and params.get('modeId') == 'plan':
        return
    elif method == 'session/set_config_option' and (
        params.get('configId'),
        params.get('value'),
    ) in (('effort', 'high'), ('model', 'claude-fable-5-2')):
        return
    elif method not in (None, 'initialize', 'session/prompt', 'session/cancel'):
        raise ValueError('counter_method_denied')


def main():
    role = sys.argv[1]
    if role not in ('strategy', 'counter'):
        raise SystemExit('invalid_role')
    record = json.loads(
        (Path.home() / '.local/share/buzz-gon/agents' / f'gon-stock-{role}.json').read_text()
    )
    replies = Replies(
        record['channel'],
        record['owner'],
        record['pubkey'],
        private_path('.private/replies.sqlite'),
    )
    command = ['codex-acp'] if role == 'strategy' else ['claude-agent-acp']
    env = {k: v for k, v in os.environ.items() if not k.startswith('BUZZ_')}
    if role == 'counter':
        env = {k: v for k, v in env.items() if not k.startswith(('ANTHROPIC_', 'CLAUDE_CODE_USE_'))}
    child = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env
    )
    write_lock, state_lock, output_lock = threading.Lock(), threading.Lock(), threading.Lock()
    pending, chunks = {}, {}

    def output(value):
        with output_lock:
            print(json.dumps(value), flush=True)

    def forward(value):
        with write_lock:
            child.stdin.write(json.dumps(value) + '\n')
            child.stdin.flush()

    def inbound():
        try:
            for line in sys.stdin:
                value = json.loads(line)
                if role == 'counter':
                    try:
                        restrict_counter(value)
                    except ValueError:
                        if 'id' in value:
                            output(
                                {
                                    'jsonrpc': '2.0',
                                    'id': value['id'],
                                    'error': {'code': -32601, 'message': 'counter_method_denied'},
                                }
                            )
                        continue
                if value.get('method') == 'session/prompt':
                    params = value['params']
                    prompt = '\n'.join(
                        p.get('text', '') for p in params['prompt'] if p.get('type') == 'text'
                    )
                    try:
                        root = reply_anchor(prompt, record['channel'])
                    except ValueError:
                        output(
                            {
                                'jsonrpc': '2.0',
                                'id': value['id'],
                                'error': {'code': -32602, 'message': 'invalid_reply_context'},
                            }
                        )
                        continue
                    with state_lock:
                        pending[value['id']] = (params['sessionId'], root)
                        chunks[params['sessionId']] = ''
                forward(value)
        finally:
            child.stdin.close()

    threading.Thread(target=inbound, daemon=True).start()
    try:
        for line in child.stdout:
            value = json.loads(line)
            if 'method' in value and 'id' in value:
                if value['method'] == 'session/request_permission':
                    forward(
                        {
                            'jsonrpc': '2.0',
                            'id': value['id'],
                            'result': {'outcome': {'outcome': 'cancelled'}},
                        }
                    )
                else:
                    forward(
                        {
                            'jsonrpc': '2.0',
                            'id': value['id'],
                            'error': {'code': -32601, 'message': 'tools_disabled'},
                        }
                    )
                continue
            params = value.get('params', {})
            update = params.get('update', {})
            with state_lock:
                session = params.get('sessionId')
                if update.get('sessionUpdate') == 'agent_message_chunk' and session in chunks:
                    chunks[session] += update.get('content', {}).get('text', '')
                    if len(chunks[session]) > 16000:
                        raise ValueError('reply_too_large')
                request = pending.pop(value.get('id'), None) if 'method' not in value else None
                text = chunks.pop(request[0], '') if request else ''
            if request and value.get('result', {}).get('stopReason') == 'end_turn':
                try:
                    replies.publish(request[1], text)
                except (
                    ValueError,
                    TypeError,
                    KeyError,
                    OSError,
                    sqlite3.Error,
                    subprocess.TimeoutExpired,
                ):
                    value = {
                        'jsonrpc': '2.0',
                        'id': value['id'],
                        'error': {'code': -32603, 'message': 'reply_delivery_failed_do_not_retry'},
                    }
            output(value)
    finally:
        child.terminate()
        child.wait(timeout=10)
        replies.db.close()


if __name__ == '__main__':
    main()
