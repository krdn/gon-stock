# P1 수용 조건 재확인

2026-11-12. P1은 보류다. P2 진입에 필요한 미완료 조건은 국내 장중 분봉의 실제 시각 관측이다.
이 문서는 [승인된 단계 기준](../../plans/github-execution-proposal.md#6-단계별-산출물)을 완화하지 않고, 남은 항목의 소유 단계를 구분한다.

## P1 조건

| 조건 | 근거 | 상태 |
| --- | --- | --- |
| 국내·미국 호가·잔고 읽기 | [6종 모의 조회](proxy-recheck.md), 미국 호가 실전 GET | PASS: 미국 잔고는 NASDAQ·1페이지 |
| 미국 날짜·시간 읽기 | 00:31 KST `us_bars` 실조회, UTC `2026-11-11T15:31:00Z`, KST·뉴욕 시각 일치 | PASS: 분봉만 |
| 국내 날짜·시간 읽기 | 기존 고정 상한과 같은 시각은 형식 확인으로 제한 | NOT_RUN: 장중 관측 필요 |
| 프록시 요청·반환과 실패 구분 | Astra·Fable 일치, Argon high→trial FAIL 기록 | PASS: Argon 사용 승인 아님 |
| 비밀값 비노출·주문 0 | tests/test_cli.py의 출력·자격 증명 검사, tests/test_kis.py의 주문 거부·고정 GET 계약 | PASS: 코드·합성 검사, 실제 호출은 조회만 |

## 장중 관측 기준 kr-bar-v1

삼성전자 모의 `kr_bars`를 같은 클라이언트로 70초 간격 두 번 조회한다. 인증 토큰을 재사용하며 자동 재시도하지 않는다.
평일 KST 09:05~15:25에만 요청한다. 이 시간 검사는 휴장·거래정지를 증명하지 않는다. 데이터가 없으면 실패다.

1. 분봉 영업일자가 요청 당시 한국 날짜와 같다.
2. 시각이 09:00~15:30이고, 요청 시작 시각을 분 단위로 내린 값보다 작다. 진행 중인 분과 요청 상한의 반향을 제외한다.
3. 해당 행의 `cntg_vol`은 유효한 양의 정수다. 원문 가격·거래량은 결과에 저장하지 않는다.
4. 두 요청 간격이 60초 이상이고 두 번째 선택 분봉 시각이 첫 번째보다 전진한다.
5. 예상 commit과 실행 commit이 같고 추적된 소스 변경이 없다.

하나라도 충족하지 않으면 FAIL이다. PASS는 날짜가 있는 완료 분봉의 전진을 관측했다는 뜻이다.
전략 입력으로 쓸 최신 호가·지연 한도·체결 품질의 검증은 아니다.

```sh
uv run python -m gon_stock.clock_probe \
  --expected-sha <검증할-main-SHA> \
  --output .private/p1-kr-clock-20261112.json
```

결과는 시각·양의 거래량 여부·commit·PASS/FAIL만 담는다. 기존 파일을 덮어쓰지 않는다.
일회성 로컬 timer로 2026-11-12 09:10 KST 실행을 준비한다. 등록 여부·대상 SHA는 이슈 #5에 기록한다.
PC 종료·절전·인증 저장소 잠금·소스 변경이면 성공을 보장할 수 없다. 실제 결과 파일을 확인하기 전에는 P1을 수용하지 않는다.
timer는 조회 결과만 남기며 이슈 종료·단계 승격·P2 개발을 자동 수행하지 않는다.

재개할 때 결과의 `status=PASS`, 두 관측과 `source_sha`를 먼저 대조한다.
코드 리뷰·최종 CI·원격 main 반영까지 확인한 뒤 이슈 #5에 P1 위임 수용을 기록하고 P2를 시작한다.
FAIL이나 파일 부재이면 원인을 기록하며 이슈를 닫지 않는다.

## 후속 단계 소유

| 항목 | 소유 | 유지할 제한 |
| --- | --- | --- |
| 국내 호가 일자·미국 호가 시간대 | P2 품질 | 미확정 event_time은 null, 다른 응답의 날짜를 결합하지 않음 |
| 신선도 계약·임계값 | P2 품질, P5 운용 | 기본 unverified, 전략·주문 입력으로 통과시키지 않음 |
| Argon high·trial 동등성 | P3 모델 선정 | 불일치 FAIL 유지, 별칭 수용·모델 대체 없음 |
| 실제 다중 페이지·전 거래소 잔고 | P5 대사 | 합성 검사와 실제 1페이지를 구분 |

근거는 [P0 전제의 단계 구분](../P0/readiness.md)과 [구현 순서](../../plans/implementation.md)다.
이 항목들을 완료로 바꾸거나 P1 실패를 숨기는 것이 아니다. 해당 단계의 진입·수용 기록에서 다시 검사한다.

## 독립 조건 검토

로컬 Claude CLI에 Fable 5.2 high를 요청했고 `canonicalModel=claude-fable-5-2`, `provider=firstParty`를 확인했다.
판정은 BLOCKED다. 국내 장중 실제 시각 근거와 수용 기록이 남았으며, Argon 선정·신선도는 후속 단계 소유라고 판단했다.
해당 검토는 main `d6988e2`의 문서·근거 대조이며 이번 코드 변경의 리뷰를 대신하지 않는다.
미국 분봉 명세의 한국기준 시각·현지 시각은 [공식 API](https://apiportal.koreainvestment.com/apiservice-apiservice?/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice)를 따른다.

이번 코드 변경의 로컬 검사: 92개 테스트·프로젝트 Ruff·빌드·문서 검사 PASS.
최종 코드 리뷰는 Fable CLI의 5시간 한도로 실패했다. `is_error=true`, `modelUsage={}`이며 검토 결과가 없다.
CLI가 안내한 초기화 시각은 2026-11-12 03:10 KST다. 같은 모델·effort로 03:12에 한 번 재시도하도록 준비한다.
리뷰 입력·실행 소스는 hash로 고정하고, 결과가 있어도 자동 병합하지 않는다. PR은 리뷰 확인 전 초안으로 유지한다.

예약 취소 명령은 다음과 같다.

```sh
systemctl --user stop gon-stock-p1-review-20261112.timer gon-stock-p1-review-20261112.service
systemctl --user stop gon-stock-p1-clock-20261112.timer gon-stock-p1-clock-20261112.service
```
