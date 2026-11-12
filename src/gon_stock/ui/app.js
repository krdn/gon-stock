'use strict';
const $ = (id) => document.getElementById(id);
let state = {paused: false, watchlist: [], runs: []};
let submitting = false;
const marketNames = {XKRX: '한국 · KRX', XNAS: '미국 · NASDAQ', XNYS: '미국 · NYSE', XASE: '미국 · AMEX'};
function node(tag, className, text) {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (text !== undefined) result.textContent = text;
  return result;
}
function stamp(value) {
  return new Date(value).toLocaleString('ko-KR', {timeZone: 'Asia/Seoul', hour12: false}) + ' KST';
}
function notice(text, error = false) {
  $('notice').textContent = text;
  $('notice').className = error ? 'notice error' : 'notice';
}
async function request(path, body) {
  const options = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'request_failed');
  return value;
}
function showError(error) {
  const messages = {discussion_busy: '다른 연구 요청을 처리 중입니다.', model_mismatch: '요청과 반환 모델이 달라 중단했습니다.',
    settings_unavailable: '프록시 설정을 확인할 수 없습니다.', credentials_missing: '프록시 인증 연결이 필요합니다.',
    timeout: '모델 응답 시간이 초과됐습니다.', provider_unavailable: '모델 제공자가 응답하지 않습니다.',
    invalid_or_unavailable_request: '입력 시각·출처·중복 여부와 연구 중단 상태를 확인해 주세요.'};
  notice(messages[error.message] || '요청을 완료하지 못했습니다. 저장된 실패 상태를 확인해 주세요.', true);
}
function render() {
  $('run-status').textContent = state.paused ? '일시중단' : '요청 가능';
  $('pause').textContent = state.paused ? '연구 요청 재개' : '연구 요청 일시중단';
  $('submit-request').disabled = state.paused || submitting || !state.watchlist.length;
  $('submit-request').textContent = submitting ? '제안과 반론 검토 중…' : '제안과 반론 검토';
  $('watch-count').textContent = state.watchlist.length;
  const selected = $('target').value;
  $('target').replaceChildren();
  $('watchlist').replaceChildren();
  if (!state.watchlist.length) {
    $('target').append(node('option', '', '관심 종목을 먼저 등록해 주세요'));
    $('watchlist').append(node('li', 'empty', '등록된 종목이 없습니다.'));
  }
  state.watchlist.forEach((target) => {
    const option = node('option', '', target.symbol + ' · ' + marketNames[target.exchange]);
    option.value = JSON.stringify(target);
    $('target').append(option);
    const item = node('li');
    const title = node('div');
    title.append(node('strong', '', target.symbol), node('small', '', marketNames[target.exchange]));
    const remove = node('button', '', '삭제');
    remove.type = 'button';
    remove.setAttribute('aria-label', target.symbol + ' 관심 목록 삭제');
    remove.addEventListener('click', async () => {
      try {await request('/api/unwatch', target); await refresh(); notice('관심 목록에서 삭제했습니다.');} catch (error) {showError(error);}
    });
    item.append(title, remove);
    $('watchlist').append(item);
  });
  if (Array.from($('target').options).some((option) => option.value === selected)) $('target').value = selected;
  $('cards').replaceChildren();
  if (!state.runs.length) $('cards').append(node('div', 'empty-state', '아직 결정 카드가 없습니다. 출처를 담은 연구 요청으로 시작해 보세요.'));
  state.runs.forEach((run) => {
    const card = run.card;
    const item = node('article', 'card' + (run.status === 'failed' ? ' failure' : ''));
    if (!card) {
      item.append(node('h3', '', run.status === 'running' ? '검토 중' : '검토 실패'), node('p', '', run.request_id));
      item.append(node('p', 'muted', run.status === 'running' ? '응답과 출처를 검사하고 있습니다. 재시작 뒤 남은 처리 중 요청은 자동 재실행하지 않습니다.' : '카드를 생성하지 않았습니다. 실패 코드: ' + run.error_code));
      $('cards').append(item);
      return;
    }
    const expired = new Date(card.expires_at).getTime() <= Date.now();
    const header = node('div', 'card-top');
    header.append(node('h3', '', card.instrument.symbol), node('span', 'badge', '관망 · 연구 전용'), node('span', 'badge' + (expired ? ' expired' : ''), expired ? '유효기간 만료' : '성과 검증 대기'));
    item.append(header, node('p', 'card-time', '자료 기준 ' + stamp(card.as_of) + ' / 만료 ' + stamp(card.expires_at)));
    item.append(node('p', 'muted', 'LLM 검토 의견 · 사실 확인 완료를 의미하지 않음'), node('p', 'card-summary', card.summary));
    const metrics = node('div', 'card-metrics');
    ['확률: 검증 대기', '기대손익: 검증 대기', '진입·손절·목표: 미제공', '주문: 불가'].forEach((text) => metrics.append(node('span', '', text)));
    item.append(metrics);
    const details = node('details');
    details.append(node('summary', '', '제안·반론 기록 (' + card.rounds.length + '회) · ' + (card.discussion_status === 'reviewed' ? '연구 논리 검토됨' : '반론·자료 부족 남음')));
    card.rounds.forEach((round) => {
      const block = node('div', 'round');
      block.append(node('strong', '', (round.role === 'proposal' ? '제안' : '독립 반론') + ' · ' + round.returned_model));
      block.append(node('small', '', '요청/반환 모델 일치 · ' + round.elapsed_seconds.toFixed(2) + '초 · 토큰 ' + (round.total_tokens ?? '미제공')));
      block.append(node('p', '', round.answer.summary));
      block.append(node('p', 'muted', '위험: ' + (round.answer.risks.join(' / ') || '미기재')));
      block.append(node('p', 'muted', '무효화: ' + (round.answer.invalidation.join(' / ') || '미기재')));
      details.append(block);
    });
    item.append(details);
    const sources = node('ul', 'sources');
    card.sources.forEach((source) => {
      const row = node('li');
      try {
        const url = new URL(source.url);
        if (url.protocol !== 'https:') return;
        const link = node('a', '', source.id + ' · ' + url.hostname);
        link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
        row.append(link, node('span', '', ' / 발표 ' + stamp(source.published_at) + ' · 사용자 제공 원문'));
        sources.append(row);
      } catch (_) {row.textContent = '잘못된 출처 URL'; sources.append(row);}
    });
    item.append(sources, node('small', '', '요청 ' + run.request_id));
    $('cards').append(item);
  });
  $('updated').textContent = '상태 확인 ' + stamp(state.server_time);
}
async function refresh() {state = await request('/api/state'); render();}
$('watch-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const exchange = $('watch-exchange').value;
  try {
    await request('/api/watch', {exchange, symbol: $('watch-symbol').value.trim().toUpperCase(), currency: exchange === 'XKRX' ? 'KRW' : 'USD'});
    $('watch-symbol').value = ''; await refresh(); notice('관심 목록에 저장했습니다.');
  } catch (error) {showError(error);}
});
$('pause').addEventListener('click', async () => {
  try {await request('/api/pause', {paused: !state.paused}); await refresh(); notice(state.paused ? '다음 모델 호출부터 중단합니다. 데이터 수집 서비스는 유지됩니다.' : '연구 요청을 재개했습니다.');} catch (error) {showError(error);}
});
$('request-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (submitting || state.paused || !state.watchlist.length) return;
  const now = new Date();
  submitting = true; render(); notice('제안과 반론을 검토하고 있습니다. 최대 두 번 보완합니다.');
  try {
    await request('/api/discuss', {request_id: crypto.randomUUID(), instrument: JSON.parse($('target').value), as_of: now.toISOString(),
      expires_at: new Date(now.getTime() + 600000).toISOString(), question: $('question').value,
      sources: [{id: 'source_1', url: $('source-url').value, published_at: new Date($('published').value).toISOString(), observed_at: now.toISOString(), excerpt: $('excerpt').value}]});
    notice('연구 카드를 저장했습니다. 성과 검증과 주문 승인을 의미하지 않습니다.');
  } catch (error) {showError(error);} finally {submitting = false; await refresh().catch(showError);}
});
refresh().catch(showError);
setInterval(() => refresh().catch(showError), 5000);
