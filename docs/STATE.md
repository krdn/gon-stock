# 현재 상태

2026-11-11: 사용자 요청으로 증권사 연동 대상을 한국투자증권(KIS)으로 변경.

- 현재 P1: KIS 국내·미국 시세·호가·잔고 읽기 전용 클라이언트와 CLI 구현. 모의 서버에서 시세·호가 4종 응답 확인. 잔고는 EGW02007(모의용 키 아님)으로 실패해 키 재등록 대기.
- KIS 공식 자료와 전환 결정: [조사 기록](research/evidence.md).
- 키움 테스트 초안은 `.private/before-kis/`에 보존하고 KIS 테스트로 교체했다.
- 다음 행동: Fable 리뷰·CI → 안전한 자격 증명 등록 → 실제 조회 검증 → 프록시 요청/반환 모델 검증.
- 키움 자격 증명 등록 대기는 취소한다. 사용자는 모의투자 API를 선택했다. 인증값은 OS 저장소에 등록했으나 모의투자용 키로 재등록해야 한다.

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
