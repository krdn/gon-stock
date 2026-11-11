# P0 Fable 5.2 독립 리뷰

2026-11-11. 최초 리뷰 판정은 CHANGES_REQUESTED이며 다음 수정은 그 지적 처리다.

## 실행 근거

- 사용자 요청에 따라 원격 프록시 대신 로컬 Claude CLI를 실행했다.
- 요청 모델: `claude-fable-5-2`, effort: `high`.
- CLI 결과: `subtype=success`, `is_error=false`.
- 응답 메타데이터: `modelUsage.claude-fable-5-2.canonicalModel=claude-fable-5-2`, `provider=firstParty`.
- 입력 packet SHA-256: `7c4c40cae094eca86aabe0abaa0095f91293bfb188d0a78ad9b0dee087c65f1b`.
- 도구·MCP·파일 수정 권한을 비활성화했다. 검토는 전달한 파일 본문에 한정한다.
- 실제 로컬 인증 성공과 원격 프록시의 인증 실패는 별개다. 프록시 복구를 주장하지 않는다.

## 지적 처리

| 번호 | 지적 | 처리 |
| --- | --- | --- |
| 1 | 승인됨/미승인 상태가 문서마다 다름 | 실행 제안·작업 지도·STATE를 승인 기록과 현재 상태에 맞춰 갱신 |
| 2 | 리뷰가 merge 전 필수인지 모호 | 기능·설계·위험 규칙 변경은 리뷰 지적 처리와 최종 검사 전 merge 금지, 사소한 문서·설정은 예외 |
| 3 | P0 종료 전제와 이월 항목이 불명확 | readiness.md에 P0 확정/후속 단계 조건을 정리 |
| 4 | 자정에 미국 세션의 손실 예산이 초기화됨 | 위험 관리일을 KST 07:00~다음 07:00으로 변경 |
| 5 | 당일 손실과 신규 진입 위험의 합산 누락 | 당일 사용 손실 예산 + 잔여 계획 손실로 사전 검사, 이익으로 예산 확대 금지 |
| 6 | DB 장애 중 청산 정책 미정 | 청산 포함 자동 전송 중단, 독립 경고·수동 복구, 대사 전 재개 금지 |
| 7 | 공백 검사가 checkout 깊이에 따라 달라질 수 있음 | 빈 트리와 HEAD를 비교해 저장소 전체를 일관되게 검사 |

1번은 관련 문서 PR 전체에 걸친 수정이다. 통합 시 실제 승인 링크·표·STATE를 다시 대조한다.
7번의 원래 실패는 리뷰어 추론이었으며 재현을 주장하지 않는다. 검사 범위를 명시적으로 고정했다.
미구현인 위험 엔진·주문 장애 동작은 P3·P5에서 실행 검증해야 한다. 문장 수정이 제품 검증은 아니다.

## 수정 검증

수정분 후속 리뷰는 **PASS**, 지적 1~7 모두 해결로 판정했다. 최초 CHANGES_REQUESTED는 보존한다.
후속 응답도 `subtype=success`, `is_error=false`, `canonicalModel=claude-fable-5-2`, `provider=firstParty`였다.
후속 입력 SHA-256: `73c09282130d003cb91f0c39c09aac4ace6f216d26b798821b0eee9fd4623f53`.
대상 diff: 준비 branch `eaff0bc..b815161`, 제안 branch `bb4b19b..1514208`, 상태 branch `4b6a2ab..aac03fa`.
CI와 통합 결과는 PR #13/#12/#3 및 P0 이슈에 최종 SHA와 함께 연결한다.
후속 리뷰는 문장·diff 검토이며 실제 위험 엔진·DB 장애·체결 시험은 NOT_RUN이다.
