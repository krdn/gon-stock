# LLM 프록시 연결 확인

프록시 주소는 Git에서 제외된 `.private/operator-settings.json`의 `llm_proxy_base_url`에 둔다.
키는 OS Secret Service의 `service=gon-stock-llm-proxy` 항목에 저장한다. 설정 파일에 키를 넣지 않는다.
이 개발 호스트에서는 다음 숨김 입력 도구로 등록한다.

```sh
~/.claude/bin/secret-prompt 'gon-stock LLM 프록시 API 키 등록' \
  secret-tool store --label='gon-stock LLM proxy' service gon-stock-llm-proxy
uv run gon-stock-llm models
uv run gon-stock-llm probe --model gpt-6-astra
```

`--model`에는 목록에서 확인한 ID를 지정한다. CLI는 고정된 짧은 연결 확인 문장만 전송한다.
계좌·시세·뉴스·전략 데이터는 전송하지 않으며 도구 호출도 제공하지 않는다.
키·프록시 주소·응답 원문은 출력하지 않는다. 요청/반환 모델, 일치 여부, 지연과 제공된 토큰 수만 출력한다.
모델 불일치나 호출 실패는 종료코드 1이다. 별칭을 자동 수용하거나 다른 모델로 대체하지 않는다.
모델 목록에 있다고 실제 생성 요청까지 성공한다고 가정하지 않는다.
반환 모델은 프록시 응답의 자기 보고이며 실제 백엔드 모델 신원을 독립 증명하지 않는다.

리다이렉트·자동 재시도·환경 프록시를 사용하지 않는다. 외부 주소는 HTTPS를 요구한다.
HTTP는 명시적으로 설정한 사설·루프백 IP만 허용하며 전송 암호화를 제공하지 않는다.
현재 통신 설정은 사용자 지정 기존 프록시를 따른다. 키는 공개 CI에 제공하지 않는다.
