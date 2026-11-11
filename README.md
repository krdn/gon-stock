# gon-stock

한국투자증권의 국내·미국 주식 데이터를 이용하는 단기 매매 연구 프로젝트.
관심 종목 선정, 근거 기반 분석, 확률 검증, 모의 운용을 거쳐 제한된 자동 주문을 구현한다.
수익 보장이나 손실 없는 매매를 목표로 주장하지 않는다.

- [시스템 설계](docs/architecture/trading-system.md)
- [구현 계획과 완료 조건](docs/plans/implementation.md)
- [GitHub 기준 개발·재개 방식 — B 승인](docs/plans/github-execution-proposal.md)
- [단계별 GitHub 작업 지도](docs/plans/project-roadmap.md)
- [공식 자료 조사](docs/research/evidence.md)
- [GitHub 운영](.github/project-management.md)
- [현재 상태](docs/STATE.md)

KIS 읽기 전용 클라이언트와 [모의투자 조회 CLI](docs/operations/kis-readonly.md)를 구현 중이다.
실제 API 조회, Buzz 에이전트 가동, 백테스트 및 실주문은 아직 검증하지 않았다.
공개 저장소에는 코드·설계·익명화된 검증만 남긴다. 계좌·인증·실제 거래 내역은 비공개로 보관한다.
