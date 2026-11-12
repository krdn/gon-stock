# 연구 데이터 저장·재생

P2는 수신 시점에 알 수 있었던 자료를 수신 순번대로 다시 읽는다. 주문·계좌·전략 성과를 구현하지 않는다.
연구 기록은 DuckDB, 이동 가능한 검증본은 Parquet으로 보관한다. PostgreSQL 주문·잔고 기록은 후속 단계다.
관심 목록은 보유 목록과 별개다. 등록·삭제는 실제 주문이나 보유 변경을 일으키지 않는다.
목록 변경 이력·Parquet 포함은 미구현이다. P3에서 오늘의 관심 목록을 과거 종목군으로 사용하지 않는다.

## 실행

`uv sync --locked` 후 저장소 루트에서 실행한다. CLI의 DB·입출력 경로는 `.private/` 아래로 제한한다.
`.private/` 디렉터리는 소유자 전용으로 제한한다. 파일과 실제 데이터는 Git·공개 CI·외부 모델로 보내지 않는다.

```sh
uv run --frozen gon-stock-data --db .private/research.duckdb watch \
  --exchange NAS --symbol AAPL --currency USD
uv run --frozen gon-stock-data --db .private/research.duckdb watchlist
uv run --frozen gon-stock-data --db .private/research.duckdb capture \
  --exchange KRX --symbol 005930 --currency KRW --environment mock
uv run --frozen gon-stock-data --db .private/research.duckdb replay \
  --at 2026-11-12T00:56:00Z --output .private/replay-20261112.json
uv run --frozen gon-stock-data --db .private/research.duckdb export \
  --output .private/snapshot-20261112
```

위 종목은 조회·등록 사용 예시이며 매매 추천이나 자동 관심 목록이 아니다.
미국 분봉 수집에는 승인된 실전 시세 GET만 사용한다. `--exchange NAS --currency USD --environment real`을 지정한다.
모의·실전 자료는 별도 DB에 저장한다. 서로 다른 제공자·환경이 섞이면 전략용 조회·품질 보고가 실패한다.
`capture`는 1회 요청만 수행하며 저장 건수와 시각만 출력한다. 빈 응답은 실패다. 잔고·주문 API를 호출하지 않는다.
현재가·호가 원문 보관과 연속 수집 서비스는 이 CLI의 범위가 아니다.

`import --input .private/events.jsonl`은 정규화 이벤트를 한 줄씩 저장한다.
오류가 발생하면 이전에 저장된 행 수를 `imported_before_failure`로 보고한다. 동일 ID·동일 본문 재입력은 멱등적이다.
전체 파일의 원자적 반영은 지원하지 않는다. 재시도 때 ID를 바꾸지 않는다.
`imported`는 정상 처리한 입력 행 수로 멱등 재입력을 포함한다. import의 출처·시각은 입력 파일의 주장이지 진위 인증이 아니다.
실제 자료를 재생할 때는 `--output .private/<새 파일>.json`을 사용한다. 파일에만 자료를 쓰고 stdout에는 건수·SHA256만 표시한다.
이 옵션 없이 실자료를 에이전트에서 실행하면 시세가 대화에 노출될 수 있으므로 사용하지 않는다.
`unwatch`는 `watch`와 같은 종목 인자를 받는다.

## 이벤트와 시점 계약

스키마 정본은 `event_store.validate_event`, KIS 분봉 변환은 `market_ingest.normalize_bars`다.
거래소 alias를 XKRX/XNAS/XNYS/XASE로 정규화하고 종목·통화를 함께 식별한다.
숫자는 유한한 십진 문자열로 보관한다. 알 수 없는 필드·계좌·인증 필드는 정규화 입력에서 거부한다.

| 필드 | 의미 |
| --- | --- |
| id, schema_version, receipt_seq | 관측 ID, 형식 버전, 저장 순번. ID 충돌은 덮어쓰지 않고 실패 |
| instrument, kind | 거래소·종목·통화, bar/quote/split |
| source, endpoint, tr_id, environment | 제공자·API 종류·TR·모의/실전/합성 |
| received_at, event_time | UTC 수신시각, 확정 또는 미확정 이벤트 시각 |
| clock_status, source_clock | 시간 판정과 원 응답에서 판독한 날짜·시각·시간대. 미확정은 전략 제외 |
| raw_sha256, data | 파싱한 원 응답 행의 정규화 JSON hash와 허용한 시세 필드. 원 응답 전체는 저장하지 않음 |
| correction_of, effective_at | 이전 관측 참조, 기업행동 효력 발생시각. split의 event_time은 발표시각 |

