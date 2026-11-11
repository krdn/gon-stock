# 프록시 업데이트 후 P1 검증

2026-11-12 KST. 프록시 업데이트 후 Fable 연결 차단은 해결됐다. P1 전체 수용은 보류한다.
프록시·기존 6종 재검증의 기준 코드는 main `faa0d492cf89c85f431770de4d76b4c853cbcd13`이다.
국내 분봉은 이 SHA에 본 PR의 미커밋 구현을 적용한 상태에서 실조회했다.

## 실제 연결 결과

`gon-stock-llm probe --model <ID>`로 모델마다 고정된 짧은 문장을 전송했다.
서버 바이너리의 버전 배너는 `v8.0.67`, commit `8bba7a7`이다.
`-version` 옵션은 지원하지 않아 종료코드 2였으며, 버전은 배너에서 확인했다.

| 요청 | 반환 | 판정 | 지연 | total_tokens |
| --- | --- | --- | --- | --- |
| claude-fable-5-2 | claude-fable-5-2 | PASS | 2.73초 | 145 |
| gpt-6-astra | gpt-6-astra | PASS | 1.65초 | 16 |
| gemini-4-argon-high | gemini-4-argon-trial | FAIL: ID 불일치 | 5.25초 | 41 |

PASS는 생성 응답과 반환 ID 일치 범위다. 프록시 자기 보고를 백엔드 신원 증명으로 해석하지 않는다.
Argon 생성은 성공했으나 동등성은 미확정이다. trial을 성능 저하나 구독 종류로 해석하지 않는다.
동일 서버 커밋의 [변환 코드](https://github.com/router-for-me/CLIProxyAPI/blob/8bba7a77c6bcbfd993516d26606bfecaa4ff49d0/internal/translator/antigravity/openai/chat-completions/antigravity_openai_response.go)는 upstream `response.modelVersion`을 읽는다.
[모델 목록](https://github.com/router-for-me/CLIProxyAPI/blob/8bba7a77c6bcbfd993516d26606bfecaa4ff49d0/internal/registry/models/models.json)은 high를 등록하지만 trial과의 동등성을 명시하지 않는다.
공유 프록시나 모델 매핑은 변경하지 않았다.

## KIS 시각과 지원 범위

00:15 KST 모의 probe의 현재가·호가·잔고 6종 모두 성공했다. 잔고는 각각 1페이지이며 미국은 NASDAQ 범위다.
미국 호가 날짜·시각은 수신 시각의 KST와 가까웠으나, 관측 일치만으로 시간대를 확정하지 않았다.

공식 포털의 API 상세와 응답 필드 명세를 다시 확인했다.

| API | 모의 TR | 날짜·시각 |
| --- | --- | --- |
| [국내 당일분봉](https://apiportal.koreainvestment.com/apiservice-apiservice?/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice) | FHKST03010200 | stck_bsop_date·stck_cntg_hour |
| [미국 REST 호가](https://apiportal.koreainvestment.com/apiservice-apiservice?/uapi/overseas-price/v1/quotations/inquire-asking-price) | 모의투자 미지원 | dymd·dhms, 시간대 미명시 |
| [미국 WebSocket 호가](https://apiportal.koreainvestment.com/apiservice-apiservice?/tryitout/HDFSASP0) | 모의투자 미지원 | 별도 실시간 응답 계약 |
| [미국 분봉](https://apiportal.koreainvestment.com/apiservice-apiservice?/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice) | 모의투자 미지원 | kymd·khms: 한국기준일자·시간 |

국내 `kr_bars`를 추가했다. 00:17:59 KST 실조회에서 `2026-11-11 15:59:00`을 읽었다.
받은 분봉 중 가장 늦은 시각이며 정규장 최종 체결·최신 호가를 증명하지 않는다.
공식 명세는 미래 시각 요청 시 현재가로 구간을 채운다고 명시한다. 반환 시각이 요청 상한과 같아 실제 체결 발생을 증명하지 않는다.
채움 조항이 이번 장 마감 후 응답의 직접 원인이라는 뜻은 아니다. 확인된 것은 날짜·시각 필드의 형식이다. 장중 실관측은 NOT_RUN이며 P1 잔여 조건이다.
날짜·시각을 `dated_bar`로 구분하며 빈 목록·잘못된 필드를 검사하고 배열 순서에 의존하지 않는다.
`event_time=null`, `freshness=unverified`를 유지한다. 분봉 날짜를 기존 호가에 결합하지 않는다.

## 다음 조건

미국 모의 호가의 성공 응답은 공식 지원을 대신하지 못한다. 선택한 경로는 **실전 API의 시세 GET만 사용하고 주문은 계속 모의·shadow로 제한**하는 것이다.
미국 분봉은 00:24 KST 별도 진단 GET에서 1행을 받았다. 한국기준 `2026-11-12T00:24:00+09:00`과 현지기준 `2026-11-11T10:24:00-05:00`이 같은 순간임을 확인했다.
정식 CLI 기능이 아닌 고정 경로 진단이며, 분봉 시각을 호가 시간대로 전용하지 않는다. 신선도는 미검증이다.
“미국 데이터 검증을 위해 실전 API의 시세 조회(GET)만 허용할까요?”라는 질문에 사용자가 “모두 적용해야함”으로 답했다.
질문은 실전 잔고·주문·유료 계약을 제외했다. [질문·답변과 범위 전사](https://github.com/krdn/gon-stock/issues/4#issuecomment-6799783406)를 기준으로 실전 시세 GET을 적용했다. 별도 실전 자격 증명을 OS 인증 저장소에 등록했다.
00:23 KST AAPL/NAS 현재가·호가 GET 실조회는 모두 성공했다. 미국 호가 시간대는 계속 `timezone_unverified`다.
실전 계좌 잔고·주문 호출은 실행안에 포함하지 않는다. 유료 시세 계약도 포함하지 않는다.
모의 전용 경로는 공식 지원 근거가 없어 채택하지 않았다.

Argon은 ID 동등성 근거가 확보될 때까지 실패 상태를 유지한다. 확인 없이 별칭을 허용하지 않는다.
신선도 임계값은 데이터 종류·거래시간을 포함한 계약과 관측이 필요하다. 현재 자료를 최신 시세로 사용하지 않는다.
P2~P5 승격, 실전 잔고 조회, 주문 호출은 수행하지 않았다.

## 검사와 리뷰

74개 테스트·프로젝트 기준 Ruff·패키지 빌드·문서 링크 검사 통과.
초기 실패는 신규 분봉 경로와 시각 파싱 미구현으로 3건이며 구현 후 통과했다.
로컬 Claude CLI에 `claude-fable-5-2`, effort `high`를 요청했다. 두 응답의 canonicalModel과 provider는 각각 `claude-fable-5-2`, `firstParty`다.
최초 CHANGES_REQUESTED의 시각 단정과 SHA·순서·경계 테스트 지적을 수정했다.
후속 리뷰는 이전 지적 해소를 확인했지만 승인 기록·STATE 불일치로 CHANGES_REQUESTED였다.
진행 중 추가된 승인 전사 링크와 실제 조회 결과를 문서·STATE에 맞추고 장중 NOT_RUN을 명시해 이 지적을 처리했다.
마지막 문서 수정은 직접 링크·내용 검사로 확인했으며 외부 PASS를 받았다고 기록하지 않는다.
최종 SHA와 CI는 연결 PR에 남긴다. `evolve docs ste-lint`는 기준 문서 부재로 실행 불가다.
범위를 넓힌 `ruff check .`는 기존 scripts/check_docs.py의 import 순서로 실패했으며 프로젝트 CI 기준인 `ruff check src tests`는 통과했다.
