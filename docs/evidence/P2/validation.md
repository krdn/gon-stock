# P2 저장·재생 검증

2026-11-12. 구현·합성 검사·소량 실제 저장은 확인했다. Fable 수정분 리뷰는 PASS다. 최종 CI·병합 전이므로 P2 수용은 보류다.
선행 [P1 수용](https://github.com/krdn/gon-stock/issues/5#issuecomment-6810933307)을 확인한 뒤 구현했다.

| 조건 | 확인한 결과 | 한계 |
| --- | --- | --- |
| 관심 종목 | 거래소 alias·통화·종목 식별, 멱등 등록·삭제·재시작 보존 | 사용자 투자 목록 아님 |
| 저장·재생 | ID 충돌 거부, 원본 보존, 수신 순번·시점 필터 | 단일 writer |
| 미래 누출 | 늦은 수신·정정·기업행동·미래/미확정/미완료 분봉 제외 | 합성 시나리오, 전략 성과 아님 |
| 품질 | 중복 후보·역순·미확정·누락 후보 검사 | 실제 누락 확정 아님 |
| 달력 | 미국 DST 전후, 추수감사절·조기 폐장, 국내 한글날·주말 | 라이브러리 일정; 연간 공지 전체 검증 아님 |
| 복구 | DB reopen·Parquet 재생 동일, 손상·미완료 export 거부 | 정전·운영 서버 복구 미검증 |
| 공개 경계 | 허용 필드만 저장, CLI `.private/` 제한, 비밀값 에러 비노출 | 제공자 원문 전체 미보관 |

로컬: 150 tests·프로젝트 Ruff·format·build·docs PASS.
calendar 라이브러리 내부에서 pandas 3.1의 향후 변경 경고 28건이 나온다. 현재 검사는 통과하며 경고를 숨기지 않았다.
DuckDB 2.0.0, exchange-calendars 4.13.2, pytz 2026.6을 lock에 고정했다. pytz는 DuckDB TIMESTAMPTZ 반환에 필요했다.

## 실제 표본

09:55 KST 국내 모의 분봉 30행(시각 확정 29), 미국 실전 시세 분봉 1행을 저장했다.
인증정보·가격·원문은 공개하지 않는다. 주문·실전 잔고 호출은 없었다.
두 DB를 닫고 다시 읽은 결과와 Parquet 재생이 모두 같았다. 이 결과는 장기 수집·전 거래일 커버리지 증명이 아니다.
국내·미국 실제 품질 보고는 모두 `bar_label_unverified`다. 실제 누락·최신성 통과로 계산하지 않는다.

| 표본 | 재생 JSON SHA256 | Parquet SHA256 |
| --- | --- | --- |
| 국내 모의 30행 | `1cb9a516dd791a4229fc3ce69ae50a7810783727b60ccd2476a5425d176be020` | `1c3e5a88ea7038d4da797e2209a8853b7e4e26fad141fd21976b67b56fae2821` |
| 미국 실전 시세 1행 | `cd499ec7854907c90c1b6e2954882ca82aededb89351869a0a458f53e3cb13e9` | `a48de9b590ae06e9daa840d6edae131a6ca888c3b43a7aa874ee6744e680d543` |

구현·실행 계약은 [운영 문서](../../operations/data-replay.md)를 따른다.
실제 자료는 `.private/p2/`, 정제 실행 요약은 `.private/p2-live-summary.json`에 보관했다.

## 확인한 출처

- [DuckDB Python](https://duckdb.org/docs/2.0/clients/python/overview), [Parquet](https://duckdb.org/docs/2.0/data/parquet/overview).
- [exchange_calendars](https://github.com/gerrymanoim/exchange_calendars): 버전과 일정 snapshot을 함께 보관.
- [NYSE 일정](https://www.nyse.com/trade/hours-calendars): 2026-11-26 휴장·11-27 13:00 ET 조기 종료 대조.
- [KIS 국내 분봉 필드](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/inquire_time_itemchartprice/chk_inquire_time_itemchartprice.py), [미국 분봉 필드](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/overseas_stock/inquire_time_itemchartprice/chk_inquire_time_itemchartprice.py).

다음 행동: Fable 5.2 독립 리뷰의 지적 처리, 최종 코드의 검증·PR·CI와 수용 여부 기록.
P3는 P2 수용 전 시작하지 않는다.

## Fable 지적 처리

요청 `claude-fable-5-2` high, 반환 canonicalModel 동일·provider firstParty·is_error=false 확인.
첫 판정 CHANGES_REQUESTED. 입력 SHA256 `29c8a8d0ab113d500c2afe231a0598bf8ff75d3c84fbd25fa0f748232b85f440`.

- B1: 실제 국내 응답의 내림차순 29행이 역순 28건으로 잘못 집계됨을 확인했다. 수신 배치 간 최초 과거 관측만 판정하도록 수정했다.
- B2: 역순 import에서 오래된 수신본이 최신으로 선택됨을 재현했다. 수신시각과 동시각 순번으로 최신본을 선택한다.
- 두 차단 지적·시각 미확정 중복의 반례 4건은 수정 전 FAIL, 수정 후 PASS다.
- M1: `replay --output`과 비공개 파일·건수/hash 출력 테스트 추가. 실제 표본은 처음부터 Python 내부에서 hash만 출력했으며 가격을 리뷰에 보내지 않았다.
- L1: 중복 signature에 source_clock 포함. 0거래량·미확정 시간은 여전히 전략 입력 제외이며 누락 후보 한계를 유지한다.
- L3: 미국 verified/unverified/future 세 분기와 event_time 검사를 추가했다. 실제 미국 표본은 verified 1행이지만 정규장 밖 1행이다.
- L4/L5/L7: 관심 목록 과거 이력·특수 개장일·NTP 전제와 후속 검증을 운영 문서에 명시했다. 연간 공지·실제 라벨·누락은 P5 운용 전 확인하며 완료로 계산하지 않는다.
- L2: 실패 코드 세분화는 보류. 현재 고정된 일반 오류와 저장된 건수를 반환하며 원문 오류 메시지를 노출하지 않는다.
- snapshot 시점 필터·symlink 경계·극대 age의 traceback 방지도 추가 검사했다.

수정 후 기존 실제 표본 품질: 국내 30행 중 역순0·중복0·미확정1·정규장밖0, 미국 1행 중 역순0·중복0·미확정0·정규장밖1.
이벤트 내용은 그대로며 데이터 삭제로 오탐을 숨기지 않았다. 수정분 Fable 재확인 PASS. 입력 SHA256 `4c940dc2e423f34bf34afffe425e0fe700c6c2dc837d6d0ff8f24cba3bd21573`, canonicalModel `claude-fable-5-2`, provider `firstParty`, is_error=false.
후속 LOW N1(빈 `--output`이 stdout으로 빠짐)을 재현 후 권고한 `is not None` 한 줄로 수정했다. 두 CLI 명령의 빈 값 거부 테스트가 통과했다. 리뷰어가 해당 수정의 재리뷰는 불필요하다고 명시했다.
