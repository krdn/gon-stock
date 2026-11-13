# 현재 상태

2026-11-13: P1·P2 위임 수용 완료. P3 구현 PR #21 병합 main `c017d8e`, main CI PASS. P3 실제 성과 수용은 품질·비용·보정 검증 미완료로 보류.

- KIS 실제 조회: 국내·미국 현재가·호가·잔고 6종 성공. 미국 잔고는 NASDAQ 범위, 잔고 각 1페이지.
- 인증: KIS와 프록시 키는 OS 인증 저장소에 등록. 기존 계좌 연결 차단은 해결됐다.
- 시각: 국내 호가 시각·미국 호가 날짜와 시각을 읽고 형식을 검사한다. 날짜·시간대 불확실성을 구분하며 신선도는 미검증으로 유지한다.
- 연속조회: 국내·미국 합성 다중 페이지·반복키·상한 검사 통과. 실제 다중 페이지는 미검증.
- 프록시 실호출: 업데이트 후 Fable 5.2·Astra 요청/반환 일치. 기존 Fable HTTP 400은 재발하지 않았다. Argon high 요청은 trial 반환으로 불일치가 남았다.
- 실전 시세: 사용자 추가 승인 후 미국 AAPL/NAS 현재가·호가 GET 성공. 실전 잔고·주문 호출 없음.
- 국내 분봉: 수정 SHA `25d72a8`의 모의 2회 관측에서 완료 분봉 09:36→09:38 KST 전진·양의 거래량 확인. kr-bar-v1 PASS이며 거래소 실체결·신선도 증명은 아니다.
- 미국 분봉: 정식 `us_bars`는 명세의 한국·뉴욕 시각 일치를 검사하고 UTC 시각을 출력한다. 미래·불일치 시각은 event_time=null이다. 신선도는 계속 unverified다.
- P2: 관심 종목·DuckDB/Parquet 저장·시점 재생·품질 구현. 150 tests·Fable 수정분 리뷰·PR/main CI PASS. [위임 수용](https://github.com/krdn/gon-stock/issues/6#issuecomment-6811449518), [검증과 한계](evidence/P2/validation.md).
- P3 구현: [계약](plans/p3-evaluation.md)에 따라 장중 기준 전략·비용·시간순 분리·확률 보정·비공개 평가 CLI·미래 수집기를 구현했다. [실행 절차](operations/p3-research.md). 175 tests·Ruff·format·build PASS, Fable 수정분 리뷰 PASS. [검증 기록](evidence/P3/implementation.md). PR #21 병합 후 main CI PASS, 리뷰 소스 동일성 확인.
- P3 과거 분석: [추가 승인과 고정 계약](plans/p3-history.md)에 따라 종목별 120개 날짜를 조회했다. 국내 실제 118일, 최초 시가 충돌 1건을 원본 보존·재조회 v2로 분리했다. [조건부 분석](evidence/P3/historical-analysis.md)의 평가 40일/243완료거래에서 평균은 비용 전 −0.066%, 25bps 비용 후 −0.316%. 미청산22·진입봉부재3 제외, 실제 비용·시점·정정 이력 미검증으로 BLOCKED. 미국 KIS는 8일 정규화·16일 시각불일치·96일 빈 응답으로 평가 불가였으나, 이후 [Alpaca SIP 120일 분석](evidence/P3/alpaca-analysis.md)을 완료했다. AAPL 평가40일/198거래 평균 비용전 +0.0114%, 25bps −0.2386%, 50bps −0.4886%; 미청산/진입봉누락0. 비용전 구간도0을 포함하고 보정표본이 부족하여 채택 근거 없음. P3 수용/P5 보류, 미래 수집 유지.
- 자료 보강 조사: 국내 118일 일봉 대조 불일치와 누락 후보 21요청 재조회/복구0 확인. 원인 미확정. Alpaca 인증 및 SIP 실제 수집 완료: 두 종목 각120일/46,800정규장봉, 계획 달력 기준 누락·중복·충돌0. 정규화/평가 연결과 236tests·Fable5.2 high PASS. 과거 정정/시점 가용성·비용 미검증. [조사 근거](evidence/P3/historical-analysis.md), [안전한 등록/실행](operations/p3-research.md#alpaca-과거-원본-확보). P3 수용/P5 보류 유지.
- 포트폴리오 구성: 사용자 당일청산 선택에 따라 [v1 계약](plans/intraday-portfolio-v1.md)과 [선별 근거](evidence/P3/portfolio-selection.md)를 작성했다. 국내 SK하이닉스/현대차·미국 NVDA/AMZN, 시장별 활성 슬롯25%씩·현금최소50%의 초기 배분 기준, 전시장 동시2종목. 현재 현금100%, 실행 연결 없음. 가상 시작자금1,000만원·원화/달러50:50 분리·공통 위험예산 유지. 과거종가/참고환율 기준 수량 예시와 현금/위험한도 검사 완료. 구성 당시 전체자금 가상원장/수익률은 NOT_RUN이었으며 후속 검증은 아래에 구분한다. P3/P5 보류.
- 가상원장: [합성 검증](evidence/P3/portfolio-ledger.md)에서 원화/달러 현금·미결제금·FX·비용·공통 손실한도·NAV/수익률과 비공개 CLI를 구현했다. 합성 24주 매수/매도 예제의 NAV10,019,176원·수익률0.19176%는 산술 검사이며 실제 성과가 아니다. 미국 과거 재생/기준ETF 연결은 아래 탐색 결과에 한정한다. 실제 체결·결제일·국내 시세 품질은 미검증, P3/P5 보류.
- 선정 종목 과거 재생: [미국40거래일 탐색](evidence/P3/portfolio-history.md). NVDA/AMZN/SPY 각15,600봉, 원화현금500만원을 포함한 전체1,000만원 기준25bps 가정33거래·손익−217,717원·수익률−2.1772%. 비용전−0.5155%, 50bps−3.7455%,75bps−5.0331%. 미국 단독 당시 국내는 단일가/거래중단 처리 미지원으로 NOT_RUN이었으며 후속 통합은 아래에 구분한다. 고정환율·미확인 결제/비용·현재선정/평가구간 재사용 탐색이며 P3/P5 보류.
- 국내·미국 통합 재생: [국내 거래중단/단일가 반영 결과](evidence/P3/kr-portfolio-replay.md). KIND CB2건·KIS VI120조회/2건·40종가세션으로 국내45,543관측의 예상시점 대조 PASS. 국내/통합8시나리오 별도체결·현금·손익 대조 PASS, 기존미국4결과 불변. 전체1,000만원25bps 가정81거래·손익−439,123원·수익률−4.3912%; 비용전−1.3954%,50bps−5.0642%,75bps−5.1392%. 국내 단독25bps−2.2141%. 원본/가정 한계와 현재선정·동일기간 재사용으로 P3/P5 보류.
- 미래 수집: 고정 SHA `c017d8e` 사용자 서비스 2개 활성. 국내 두 종목에서 10:57/10:58 KST 연속 저장, 중단 후 DB 재열기 보존과 재시작 수집 확인. 미국도 [첫 정규장 수집](evidence/P3/us-first-capture.md)에서 AAPL/QQQ 23:30→23:33 KST 완료 분봉·양의 거래량·DB 재열기 보존을 확인했다. 종료 한도 2026-11-19 09:00 KST, 오류 시 중단, 수집 중 호스트 절전 방지.
- P3 첫날 품질: [점검 기록](evidence/P3/first-day-quality.md). 국내 1,100행 스냅샷, 종목별 완료 시각 조건 통과 고유 분봉 263개(10:56~15:18 KST). 라벨 미확인으로 누락 판정 보류. Nasdaq 2026 정규 일정 251세션 대조 일치. 미국 첫 조회는 11/12 23:31에 실제 저장됐으며 초기 16행 스냅샷을 고정했다. 장외 export 후 국내 수집 재기동·양 시장 active 확인.
- P4 병행: [2026-11-12 추가 승인](https://github.com/krdn/gon-stock/issues/4#issuecomment-6812438087)으로 P3 검증과 [P4 개발](plans/p4-decision-flow.md)을 병행한다. P4 기술 검증은 P3 성과 수용이 아니다.
- P4 로컬 구현: 연구 작업대·관심 목록·검토·관망 카드·중단 상태, 합성 입력의 실제 프록시 응답·카드 저장·화면 검증 PASS.
- P4 Buzz: 사용자 제공 CLI로 전용 신원 2개 생성·소유자 서명·가입 검증. Astra 전략→agy Argon 반론의 실제 같은 스레드 응답과 운영자가 요약한 관망 카드·알림 재조회 PASS. 웹 카드 자동 연동·상시 운용은 별개다.
- P4 리뷰: Fable 429 이후 [사용자 임시 승인](https://github.com/krdn/gon-stock/issues/4#issuecomment-6813761223)으로 agy Argon high 사용. 첫 지적 수정과 208 tests·Ruff·format·build PASS. 수정분 리뷰 PASS·리뷰 소스 동일성 확인. PR #23 병합 main `b8e8ca8`, PR/main CI PASS. [P4 최소 기술 검증 위임 수용](evidence/P4/acceptance.md).
- 다음 행동: [P3 #7](https://github.com/krdn/gon-stock/issues/7) 미래 자료와 품질 근거 확보, [P4 #8](https://github.com/krdn/gon-stock/issues/8) 제한된 기술 검증 수용 완료. Fable 복귀: 로컬 CLI canonicalModel/firstParty와 프록시 요청·반환 일치, 웹 카드 생성·브라우저 표시 PASS. Buzz 새 스레드의 Astra 전략→Fable 반론을 원격 재조회했고 반론 세션 반환 모델 Fable 5.2·도구 사용 0을 확인했다. 임시 Argon 경로 종료. P5 통합 운용 진입은 P3·P4 수용 후다.
- P5 전 필수: 실제 분봉 라벨·누락·연간 거래소 공지·서버 시계 오차 확인. P3는 현재 관심 목록을 과거 종목군으로 사용하지 않고 정규장 밖 자료를 거래 입력에서 제외한다.
- 후속 소유: 호가 일자·시간대와 신선도는 P2 품질/P5 운용, Argon 동등성은 P3 선정에서 검사한다. Argon 불일치 FAIL을 유지한다.
- 코드 리뷰: 로컬 Fable 5.2 high 요청, canonicalModel·firstParty 반환 확인. 본체·수정분 PASS. 97 tests·프로젝트 Ruff·format·build·docs PASS. [관측과 비차단 지적 처리](evidence/P1/acceptance.md).
- [업데이트 후 검증과 데이터 경로 선택](evidence/P1/proxy-recheck.md).
- [후속 검증 근거](evidence/P1/follow-up.md) · [KIS 실행](operations/kis-readonly.md) · [프록시 실행](operations/llm-proxy.md).
- [P1 이슈](https://github.com/krdn/gon-stock/issues/5). 주문 호출 0, 실전 계좌 조회·배포·실거래 미실행.

## P0 당시 기록

아래는 기존 P0 작업 기록이며 KIS 연결 성공의 근거가 아니다.

- 확인: 공식 키움 국내·미국 API 문서, Buzz CLI 생성 방식, 로컬 프록시 연동 문서.
- 프록시: 루트 HTTP 응답과 인증된 모델 목록 확인. Astra·Fable 5.2·Argon ID가 목록에 있음.
- 원격 리뷰 요청: 프록시 HTTP 503 인증 실패. 복구 성공을 주장하지 않음.
- 현재 리뷰 경로: 사용자 지정 로컬 Claude CLI. Fable 5.2 응답과 modelUsage/canonicalModel 확인, 최초 판정 CHANGES_REQUESTED, 수정분 검증 진행.
- 모델 정책: 리뷰는 Fable 5.2만 사용. 기존 전역 리뷰 설정을 변경하지 않음.
- 승인 범위: [총괄 이슈의 사용자 답변](https://github.com/krdn/gon-stock/issues/4#issuecomment-6794757846). P0~P4 개발과 P5 모의 검증, P7 실거래 별도 결정.
- 준비: PR #13의 개발 재개 지침·작업 양식·문서 CI. 실제 기능 구현과 구분.
- 미구현: 데이터 연결, 전략, 주문, Buzz 채널·에이전트, 실시간 운영.
- 미검증: 수익성, 백테스트, 모의 체결, 실전 체결, 손실 제한 동작.
- GitHub 기능별 상태: [운영 계획](../.github/project-management.md).
- 원격: [공개 저장소](https://github.com/krdn/gon-stock), [P0 이슈](https://github.com/krdn/gon-stock/issues/1), [Project](https://github.com/users/krdn/projects/19), [설계 토론](https://github.com/krdn/gon-stock/discussions/2).
- Wiki: 기능 활성화만 확인. Wiki Git 원격 조회 실패로 첫 페이지는 미생성. docs가 현재 기준 문서.
- 검사: 로컬 링크와 git diff 공백 검사 통과. evolve 문체 검사는 기준 파일 부재로 실행 불가.
- 터미널: 사용자가 리서치용 pane 사용을 요청함. 현재 도구에서 기존 오른쪽 pane 제어는 미확인.
- 다음 작업: PR #13/#12/#3 수정분 검증·통합과 P0 수용 판단 후 P1 읽기 전용 연결.
- P0 종료 조건과 후속 이월 항목은 PR #13의 docs/evidence/P0/readiness.md를 기준으로 통합한다.
