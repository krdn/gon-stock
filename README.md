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
- [과거 분봉 분석 결과와 한계](docs/evidence/P3/historical-analysis.md) · [미국 Alpaca 120일 분석](docs/evidence/P3/alpaca-analysis.md)
- [당일 청산 포트폴리오 v1](docs/plans/intraday-portfolio-v1.md) · [종목 선별 근거](docs/evidence/P3/portfolio-selection.md) · [가상원장 검증](docs/evidence/P3/portfolio-ledger.md)
- [P3 평가 계약](docs/plans/p3-evaluation.md) · [연구·미래 수집 실행](docs/operations/p3-research.md)
- [P4 연구 작업대·Buzz 연결](docs/operations/p4-workbench.md)

KIS 읽기 전용 클라이언트와 [모의투자 조회 CLI](docs/operations/kis-readonly.md)로 6종 실제 조회를 확인했다.
[LLM 프록시 CLI](docs/operations/llm-proxy.md)는 요청·반환 모델 일치와 실패를 구분한다.
P1은 모의 분봉 시각 전진·Fable 코드 리뷰·병합 후 CI 확인을 거쳐 위임 수용했다. P2 [저장·재생 CLI](docs/operations/data-replay.md)도 리뷰·CI·소량 표본 재생을 확인해 위임 수용했다.
시세 신선도·Argon 모델 일치·상시 운용 성과·실주문은 미검증 또는 미완료다.
공개 저장소에는 코드·설계·익명화된 검증만 남긴다. 계좌·인증·실제 거래 내역은 비공개로 보관한다.
