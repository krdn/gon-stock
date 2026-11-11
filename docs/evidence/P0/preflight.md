# P0 실행 준비 기록

2026-11-11. P0는 진행 중이며 아직 수용되지 않았다.

## 승인

- 대상: execution-v1, PR #12의 `bb4b19bc73cf37ade3e5c8785c16655a484703ef`.
- [실제 사용자 답변 전사](https://github.com/krdn/gon-stock/issues/4#issuecomment-6794757846).
- 허용: P0~P4 개발·P5 모의 검증·범위 내 PR/검사/리뷰/통합/기록.
- 실거래 시작은 별도 결정이다. 사용자 승인과 에이전트 전사 기록을 구분한다.

## 로컬 확인

| 검사 | 결과 | 한계 |
| --- | --- | --- |
| Python 3.13 | uv 관리 Python 3.13.11 확인 | 배포 서버 환경은 별도 검증 |
| 문서 링크·코드블록 | 등록 Markdown 10개 통과 | 외부 URL·제목 앵커 제외 |
| 검사 도구 오류 탐지 | 누락 링크·미종결 코드블록 거부, 정상 문서 통과 | 임시 fixture로 실행 |
| Python 구문 | py_compile 통과 | 거래 코드 없음 |
| Git 공백 검사 | 통과 | 런타임 증거 아님 |
| GitHub Actions | [PR #13 검사 통과](https://github.com/krdn/gon-stock/actions/runs/43014029706) | 준비 코드 첫 SHA의 검사이며 후속 변경은 재검사 |
| pane 제어 | Orca runtime metadata 없음 | 현재 탭 pane을 생성·제어했다고 주장하지 않음 |

## 원격 Fable 5.2 차단 이력

사용자 재인증 답변 이후에도 요청은 HTTP 503, `auth_unavailable`과 refresh 오류로 거부됐다.
저장된 인증 갱신 정보는 새 인증 반영을 입증하지 못했다. 인증값은 출력하거나 공개하지 않았다.
리뷰 입력 SHA-256: `b15de28d8cddba1d332b3d2c7670311721679adbfe8b1a05af3b40f00f2fd77b`.
이 원격 요청에서는 리뷰 응답이 없었고 다른 모델로 대체하지 않았다.
후속 사용자 지시에 따라 로컬 Claude CLI로 실행해 실제 Fable 5.2 응답을 받았다.
[로컬 리뷰와 지적 처리](fable-review.md)를 별도로 기록한다. 리뷰 지적 검증 전 P0를 수용하거나 종속 P1을 시작하지 않는다.

## 다음 행동

로컬 Fable 리뷰 지적 수정 검증 → 최종 SHA 검사 → 문서/준비 PR 통합 → P0 수용 판단.
기존 PR #3과 #12는 별도 branch다. 준비 PR과 통합할 때 최신 main 기준으로 충돌·링크·STATE를 확인한다.

키움 공식 소프트웨어의 재배포·수정 제한을 확인했다. 공개 코드에 원본을 복사하지 않는 방향을 [조사 기록](../../research/evidence.md)에 반영했다.
