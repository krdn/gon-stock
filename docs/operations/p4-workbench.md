# 연구 작업대와 Buzz 전달

[병행 승인·범위](../plans/p4-decision-flow.md). 이 화면은 연구 전용이며 주문 경로가 없다.
P3 성과·확률은 검증 대기, 보유 상태는 미연결이다. Buzz 전용 에이전트 연결은 별도 검증한다.

## 실행과 사용

```sh
uv run gon-stock-workbench serve --port 8765
```

브라우저에서 `http://127.0.0.1:8765`를 연다. 관심 종목을 등록하고 질문·HTTPS 출처 URL·발표 시각·
원문 발췌를 입력한다. 브라우저는 현재 시각을 관측/기준시각으로 기록하며 유효기간은 10분이다.
시간대가 있는 CLI 입력은 다음과 같이 실행한다.

```sh
uv run gon-stock-workbench discuss --request .private/p4/request.json
uv run gon-stock-workbench export --request-id my_request \
  --output .private/p4/my_request.json
```

요청 JSON은 `request_id`(영문/숫자/하이픈/밑줄 1~64자), `instrument`(`exchange`, `symbol`, `currency`),
`as_of`, `expires_at`, `question`, `sources`만 가진다. sources는 1~8개이며 각 항목은
`id`, `url`, `published_at`, `observed_at`, `excerpt`다. 날짜는 시간대를 포함한 ISO 형식이다.
발표≤관측≤기준≤현재<만료 순서를 검사한다. 만료는 기준시각 이후 최대 15분이다.
예를 들어 과거 발표 자료를 지금 수집했다면 `published_at`은 발표시각, `observed_at`은 지금이다.

프록시 설정은 [기존 Secret Service 경로](llm-proxy.md)를 사용한다. 질문·발췌·이전 검토 의견만
프록시에 보내며 계좌·인증값은 입력하지 않는다. Astra와 Fable 5.2의 요청/반환 ID가 같아야 한다.
보완은 최대 두 번, 전체 모델 호출은 최대 여섯 번이다. 도구 호출은 제공하지 않는다.
‘일시중단’은 다음 모델 호출을 막는다. 이미 진행 중인 응답은 끝난 뒤 중단된다.
P3 데이터 수집 서비스는 이 버튼과 독립적이다.

관심 목록·요청·응답·카드는 `.private/p4/workbench.sqlite`에 저장한다. 수집 DB를 열거나 수정하지 않는다.
같은 요청 ID는 실패 후에도 자동 재시도하지 않는다. 프로세스 중단 시 `running`으로 남은 요청은
실제 결과를 확인한 뒤 새 요청으로 판단한다. 기록을 삭제해 중복 방지를 우회하지 않는다.
서버는 루프백에만 바인딩하고 외부 Origin의 변경 요청을 거부한다. 원격 공개용 인증 서버는 아니다.
터미널에서는 Ctrl-C로, 사용자 서비스에서는 `systemctl --user stop gon-stock-p4-workbench`로 중단한다.

## Buzz 연결 준비

현재 Codex 셸에는 Buzz 인증이 없다. 실행 중인 다른 에이전트의 키를 추출하거나 관리 JSON을 수정하지 않는다.
사용자가 승인한 Buzz 인증 런타임에서 다음 공식 CLI 경로를 사용한다.

```sh
buzz channels create --name gon-stock-research --type stream --visibility private
buzz channels create --name gon-stock-signals --type stream --visibility private
buzz channels create --name gon-stock-ops --type stream --visibility private
```

먼저 같은 이름의 기존 채널을 조회하고 재사용 가능 여부를 확인한다. 생성 응답의 UUID를 비공개 설정에 저장한다.
전용 에이전트는 `buzz agents draft-create --channel <UUID> --display-name <이름> --system-prompt -`로
소유자 Desktop의 생성 폼을 연다. 초안 생성은 실제 저장·모델 매핑·실행 증거가 아니다.
이름은 `GON-STOCK · 전략`, `GON-STOCK · 반론`으로 기존 에이전트와 구분한다.
전략은 Astra, 반론은 Fable 5.2를 요청하며 실제 반환 모델을 대조한다.
리서치 Argon의 ID 불일치는 아직 해결되지 않았다. 다른 모델을 Argon으로 등록하지 않는다.

비공개 `.private/p4/buzz.json`에는 `relay`(HTTPS URL), `sender_pubkey`(전송 주체의 64자리 공개키),
`allowed_members`(허용된 공개키 배열), `channels`(`research`, `signals`, `ops`의 UUID 매핑)를 둔다.
키·인증 태그는 파일이나 명령 인수로 넣지 않는다. Buzz가 제공하는 인증된 실행 환경을 그대로 사용한다.

```sh
uv run gon-stock-buzz preflight
uv run gon-stock-buzz publish --request-id my_request
```

preflight는 실제 전송 주체, 세 private 채널의 이름·멤버십·허용 구성원 집합을 확인한다.
publish는 이미 생성된 로컬 프록시 검토 기록을 research 스레드와 signals/ops에 전달한다.
**이 전달기는 Buzz 전용 에이전트 응답을 구현하거나 가장하지 않는다.** 기록의 첫 메시지에도 이를 명시한다.
LLM 문자열의 멘션 표기는 알림을 만들지 않도록 바꾼다. 가격 원문·출처 발췌 전체는 전송하지 않는다.
전송 후 event ID·작성자·본문·채널·스레드를 재조회해야 verified가 된다.
타임아웃·부분 전송·재조회 실패는 재시도하지 않고, 비공개 delivery 기록과 실제 채널을 대조한다.
카드가 만료됐거나 공개 채널·예상 밖 구성원이 있으면 전송하지 않는다.

P4 전체 수용에는 전용 에이전트 identity 등록과 실제 같은 스레드의 요청→반론→카드 증거가 추가로 필요하다.
로컬 모델 호출 성공과 전달 어댑터의 합성 검사는 이 조건을 대신하지 않는다.
