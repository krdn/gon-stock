import importlib
import json
import subprocess
from datetime import timedelta

import pytest
from test_decisions import NOW, client, packet

from gon_stock.decisions import DecisionStore, discuss

SENDER = 'a' * 64
CHANNELS = {
    'research': '10000000-0000-0000-0000-000000000001',
    'signals': '10000000-0000-0000-0000-000000000002',
    'ops': '10000000-0000-0000-0000-000000000003',
}


def api():
    try:
        return importlib.import_module('gon_stock.buzz')
    except ModuleNotFoundError:
        pytest.fail('P4 Buzz adapter is not implemented')


def config():
    return {
        'relay': 'https://relay.example',
        'sender_pubkey': SENDER,
        'allowed_members': [SENDER],
        'channels': CHANNELS,
    }


def process(monkeypatch, *, public=False, unconfirmed=False):
    events, writes = [], []
    monkeypatch.setenv('BUZZ_PRIVATE_KEY', 'synthetic-only-signing-key')

    def run(args, *, input=None, **kwargs):
        assert 'synthetic-only-signing-key' not in str(args)
        if 'users' in args:
            value = [{'pubkey': SENDER}]
        elif 'channels' in args and 'list' in args:
            assert '--visibility' in args and 'private' in args and '--member' in args
            value = (
                []
                if public
                else [
                    {'channel_id': channel, 'name': 'gon-stock-' + role}
                    for role, channel in CHANNELS.items()
                ]
            )
        elif 'members' in args:
            value = [{'pubkey': SENDER, 'role': 'admin'}]
        elif 'send' in args:
            assert args[args.index('--content') + 1] == '-'
            channel = args[args.index('--channel') + 1]
            tags = [['h', channel]]
            if '--reply-to' in args:
                tags.append(['e', args[args.index('--reply-to') + 1], '', 'root'])
            event = {
                'id': f'{len(events) + 1:064x}',
                'content': input,
                'pubkey': SENDER,
                'tags': tags,
            }
            events.append(event)
            writes.append(input)
            value = {'accepted': True, 'event_id': event['id']}
        elif 'get' in args:
            value = [] if unconfirmed else list(events)
        else:
            pytest.fail('unknown CLI path')
        return subprocess.CompletedProcess(args, 0, json.dumps(value), '')

    monkeypatch.setattr(subprocess, 'run', run)
    return writes


def completed(store):
    with client([{}, {}], []) as llm:
        value = packet()
        value['question'] = '합성 @everyone nostr:npub1test 연결 검사'
        return discuss(store, llm, value, now=lambda: NOW)


def test_private_transcript_delivery_requires_remote_readback_and_no_repeat(tmp_path, monkeypatch):
    writes = process(monkeypatch)
    with DecisionStore(tmp_path / 'state.sqlite') as store:
        completed(store)
        result = api().publish(store, api().BuzzCLI(config()), 'fixture_1', now=lambda: NOW)
        assert result['status'] == 'verified' and len(result['events']) == 6
        assert all('@everyone' not in body and 'nostr:npub1' not in body for body in writes)
        assert any('로컬 프록시 검토 기록' in body for body in writes)
        with pytest.raises(ValueError):
            api().publish(store, api().BuzzCLI(config()), 'fixture_1', now=lambda: NOW)
    assert len(writes) == 6


def test_public_or_nonmember_channel_never_receives_content(tmp_path, monkeypatch):
    writes = process(monkeypatch, public=True)
    with DecisionStore(tmp_path / 'state.sqlite') as store:
        completed(store)
        with pytest.raises(ValueError):
            api().publish(store, api().BuzzCLI(config()), 'fixture_1', now=lambda: NOW)
    assert writes == []


def test_accepted_without_readback_is_uncertain_and_not_retried(tmp_path, monkeypatch):
    writes = process(monkeypatch, unconfirmed=True)
    with DecisionStore(tmp_path / 'state.sqlite') as store:
        completed(store)
        with pytest.raises(ValueError):
            api().publish(store, api().BuzzCLI(config()), 'fixture_1', now=lambda: NOW)
        delivery = store.get('fixture_1')['delivery']
        assert delivery['status'] == 'failed' and len(delivery['events']) == 1
        assert delivery['events'][0]['verified'] is False
        with pytest.raises(ValueError):
            api().publish(store, api().BuzzCLI(config()), 'fixture_1', now=lambda: NOW)
    assert len(writes) == 1


def test_expired_card_sends_no_message(tmp_path, monkeypatch):
    writes = process(monkeypatch)
    with DecisionStore(tmp_path / 'state.sqlite') as store:
        completed(store)
        with pytest.raises(ValueError, match='card_not_publishable'):
            api().publish(
                store, api().BuzzCLI(config()), 'fixture_1', now=lambda: NOW + timedelta(minutes=11)
            )
    assert writes == []
