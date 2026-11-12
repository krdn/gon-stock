# P4 최소 기술 검증 수용

2026-11-12. Agent 위임 수용이며 사용자 직접 수용이나 전략 성과 승인이 아니다.
[execution-v1 B 승인](https://github.com/krdn/gon-stock/issues/4#issuecomment-6794757846),
[P4 병행 승인](https://github.com/krdn/gon-stock/issues/4#issuecomment-6812438087),
[Argon 임시 사용 지시](https://github.com/krdn/gon-stock/issues/4#issuecomment-6813761223)를 적용했다.

- 구현 [PR #23](https://github.com/krdn/gon-stock/pull/23), 병합 SHA `b8e8ca810dfbe37d549e20e774b08f83f83a9e0c`.
- [PR CI](https://github.com/krdn/gon-stock/actions/runs/43150618636)·[main CI](https://github.com/krdn/gon-stock/actions/runs/43150732984) PASS.
- 208 tests·Ruff·format·build·문서 검사 PASS. Argon 최초 지적 4건 재현/수정 후 수정분 리뷰 PASS.
  리뷰된 소스·테스트와 병합 main의 SHA-256 일치. agy 서버 반환 모델 ID는 미제공이다.
- 로컬 작업대: 관심 목록·출처/시각 검사·제안/반론·관망 카드·중단·실패 저장, 실제 프록시 합성 입력과 화면 검증 PASS.
- Buzz: 세 private 채널, 전용 전략/반론 신원·소유자 서명·가입, 같은 스레드의 실제 Astra/Argon 응답 재조회 PASS.
  운영자가 확인한 두 응답의 관망 카드와 signals/ops 알림도 재조회했다. 검증 자료는 합성이며 시장 근거가 아니다.
- 로컬 실행: 병합 SHA를 고정한 별도 worktree에서 `gon-stock-p4-workbench` 서비스 실행.
  루프백 `http://127.0.0.1:8765` 실제 화면·상태·비공개 파일 경로 거부, 재시작 후 중단 상태 유지 확인.
  웹의 기존 Fable 프록시 호출은 한도 해제 전까지 일시중단했다. Buzz 반론 검증은 Argon 경로다.

수용 범위는 연구 전용 구현과 제한된 실제 요청·응답이다. 주문·계좌 접근·확률·수익성·상시 운용 수용은 아니다.
Buzz 응답을 웹 카드로 자동 가져오지 않으며, 이번 네이티브 검증용 최종 카드는 운영자 요약이다.
네이티브 검증 서비스는 15분 미사용/30분 실행 한도로 종료한다. 재실행 시 새 요청 왕복을 확인한다.
Fable 한도 해제는 안내 시각만으로 확정하지 않고 실제 호출로 확인한 뒤 임시 경로를 되돌린다.

P3 실제 성과 수용은 미래 자료·품질·표본 근거 대기이며 P5 진입은 계속 보류한다.
[상세 검사](implementation.md) · [실행과 중단](../../operations/p4-workbench.md).

## Fable 복귀 — 2026-11-12 14:00 KST

- 로컬 CLI: `claude-fable-5-2` high 요청, READY·canonicalModel 일치·firstParty 확인. 한도 해제 예정 시각이 아닌 실제 응답으로 판단했다.
- 웹: 프록시 요청·반환 ID 일치, 새 합성 요청의 Astra→Fable 두 응답·관망 카드 저장·브라우저 표시 PASS. 재시작 후 카드·재개 상태 보존 PASS.
- Buzz: 기존 Argon 검증 서비스 종료 확인. Fable 어댑터로 교체하고 새 스레드의 전략·반론 작성자/채널/본문/연결을 원격 재조회했다. 반론 delivery=verified, 세션 반환 모델 `claude-fable-5-2`, 도구 사용 0.
- 반론 세션 생성 시 도구/MCP 서버를 비우고 Fable 5.2 high를 고정한다. 위조된 세션 옵션을 대체하는 subprocess 경계 검사 포함 211 tests PASS. 프로젝트 Ruff·format·build PASS. 저장소 전체 Ruff에서는 기존 `scripts/check_docs.py` import 순서 지적이 남아 있으며 이 변경에서 수정하지 않았다.
- 검증 입력은 가상 종목·합성 출처다. 실제 연구 품질·성과·자동 Buzz→웹 카드 연동의 증거는 아니다. 검증 후 네이티브 두 서비스를 중단했다. 웹 작업대와 P3 수집은 유지한다. P3/P5 경계는 유지한다.

- Fable 최초 리뷰의 세션 재개 우회·전역 설정 유입 지적을 수정했다. 허용한 ACP 메서드만 전달하고 모델/effort 변경을 제한하며 `settingSources=[]`, `strictMcpConfig=true`를 적용한다. 전용 system prompt 문자열은 보존하고 counter 하위 프로세스의 `ANTHROPIC_*`·`CLAUDE_CODE_USE_*` 환경을 제거한다.
- 수정 후 새 Buzz 반론 답글·반환 모델·도구 사용 0을 재확인했다. 별도 동일 옵션 어댑터 프로브의 init `tools=[]`, `mcp_servers=[]` 확인. 내장 plugin 4개는 남아 있다. 어댑터 0.84.0, Claude CLI 2.1.322. 프로브 사용량에는 Fable 외 보조 Haiku 5.5가 함께 기록돼 전체 내부 호출의 Fable 전용성은 주장하지 않는다.

- Fable 5.2 high 수정분 리뷰 PASS, canonicalModel·firstParty 및 리뷰된 코드/테스트/비공개 실행기 해시 일치 확인. 문자열 외 system prompt 거부와 환경 필터의 별도 회귀 검사는 비차단 후속 항목이다.
