import importlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from gon_stock.llm import ProxyClient, ProxyFailure

NOW = datetime(2026, 11, 12, 2, 30, tzinfo=UTC)


def api():
    try:
        return importlib.import_module('gon_stock.decisions')
    except ModuleNotFoundError:
        pytest.fail('P4 decision flow is not implemented')


def packet():
    return {
        'request_id': 'fixture_1',
        'instrument': {'exchange': 'XNAS', 'symbol': 'TEST', 'currency': 'USD'},
        'as_of': NOW.isoformat(),
        'expires_at': (NOW + timedelta(minutes=10)).isoformat(),
        'question': '합성 연결 검사: 이 자료만으로 거래를 승인할 수 있는가?',
        'sources': [
            {
                'id': 's1',
                'url': 'https://example.org/fixture',
                'published_at': (NOW - timedelta(minutes=2)).isoformat(),
                'observed_at': (NOW - timedelta(minutes=1)).isoformat(),
                'excerpt': '합성 예제. 실적·시세·성과 자료가 없다.',
            }
        ],
    }


def answer(disposition='support'):
    return {
        'summary': '자료 부족으로 성과는 검증 대기다.',
        'disposition': disposition,
        'source_ids': ['s1'],
        'risks': ['표본 부족'],
        'invalidation': ['원문 정정'],
    }


def client(replies, calls):
    def handler(request):
        if request.url.path == '/v1/models':
            return httpx.Response(
                200, json={'data': [{'id': 'gpt-6-astra'}, {'id': 'claude-fable-5-2'}]}
            )
        body = json.loads(request.content)
        calls.append(body)
        assert 'tools' not in body and 'functions' not in body
        result = replies.pop(0)
        return httpx.Response(
            200,
            json={
                'model': result.get('model', body['model']),
                'choices': [
                    {
                        'finish_reason': 'stop',
                        'message': {
                            'content': json.dumps(
                                result.get('answer', answer()), ensure_ascii=False
                            )
                        },
                    }
                ],
                'usage': {'total_tokens': 100},
            },
        )

    return ProxyClient(
        'https://proxy.example', 'fixture-key', transport=httpx.MockTransport(handler)
    )


def test_proposal_counterargument_never_authorizes_trading(tmp_path):
    calls = []
    with (
        api().DecisionStore(tmp_path / 'workbench.sqlite') as store,
        client([{}, {}], calls) as llm,
    ):
        card = api().discuss(store, llm, packet(), now=lambda: NOW)
        assert card['action'] == '관망' and card['order_allowed'] is False
        assert card['mode'] == 'research' and card['p3_status'] == 'pending'
        assert card['probability'] is None and card['expected_return'] is None
        assert card['entry_range'] is None and card['stop'] is None and card['target'] is None
        assert [r['role'] for r in card['rounds']] == ['proposal', 'counterargument']
        assert card['discussion_status'] == 'reviewed'
        assert [r['requested_model'] for r in card['rounds']] == ['gpt-6-astra', 'claude-fable-5-2']
        assert all(r['requested_model'] == r['returned_model'] for r in card['rounds'])
        with pytest.raises(ValueError, match='request_exists'):
            api().discuss(store, llm, packet(), now=lambda: NOW)
    assert len(calls) == 2
    with api().DecisionStore(tmp_path / 'workbench.sqlite') as store:
        assert store.runs()[0]['card'] == card


def test_counterargument_has_two_revision_limit(tmp_path):
    calls = []
    replies = [{'answer': answer('challenge')} for _ in range(6)]
    with api().DecisionStore(tmp_path / 'workbench.sqlite') as store, client(replies, calls) as llm:
        card = api().discuss(store, llm, packet(), now=lambda: NOW)
    assert len(calls) == 6
    assert card['discussion_status'] == 'disputed' and card['action'] == '관망'


@pytest.mark.parametrize('mutation', ['future', 'expired', 'source_after_cutoff', 'unknown_field'])
def test_untrusted_packet_is_refused_before_model_call(tmp_path, mutation):
    value = packet()
    if mutation == 'future':
        value['as_of'] = (NOW + timedelta(minutes=1)).isoformat()
    elif mutation == 'expired':
        value['expires_at'] = NOW.isoformat()
    elif mutation == 'source_after_cutoff':
        value['sources'][0]['observed_at'] = (NOW + timedelta(seconds=1)).isoformat()
    else:
        value['account'] = 'not-allowed'
    with api().DecisionStore(tmp_path / 'workbench.sqlite') as store, client([], []) as llm:
        with pytest.raises(ValueError):
            api().discuss(store, llm, value, now=lambda: NOW)
        assert store.runs() == []


@pytest.mark.parametrize(
    'reply',
    [
        {'model': 'different'},
        {'answer': {**answer(), 'probability': 0.99}},
        {'answer': {**answer(), 'source_ids': ['invented']}},
    ],
)
def test_failed_model_or_fabricated_source_is_recorded_without_card(tmp_path, reply):
    with api().DecisionStore(tmp_path / 'workbench.sqlite') as store, client([reply], []) as llm:
        with pytest.raises((ValueError, ProxyFailure)):
            api().discuss(store, llm, packet(), now=lambda: NOW)
        run = store.runs()[0]
        assert run['status'] == 'failed' and run['card'] is None


def test_watchlist_persists_and_paused_research_sends_no_request(tmp_path):
    path = tmp_path / 'workbench.sqlite'
    with api().DecisionStore(path) as store:
        store.watch(packet()['instrument'])
        store.pause(True)
    with api().DecisionStore(path) as store, client([], []) as llm:
        assert store.watchlist() == [packet()['instrument']]
        with pytest.raises(ValueError, match='research_paused'):
            api().discuss(store, llm, packet(), now=lambda: NOW)
        store.unwatch(packet()['instrument'])
        assert store.watchlist() == []


def test_pause_during_first_model_response_prevents_counterargument(tmp_path):
    path = tmp_path / 'workbench.sqlite'
    calls = []

    def handler(request):
        if request.url.path == '/v1/models':
            return httpx.Response(200, json={'data': [{'id': 'gpt-6-astra'}]})
        calls.append(request)
        with api().DecisionStore(path) as controller:
            controller.pause(True)
        return httpx.Response(
            200,
            json={
                'model': 'gpt-6-astra',
                'choices': [
                    {'finish_reason': 'stop', 'message': {'content': json.dumps(answer())}}
                ],
            },
        )

    with (
        api().DecisionStore(path) as store,
        ProxyClient(
            'https://proxy.example', 'fixture-key', transport=httpx.MockTransport(handler)
        ) as llm,
    ):
        with pytest.raises(ValueError, match='research_paused'):
            api().discuss(store, llm, packet(), now=lambda: NOW)
        assert store.runs()[0]['status'] == 'failed'
    assert len(calls) == 1
