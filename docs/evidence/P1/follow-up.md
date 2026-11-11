# P1 시각·연속조회·프록시 후속 검증

2026-11-11. KIS 연결은 [초기 구현](kis-readonly.md) 이후 전체 인증 재등록으로 해결됐다.
모의 서버에서 국내·미국 현재가·호가·잔고 6종의 실제 성공 응답을 확인했다.
미국 잔고 범위는 NASDAQ이며 두 잔고 모두 1페이지·추가 페이지 없음이다. 주문 호출은 0이다.
미국 호가 공식 명세의 모의 TR 표시는 “모의투자 미지원”이다. 모의 서버의 실제 성공 응답과 공식 지원 여부를 구분한다.
미국 현재가와 잔고의 모의 TR은 공식 명세에 존재한다. 미국 호가 모의 응답의 지속 제공을 보장하거나 P5 체결 검증 근거로 사용하지 않는다.

## 시각과 신선도

[국내 호가 공식 명세](https://apiportal.koreainvestment.com/apiservice-apiservice?/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn)의 `aspr_acpt_hour`는 시각만 제공한다.
[미국 호가 공식 명세](https://apiportal.koreainvestment.com/apiservice-apiservice?/uapi/overseas-price/v1/quotations/inquire-asking-price)의 `dymd`·`dhms`는 날짜·시각이며, 확인한 필드 설명에는 시간대가 명시되지 않았다.
2026-11-11 실제 응답에서 해당 시각 필드를 읽었다. 현재가 응답에는 대응하는 체결 시각 필드가 없었다.

CLI는 `clock.status`를 `missing`, `time_only`, `timezone_unverified`, `invalid`로 구분한다.
입력 형식과 날짜·시간 유효성을 검사하며 검증되지 않은 원문을 그대로 출력하지 않는다.
수신일자를 호가 일자로 붙이거나 수신 시각을 시장 이벤트 시각으로 바꾸지 않는다.
현재 `event_time=null`, `freshness=unverified`를 유지한다. 시각 필드 확인은 신선도 통과가 아니다.

## 연속조회

국내 잔고의 기존 연속조회 검사에 미국 FK200/NK200 전달, 종료, 반복키, 빈 키, 100페이지 상한 검사를 추가했다.
다중 페이지는 합성 HTTP 응답으로 검증했다. 실제 계좌는 1페이지이므로 실제 다중 페이지 성공은 미검증이다.
이를 만들기 위해 포지션이나 주문을 생성하지 않았다.

## 프록시

OS 인증 저장소에 프록시 키를 등록하고 인증된 모델 목록을 확인했다.
고정된 연결 확인 문장으로 실제 생성 요청을 수행했다. 계좌·시세 원문은 전송하지 않았다.

| 요청 | 반환 | 결과 |
| --- | --- | --- |
| gpt-6-astra | gpt-6-astra | 일치, 약 2.43초, total_tokens 312 |
| gemini-4-argon-high | gemini-4-argon-trial | 불일치, 약 7.15초, total_tokens 41 |
| claude-fable-5-2 | 미확인 | provider_unavailable (HTTP 502/503/504 구분 안 됨) |

반환 ID는 프록시 자기 보고다. 모델 대체·설정 변경을 하지 않았으며 Argon 불일치를 PASS로 계산하지 않는다.
프록시 Fable 실패와 개발 리뷰용 로컬 Claude CLI는 다른 경로다.

## 검사와 남은 조건

로컬 테스트 67개·Ruff·빌드·문서 검사 통과. 로컬 Fable 5.2 리뷰 PASS이며 반환 `canonicalModel=claude-fable-5-2`, `provider=firstParty`를 확인했다.
비차단 지적에 따라 FK200 전달 단언을 추가하고 출력 범위와 HTTP 오류 분류 문구를 수정했다. 최종 수정은 로컬 검사로 확인했고 외부 리뷰를 반복하지 않았다.
최종 SHA CI는 연결 PR에서 기록한다.
P1 전체는 진행 중이다. 확정된 이벤트 시각과 신선도 기준, Argon 라우팅 불일치, 프록시 Fable 가용성 확인이 남았다.
실제 다중 페이지 조회는 데이터가 생길 때 검증한다. P2~P5를 완료로 승격하지 않는다.

원격 프록시의 Claude 인증 만료 메타데이터를 읽기 전용으로 확인했다. 사용자 원격 재인증 완료 후 다시 요청했다. completion HTTP 400과 Claude Code 클라이언트 버전 호환 오류가 관측됐다. 로컬 Claude CLI는 2.1.322이며 개발 리뷰가 정상 동작한다. 공유 프록시의 버전·헤더를 임의로 변경하지 않았다.
Argon 응답의 trial 표기는 곧 모델 성능 저하를 뜻하지 않는다. 사용 중인 프록시 커밋의 [응답 변환 코드](https://github.com/router-for-me/CLIProxyAPI/blob/bf93416/internal/translator/antigravity/openai/chat-completions/antigravity_openai_response.go)는 upstream `response.modelVersion`을 응답 model에 넣는다. 요청 ID와의 동등성은 별도 확인이 필요하며 자동 수용하지 않는다.
