# P3 연구 실행

[평가 계약](../plans/p3-evaluation.md)을 먼저 고정한다. 과거 수신시각·정정 이력 자료가 없어
사용자는 2026-11-12 미래 수집 자료로 검증하기로 했다. 현재 구현과 합성 검사는 실제 성과 수용이 아니다.

## 미래 자료 수집

실전 인증 저장소를 사용하는 시세 GET 전용이다. 국내 `005930`/`069500`, 미국 `AAPL`/`QQQ`는
최초 연구 종목/기준 ETF 쌍이며 추천 종목이나 과거 종목군이 아니다. 두 시장은 별도 DB로 수집·평가한다.
한 프로세스가 한 DB를 쓰며, 동시 export는 수집기를 멈춘 다음 수행한다.

```sh
uv run gon-stock-collect --exchange XKRX --symbols 005930 069500 \
  --db .private/p3/kr.duckdb --until 2026-11-19T00:00:00Z
uv run gon-stock-collect --exchange XNAS --symbols AAPL QQQ \
  --db .private/p3/us.duckdb --until 2026-11-19T00:00:00Z
```

`--until`은 현재 이후 7일 이내의 UTC 시각으로 정한다. 정규장 시작 1분 20초 후부터
종료 1분 20초 후까지 분당 조회한다. 미국은 진행 중인 봉과 직전 봉을 받을 수 있도록 2개를 요청한다.
국내 응답에서도 원천 시각 기준 최신 2개만 저장한다. 수신 시각과 미확정 상태는 그대로 보존한다.
오류는 재시도 없이 프로세스를 종료한다. 유효한 빈 응답은 0행으로 기록하며 누락 증거로 남는다.
재시작은 동일 명령과 DB, 새 종료 시각으로 한다. 중단 동안의 과거 수신 시각을 만들어 채우지 않는다.
달력 스냅샷·기간·사전 종목군은 DB 옆 JSON에 남긴다. 달력의 실제 공지 대조는 아직 미검증이다.

터미널 실행은 Ctrl-C로 중단한다. 사용자 systemd 서비스로 실행했다면
`systemctl --user stop gon-stock-p3-kr gon-stock-p3-us`로 중단한다.
수집 서비스는 `systemd-inhibit --what=sleep --mode=block`으로 감싸 실행 중 호스트 절전을 막는다.
서비스 중단 시 제한도 해제된다. 강제 절전 후에는 토큰 만료 시계가 어긋날 수 있어 프로세스를 재시작한다.
전원 꺼짐·강제 절전·네트워크 단절은 수집 누락을 만든다. 로컬 수집은 P5 상시 운용 검증과 구분한다.

## 평가

수집기를 중단하고 `gon-stock-data --db … export --output .private/p3/snapshot`으로
Parquet와 해시 manifest를 고정한다. 평가는 아래와 같이 실행한다.

```sh
uv run gon-stock-research --snapshot .private/p3/snapshot \
  --manifest .private/p3/manifest.json --output .private/p3/report.json
```

manifest 필드는 `schema_version: 1`, `strategy_id: relative-volume-intraday-v1`,
`dataset_sha256`(export manifest의 sha256), `universe`(instrument 배열), `benchmark`(instrument),
`calendar`(품질 도구의 달력 스냅샷), `train_end`, `calibration_end`, `test_end`(YYYY-MM-DD),
`source_kind`(`observed`/`vendor_history`/`synthetic`), `environment`(`real`/`mock`/`synthetic`),
`costs`, `verified`다. instrument는 `exchange`, `symbol`, `currency`를 가진다.

`costs`에는 `commission_each`, `tax_sell`, `spread_each`, `slippage_each`, `fx_each`를
bps 숫자 문자열로 모두 지정한다. `verified`의 `bar_labels`, `calendar`, `coverage`,
`corporate_actions`, `universe_pit`, `costs`는 증거가 있을 때만 true로 설정한다.
수동 플래그는 증명 자체가 아니므로 검증 근거와 원본을 함께 검토해야 한다.

입출력은 `.private/` 내부만 허용하고 보고서는 덮어쓰지 않는다. stdout에는 상태·개수·해시·차단만 출력한다.
소스/계약/자료 해시와 실행 결과를 남기고 `.private/p3-runs.jsonl`에서 같은 holdout 재사용을 차단한다.
단일 연구 프로세스로 실행한다. ledger 삭제나 기간 변경으로 독립 표본을 만든 것으로 간주하지 않는다.
`BLOCKED`와 합성 리허설도 같은 종목·기간의 holdout을 소진한다. 진행 확인용으로 실제 평가 기간을
사용하지 않는다. 종목 순서·거래소 별칭 변경으로 같은 구간을 재실행해서도 안 된다.
`BLOCKED`는 자료/검증 부족, `REJECTED`는 기준 미달, `CANDIDATE_PASS`는 후보 기준 통과다.
후보 통과도 P3 수용·P4 시작·주문 승인이 아니다.
