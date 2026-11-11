# 구현 근거 조사

조사일: 2026-11-11. [설계](../architecture/trading-system.md) · [계획](../plans/implementation.md)

## 확인한 사실

| ID | 근거 | 설계에 미치는 영향 |
| --- | --- | --- |
| F1 | [키움 공식 REST API 저장소](https://github.com/Kiwoom-Securities/Kiwoom-REST-API)는 국내·미국 주식 HTTP 및 WebSocket 예제를 제공한다. | 국내·미국부터 구현한다. 모든 해외 거래소 지원으로 확대 해석하지 않는다. |
| F2 | [키움 이용안내](https://openapi.kiwoom.com/intro/serviceInfo)는 허용 IP 등록과 실전·모의 App Key 분리를 설명한다. | 배포 서버의 출구 IP를 확인하고 환경별 인증을 분리한다. |
| F3 | [OpenDART](https://opendart.fss.or.kr/intro/main.do)는 공시 원문과 주요 재무정보를 제공한다. | 국내 이벤트 분석의 원문 근거로 사용한다. 가격 스트림 대체재로 쓰지 않는다. |
| F4 | [SEC EDGAR API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)는 제출 이력과 XBRL 정보를 제공한다. | 미국 공시를 보완한다. 제공기관의 접근 정책을 준수한다. |
| F5 | [NautilusTrader](https://github.com/nautechsystems/nautilus_trader)는 이벤트 기반 백테스트·실행 엔진이며 LGPL-3.0이다. | 체결 재현 후보로 검토하되 키움 어댑터와 라이선스 검증이 필요하다. |
| F6 | [Qlib](https://github.com/microsoft/qlib)는 정량 투자 연구 플랫폼이며 MIT 라이선스다. | 연구 후보로 보류한다. 키움 주문 연결이나 수익성을 제공한다고 가정하지 않는다. |
| F7 | 로컬 `buzz agents draft-create --help`는 소유자 Desktop의 에이전트 생성 폼을 여는 명령으로 설명한다. | 초안 전송과 실제 에이전트 저장·실행을 구분한다. |
| F8 | 로컬 `buzz channels create --help`는 private 채널, stream/forum 유형을 지원한다. | 리서치 채널과 매매 알림 채널을 분리할 수 있다. |
| F9 | [단타 위험 설명](https://www.investor.gov/additional-resources/spotlight/formerdirectorlorischock-directors-take/thinking-day-trading-know-risks)은 단기 매매의 손실·레버리지 위험을 설명한다. | 매일 수익·무손실을 수용 기준으로 두지 않는다. |

키움 저장소는 공개 CLI 소스와 PyPI CLI 패키지를 구분한다. 공식 명세를 기준으로 작은 어댑터를 만들되,
도입할 코드의 LICENSE.md와 배포 조건을 별도로 검토한다. 별 수나 설치 수로 품질을 판정하지 않는다.
데이터 서비스의 가격·지연·보관·재배포 권한, 모의투자의 미국 지원 범위와 체결 방식은 아직 검증하지 않았다.

## 선택 근거

1. 공식 키움 어댑터 + 단순 기준 전략: 연동 추적이 쉽고 초기 의존성이 작다. 우선 선택한다.
2. NautilusTrader 전체 도입: 체결 시뮬레이션에 유리하지만 어댑터 구현과 엔진 학습 비용이 크다. 기술 검증 후 결정한다.
3. Qlib 전체 도입: 연구 실험에 유리하지만 초기 두 시장의 실행 계층에는 과하다. 필요가 확인될 때 추가한다.
4. LLM 트레이딩 에이전트 저장소 전체 복제: 주장된 수익성과 실거래 정확성을 확인하지 못했다. 채택하지 않는다.

위 선택은 요구사항에 따른 설계 판단이며 성능 비교 실험 결과가 아니다.
