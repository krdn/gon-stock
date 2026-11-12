# P3 구현 검증

2026-11-12. 실제 성과 수용과 구분하는 엔진·수집기 검증 기록이다.
[계약](../../plans/p3-evaluation.md) · [실행](../../operations/p3-research.md) · [이슈 #7](https://github.com/krdn/gon-stock/issues/7).

- PASS: 전체 175 tests, Ruff, format, build, 문서 링크·코드블록, diff 공백 검사.
- 기존 달력 의존성에서 Pandas 경고 28개가 남았으며 테스트 실패는 아니다.
- 합성 검증: 다음 분 진입, 손절/목표 동시 접촉의 손절 우선, 갭, 청산가 기준 비용,
  누락 거래 미해결 처리, 미래 수신 자료 배제, 시간순 분리·embargo, Wilson 기준값,
  결정적 bootstrap, 보정/test 분리, 비공개 출력, holdout 재사용 차단.
- 수집 합성 검증: 완료 분 이후 예약, 장 종료 후 중지, 응답 순서와 무관한 최신 2행,
  실제 수신시각 보존, GET 오류 전파, 절전 후 늦은 요청 건너뛰기.
- Fable 본체 리뷰: `claude-fable-5-2` high 요청, `canonicalModel=claude-fable-5-2`,
  `provider=firstParty`, `is_error=false`. CHANGES_REQUESTED 두 건을 재현했다.
  test 거래가 없는 그룹의 확률 출력과 절전 복귀 후 장외 조회를 각각 수정해 RED→GREEN을 확인했다.
- 본체 응답에 내부 advisor 사용 고지가 있었다. 수정분 호출에는 다른 모델·advisor 사용 금지를 명시했다.
- 수정분 Fable 리뷰: PASS. 같은 요청/반환 모델과 firstParty, is_error=false를 확인했다.
  응답은 Fable 단독 검토를 명시했고 B1·B2 및 KIS 토큰 갱신·NREC 소비 경로를 확인했다.
- 절전 동안 monotonic 토큰 만료 시계가 멈추는 가용성 한계는 수집 프로세스의 sleep inhibitor로 대응한다.
  systemd-inhibit 사전 실행 PASS. 중단 시 inhibitor도 해제하며 강제 절전·재부팅 후 재시작해야 한다.
- 리뷰 파일별 SHA-256과 최종 소스 일치를 확인했다. CI·병합·실제 수집은 후속 기록으로 남긴다.

실제 자료·비용·봉 라벨·정정/기업행동·거래소 공지·coverage 증거 부족으로 P3 성과 수용은 BLOCKED다.
수동 manifest 플래그나 합성 후보 통과를 실제 근거로 보지 않는다. P4 진입·실주문은 실행하지 않았다.
