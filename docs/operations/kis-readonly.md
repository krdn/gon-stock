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

CLI는 원문 잔고·계좌·인증값을 출력하지 않고 조회 성공 여부·페이지 수·수신 시각·검증한 원본 시각·신선도 상태를 출력한다.
수신 시각은 거래소 이벤트 시각이 아니다. `clock`은 검증된 형식의 원본 날짜·시각과 그 한계를 표시한다.
국내 호가는 날짜가 없어 `time_only`, 미국 호가는 시간대가 미확정이라 `timezone_unverified`다.
시각이 없는 응답은 `missing`, 잘못된 형식은 `invalid`다. `freshness=unverified`를 최신 시세로 취급하지 않는다.
실시간성·시세 지연은 별도로 검증해야 한다.
HTTPX 로거는 WARNING 이상으로 유지한다. INFO 요청 URL에는 계좌번호가 포함될 수 있다.
Python 호출 결과의 `payload`는 비공개 금융 데이터이므로 로그·공개 CI·LLM에 전달하지 않는다.
단일 `fetch`의 `more`가 참이면 일부 페이지만 받은 것이다. 잔고 전체는 `fetch_pages`를 쓴다.
미국 잔고는 지정한 거래소 범위이며 전체 미국 계좌로 해석하지 않는다.

probe는 첫 실패에서 종료코드 1로 중단한다. 이후 항목은 실행되지 않는다.
네트워크 재시도와 주문 API는 제공하지 않는다. 토큰은 프로세스 메모리에서만 재사용한다.
CLI를 연속 실행하면 토큰을 새로 발급하므로 KIS 발급 제한에 걸릴 수 있다. 제한 오류를 반복 호출로 우회하지 않는다.
요청 사이에는 최소 1.1초를 두며 여러 프로세스 사이의 총 호출량은 제어하지 않는다.
미국 호가는 모의 서버에서 성공 응답을 관찰했지만 공식 명세는 모의투자 미지원으로 표시한다.
이 경로의 응답을 공식 지원이나 실전 체결 품질의 증거로 사용하지 않는다.

공식 근거: [KIS 예제](https://github.com/koreainvestment/open-trading-api/tree/main/examples_llm),
[환경 설정](https://github.com/koreainvestment/open-trading-api/blob/main/kis_devlp.yaml).

오류 분류는 HTTP 상태와 [KIS 오류 코드](https://apiportal.koreainvestment.com/faq-error-code)를 함께 사용한다.

## 날짜가 있는 국내 분봉 확인

```sh
uv run gon-stock kr_bars --environment mock --symbol 005930
```

공식 모의 지원 `FHKST03010200`을 사용한다. 조회 상한은 현재 한국 시각과 `15:30:00` 중 이른 값이며, 과거 데이터 포함은 `N`이다.
반환된 분봉들의 날짜·시간을 모두 검사하고 가장 늦은 값을 `clock.status=dated_bar`로 출력한다.
빈 목록은 `missing`, 잘못된 값은 `invalid`다. 조회 성공과 시각 유효성은 별개다.
이 값은 분봉 응답의 날짜·시각 필드이며 호가 시각이 아니다.
공식 명세는 미래 시각 조회 시 현재가로 구간을 채운다고 설명한다. 요청 상한과 같은 시각은 체결 발생을 증명하지 않는다.
현재 시각 이후 구간을 요청하지 않는 형식 진단용이며 장중 실관측은 미검증이다. 실시간 수집·전체 일중 이력 조회 기능이 아니다.
`event_time=null`, `freshness=unverified`를 유지하며, 수신일자를 호가에 붙이지 않는다.

## 미국 분봉 시각 확인

사용자가 승인한 실전 시세 GET 범위에서만 실행한다. 모의 환경은 네트워크 요청 전에 거부한다.

```sh
uv run gon-stock us_bars --environment real --symbol AAPL --exchange NAS
```

최근 1분봉 1건을 요청한다. 공식 `kymd/khms`는 한국기준 일자·시간이다.
`xymd/xhms`가 뉴욕 시각으로 같은 순간을 나타내는지도 검사한다.
일치하면 `timestamped_bar`와 UTC `event_time`을 출력한다. 이는 분봉 기준 시각이며 최종 체결 시각이 아니다.
불일치는 `inconsistent`, 미래 시각은 `future`이며 `event_time=null`이다.
빈 목록·잘못된 값은 각각 `missing`·`invalid`다. 모든 경우 신선도는 `unverified`다.
이 시각을 현재가나 호가 응답에 결합하지 않는다. 주문·잔고는 조회하지 않는다.
