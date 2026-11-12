import argparse
import json
import os
import re
import sqlite3
import subprocess
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from gon_stock.data_cli import private_path
from gon_stock.decisions import DecisionStore
from gon_stock.event_store import digest, utc


def _hex(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _plain(value):
    return (
        value.replace('@', '＠')
        .replace('nostr:', 'nostr\u200b:')
        .replace('npub1', 'npub\u200b1')
        .replace('nprofile1', 'nprofile\u200b1')
    )


class BuzzCLI:
    def __init__(self, config):
        if not isinstance(config, dict) or set(config) - {'cli'} != {
            'relay',
            'sender_pubkey',
            'allowed_members',
            'channels',
        }:
            raise ValueError('invalid_buzz_config')
        if not isinstance(config['relay'], str):
            raise ValueError('invalid_relay')
        url = urlsplit(config['relay'])
        if (
            url.scheme != 'https'
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError('invalid_relay')
        if (
            not _hex(config['sender_pubkey'])
            or not isinstance(config['allowed_members'], list)
            or not all(_hex(value) for value in config['allowed_members'])
            or config['sender_pubkey'] not in config['allowed_members']
        ):
            raise ValueError('invalid_members')
        channels = config['channels']
        if not isinstance(channels, dict) or set(channels) != {'research', 'signals', 'ops'}:
            raise ValueError('invalid_channels')
        if not all(isinstance(value, str) for value in channels.values()):
            raise ValueError('invalid_channels')
        if len(set(channels.values())) != 3 or any(
            str(UUID(value)) != value for value in channels.values()
        ):
            raise ValueError('invalid_channels')
        cli = config.get('cli', 'buzz')
        if cli not in ('buzz', 'buzz-gon') or (
            cli == 'buzz-gon' and config['relay'] != 'https://buzz.krdn.kr'
        ):
            raise ValueError('invalid_cli')
        self.command = ['buzz-gon'] if cli == 'buzz-gon' else ['buzz', '--relay', config['relay']]
        if cli == 'buzz' and not os.environ.get('BUZZ_PRIVATE_KEY'):
            raise ValueError('buzz_authenticated_runtime_required')
        self.config = config

    def call(self, args, *, content=None):
        try:
            result = subprocess.run(
                [*self.command, *args],
                input=content,
                text=True,
                capture_output=True,
                timeout=45,
            )
            if result.returncode:
                raise ValueError('buzz_command_failed')
            return json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            raise ValueError('buzz_command_failed') from None

    def preflight(self):
        profiles = self.call(['users', 'get'])
        if (
            not isinstance(profiles, list)
            or len(profiles) != 1
            or not isinstance(profiles[0], dict)
            or profiles[0].get('pubkey') != self.config['sender_pubkey']
        ):
            raise ValueError('buzz_identity_mismatch')
        channels = self.call(['channels', 'list', '--visibility', 'private', '--member'])
        if not isinstance(channels, list) or any(not isinstance(row, dict) for row in channels):
            raise ValueError('invalid_channel_response')
        for role, channel in self.config['channels'].items():
            if not any(
                row.get('channel_id') == channel and row.get('name') == 'gon-stock-' + role
                for row in channels
            ):
                raise ValueError('private_channel_not_verified')
            members = self.call(['channels', 'members', '--channel', channel])
            if (
                not isinstance(members, list)
                or any(not isinstance(row, dict) or not _hex(row.get('pubkey')) for row in members)
                or {row['pubkey'] for row in members} != set(self.config['allowed_members'])
            ):
                raise ValueError('channel_members_mismatch')

    def send(self, channel, content, reply_to=None):
        args = ['messages', 'send', '--channel', channel, '--content', '-']
        if reply_to:
            args += ['--reply-to', reply_to]
        value = self.call(args, content=content)
        if (
            not isinstance(value, dict)
            or value.get('accepted') is not True
            or not _hex(value.get('event_id'))
        ):
            raise ValueError('message_not_accepted')
        return value['event_id']

    def verify(self, channel, event_id, content, reply_to=None):
        events = self.call(['messages', 'get', '--channel', channel, '--limit', '100'])
        if not isinstance(events, list) or any(not isinstance(row, dict) for row in events):
            raise ValueError('message_not_verified')
        event = next((row for row in events if row.get('id') == event_id), None)
        if (
            event is None
            or event.get('pubkey') != self.config['sender_pubkey']
            or event.get('content') != content
            or ['h', channel] not in event.get('tags', [])
        ):
            raise ValueError('message_not_verified')
        if reply_to and not any(
            len(tag) >= 4 and tag[0] == 'e' and tag[1] == reply_to and tag[3] in ('root', 'reply')
            for tag in event['tags']
        ):
            raise ValueError('thread_not_verified')


def publish(store, client, request_id, *, now=lambda: datetime.now(UTC)):
    record = store.get(request_id)
    card = record['card']
    if (
        record['status'] != 'completed'
        or not card
        or card['order_allowed'] is not False
        or card['mode'] != 'research'
        or card['p3_status'] != 'pending'
        or card['probability'] is not None
        or card['action'] != '관망'
        or not utc(card['as_of']) <= utc(now()) < utc(card['expires_at'])
    ):
        raise ValueError('card_not_publishable')
    client.preflight()
    record = store.begin_delivery(request_id)
    delivery = record['delivery']
    channels = client.config['channels']
    root = None
    summary = (
        '연구 카드 · 관망 · 주문 불가\n요청 '
        + request_id
        + '\n자료 기준 '
        + card['as_of']
        + '\n유효기한 '
        + card['expires_at']
        + '\n성과·확률·기대손익: 검증 대기\n'
        + card['summary']
        + '\n출처(사용자 제공·사실 확인 미완료):\n'
        + '\n'.join(
            source['id'] + ' ' + source['url'] + ' / 발표 ' + source['published_at']
            for source in card['sources']
        )
    )
    messages = [
        (
            'request',
            'research',
            '로컬 프록시 검토 기록 — Buzz 전용 에이전트 응답이 아닙니다.\n'
            + '요청 '
            + request_id
            + '\n'
            + record['request']['question'],
        )
    ]
    for index, row in enumerate(record['rounds']):
        messages.append(
            (
                f'round_{index}',
                'research',
                row['role']
                + ' · 요청 '
                + row['requested_model']
                + ' / 반환 '
                + row['returned_model']
                + '\n'
                + row['answer']['summary']
                + '\n위험: '
                + ' / '.join(row['answer']['risks'])
                + '\n무효화: '
                + ' / '.join(row['answer']['invalidation']),
            )
        )
    messages += [
        ('final', 'research', summary),
        ('signal', 'signals', summary),
        (
            'ops',
            'ops',
            '연구 요청 ' + request_id + ': 토론 기록·카드 전송 확인. P3 검증 대기·주문 불가.',
        ),
    ]
    try:
        for label, destination, text in messages:
            if utc(now()) >= utc(card['expires_at']):
                raise ValueError('card_expired_during_delivery')
            text = _plain(text)
            channel = channels[destination]
            reply = root if destination == 'research' else None
            event = {
                'label': label,
                'channel': channel,
                'event_id': None,
                'content_sha256': digest(text),
                'verified': False,
            }
            delivery['events'].append(event)
            store.save(record)
            event['event_id'] = client.send(channel, text, reply)
            store.save(record)
            client.verify(channel, event['event_id'], text, reply)
            event['verified'] = True
            if root is None:
                root = event['event_id']
            store.save(record)
        delivery['status'] = 'verified'
        store.save(record)
        return delivery
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error):
        delivery.update(status='failed', error_code='delivery_incomplete_do_not_retry')
        store.save(record)
        raise


def main():
    parser = argparse.ArgumentParser(
        description='명시적으로 요청한 연구 기록을 private Buzz 채널에 전달'
    )
    parser.add_argument('command', choices=['preflight', 'publish'])
    parser.add_argument('--config', default='.private/p4/buzz.json')
    parser.add_argument('--db', default='.private/p4/workbench.sqlite')
    parser.add_argument('--request-id')
    args = parser.parse_args()
    try:
        config = json.loads(private_path(args.config).read_text())
        client = BuzzCLI(config)
        if args.command == 'preflight':
            client.preflight()
            result = {'status': 'verified', 'scope': 'identity_private_channels_members'}
        else:
            if not args.request_id:
                raise ValueError('request_id_required')
            with DecisionStore(private_path(args.db)) as store:
                delivery = publish(store, client, args.request_id)
                result = {'status': delivery['status'], 'verified_events': len(delivery['events'])}
        print(json.dumps(result))
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error):
        print(json.dumps({'status': 'failed', 'code': 'buzz_operation_failed'}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
