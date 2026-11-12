# 현재 상태

2026-11-12: P1 위임 수용 완료. PR #17 병합 main `0d4e956`, main CI PASS와 관측 소스 해시 동일성 확인.

- KIS 실제 조회: 국내·미국 현재가·호가·잔고 6종 성공. 미국 잔고는 NASDAQ 범위, 잔고 각 1페이지.
- 인증: KIS와 프록시 키는 OS 인증 저장소에 등록. 기존 계좌 연결 차단은 해결됐다.
- 시각: 국내 호가 시각·미국 호가 날짜와 시각을 읽고 형식을 검사한다. 날짜·시간대 불확실성을 구분하며 신선도는 미검증으로 유지한다.
- 연속조회: 국내·미국 합성 다중 페이지·반복키·상한 검사 통과. 실제 다중 페이지는 미검증.
- 프록시 실호출: 업데이트 후 Fable 5.2·Astra 요청/반환 일치. 기존 Fable HTTP 400은 재발하지 않았다. Argon high 요청은 trial 반환으로 불일치가 남았다.
- 실전 시세: 사용자 추가 승인 후 미국 AAPL/NAS 현재가·호가 GET 성공. 실전 잔고·주문 호출 없음.
- 국내 분봉: 수정 SHA `25d72a8`의 모의 2회 관측에서 완료 분봉 09:36→09:38 KST 전진·양의 거래량 확인. kr-bar-v1 PASS이며 거래소 실체결·신선도 증명은 아니다.
- 미국 분봉: 정식 `us_bars`는 명세의 한국·뉴욕 시각 일치를 검사하고 UTC 시각을 출력한다. 미래·불일치 시각은 event_time=null이다. 신선도는 계속 unverified다.
- 다음 행동: [P2 이슈 #6](https://github.com/krdn/gon-stock/issues/6)의 저장·재생·품질 구현. [P1 위임 수용 근거](https://github.com/krdn/gon-stock/issues/5#issuecomment-6810933307).
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
