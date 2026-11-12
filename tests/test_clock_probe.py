import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from gon_stock.clock_probe import main, observe_twice
from gon_stock.kis import ConnectionFailure, Credentials, KisReadClient
from gon_stock.market_clock import select_completed_domestic_bar


def row(hour='090900', volume='10', date='20261112'):
    return {'stck_bsop_date': date, 'stck_cntg_hour': hour, 'cntg_vol': volume}


def test_completed_positive_bar_excludes_current_minute_and_zero_volume():
    at = datetime(2026, 11, 12, 0, 10, 30, tzinfo=UTC)
    selected = select_completed_domestic_bar([row('091000'), row('090900', '0'), row('090800')], at)
    assert selected == datetime(2026, 11, 12, 0, 8, tzinfo=UTC)


@pytest.mark.parametrize(
    'rows',
    [
        [],
        [row('091000')],
        [row(volume='0')],
        [row(date='20261111')],
        [row('085900')],
    ],
)
def test_no_eligible_domestic_bar_never_passes(rows):
    with pytest.raises(ValueError, match='no_completed_trade_bar'):
        select_completed_domestic_bar(rows, datetime(2026, 11, 12, 0, 10, tzinfo=UTC))


@pytest.mark.parametrize('rows', [None, [None], [row('secret')], [row(volume='NaN')]])
def test_malformed_domestic_bar_fails_closed(rows):
    with pytest.raises(ValueError, match='invalid_clock_sample'):
        select_completed_domestic_bar(rows, datetime(2026, 11, 12, 0, 10, tzinfo=UTC))


@pytest.mark.parametrize('advances', [True, False])
def test_two_observations_require_clock_progress_and_reuse_one_token(monkeypatch, advances):
    class Clock(datetime):
        value = datetime(2026, 11, 12, 0, 10, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.value.astimezone(tz)

    def sleep(seconds):
        if seconds >= 60:
            Clock.value += timedelta(seconds=seconds)

    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == '/oauth2/tokenP':
            return httpx.Response(
                200,
                json={
                    'access_token': 'secret',
                    'token_type': 'Bearer',
                    'expires_in': 86400,
                },
            )
        assert request.method == 'GET'
        assert request.url.path.endswith('/inquire-time-itemchartprice')
        hour = '091000' if advances and len(calls) == 3 else '090900'
        return httpx.Response(200, json={'rt_cd': '0', 'output1': {}, 'output2': [row(hour)]})

    monkeypatch.setattr('gon_stock.clock_probe.datetime', Clock)
    monkeypatch.setattr('gon_stock.kis.datetime', Clock)
    monkeypatch.setattr('gon_stock.clock_probe.time.sleep', sleep)
    with KisReadClient(
        Credentials('key', 'secret', '12345678', '01'),
        'mock',
        transport=httpx.MockTransport(handler),
    ) as client:
        if advances:
            samples = observe_twice(client)
            assert samples[0]['completed_bar_time'] == '2026-11-12T00:09:00+00:00'
            assert samples[1]['completed_bar_time'] == '2026-11-12T00:10:00+00:00'
            assert all(x['positive_volume'] for x in samples)
        else:
            with pytest.raises(ConnectionFailure, match='clock_not_advanced'):
                observe_twice(client)
    assert len(calls) == 3


def test_outside_observation_window_makes_no_request(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 11, 15, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr('gon_stock.clock_probe.datetime', Clock)
    calls = []
    with KisReadClient(
        Credentials('key', 'secret', '12345678', '01'),
        'mock',
        transport=httpx.MockTransport(lambda r: calls.append(r)),
    ) as client:
        with pytest.raises(ConnectionFailure, match='outside_observation_window'):
            observe_twice(client)
    assert calls == []


@pytest.mark.parametrize('change', ['tracked', 'untracked', 'lock'])
def test_main_detects_source_changes_from_subdirectory(tmp_path, monkeypatch, change):
    env = {**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}

    def git(*args):
        return subprocess.check_output(['git', *args], cwd=tmp_path, env=env, text=True).strip()

    git('init', '-q')
    source = tmp_path / 'src/gon_stock'
    source.mkdir(parents=True)
    (source / 'module.py').write_text('VALUE = 1\n')
    (tmp_path / 'uv.lock').write_text('version = 1\n')
    git('add', '.')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture')
    sha = git('rev-parse', 'HEAD')
    target = {
        'tracked': source / 'module.py',
        'untracked': source / 'extra.py',
        'lock': tmp_path / 'uv.lock',
    }[change]
    target.write_text('changed\n')
    output = tmp_path / 'result.json'
    monkeypatch.chdir(source)
    monkeypatch.setattr('sys.argv', ['clock-probe', '--expected-sha', sha, '--output', str(output)])
    original_run = subprocess.run
    secret_calls = []

    def run(args, **kwargs):
        if args[0] == 'secret-tool':
            secret_calls.append(args)
            return subprocess.CompletedProcess(args, 1, '', '')
        return original_run(args, **kwargs)

    monkeypatch.setattr(subprocess, 'run', run)
    with pytest.raises(SystemExit):
        main()
    assert json.loads(output.read_text())['code'] == 'source_changed'
    assert secret_calls == []


def test_main_sha_mismatch_remains_visible_when_output_write_fails(tmp_path, monkeypatch, capsys):
    output = tmp_path / 'result.json'
    monkeypatch.setattr(
        'sys.argv', ['clock-probe', '--expected-sha', 'wrong', '--output', str(output)]
    )
    original_open = Path.open

    def fail_output(path, *args, **kwargs):
        if path == output:
            raise PermissionError('unwritable')
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', fail_output)
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    summary = capsys.readouterr().out.splitlines()[0]
    assert json.loads(summary)['code'] == 'source_changed'


def test_main_refuses_existing_result_file(tmp_path, monkeypatch):
    output = tmp_path / 'result.json'
    output.write_text('preserve')
    monkeypatch.setattr(
        'sys.argv', ['clock-probe', '--expected-sha', 'wrong', '--output', str(output)]
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert output.read_text() == 'preserve'
