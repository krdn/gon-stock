# P4 로컬 구현 검증

2026-11-12. [병행 승인·범위](../../plans/p4-decision-flow.md) · [실행](../../operations/p4-workbench.md).
P4 전체 수용은 아직 아니다. 전용 Buzz 에이전트와 실제 채널 연결 증거가 남아 있다.

- PASS: 195 tests·Ruff·format·build. 기존 달력 의존성 Pandas 경고 28개.
- 결정 흐름: 출처·시각 검증, Astra 제안→Fable 반론, 최대 두 번 보완, 모델 불일치/형식 오류 실패,
  요청 중복 방지, 처리 중 일시중단 시 다음 모델 호출 차단, 실패 기록 보존 검사.
- 카드: 연구·관망·주문 불가, 확률/기대손익/매매 가격 null, 자료 기준시각과 유효기한 표시.
- 실제 프록시 연결 검사: 합성 문장만 입력했다. gpt-6-astra 요청/반환 일치(18.12초, 1,178 tokens),
  claude-fable-5-2 요청/반환 일치(16.71초, 5,318 tokens). 카드 저장과 자료 부족 표시 확인.
  이는 프록시 자기 보고와 연결/형식 검증이며 실제 전략·출처 정확성 검증이 아니다.
- 브라우저: 관심 종목 등록·삭제, 연구 일시중단·재개, 실제 카드 표시, reload 후 저장 유지 확인.
  390px 화면에서 가로 넘침 없음. 대비 문제 수정 후 desktop/mobile axe 검사 위반 0건.
- Buzz 전달기: subprocess 경계 합성 검사로 private 채널/구성원, accepted 후 원격 재조회,
  부분 전송 실패 기록·재시도 금지, 만료 카드 미전송 확인. 실제 전송은 NOT_RUN.
- 연결 차단: 현재 셸에 BUZZ_PRIVATE_KEY가 없고 Orca 자동 실행은 runtime_open_timeout.
  실행 중인 다른 에이전트 키 추출이나 managed JSON 직접 수정은 수행하지 않았다.
- 독립 Fable 5.2 high 코드 리뷰: BLOCKED. 로컬 Claude CLI가 HTTP 429
  usage_limit_reached를 반환했고 해제 안내는 2026-11-12 13:10 KST였다.
  모델 응답·판정은 없으며 PASS가 아니다. Draft PR·CI까지만 진행하고 리뷰 전 병합하지 않는다.

P3 수집은 별도 고정 worktree에서 계속 실행한다. P3 성과 수용과 P5 통합 운용은 보류한다.
