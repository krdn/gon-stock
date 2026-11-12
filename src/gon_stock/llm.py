import ipaddress
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx


class ProxyFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(f'프록시 확인 실패: {code}')


@dataclass(frozen=True)
class ProbeResult:
    requested_model: str
    returned_model: str
    elapsed_seconds: float
    total_tokens: int | None

    @property
    def model_matches(self):
        return self.requested_model == self.returned_model


@dataclass(frozen=True)
class CompletionResult(ProbeResult):
    content: str = field(repr=False)


class ProxyClient:
    def __init__(self, base_url: str, api_key: str, *, transport=None):
        if not isinstance(base_url, str):
            raise ProxyFailure('invalid_base_url')
        invalid = False
        try:
            url = urlsplit(base_url)
            invalid = (
                url.scheme not in ('http', 'https')
                or not url.hostname
                or bool(url.username or url.password or url.query or url.fragment)
                or url.path.rstrip('/') not in ('', '/v1')
            )
            if url.scheme == 'http':
                host = ipaddress.ip_address(url.hostname)
                invalid = invalid or not (host.is_private or host.is_loopback)
            _ = url.port
        except ValueError:
            invalid = True
        if invalid:
            raise ProxyFailure('invalid_base_url')
        if not isinstance(api_key, str) or not re.fullmatch(r'[\x21-\x7e]+', api_key):
            raise ProxyFailure('invalid_credentials')
        self._key = api_key
        self._models = None
        self._http = httpx.Client(
            base_url=base_url.rstrip('/') + ('' if url.path.rstrip('/') == '/v1' else '/v1'),
            headers={'authorization': f'Bearer {api_key}'},
            timeout=90,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._http.close()
        self._http.headers.clear()
        self._key = ''

    def _request(self, method, path, **kwargs):
        failure = None
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.TimeoutException:
            failure = 'timeout'
        except httpx.HTTPError:
            failure = 'network_error'
        if failure:
            raise ProxyFailure(failure)
        status = response.status_code
        if status in (401, 403):
            raise ProxyFailure('authentication_failed')
        if status == 429:
            raise ProxyFailure('rate_limited')
        if status in (502, 503, 504):
            raise ProxyFailure('provider_unavailable')
        if status != 200:
            raise ProxyFailure('http_error')
        try:
            data = response.json()
        except (ValueError, UnicodeError):
            data = None
        if not isinstance(data, dict):
            raise ProxyFailure('invalid_response')
        return data

    def _valid_model(self, model):
        return (
            isinstance(model, str)
            and model != self._key
            and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:+-]{0,199}', model) is not None
        )

    def models(self) -> list[str]:
        if self._models is None:
            data = self._request('GET', 'models').get('data')
            if not isinstance(data, list) or any(
                not isinstance(item, dict) or not self._valid_model(item.get('id')) for item in data
            ):
                raise ProxyFailure('invalid_response')
            self._models = list(dict.fromkeys(item['id'] for item in data))
        return list(self._models)

    def probe(self, model: str) -> ProbeResult:
        result = self.complete(
            model, [{'role': 'user', 'content': 'Reply with OK only.'}], max_tokens=256
        )
        return ProbeResult(
            result.requested_model,
            result.returned_model,
            result.elapsed_seconds,
            result.total_tokens,
        )

    def complete(self, model: str, messages: list[dict], *, max_tokens=2048) -> CompletionResult:
        if (
            not isinstance(messages, list)
            or not 1 <= len(messages) <= 16
            or any(
                not isinstance(message, dict)
                or set(message) != {'role', 'content'}
                or message['role'] not in ('system', 'user', 'assistant')
                or not isinstance(message['content'], str)
                or not message['content'].strip()
                for message in messages
            )
            or sum(len(message['content']) for message in messages) > 64000
            or type(max_tokens) is not int
            or not 1 <= max_tokens <= 8192
        ):
            raise ProxyFailure('invalid_messages')
        if not self._valid_model(model):
            raise ProxyFailure('invalid_model')
        if model not in self.models():
            raise ProxyFailure('model_not_listed')
        started = time.monotonic()
        data = self._request(
            'POST',
            'chat/completions',
            json={
                'model': model,
                'messages': messages,
                'stream': False,
                'max_tokens': max_tokens,
            },
        )
        elapsed = time.monotonic() - started
        returned = data.get('model')
        choices = data.get('choices')
        if not self._valid_model(returned) or not isinstance(choices, list) or not choices:
            raise ProxyFailure('invalid_response')
        choice = choices[0]
        if not isinstance(choice, dict) or not isinstance(choice.get('message'), dict):
            raise ProxyFailure('invalid_response')
        content = choice['message'].get('content')
        if (
            choice.get('finish_reason') != 'stop'
            or not isinstance(content, str)
            or not content.strip()
            or choice['message'].get('tool_calls')
        ):
            raise ProxyFailure('incomplete_response')
        usage = data.get('usage')
        tokens = usage.get('total_tokens') if isinstance(usage, dict) else None
        if tokens is not None and (type(tokens) is not int or tokens < 0):
            raise ProxyFailure('invalid_response')
        return CompletionResult(model, returned, elapsed, tokens, content)
