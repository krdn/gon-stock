# 개발 작업 지도

2026-11-11 · 모든 단계는 계획 등록 상태이며 개발 승인은 아직 없다.

[실행 제안 execution-v1](github-execution-proposal.md) · [총괄 이슈 #4](https://github.com/krdn/gon-stock/issues/4) · [Project #19](https://github.com/users/krdn/projects/19)

| 순서 | 단계 이슈 | 선행 단계 | 실행 허용 상태 |
| --- | --- | --- | --- |
| P0 | [설계 확정 #1](https://github.com/krdn/gon-stock/issues/1) | 사용자 실행 제안 승인 | 승인 대기·Fable 리뷰 미완료 |
| P1 | [읽기 전용 연결 #5](https://github.com/krdn/gon-stock/issues/5) | P0 | 미승인 |
| P2 | [저장·재생 #6](https://github.com/krdn/gon-stock/issues/6) | P1 | 미승인 |
| P3 | [전략·확률 검증 #7](https://github.com/krdn/gon-stock/issues/7) | P2 | 미승인 |
| P4 | [Buzz·최소 화면 #8](https://github.com/krdn/gon-stock/issues/8) | P3 | 미승인 |
| P5 | [모의·관찰 #9](https://github.com/krdn/gon-stock/issues/9) | P4 | 미승인 |
| P6 | [실전 준비 #10](https://github.com/krdn/gon-stock/issues/10) | P5 결과 수용 | 미승인 |
| P7 | [제한 운용 #11](https://github.com/krdn/gon-stock/issues/11) | P6·별도 실거래 시작 결정 | 미승인 |

단계 아래의 세부 구현 이슈는 해당 단계 착수 시 만든다. 설계 변경으로 폐기될 수 있는 작업을 미리 대량 생성하지 않는다.
선행 관계는 승격 순서다. 앞 단계의 증거를 요구하지 않는 독립 조사·문서는 승인 범위에서 병행할 수 있다.
예측 성능 부족으로 되돌아가면 실패 원인과 새 작업을 연결하며 기존 실패 증거를 지우지 않는다.

## 이번 제안의 검증

- 공식 GitHub 문서에서 Projects·하위 이슈·의존성·CI·배포 검토·artifact 기능 확인.
- 실행 제안 문서와 기존 제품 설계의 단계 대응을 직접 확인.
- Fable 5.2 리뷰 요청: HTTP 503으로 실패. 반환 모델·리뷰 결론 없음. 다른 모델로 대체하지 않음.
- 최초 리뷰 입력 SHA-256: `4308c619cc254aa5e79556684ae76449c4cb8b82dd5478704e190438fb2b28e8`.
- 이 파일 및 원격 작업 지도는 위 리뷰 이후 추가한 기록이며 외부 리뷰를 받지 않음.
- 문서 PR은 사용자 검토를 위한 초안이다. CI·운영 실행기·거래 코드·Buzz 에이전트는 이번에 구현하지 않음.

공개 자료에는 계좌 금액·거래 원장·API 키·프록시 인증·비공개 데이터가 포함되지 않는다.
