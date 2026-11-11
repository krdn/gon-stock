# GitHub 운영 계획

공개 저장소의 문서·이슈가 개발 기록의 기준이다. 거래 원장과 개인정보의 저장소로 사용하지 않는다.
초기 상태는 모든 원격 기능 pending이며 실제 URL·권한을 조회한 뒤 상태를 갱신한다.

| 기능 | 용도 | 초기 상태 |
| --- | --- | --- |
| Code·PR | 설계·구현·리뷰·버전별 변경 | pending |
| Issues·하위 이슈 | 단계별 수용 기준·버그·예측 실패 개선 | pending |
| Projects | 단계, 상태, 우선순위, 차단 사유, 검증 근거 | pending |
| Milestones·Labels | P0~P7 단계 묶음과 작업 분류 | pending |
| Discussions | 전략 후보·반론·검증 결론, 확정 시 문서 연결 | pending |
| Wiki | 설치·운영·복구 안내의 입구, 원문 docs 링크 | pending |
| Actions | 문서·타입·테스트·재현 검증, 익명 보고서 | pending |
| Releases·Tags | 검증된 버전·변경 내역·롤백 기준 | 구현 후 적용 |
| Environments·Deployments | paper/live 분리와 배포 이력 | 배포 단계 적용 |
| Security·의존성 검사 | 비밀값·취약점·공급망 검사 | 지원 플랜·권한 확인 후 적용 |
| Rulesets·CODEOWNERS | branch 보호·소유권 | 현재 권한·개인 repo 제약 확인 후 적용 |
| Insights·Project charts | 진행·결함·검증 추이 | 실제 기록 축적 후 적용 |
| Packages | 실행 이미지 배포 | 이미지 배포 단계 적용 |
| Pages | 공개 문서 사이트 | 개인 거래 대시보드는 공개하지 않음; 현재 불필요 |

Project 상태는 Backlog→Ready→In progress→Review→Verified→Done으로 계획한다.
구현 완료와 사용자 수용을 구분한다. 원격 기능이 불가능하면 사유와 Issues/docs 대체 경로를 남긴다.
Wiki와 Discussions를 사용하더라도 설계를 여러 곳에 복제하지 않는다.
실시간 거래·비상 정지는 GitHub Actions 스케줄이나 GitHub 가용성에 의존하지 않는다.
