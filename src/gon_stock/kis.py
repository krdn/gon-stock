import re
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx

from gon_stock.market_clock import MarketClock, read_market_clock


class ConnectionFailure(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(f'연결 확인 실패: {code}')


@dataclass(frozen=True)
class Credentials:
    app_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    account: str = field(repr=False)
    product: str = field(repr=False)


@dataclass(frozen=True)
class ReadResult:
    payload: dict = field(repr=False)
    received_at: datetime
    more: bool
    event_time: datetime | None = None
    clock: MarketClock | None = None


ROUTES = {
    'us_bars': (
        '/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice',
        'HHDFS76950200',
    ),
    'kr_bars': (
        '/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice',
        'FHKST03010200',
    ),
    'kr_quote': ('/uapi/domestic-stock/v1/quotations/inquire-price', 'FHKST01010100'),
    'kr_orderbook': (
        '/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn',
        'FHKST01010200',
    ),
    'us_quote': ('/uapi/overseas-price/v1/quotations/price', 'HHDFS00000300'),
    'us_orderbook': ('/uapi/overseas-price/v1/quotations/inquire-asking-price', 'HHDFS76200100'),
    'kr_holdings': ('/uapi/domestic-stock/v1/trading/inquire-balance', 'TTTC8434R'),
    'us_holdings': ('/uapi/overseas-stock/v1/trading/inquire-balance', 'TTTS3012R'),
}
HOSTS = {
    'mock': 'https://openapivts.koreainvestment.com:29443',
    'real': 'https://openapi.koreainvestment.com:9443',
}


class KisReadClient:
    def __init__(self, credentials: Credentials, environment: str, *, transport=None):
        if environment not in HOSTS:
            raise ConnectionFailure('invalid_environment')
        if any(
            not isinstance(v, str)
            or not v
            or not v.isascii()
            or any(ord(c) < 33 or ord(c) == 127 for c in v)
            for v in (credentials.app_key, credentials.secret_key)
        ):
            raise ConnectionFailure('invalid_credentials')
        if not re.fullmatch(r'[0-9]{8}', credentials.account) or not re.fullmatch(
            r'[0-9]{2}', credentials.product
        ):
            raise ConnectionFailure('invalid_account')
        self._credentials = credentials
        self._environment = environment
        self._http = httpx.Client(
            base_url=HOSTS[environment],
            transport=transport,
            timeout=15,
            follow_redirects=False,
            trust_env=False,
        )
        self._token = ''
        self._expires = 0.0
        self._next_request = 0.0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._http.close()
        self._token = ''

    def _request(self, method, path, **kwargs):
        time.sleep(max(0, self._next_request - time.monotonic()))
        self._next_request = time.monotonic() + 1.1
        error = None
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.TimeoutException:
            error = 'timeout'
        except httpx.HTTPError:
            error = 'network_error'
        if error:
            raise ConnectionFailure(error)
        try:
            data = response.json()
        except (ValueError, UnicodeError):
            data = None
        if isinstance(data, dict):
            codes = {
                'EGW00201': 'rate_limited',
                'EGW00133': 'rate_limited',
                'EGW00121': 'authentication_failed',
                'EGW00123': 'authentication_failed',
                'EGW02007': 'environment_mismatch',
            }
            for key in ('msg_cd', 'error_code'):
                value = data.get(key)
                if isinstance(value, str) and value in codes:
                    raise ConnectionFailure(codes[value])
        if response.status_code == 429:
            raise ConnectionFailure('rate_limited')
        if response.status_code in (401, 403):
            raise ConnectionFailure('authentication_failed')
        if response.status_code != 200:
            raise ConnectionFailure('http_error')
        if not isinstance(data, dict):
            raise ConnectionFailure('invalid_response')
        return data, response.headers

    def _authenticate(self):
        if self._token and time.monotonic() < self._expires:
            return
        started = time.monotonic()
        data, _ = self._request(
            'POST',
            '/oauth2/tokenP',
            json={
                'grant_type': 'client_credentials',
                'appkey': self._credentials.app_key,
                'appsecret': self._credentials.secret_key,
            },
        )
        token = data.get('access_token')
        expiry = data.get('expires_in')
        if (
            not isinstance(token, str)
            or not re.fullmatch(r'[\x21-\x7e]+', token)
            or (type(expiry) is not int or expiry <= 60)
            or str(data.get('token_type', '')).lower() != 'bearer'
        ):
            raise ConnectionFailure('invalid_response')
        self._token = token
        self._expires = started + expiry - 60

    def _params(self, operation, args):
        if operation not in ROUTES:
            raise ConnectionFailure('operation_not_allowed')
        if operation == 'us_bars' and self._environment != 'real':
            raise ConnectionFailure('unsupported_environment')
        holdings = operation.endswith('holdings')
        us = operation.startswith('us_')
        allowed = ({'exchange'} if us else set()) | (set() if holdings else {'symbol'})
        if set(args) != allowed or any(not isinstance(v, str) for v in args.values()):
            raise ConnectionFailure('invalid_request')
        if us and args['exchange'] not in (
            ('NASD', 'NYSE', 'AMEX') if holdings else ('NAS', 'NYS', 'AMS')
        ):
            raise ConnectionFailure('invalid_request')
        if not holdings:
            if not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,15}' if us else r'[0-9]{6}', args['symbol']):
                raise ConnectionFailure('invalid_request')
            if us:
                if operation == 'us_bars':
                    return {
                        'AUTH': '',
                        'EXCD': args['exchange'],
                        'SYMB': args['symbol'],
                        'NMIN': '1',
                        'PINC': '1',
                        'NEXT': '',
                        'NREC': '1',
                        'FILL': '',
                        'KEYB': '',
                    }
                return {'AUTH': '', 'EXCD': args['exchange'], 'SYMB': args['symbol']}
            if operation == 'kr_bars':
                return {
                    'FID_COND_MRKT_DIV_CODE': 'J',
                    'FID_INPUT_ISCD': args['symbol'],
                    'FID_INPUT_HOUR_1': min(
                        datetime.now(ZoneInfo('Asia/Seoul')).strftime('%H%M%S'), '153000'
                    ),
                    'FID_PW_DATA_INCU_YN': 'N',
                    'FID_ETC_CLS_CODE': '',
                }
            return {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': args['symbol']}
        params = {'CANO': self._credentials.account, 'ACNT_PRDT_CD': self._credentials.product}
        if us:
            params.update(
                OVRS_EXCG_CD=args['exchange'],
                TR_CRCY_CD='USD',
                CTX_AREA_FK200='',
                CTX_AREA_NK200='',
            )
        else:
            params.update(
                AFHR_FLPR_YN='N',
                OFL_YN='',
                INQR_DVSN='02',
                UNPR_DVSN='01',
                FUND_STTL_ICLD_YN='N',
                FNCG_AMT_AUTO_RDPT_YN='N',
                PRCS_DVSN='00',
                CTX_AREA_FK100='',
                CTX_AREA_NK100='',
            )
        return params

    def _fetch(self, operation, params, continuation=''):
        path, tr_id = ROUTES[operation]
        if operation.endswith('holdings') and self._environment == 'mock':
            tr_id = 'V' + tr_id[1:]
        self._authenticate()
        data, headers = self._request(
            'GET',
            path,
            params=params,
            headers={
                'authorization': f'Bearer {self._token}',
                'appkey': self._credentials.app_key,
                'appsecret': self._credentials.secret_key,
                'tr_id': tr_id,
                'tr_cont': continuation,
                'custtype': 'P',
                'content-type': 'application/json; charset=utf-8',
            },
        )
        if not isinstance(data.get('rt_cd'), str):
            raise ConnectionFailure('invalid_response')
        if data['rt_cd'] != '0':
            raise ConnectionFailure('broker_rejected')
        if operation.endswith('quote'):
            valid = isinstance(data.get('output'), dict) and bool(data['output'])
        elif operation in ('kr_bars', 'us_bars'):
            valid = isinstance(data.get('output1'), dict) and isinstance(data.get('output2'), list)
        elif operation.endswith('holdings'):
            valid = isinstance(data.get('output1'), list) and isinstance(
                data.get('output2'), (list, dict)
            )
        else:
            valid = (
                isinstance(data.get('output1'), dict)
                and bool(data['output1'])
                and (isinstance(data.get('output2'), (dict, list)))
            )
        if not valid or headers.get('tr_cont', '') not in ('', 'D', 'E', 'F', 'M'):
            raise ConnectionFailure('invalid_response')
        more = headers.get('tr_cont') in ('F', 'M')
        received_at = datetime.now(UTC)
        clock = read_market_clock(operation, data)
        if clock.event_time and clock.event_time > received_at:
            clock = replace(clock, status='future')
        return ReadResult(data, received_at, more, event_time=clock.event_time, clock=clock)

    def fetch(self, operation: str, **params) -> ReadResult:
        return self._fetch(operation, self._params(operation, params))

    def fetch_pages(self, operation: str, **args) -> list[ReadResult]:
        params = self._params(operation, args)
        if not operation.endswith('holdings'):
            raise ConnectionFailure('operation_not_allowed')
        suffix = '200' if operation.startswith('us_') else '100'
        fk, nk = f'CTX_AREA_FK{suffix}', f'CTX_AREA_NK{suffix}'
        pages, seen = [], set()
        for _ in range(100):
            page = self._fetch(operation, params, 'N' if pages else '')
            pages.append(page)
            if not page.more:
                return pages
            keys = tuple(page.payload.get(k.lower()) for k in (fk, nk))
            if any(not isinstance(k, str) for k in keys) or not keys[1].strip():
                raise ConnectionFailure('invalid_response')
            if keys in seen:
                raise ConnectionFailure('pagination_cycle')
            seen.add(keys)
            params.update(zip((fk, nk), keys, strict=True))
        raise ConnectionFailure('pagination_limit')