원문 hash는 출처 식별 흔적이다. 삭제한 원문 전체를 복구하거나 보유 원문과 대조할 수 있다는 뜻은 아니다.
내부 body hash는 손상을 검사하며 전자서명이나 악의적 재작성 방지 수단은 아니다.

예: 10:00 분봉을 10:01:02에 받았고 정정본을 10:05에 받았다면, 10:03 재생에는 원본만 나온다.
감사 재생은 `received_at <= T`인 모든 관측을 보존하고 수신 순번으로 정렬한다. 늦게 온 과거 자료를 소급하지 않는다.
같은 본문을 다른 ID로 관측하면 삭제하지 않는다. 품질 보고에서 중복 후보로 구분한다.
전략용 최신본은 수신시각·동시각 저장순번으로 선택한다. 감사 재생의 저장순번은 바꾸지 않는다.
늦은 도착은 앞선 수신 배치의 최대 이벤트 시각보다 과거인 최초 관측이다. 같은 응답의 내림차순·겹친 재관측을 역순으로 세지 않는다.

`replay --max-age-seconds 120`은 추가 필터를 적용한다. 이 숫자는 사용 예시이며 승인된 매매 지연 한도가 아니다.
시각이 확정되고 미래가 아니며, 미완료 분봉이 아니고, 지정 최대 나이 안에 있는 최신 논리 관측만 남긴다.
split은 수신 후이면서 효력 발생 이후에만 포함한다. 주가를 자동으로 과거 수정하지 않는다.
이 필터는 데이터 시각 검사다. 거래 시간·관심 종목·위험·호가·성과 검사와 주문 허용을 대신하지 않는다.
호가 일자·시간대가 확정되지 않으면 null/unverified를 유지하며 다른 응답의 날짜를 붙이지 않는다.

## 품질과 달력

```sh
uv run --frozen gon-stock-data --db .private/research.duckdb quality \
  --exchange KRX --symbol 005930 --currency KRW \
  --start 2026-11-12T00:25:00Z --end 2026-11-12T00:55:00Z \
  --at 2026-11-12T00:56:00Z --output .private/quality-20261112.json
```

달력 라이브러리 버전·거래 구간·범위·hash를 보고서와 함께 저장한다.
KRX에는 XKRX, 미국 세 거래소에는 XNYS 정규장 일정을 사용한다. 개별 종목 거래정지·장외 거래는 포함하지 않는다.
`exchange-calendars==4.13.2`가 만든 일정이며 대상 연도 전체의 거래소 공지 대조를 완료한 달력은 아니다.
과거 시점에 공지된 달력만으로 구성됐다는 증명도 없으므로 달력은 감사 품질 검사에만 사용한다.

분봉 시각이 시작/종료 중 무엇인지 확인한 자료만 `--bar-label start` 또는 `end`로 지정한다.
기본값은 `bar_label_unverified`이고 누락을 판정하지 않는다.
지정했어도 거래가 없는 분과 공급자가 생략한 분을 구분할 근거가 부족하므로 `gap_candidates`만 반환한다.
휴장·조기 폐장 밖 구간을 누락 후보에 넣지 않는다. `--start/--end`는 실제 확보 범위 안으로 지정해야 한다.

## 복구와 한계

한 프로세스·한 writer로 사용한다. 동시 서버나 분산 저장소로 사용하지 않는다.
로컬 시계 동기화가 전제다. 2026-11-12 개발 호스트에서 `timedatectl show -p NTPSynchronized --value`의 `yes`를 확인했다.
이 확인은 KIS 서버와의 실제 시계 오차 측정이 아니다. 운용 서버는 P5에서 다시 확인한다.
저장 오류는 DuckDB transaction을 rollback한다. 실행 재개 뒤 DB 재생을 확인한다.
export 대상은 새 디렉터리여야 한다. manifest가 없거나 Parquet hash가 다르면 검증본을 읽지 않는다.
`event_store.read_snapshot(path, cutoff)`으로 DB와 같은 수신 순서·시점 필터를 적용한다.
실패한 export 디렉터리는 완료 증거로 쓰지 않고 새 경로로 다시 내보낸다.
DB 전체 복원·장기 백업 정책·다중 프로세스 내구성은 아직 운용 검증하지 않았다.

개인용 사용 범위는 KIS 포털의 [이용약관](https://apiportal.koreainvestment.com/intro) 제5조 제3항을 확인했다(2026-11-12).
개인 프로그램의 비공개 소량 연구 표본으로 범위를 제한한다. 제3자 제공·상용 재배포·외부 LLM 시세 전송으로 확대하지 않는다.
장기·대량 보존이나 추가 데이터 공급자 도입은 별도 이용 조건을 확인한다.
