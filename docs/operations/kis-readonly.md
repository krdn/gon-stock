# KIS 모의투자 조회

현재 사용자 선택은 모의투자 API다. OS Secret Service와 `secret-tool`을 사용할 수 있는 Linux에서 실행한다.

```sh
uv sync --locked
uv run gon-stock register --environment mock
uv run gon-stock probe --environment mock
```

등록은 실제 터미널의 숨김 입력으로 App Key·App Secret·계좌 앞 8자리·상품코드 2자리를 받는다.
값은 파일·명령 인수 대신 OS 인증 저장소에 보관하며 환경별로 분리한다.
KIS 모의투자 계좌의 키를 입력한다. 실전 키로 자동 전환하지 않는다.
등록 후 저장값을 다시 읽어 비교하지만 이 결과가 KIS 인증 성공을 뜻하지는 않는다.

`probe`는 삼성전자·AAPL의 시세와 호가, 국내 잔고·NASDAQ 잔고를 한 프로세스에서 조회한다.
종목별 조회는 `kr_quote --symbol 005930`, `us_quote --symbol AAPL --exchange NAS`처럼 실행한다.
모든 호출에 `--environment mock`을 명시한다.

CLI는 원문 잔고·계좌·인증값을 출력하지 않고 조회 성공 여부·페이지 수·수신 시각만 출력한다.
수신 시각은 거래소 이벤트 시각이 아니다. 실시간성·시세 지연은 별도로 검증해야 한다.
HTTPX 로거는 WARNING 이상으로 유지한다. INFO 요청 URL에는 계좌번호가 포함될 수 있다.
Python 호출 결과의 `payload`는 비공개 금융 데이터이므로 로그·공개 CI·LLM에 전달하지 않는다.
단일 `fetch`의 `more`가 참이면 일부 페이지만 받은 것이다. 잔고 전체는 `fetch_pages`를 쓴다.
미국 잔고는 지정한 거래소 범위이며 전체 미국 계좌로 해석하지 않는다.

probe는 첫 실패에서 종료코드 1로 중단한다. 이후 항목은 실행되지 않는다.
네트워크 재시도와 주문 API는 제공하지 않는다. 토큰은 프로세스 메모리에서만 재사용한다.
CLI를 연속 실행하면 토큰을 새로 발급하므로 KIS 발급 제한에 걸릴 수 있다. 제한 오류를 반복 호출로 우회하지 않는다.
요청 사이에는 최소 1.1초를 두며 여러 프로세스 사이의 총 호출량은 제어하지 않는다.
모의 서버에서 API별 사용 가능 여부는 실호출 결과로 판단한다.

공식 근거: [KIS 예제](https://github.com/koreainvestment/open-trading-api/tree/main/examples_llm),
[환경 설정](https://github.com/koreainvestment/open-trading-api/blob/main/kis_devlp.yaml).

오류 분류는 HTTP 상태와 [KIS 오류 코드](https://apiportal.koreainvestment.com/faq-error-code)를 함께 사용한다.
