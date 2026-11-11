# 현재 상태

2026-11-11: 초기 조사와 설계 초안 작성.

- 확인: 공식 키움 국내·미국 API 문서, Buzz CLI 생성 방식, 로컬 프록시 연동 문서.
- 프록시: 루트 HTTP 응답과 인증된 모델 목록 확인. Astra·Fable 5.2·Argon ID가 목록에 있음.
- 리뷰: Fable 5.2 실제 요청은 HTTP 503으로 실패. 반환 모델·응답 본문 검증 및 리뷰 통과는 미달성.
- 모델 정책: 리뷰는 Fable 5.2만 사용. 기존 전역 리뷰 설정을 변경하지 않음.
- 미구현: 데이터 연결, 전략, 주문, Buzz 채널·에이전트, 실시간 운영.
- 미검증: 수익성, 백테스트, 모의 체결, 실전 체결, 손실 제한 동작.
- GitHub 기능별 상태: [운영 계획](../.github/project-management.md).
- 원격: [공개 저장소](https://github.com/krdn/gon-stock), [P0 이슈](https://github.com/krdn/gon-stock/issues/1), [Project](https://github.com/users/krdn/projects/19), [설계 토론](https://github.com/krdn/gon-stock/discussions/2).
- Wiki: 기능 활성화만 확인. Wiki Git 원격 조회 실패로 첫 페이지는 미생성. docs가 현재 기준 문서.
- 검사: 로컬 링크와 git diff 공백 검사 통과. evolve 문체 검사는 기준 파일 부재로 실행 불가.
- 터미널: 사용자가 리서치용 pane 사용을 요청함. 현재 도구에서 기존 오른쪽 pane 제어는 미확인.
- 다음 작업: 설계 리뷰, 연결 가능 모델과 시장·운영 조건 확정, P1 읽기 전용 연결.
