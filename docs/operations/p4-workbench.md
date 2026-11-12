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

2026-11-12 사용자가 등록한 `buzz-gon` 인증 경로를 확인했다. Herdr 터미널에서 이 CLI를 사용하며
Orca 제어는 필요하지 않다. 래퍼가 OS 키 저장소에서 인증을 전달하므로 앱은 비밀값을 읽지 않는다.
실행 중인 다른 에이전트의 키를 추출하거나 관리 JSON을 수정하지 않는다.
다음 세 채널은 이미 생성했으므로 먼저 조회하고 재사용한다.

```sh
buzz-gon channels create --name gon-stock-research --type stream --visibility private
buzz-gon channels create --name gon-stock-signals --type stream --visibility private
buzz-gon channels create --name gon-stock-ops --type stream --visibility private
```

먼저 같은 이름의 기존 채널을 조회하고 재사용 가능 여부를 확인한다. 생성 응답의 UUID를 비공개 설정에 저장한다.
전용 신원은 사용자가 추가한 `buzz-gon agents create --name <이름> --channel <UUID>
--system-prompt-file <파일>`로 생성하고 `agents inspect --name <이름>`으로 재조회한다.
이 경로는 Orca·Desktop 없이 소유자 서명·프로필·가입을 검증한다. 공식 `draft-create`와 별개다.
현재 이름은 `gon-stock-strategy`, `gon-stock-counter`이며 신원·지침은
`~/.local/share/buzz-gon/agents/`에, 키는 OS Secret Service에 있다. 기존 에이전트는 수정하지 않는다.

`buzz-acp`와 `gon_stock.acp_reply`가 전용 신원으로 응답한다. 소유자 멘션만 받으며
고정 연구 채널·소유자 작성 root·15분 이내 요청을 확인한다. 스레드당 역할별 한 번만 게시하고
부분 전송 실패도 재시도하지 않는다. 모델의 ACP 도구·권한 요청을 거부하며 Buzz 인증값은
하위 모델 프로세스에 넘기지 않는다. 최종 텍스트만 전송하고 원격 본문·작성자·스레드를 재조회한다.

[사용자 임시 승인](https://github.com/krdn/gon-stock/issues/4#issuecomment-6813761223)에 따라
전략은 `codex-acp`의 Astra high, 반론은 Fable 한도 해제 전 `agy acp`의 Argon high다.
ACP 모델 선택 성공은 서버 내부 모델의 독립 증명이 아니다. 기존 프록시 Argon 불일치는 미해결이다.
로컬 웹 작업대의 Astra→Fable 프록시 경로와 이 Buzz 런타임은 별개다.

현재 로컬 실행기는 `.private/p4/run-buzz-native.py`이며 인수는 `strategy` 또는 `counter`다.
검증용 사용자 서비스는 `gon-stock-p4-strategy`, `gon-stock-p4-counter`다.
15분 미사용 또는 서비스 시작 후 30분에 종료하며 자동 재시작하지 않는다.
중단은 `systemctl --user stop gon-stock-p4-strategy gon-stock-p4-counter`로 한다.
재개 시 신원/채널 검사와 새 요청 왕복을 다시 확인한다. P3 수집 서비스와 독립적이다.

비공개 `.private/p4/buzz.json`에는 `relay`(HTTPS URL), `sender_pubkey`(전송 주체의 64자리 공개키),
`allowed_members`(공통 공개키 배열 또는 역할별 배열 객체), `channels`(`research`, `signals`, `ops`의 UUID 매핑)를 둔다.
현재 설정에는 `"cli": "buzz-gon"`을 추가한다. 이 경로의 relay는 `https://buzz.krdn.kr`만 허용한다.
기존 `buzz` 경로는 `cli` 생략 시 유지되며 인증된 실행 환경이 필요하다.
키·인증 태그는 파일이나 명령 인수로 넣지 않는다.

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

전용 두 신원의 실제 같은 스레드 응답과 운영자가 요약한 관망 카드·알림을 재조회했다.
이 검증은 Buzz 응답을 웹 카드로 자동 가져오는 기능이나 상시 운용·전략 성과 검증을 뜻하지 않는다.
