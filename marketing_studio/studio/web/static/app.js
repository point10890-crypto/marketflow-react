/* Marketing Studio SPA — 의존성 없음 (fetch + 템플릿 리터럴) */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = (n) => (Number(n) || 0).toLocaleString('ko-KR');
const won = (n) => (n === null || n === undefined || n === '' ? '-' : num(n) + '원');
const dt = (s) => (s ? String(s).replace('T', ' ').slice(0, 16) : '');
const STATUS_KO = { new: '신규', content_ready: '콘텐츠 준비', video_ready: '영상 완료', packaged: '패키지 완료', published: '발행됨' };
const JOB_KO = { naver_login: '네이버 로그인', crawl: '캠페인 수집', import_campaign: '캠페인 가져오기', import_url: 'URL 가져오기', probe: 'DOM 프로브', blog: '블로그 생성', script: '대본 생성', video: '영상 제작', package: '패키지 생성', pipeline: '전체 파이프라인' };
const CHANNELS = { naver_blog: '네이버 블로그', naver_clip: '네이버 클립', youtube: '유튜브 쇼츠', instagram: '인스타그램 릴스', other: '기타' };
const VOICES = ['ko-KR-SunHiNeural', 'ko-KR-InJoonNeural', 'ko-KR-HyunsuMultilingualNeural'];

const state = { view: 'dashboard', param: '', status: null, seenJobs: null, activeJobs: [] };

async function api(path, opts = {}) {
  const init = { method: opts.method || 'GET', headers: { 'Content-Type': 'application/json' } };
  if (opts.body !== undefined) init.body = JSON.stringify(opts.body);
  const res = await fetch(path, init);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
let toastTimer = null;
function toast(msg, kind = 'ok') {
  const el = $('#toast');
  el.textContent = msg;
  el.className = `toast ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), kind === 'err' ? 7000 : 3500);
}
function openModal(html) { $('#modalBody').innerHTML = html; $('#modal').classList.remove('hidden'); }
function closeModal() { $('#modal').classList.add('hidden'); $('#modalBody').innerHTML = ''; }
async function copyText(text, label = '복사됨') { try { await navigator.clipboard.writeText(text); toast(label); } catch { toast('클립보드 복사 실패 — 직접 선택해 복사하세요', 'err'); } }
const copyStore = new Map();
/* 텍스트를 onclick 속성에 인라인하지 않고 키로 참조 (따옴표/줄바꿈 안전) */
function copyBtn(text, label, cls = 'btn sm', title = '복사') {
  const key = `k${copyStore.size + 1}_${Math.random().toString(36).slice(2, 8)}`;
  copyStore.set(key, { text: String(text ?? ''), label });
  return `<button class="${cls}" type="button" data-action="copy" data-key="${key}">${esc(title)}</button>`;
}
async function runJob(path, body, label) {
  try { await api(path, { method: 'POST', body: body || {} }); toast(`${label} 작업을 시작했습니다`); pollJobs(); } catch (e) { toast(e.message, 'err'); }
}
function formData(form) { const o = {}; new FormData(form).forEach((v, k) => { o[k] = v; }); $$('input[type=checkbox]', form).forEach((c) => { o[c.name] = c.checked; }); return o; }

/* ------------------------------------------------------------------ routing */
function route() {
  const hash = location.hash.replace(/^#\/?/, '') || 'dashboard';
  const [view, ...rest] = hash.split('/');
  state.view = views[view] ? view : 'dashboard';
  state.param = rest.join('/');
  $$('#nav a').forEach((a) => a.classList.toggle('active', a.dataset.view === state.view));
  render();
}
async function render() {
  const el = $('#view');
  el.innerHTML = '<div class="muted">불러오는 중…</div>';
  try { el.innerHTML = await views[state.view](); bind(el); } catch (e) { el.innerHTML = `<div class="card">오류: ${esc(e.message)}</div>`; }
}
function bind(root) { $$('[data-action]', root).forEach((el) => { el.onclick = (ev) => { ev.preventDefault(); actions[el.dataset.action]?.(el.dataset, el); }; }); }

/* ------------------------------------------------------------------ jobs */
function jobLabel(j) { return JOB_KO[j.type] || j.type; }
function renderJobsBar(active) {
  $('#jobsBar').innerHTML = active.length ? active.map((j) => `
    <div class="job-chip"><b>${esc(jobLabel(j))}</b><div class="bar"><i style="width:${j.progress}%"></i></div><span class="msg" title="${esc(j.message)}">${esc(j.message)}</span>
    <button class="btn sm ghost" onclick="cancelJob('${j.id}')">취소</button></div>`).join('')
    : '<span class="muted small">진행 중인 작업 없음</span>';
}
async function cancelJob(id) { try { await api(`/api/jobs/${id}/cancel`, { method: 'POST' }); toast('취소 요청'); } catch (e) { toast(e.message, 'err'); } }
async function pollJobs() {
  try {
    const { jobs } = await api('/api/jobs?limit=10');
    const active = jobs.filter((j) => ['queued', 'running'].includes(j.status));
    state.activeJobs = active;
    renderJobsBar(active);
    if (state.seenJobs === null) { state.seenJobs = {}; jobs.forEach((j) => { state.seenJobs[j.id] = j.status; }); return; }
    let refresh = false;
    for (const j of jobs) {
      const prev = state.seenJobs[j.id];
      const wasActive = prev === undefined ? ['queued', 'running'].includes(j.status) : ['queued', 'running'].includes(prev);
      if (wasActive && !['queued', 'running'].includes(j.status)) {
        if (j.status === 'done') { toast(`완료: ${jobLabel(j)}`); if (j.type === 'probe') showProbe(j.result); }
        else toast(`${j.status === 'failed' ? '실패' : '취소'}: ${jobLabel(j)} — ${j.error || ''}`, 'err');
        refresh = true;
      }
      state.seenJobs[j.id] = j.status;
    }
    if (refresh) { render(); loadStatus(); }
  } catch { /* 서버 재시작 중 */ }
}
async function loadStatus() {
  try {
    const s = await api('/api/status');
    state.status = s;
    $('#version').textContent = `v${s.version} · ${s.llm_mode === 'llm' ? 'LLM ' + s.llm_providers.join('/') : '템플릿 모드'}`;
    $('#sysStatus').innerHTML = [
      `<span>${s.naver_logged_in ? '🟢' : '⚪'} 네이버 로그인 ${s.naver_logged_in ? '됨' : '안 됨'}</span>`,
      `<span>${s.ffmpeg ? '🟢' : '🔴'} ffmpeg ${s.ffmpeg ? s.ffmpeg_version : '없음'}</span>`,
      `<span>${s.font_hangul ? '🟢' : '🟡'} 한글 폰트</span>`,
      `<span>${s.edge_tts ? '🟢' : '🟡'} TTS(edge)</span>`,
      `<span>${s.llm_mode === 'llm' ? '🟢' : '🟡'} LLM ${s.llm_mode === 'llm' ? s.llm_providers.join('/') : '템플릿'}</span>`,
    ].join('');
  } catch { $('#sysStatus').textContent = '서버 연결 실패'; }
}

/* ------------------------------------------------------------------ views */
const views = {};

views.dashboard = async () => {
  const [sum, jobs, st] = await Promise.all([api('/api/earnings/summary'), api('/api/jobs?limit=8'), api('/api/status')]);
  const c = sum.counts;
  return `
  <h1>대시보드</h1>
  <div class="grid g4" style="margin-bottom:16px">
    <div class="card kpi"><div class="label">상품</div><div class="value">${num(c.products)}</div><div class="sub">캠페인 ${num(c.campaigns)}건 수집</div></div>
    <div class="card kpi"><div class="label">콘텐츠</div><div class="value">${num(c.blogs + c.scripts)}</div><div class="sub">블로그 ${num(c.blogs)} · 대본 ${num(c.scripts)}</div></div>
    <div class="card kpi"><div class="label">영상</div><div class="value">${num(c.videos)}</div><div class="sub">쇼츠/클립 세로 영상</div></div>
    <div class="card kpi"><div class="label">누적 수수료</div><div class="value">${won(sum.totals.commission)}</div><div class="sub">최근 30일 ${won(sum.last_30_days.commission)} · 클릭 ${num(sum.totals.clicks)}</div></div>
  </div>
  <div class="grid g2">
    <div class="card">
      <h2>⚡ 빠른 실행 — URL 하나로 블로그 + 대본 + 영상 + 패키지</h2>
      <form id="quickRun" class="col">
        <input name="url" placeholder="https://smartstore.naver.com/... 또는 브랜드커넥트 캠페인 URL" required>
        <div class="row">
          <label class="row small"><input type="checkbox" name="with_blog" checked style="width:auto"> 블로그</label>
          <label class="row small"><input type="checkbox" name="with_video" checked style="width:auto"> 영상 제작</label>
          <label class="row small"><input type="checkbox" name="with_package" checked style="width:auto"> 발행 패키지</label>
          <select name="format" style="width:150px"><option value="shorts">쇼츠 45초</option><option value="review">리뷰 2~3분</option></select>
          <button class="btn primary" type="submit">전체 실행</button>
        </div>
      </form>
      <div class="steps" style="margin-top:14px">
        <div class="s"><b>1. 수집</b>상세정보 + 스크린샷 3장↑</div><div class="s"><b>2. SEO 블로그</b>키워드·소제목·FAQ·표시문구</div><div class="s"><b>3. 대본</b>훅→특징→가격→CTA</div><div class="s"><b>4. 영상</b>TTS + 자막 + 켄번즈 MP4</div>
      </div>
    </div>
    <div class="card">
      <h2>🩺 시스템 상태</h2>
      ${st.problems.length ? st.problems.map((p) => `<div class="problem">⚠ ${esc(p)}</div>`).join('') : '<div class="ok-line">✔ 모든 구성 요소 정상</div>'}
      <div class="small muted" style="margin-top:8px">ffmpeg: ${esc(st.ffmpeg || '없음')}<br>폰트: ${esc(st.font || '없음')}<br>LLM: ${st.llm_providers.length ? esc(st.llm_providers.join(' → ')) : '템플릿 모드 (.env 에 API 키 입력)'}<br>홈: ${esc(st.home)}</div>
      <div class="row" style="margin-top:10px"><a class="btn sm" href="#/settings">설정</a><a class="btn sm" href="#/brandconnect">브랜드커넥트 로그인/수집</a></div>
    </div>
  </div>
  <div class="grid g2" style="margin-top:16px">
    <div class="card">
      <h2>🕒 최근 작업</h2>
      ${jobs.jobs.length ? `<table><thead><tr><th>작업</th><th>상태</th><th>메시지</th><th>시각</th></tr></thead><tbody>${jobs.jobs.map((j) => `<tr><td>${esc(jobLabel(j))}</td><td><span class="badge ${j.status === 'done' ? 'ok' : j.status === 'failed' ? 'err' : j.status === 'running' ? 'info' : ''}">${esc(j.status)}</span></td><td class="small">${esc(j.error || j.message)}</td><td class="small nowrap">${dt(j.updated_at)}</td></tr>`).join('')}</tbody></table>` : '<div class="muted">아직 작업이 없습니다.</div>'}
    </div>
    <div class="card">
      <h2>🧮 수익 계산기</h2>
      <form id="calcForm" class="grid g3" style="gap:8px">
        <label class="f">판매가(원)<input name="price" value="49000"></label>
        <label class="f">수수료율(%)<input name="commission_rate" value="10"></label>
        <label class="f">월 방문수<input name="visits" value="3000"></label>
        <label class="f">링크 클릭률<input name="ctr" value="0.06"></label>
        <label class="f">구매 전환율<input name="cvr" value="0.025"></label>
        <div style="display:flex;align-items:flex-end"><button class="btn" type="submit">계산</button></div>
      </form>
      <div id="calcOut" class="small muted" style="margin-top:10px">월 방문 × 클릭률 × 전환율 × 판매가 × 수수료율 = 예상 수수료</div>
    </div>
  </div>`;
};

views.brandconnect = async () => {
  const [{ campaigns }, login] = await Promise.all([api('/api/campaigns'), api('/api/naver/status')]);
  const types = [...new Set(campaigns.map((c) => c.campaign_type).filter(Boolean))];
  return `
  <h1>브랜드커넥트</h1>
  <div class="grid g2" style="margin-bottom:16px">
    <div class="card">
      <h2>1. 네이버 로그인 (최초 1회)</h2>
      <div class="row" style="margin-bottom:8px"><span class="badge ${login.logged_in ? 'ok' : 'warn'}">${login.logged_in ? '로그인 세션 있음' : '로그인 필요'}</span><button class="btn sm" data-action="naverStatus">상태 새로고침</button></div>
      <p class="small muted">브라우저 창이 열리면 직접 로그인하세요 (캡차·2단계 인증 포함). 세션은 <span class="mono">data/browser_profile</span> 에 저장되어 계속 재사용됩니다. 자동 로그인은 하지 않습니다.</p>
      <button class="btn primary" data-action="naverLogin">네이버 로그인 창 열기</button>
    </div>
    <div class="card">
      <h2>2. 캠페인 수집</h2>
      <form id="crawlForm" class="row">
        <label class="f">페이지 수<input name="max_pages" value="3" style="width:90px"></label>
        <label class="f">최대 건수<input name="limit" value="50" style="width:90px"></label>
        <label class="f">상세 자동 수집<input name="detail_limit" value="0" style="width:90px" title="목록 수집 후 이 개수만큼 상세+스크린샷까지 자동 수집"></label>
        <div style="display:flex;align-items:flex-end"><button class="btn primary" type="submit">수집 시작</button></div>
      </form>
      <p class="small muted" style="margin-top:8px">목록 URL: <span class="mono">${esc(state.status?.brandconnect_url || '')}</span> (설정에서 변경) · 수집한 원본 HTML 은 <span class="mono">data/campaigns/</span> 에 저장됩니다.</p>
    </div>
  </div>
  <div class="card" style="margin-bottom:16px">
    <div class="row between" style="margin-bottom:10px"><h2 style="margin:0">캠페인 ${num(campaigns.length)}건</h2>
      <div class="row"><input id="campFilter" placeholder="검색 (제목/브랜드)" style="width:220px"><select id="campType" style="width:140px"><option value="">전체 유형</option>${types.map((t) => `<option>${esc(t)}</option>`).join('')}</select><button class="btn sm danger" data-action="clearCampaigns">목록 비우기</button></div></div>
    ${campaigns.length ? `<table id="campTable"><thead><tr><th></th><th>캠페인</th><th>브랜드</th><th>유형</th><th>리워드</th><th>기간</th><th>상태</th><th></th></tr></thead><tbody>
      ${campaigns.map((c) => `<tr data-title="${esc((c.title + ' ' + c.brand).toLowerCase())}" data-type="${esc(c.campaign_type)}">
        <td>${c.thumbnail ? `<img src="${esc(c.thumbnail)}" style="width:48px;height:48px;object-fit:cover;border-radius:6px">` : ''}</td>
        <td><a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.title)}</a></td><td>${esc(c.brand)}</td><td><span class="badge info">${esc(c.campaign_type || '-')}</span></td><td class="small">${esc(c.reward)}</td><td class="small nowrap">${esc(c.period)}</td>
        <td>${c.product_id ? `<a href="#/products/${c.product_id}" class="badge ok">상품 등록됨</a>` : '<span class="badge">미수집</span>'}</td>
        <td class="nowrap"><button class="btn sm" data-action="importCampaign" data-id="${c.id}">가져오기</button> <button class="btn sm accent" data-action="runCampaign" data-id="${c.id}">전체 실행</button></td></tr>`).join('')}
    </tbody></table>` : '<div class="hint">아직 수집된 캠페인이 없습니다. 로그인 후 "수집 시작"을 누르세요. 목록이 비어 있으면 아래 DOM 프로브로 실제 페이지 구조를 확인하고 설정 → 셀렉터를 조정하세요.</div>'}
  </div>
  <div class="card">
    <h2>🔍 DOM 프로브 (셀렉터 튜닝)</h2>
    <p class="small muted">브랜드커넥트 화면 구조가 바뀌어 수집이 안 될 때 사용합니다. 로그인 세션으로 페이지를 열어 HTML·스크린샷·구조 리포트를 <span class="mono">data/probe/</span> 에 저장하고 요약을 보여줍니다.</p>
    <form id="probeForm" class="row"><input name="url" placeholder="https://brandconnect.naver.com/..." style="flex:1"><button class="btn" type="submit">프로브 실행</button></form>
    <div id="probeOut"></div>
  </div>`;
};

views.products = async () => {
  if (state.param) { showProduct(state.param); }
  const { products } = await api('/api/products');
  return `
  <h1>상품</h1>
  <div class="grid g2" style="margin-bottom:16px">
    <div class="card"><h2>URL 로 가져오기</h2>
      <form id="importForm" class="row"><input name="url" placeholder="스마트스토어 / 브랜드스토어 / 쿠팡 / 브랜드커넥트 캠페인 URL" style="flex:1" required><label class="row small"><input type="checkbox" name="capture" checked style="width:auto">스크린샷</label><button class="btn primary" type="submit">가져오기</button></form>
      <p class="small muted" style="margin-top:6px">상세정보(가격·브랜드·특징·스펙) 추출 + 화면/모바일/전체 스크린샷 + 상품 이미지 다운로드 (최소 3장 보장)</p></div>
    <div class="card"><h2>직접 입력</h2><p class="small muted">캠페인 페이지가 없거나 오프라인 상품이면 직접 등록 후 이미지를 <span class="mono">data/products/&lt;id&gt;/</span> 에 넣으세요.</p><button class="btn" data-action="manualProduct">상품 직접 추가</button></div>
  </div>
  ${products.length ? `<div class="grid cards">${products.map((p) => `
    <div class="card pcard">
      ${p.thumbnail_url ? `<img class="thumb" src="${esc(p.thumbnail_url)}" alt="">` : '<div class="thumb empty">이미지 없음</div>'}
      <div class="title">${esc(p.name)}</div>
      <div class="meta">${esc(p.brand || '-')} · ${won(p.price)}${p.discount_rate ? ` <span class="badge ok">${p.discount_rate}%↓</span>` : ''}${p.commission_rate ? ` · 수수료 ${p.commission_rate}%` : ''}</div>
      <div class="row small"><span class="badge ${p.status === 'new' ? '' : 'ok'}">${esc(STATUS_KO[p.status] || p.status)}</span><span class="muted">미디어 ${p.media_urls.length}장 · ${esc(p.source)}</span>${p.affiliate_url ? '<span class="badge info">제휴링크</span>' : '<span class="badge warn">링크 없음</span>'}</div>
      <div class="actions">
        <button class="btn sm" data-action="openProduct" data-id="${p.id}">상세</button>
        <button class="btn sm" data-action="genBlog" data-id="${p.id}">블로그</button>
        <button class="btn sm" data-action="genScript" data-id="${p.id}">대본</button>
        <button class="btn sm" data-action="genVideo" data-id="${p.id}">영상</button>
        <button class="btn sm" data-action="genPackage" data-id="${p.id}">패키지</button>
        <button class="btn sm accent" data-action="runProduct" data-id="${p.id}">전체 실행</button>
        <button class="btn sm danger ghost" data-action="deleteProduct" data-id="${p.id}">삭제</button>
      </div>
    </div>`).join('')}</div>` : '<div class="hint">상품이 없습니다. URL 을 입력해 가져오거나 브랜드커넥트에서 캠페인을 수집하세요.</div>'}`;
};

async function showProduct(id) {
  let d;
  try { d = await api(`/api/products/${id}`); } catch (e) { toast(e.message, 'err'); return; }
  const p = d.product;
  const kw = p.keywords || {};
  const features = (p.features || []).join('\n');
  openModal(`
    <div class="row between"><h2 style="margin:0">${esc(p.name)}</h2><span class="badge">${esc(STATUS_KO[p.status] || p.status)}</span></div>
    <div class="gallery" style="margin:12px 0">${p.media_urls.map((u) => `<img src="${esc(u)}" onclick="window.open('${esc(u)}')">`).join('') || '<span class="muted small">이미지 없음</span>'}</div>
    <div class="grid g2">
      <form id="productForm" class="col" data-id="${p.id}">
        <label class="f">상품명<input name="name" value="${esc(p.name)}"></label>
        <div class="grid g2" style="gap:8px"><label class="f">브랜드<input name="brand" value="${esc(p.brand)}"></label><label class="f">카테고리<input name="category" value="${esc(p.category)}"></label></div>
        <div class="grid g3" style="gap:8px"><label class="f">판매가<input name="price" value="${p.price ?? ''}"></label><label class="f">정가<input name="original_price" value="${p.original_price ?? ''}"></label><label class="f">수수료율(%)<input name="commission_rate" value="${p.commission_rate ?? ''}"></label></div>
        <label class="f">제휴 링크 (브랜드커넥트 커넥트링크 / 쿠팡 파트너스 등) — 블로그·영상 CTA 에 삽입<input name="affiliate_url" value="${esc(p.affiliate_url)}" placeholder="https://..."></label>
        <label class="f">상품 페이지 URL<input name="product_url" value="${esc(p.product_url)}"></label>
        <label class="f">특징 (한 줄에 하나)<textarea name="features" style="min-height:90px">${esc(features)}</textarea></label>
        <label class="f">메모<input name="notes" value="${esc(p.notes)}"></label>
        <div class="row"><button class="btn primary" type="submit">저장</button><button class="btn" type="button" data-action="refreshKeywords" data-id="${p.id}">키워드 다시 분석</button></div>
      </form>
      <div class="col">
        <div class="card"><h3>키워드</h3>
          <div><b>핵심:</b> ${esc(kw.primary || '(블로그 생성 시 분석)')}</div>
          <div class="small muted">보조: ${esc((kw.secondary || []).slice(0, 5).join(', '))}</div>
          <div class="small muted">롱테일: ${esc((kw.longtail || []).slice(0, 3).join(', '))}</div>
          <div class="small" style="margin-top:4px">${(kw.hashtags || []).map((h) => `<span class="badge">${esc(h)}</span> `).join('')}</div>
          ${kw.volumes && Object.keys(kw.volumes).length ? `<div class="small muted" style="margin-top:4px">월 검색량: ${Object.entries(kw.volumes).slice(0, 5).map(([k, v]) => `${esc(k)} ${num(v)}`).join(' · ')}</div>` : ''}
        </div>
        <div class="card"><h3>링크 &amp; 링크인바이오</h3>
          ${p.best_link ? `<div class="small ellipsis"><a href="${esc(p.best_link)}" target="_blank" rel="noopener">${esc(p.best_link)}</a></div>
          <textarea class="mono" style="min-height:90px;margin-top:6px" readonly>${esc(d.link_in_bio)}</textarea>
          <div class="row" style="margin-top:6px">${copyBtn(d.link_in_bio, '문구 복사됨', 'btn sm', '문구 복사')}${Object.entries(d.channel_links || {}).map(([ch, url]) => copyBtn(url, `${CHANNELS[ch] || ch} 링크 복사됨`, 'btn sm ghost', CHANNELS[ch] || ch)).join('')}</div>` : '<div class="small muted">제휴 링크를 입력하면 채널별 UTM 링크와 고정댓글 문구가 생성됩니다.</div>'}
        </div>
        <div class="card"><h3>콘텐츠 / 영상</h3>
          ${d.contents.length ? d.contents.map((c) => `<div class="row between small"><a href="#/contents/${c.id}" onclick="closeModal()">${c.kind === 'blog' ? '📝' : '🎬'} ${esc(c.title)}</a><span class="muted">${c.kind === 'blog' ? `SEO ${c.seo_score}` : `${Math.round(c.duration)}초`} · ${esc(c.provider)}</span></div>`).join('') : '<div class="small muted">아직 없음</div>'}
          ${d.videos.map((v) => `<div class="row between small"><a href="#/videos" onclick="closeModal()">🎥 ${esc(v.title)}</a><span class="muted">${Math.round(v.duration)}초 · ${esc(v.tts_engine)}</span></div>`).join('')}
          <div class="row" style="margin-top:8px"><button class="btn sm" type="button" data-action="genBlog" data-id="${p.id}">블로그 생성</button><button class="btn sm" type="button" data-action="genScript" data-id="${p.id}">쇼츠 대본</button><button class="btn sm" type="button" data-action="genScript" data-id="${p.id}" data-format="review">리뷰 대본</button><button class="btn sm" type="button" data-action="genVideo" data-id="${p.id}">영상 제작</button><button class="btn sm" type="button" data-action="genPackage" data-id="${p.id}">패키지</button></div>
        </div>
        ${p.campaign && Object.keys(p.campaign).length ? `<div class="card small"><h3>캠페인</h3>${Object.entries(p.campaign).filter(([, v]) => v).map(([k, v]) => `<div><b>${esc(k)}:</b> ${esc(v)}</div>`).join('')}</div>` : ''}
        ${p.description ? `<div class="card small muted">${esc(p.description).slice(0, 500)}</div>` : ''}
      </div>
    </div>`);
  bind($('#modalBody'));
  $('#productForm').onsubmit = async (ev) => {
    ev.preventDefault();
    try { await api(`/api/products/${p.id}`, { method: 'PUT', body: formData(ev.target) }); toast('저장됨'); closeModal(); render(); } catch (e) { toast(e.message, 'err'); }
  };
}

views.contents = async () => {
  if (state.param) return contentDetail(state.param);
  const { contents } = await api('/api/contents');
  const { products } = await api('/api/products');
  const names = Object.fromEntries(products.map((p) => [p.id, p.name]));
  const blogs = contents.filter((c) => c.kind === 'blog');
  const scripts = contents.filter((c) => c.kind === 'script');
  const row = (c) => `<tr><td>${c.kind === 'blog' ? '📝' : '🎬'}</td><td><a href="#/contents/${c.id}">${esc(c.title)}</a><div class="small muted">${esc(names[c.product_id] || c.product_id)}</div></td>
    <td>${c.kind === 'blog' ? `<span class="badge ${c.seo_score >= 80 ? 'ok' : c.seo_score >= 60 ? 'warn' : 'err'}">SEO ${c.seo_score}</span> <span class="small muted">${num(c.char_count)}자</span>` : `<span class="badge info">${esc(c.format)}</span> <span class="small muted">${c.scenes.length}장면 · ${Math.round(c.duration)}초</span>`}</td>
    <td class="small">${esc(c.provider)}</td><td class="small nowrap">${dt(c.updated_at)}</td><td class="nowrap"><button class="btn sm danger ghost" data-action="deleteContent" data-id="${c.id}">삭제</button></td></tr>`;
  return `<h1>콘텐츠 스튜디오</h1>
  <div class="grid g2">
    <div class="card"><h2>📝 블로그 (${blogs.length})</h2>${blogs.length ? `<table><tbody>${blogs.map(row).join('')}</tbody></table>` : '<div class="muted small">상품 카드에서 "블로그"를 눌러 생성하세요.</div>'}</div>
    <div class="card"><h2>🎬 영상 대본 (${scripts.length})</h2>${scripts.length ? `<table><tbody>${scripts.map(row).join('')}</tbody></table>` : '<div class="muted small">상품 카드에서 "대본"을 눌러 생성하세요.</div>'}</div>
  </div>`;
};

async function contentDetail(id) {
  const { content: c } = await api(`/api/contents/${id}`);
  if (c.kind === 'blog') {
    const rep = c.seo_report || { checks: [], suggestions: [] };
    return `<div class="row between" style="margin-bottom:12px"><a href="#/contents" class="btn sm">← 목록</a><div class="row">${copyBtn(c.plain_text, '네이버 에디터용 텍스트 복사', 'btn sm', '텍스트 복사')}${copyBtn(c.html, 'HTML 복사', 'btn sm', 'HTML 복사')}${copyBtn(c.markdown, '마크다운 복사', 'btn sm', 'MD 복사')}<button class="btn sm accent" data-action="genVideo" data-id="${c.product_id}">이 상품 영상 제작</button></div></div>
    <div class="grid" style="grid-template-columns:1fr 320px;gap:16px">
      <div class="card">
        <div class="tabs"><button class="active" data-tab="preview">미리보기</button><button data-tab="edit">마크다운 편집</button><button data-tab="text">네이버 텍스트</button></div>
        <div id="tab-preview" class="preview">${c.html_preview}</div>
        <div id="tab-edit" class="col" hidden>
          <form id="blogForm" class="col">
            <label class="f">제목<input name="title" value="${esc(c.title)}"></label>
            <label class="f">요약(meta)<input name="meta_description" value="${esc(c.meta_description)}"></label>
            <label class="f">해시태그 (공백 구분)<input name="hashtags" value="${esc(c.hashtags.join(' '))}"></label>
            <textarea name="markdown" class="mono" style="min-height:420px">${esc(c.markdown)}</textarea>
            <div class="row"><button class="btn primary" type="submit">저장 &amp; SEO 재채점</button><span class="small muted">이미지 경로는 로컬 파일 경로입니다. 발행 패키지에서 images/ 로 정리됩니다.</span></div>
          </form>
        </div>
        <div id="tab-text" hidden><textarea class="mono" style="min-height:520px" readonly>${esc(c.plain_text)}</textarea><p class="small muted">네이버 블로그 에디터에 붙여넣고 [이미지 삽입] 자리에 해당 이미지를 업로드하세요.</p></div>
      </div>
      <div class="col">
        <div class="card"><div class="row"><div class="ring" style="--p:${c.seo_score}"><span>${c.seo_score}</span></div><div><div><b>SEO 점수</b></div><div class="small muted">${num(c.char_count)}자 · 이미지 ${c.images.length}장 · ${esc(c.provider)}</div><div class="small muted">핵심: ${esc(c.primary_keyword)}</div></div></div>
          <div class="checks" style="margin-top:12px">${(rep.checks || []).map((k) => `<div>${k.passed ? '✅' : '❌'} ${esc(k.label)} <span class="w">${esc(k.detail)}</span></div>`).join('')}</div>
          ${(rep.suggestions || []).length ? `<div class="hint" style="margin-top:10px">${rep.suggestions.map((s) => `• ${esc(s)}`).join('<br>')}</div>` : ''}
        </div>
        <div class="card small"><h3>키워드</h3>${c.keywords.map((k) => `<span class="badge">${esc(k)}</span> `).join('')}<div style="margin-top:6px">${c.hashtags.map((h) => `<span class="badge info">${esc(h)}</span> `).join('')}</div></div>
      </div>
    </div>`;
  }
  const scenes = c.scenes || [];
  return `<div class="row between" style="margin-bottom:12px"><a href="#/contents" class="btn sm">← 목록</a><div class="row">${copyBtn(scenes.map((s, i) => `#${i + 1} [${s.caption}] ${s.narration}`).join('\n'), '대본 복사', 'btn sm', '대본 복사')}<button class="btn sm accent" data-action="genVideo" data-id="${c.product_id}" data-script="${c.id}">이 대본으로 영상 제작</button></div></div>
  <div class="card">
    <form id="scriptForm" class="col">
      <div class="grid g2" style="gap:8px"><label class="f">제목<input name="title" value="${esc(c.title)}"></label><label class="f">해시태그<input name="hashtags" value="${esc(c.hashtags.join(' '))}"></label></div>
      <label class="f">설명란 (유튜브/클립)<textarea name="description" style="min-height:70px">${esc(c.description)}</textarea></label>
      <table><thead><tr><th>#</th><th>유형</th><th>자막 (화면)</th><th>내레이션 (TTS)</th><th class="num">초</th><th>비주얼</th></tr></thead><tbody>
      ${scenes.map((s, i) => `<tr class="scene-row"><td>${i + 1}</td><td><span class="badge">${esc(s.kind)}</span></td><td><input name="caption_${i}" value="${esc(s.caption)}"></td><td><input name="narration_${i}" value="${esc(s.narration)}"></td><td class="num"><input name="duration_${i}" value="${s.duration}" style="width:64px"></td><td>${s.visual_url ? `<img src="${esc(s.visual_url)}" style="height:40px;border-radius:4px">` : '<span class="small muted">자동</span>'}</td></tr>`).join('')}
      </tbody></table>
      <div class="row"><button class="btn primary" type="submit">대본 저장</button><span class="small muted">${esc(c.format)} · 총 ${Math.round(c.duration)}초 · ${esc(c.provider)}</span></div>
    </form>
  </div>`;
}

views.videos = async () => {
  const [{ videos }, { products }] = await Promise.all([api('/api/videos'), api('/api/products')]);
  const names = Object.fromEntries(products.map((p) => [p.id, p.name]));
  return `<h1>영상</h1>${videos.length ? `<div class="grid g3">${videos.map((v) => {
    const m = v.metadata || {};
    const meta = `${m.title || v.title}\n\n${m.description || ''}\n\n${(m.hashtags || []).join(' ')}`;
    return `<div class="card video-card col">
      <video controls preload="metadata" poster="${esc(v.thumbnail_url)}" src="${esc(v.url)}"></video>
      <div><b>${esc(v.title)}</b><div class="small muted">${esc(names[v.product_id] || '')} · ${Math.round(v.duration)}초 · ${v.width}x${v.height} · TTS ${esc(v.tts_engine)}${m.bgm ? ' · BGM' : ''}</div></div>
      ${(m.warnings || []).length ? `<div class="problem">${m.warnings.map(esc).join('<br>')}</div>` : ''}
      ${m.tts_error && v.tts_engine === 'silent' ? `<div class="problem small">TTS 실패(무음): ${esc(m.tts_error)}</div>` : ''}
      <div class="row"><a class="btn sm" href="${esc(v.url)}" download>MP4 다운로드</a>${v.srt_url ? `<a class="btn sm ghost" href="${esc(v.srt_url)}" download>SRT</a>` : ''}${copyBtn(meta, '제목/설명/태그 복사', 'btn sm ghost', '설명란 복사')}<button class="btn sm danger ghost" data-action="deleteVideo" data-id="${v.id}">삭제</button></div>
    </div>`; }).join('')}</div>` : '<div class="hint">영상이 없습니다. 상품 카드의 "영상" 또는 대본 화면의 "이 대본으로 영상 제작"을 누르세요. TTS 는 edge-tts(무료) 를 사용하며 인터넷이 필요합니다.</div>'}`;
};

views.earnings = async () => {
  const [sum, { earnings }, { products }] = await Promise.all([api('/api/earnings/summary'), api('/api/earnings'), api('/api/products')]);
  const names = Object.fromEntries(products.map((p) => [p.id, p.name]));
  const maxCh = Math.max(1, ...sum.by_channel.map((c) => c.commission));
  return `<h1>수익 관리</h1>
  <div class="grid g4" style="margin-bottom:16px">
    <div class="card kpi"><div class="label">누적 수수료</div><div class="value">${won(sum.totals.commission)}</div><div class="sub">매출 ${won(sum.totals.revenue)}</div></div>
    <div class="card kpi"><div class="label">클릭 → 주문</div><div class="value">${num(sum.totals.clicks)} → ${num(sum.totals.orders)}</div><div class="sub">전환율 ${sum.conversion_rate}%</div></div>
    <div class="card kpi"><div class="label">클릭당 수익 (EPC)</div><div class="value">${won(sum.epc)}</div><div class="sub">주문당 ${won(sum.avg_commission_per_order)}</div></div>
    <div class="card kpi"><div class="label">최근 30일</div><div class="value">${won(sum.last_30_days.commission)}</div><div class="sub">클릭 ${num(sum.last_30_days.clicks)} · 주문 ${num(sum.last_30_days.orders)}</div></div>
  </div>
  <div class="grid g2" style="margin-bottom:16px">
    <div class="card"><h2>채널별 수수료</h2>${sum.by_channel.length ? `<div class="bars">${sum.by_channel.map((c) => `<div class="b"><span>${esc(c.label)}</span><i style="width:${Math.round(c.commission / maxCh * 100)}%"></i><span class="num">${won(c.commission)}</span></div>`).join('')}</div>` : '<div class="muted small">데이터 없음</div>'}
      <h2 style="margin-top:16px">상품별 TOP</h2>${sum.by_product.length ? `<table><tbody>${sum.by_product.map((p) => `<tr><td>${esc(p.name)}</td><td class="num">${num(p.clicks)}클릭</td><td class="num">${num(p.orders)}주문</td><td class="num"><b>${won(p.commission)}</b></td></tr>`).join('')}</tbody></table>` : '<div class="muted small">데이터 없음</div>'}</div>
    <div class="card"><h2>수익 입력</h2>
      <form id="earnForm" class="grid g3" style="gap:8px">
        <label class="f">날짜<input type="date" name="date" value="${new Date().toISOString().slice(0, 10)}"></label>
        <label class="f">채널<select name="channel">${Object.entries(CHANNELS).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></label>
        <label class="f">상품<select name="product_id"><option value="">(미지정)</option>${products.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}</select></label>
        <label class="f">클릭<input name="clicks" value="0"></label><label class="f">주문<input name="orders" value="0"></label><label class="f">매출(원)<input name="revenue" value="0"></label>
        <label class="f">수수료(원)<input name="commission" value="0"></label><label class="f" style="grid-column:span 2">메모<input name="note"></label>
        <div><button class="btn primary" type="submit">추가</button></div>
      </form>
      <h3 style="margin-top:14px">정산 CSV 가져오기</h3>
      <form id="csvForm" class="col"><textarea name="csv" class="mono" placeholder="브랜드커넥트/쿠팡 정산 내역을 CSV 로 붙여넣기 (헤더: 날짜, 채널, 상품, 클릭, 주문, 매출, 수수료 — 순서/이름 자유)"></textarea><div><button class="btn" type="submit">가져오기</button></div></form>
    </div>
  </div>
  <div class="card"><h2>내역 (${earnings.length})</h2>${earnings.length ? `<table><thead><tr><th>날짜</th><th>채널</th><th>상품</th><th class="num">클릭</th><th class="num">주문</th><th class="num">매출</th><th class="num">수수료</th><th>메모</th><th></th></tr></thead><tbody>
    ${earnings.map((e) => `<tr><td class="nowrap">${esc(e.date)}</td><td>${esc(CHANNELS[e.channel] || e.channel)}</td><td class="small">${esc(names[e.product_id] || '-')}</td><td class="num">${num(e.clicks)}</td><td class="num">${num(e.orders)}</td><td class="num">${won(e.revenue)}</td><td class="num"><b>${won(e.commission)}</b></td><td class="small muted">${esc(e.note)}</td><td><button class="btn sm danger ghost" data-action="deleteEarning" data-id="${e.id}">삭제</button></td></tr>`).join('')}</tbody></table>` : '<div class="muted small">아직 입력된 수익이 없습니다. 발행 후 채널별 클릭/주문/수수료를 기록하면 EPC 와 상품별 성과를 볼 수 있습니다.</div>'}</div>`;
};

views.settings = async () => {
  const [{ settings: s, runtime }, sel, st] = await Promise.all([api('/api/settings'), api('/api/settings/selectors'), api('/api/status')]);
  const val = (k, d = '') => (runtime[k] ?? s[k] ?? d);
  state.effectiveSelectors = sel.effective;
  return `<h1>설정</h1>
  <div class="grid g2">
    <div class="card"><h2>콘텐츠 / 영상 기본값</h2>
      <form id="settingsForm" class="col">
        <label class="f">블로그 톤<input name="blog_tone" value="${esc(val('blog_tone'))}"></label>
        <label class="f">블로그 목표 글자수<input name="blog_length" value="${esc(val('blog_length'))}"></label>
        <label class="f">TTS 음성 (edge-tts)<input name="tts_voice" list="voices" value="${esc(val('tts_voice'))}"><datalist id="voices">${VOICES.map((v) => `<option value="${v}">`).join('')}</datalist></label>
        <label class="f">TTS 속도 (예: +5%, -10%)<input name="tts_rate" value="${esc(val('tts_rate'))}"></label>
        <label class="f">제휴 표시 문구 (공정위)<textarea name="disclosure" style="min-height:70px">${esc(val('disclosure'))}</textarea></label>
        <label class="f">작성자 이름 (블로그 하단)<input name="creator_name" value="${esc(val('creator_name'))}"></label>
        <label class="f">브랜드커넥트 캠페인 목록 URL<input name="brandconnect_url" value="${esc(val('brandconnect_url'))}"></label>
        <label class="f">상품당 최소 이미지 수<input name="min_screenshots" value="${esc(val('min_screenshots', 3))}"></label>
        <label class="row small"><input type="checkbox" name="headless" ${val('headless') ? 'checked' : ''} style="width:auto"> 헤드리스 크롤링 (끄면 브라우저 창이 보임 — 문제 확인용)</label>
        <div><button class="btn primary" type="submit">저장</button></div>
      </form>
    </div>
    <div class="col">
      <div class="card"><h2>환경 (.env)</h2>
        <table><tbody>
          <tr><td>LLM 우선순위</td><td class="mono small">${esc(s.llm_order.join(' → '))}</td></tr>
          ${Object.entries(s.llm_keys).map(([k, v]) => `<tr><td>${k} 키</td><td>${v ? `<span class="badge ok">${esc(v)}</span> <span class="small muted mono">${esc(s.models[k])}</span>` : '<span class="badge">없음</span>'}</td></tr>`).join('')}
          <tr><td>네이버 검색광고 API</td><td>${s.naver_searchad ? '<span class="badge ok">연결</span>' : '<span class="badge">없음 (휴리스틱 키워드)</span>'}</td></tr>
          <tr><td>ffmpeg</td><td class="small mono">${esc(st.ffmpeg || '없음')} ${esc(st.ffmpeg_version)}</td></tr>
          <tr><td>한글 폰트</td><td class="small mono">${esc(st.font || '없음')} ${st.font_hangul ? '✅' : '❌'}</td></tr>
          <tr><td>크로미움</td><td class="small mono">${esc(st.chromium_path)}</td></tr>
          <tr><td>홈 디렉토리</td><td class="small mono">${esc(s.home)}</td></tr>
        </tbody></table>
        <p class="small muted">API 키·경로는 <span class="mono">.env</span> 파일에서 수정 후 서버를 재시작하세요.</p>
      </div>
      <div class="card"><h2>브랜드커넥트 셀렉터 오버라이드</h2>
        <p class="small muted">기본 후보 셀렉터를 JSON 으로 덮어씁니다 (<span class="mono">data/selectors.override.json</span>). 비우고 저장하면 기본값으로 복귀. 예: <span class="mono">{"list":{"item":["ul.CampaignList > li"]}}</span></p>
        <form id="selForm" class="col"><textarea name="override" class="mono" style="min-height:160px">${esc(sel.override)}</textarea><div class="row"><button class="btn" type="submit">저장</button><button class="btn ghost" type="button" data-action="showSelectors">현재 적용값 보기</button></div></form>
      </div>
    </div>
  </div>`;
};

/* ------------------------------------------------------------------ actions */
const actions = {
  copy: (d) => { const item = copyStore.get(d.key); if (item) copyText(item.text, item.label); },
  showSelectors: () => openModal(`<h2>현재 적용 셀렉터</h2><pre class="json">${esc(JSON.stringify(state.effectiveSelectors || {}, null, 2))}</pre>`),
  naverLogin: () => runJob('/api/naver/login', {}, '네이버 로그인'),
  naverStatus: async () => { try { const r = await api('/api/naver/status?refresh=1'); toast(r.logged_in ? '로그인 세션 확인됨' : '로그인되어 있지 않습니다', r.logged_in ? 'ok' : 'err'); loadStatus(); render(); } catch (e) { toast(e.message, 'err'); } },
  clearCampaigns: async () => { if (!confirm('캠페인 목록을 비울까요? (상품은 유지)')) return; await api('/api/campaigns', { method: 'DELETE' }); render(); },
  importCampaign: (d) => runJob(`/api/campaigns/${d.id}/import`, {}, '캠페인 가져오기'),
  runCampaign: (d) => runJob('/api/pipeline/run', { campaign_id: d.id }, '전체 파이프라인'),
  openProduct: (d) => showProduct(d.id),
  genBlog: (d) => runJob(`/api/products/${d.id}/blog`, {}, '블로그 생성'),
  genScript: (d) => runJob(`/api/products/${d.id}/script`, { format: d.format || 'shorts' }, '대본 생성'),
  genVideo: (d) => runJob(`/api/products/${d.id}/video`, { script_id: d.script || null }, '영상 제작'),
  genPackage: (d) => runJob(`/api/products/${d.id}/package`, {}, '패키지 생성'),
  runProduct: (d) => runJob('/api/pipeline/run', { product_id: d.id }, '전체 파이프라인'),
  deleteProduct: async (d) => { if (!confirm('상품과 관련 콘텐츠를 삭제할까요?')) return; try { await api(`/api/products/${d.id}`, { method: 'DELETE' }); toast('삭제됨'); render(); } catch (e) { toast(e.message, 'err'); } },
  deleteContent: async (d) => { if (!confirm('삭제할까요?')) return; await api(`/api/contents/${d.id}`, { method: 'DELETE' }); render(); },
  deleteVideo: async (d) => { if (!confirm('영상 기록을 삭제할까요? (파일은 output/videos 에 남음)')) return; await api(`/api/videos/${d.id}`, { method: 'DELETE' }); render(); },
  deleteEarning: async (d) => { await api(`/api/earnings/${d.id}`, { method: 'DELETE' }); render(); },
  refreshKeywords: async (d) => { try { await api(`/api/products/${d.id}/keywords`, { method: 'POST' }); toast('키워드 갱신'); showProduct(d.id); } catch (e) { toast(e.message, 'err'); } },
  manualProduct: () => {
    openModal(`<h2>상품 직접 추가</h2><form id="manualForm" class="col">
      <label class="f">상품명 *<input name="name" required></label>
      <div class="grid g2" style="gap:8px"><label class="f">브랜드<input name="brand"></label><label class="f">카테고리<input name="category" placeholder="예: 생활가전 > 무선청소기"></label></div>
      <div class="grid g3" style="gap:8px"><label class="f">판매가<input name="price"></label><label class="f">정가<input name="original_price"></label><label class="f">수수료율(%)<input name="commission_rate"></label></div>
      <label class="f">제휴 링크<input name="affiliate_url"></label><label class="f">상품 URL<input name="product_url"></label>
      <label class="f">설명<textarea name="description"></textarea></label><label class="f">특징 (한 줄에 하나)<textarea name="features"></textarea></label>
      <div><button class="btn primary" type="submit">추가</button></div></form>`);
    $('#manualForm').onsubmit = async (ev) => { ev.preventDefault(); try { const body = formData(ev.target); if (body.commission_rate === '') delete body.commission_rate; else body.commission_rate = Number(body.commission_rate); await api('/api/products/manual', { method: 'POST', body }); toast('추가됨'); closeModal(); render(); } catch (e) { toast(e.message, 'err'); } };
  },
};

function showProbe(r) {
  if (!r) return;
  const html = `<h2>DOM 프로브 결과</h2><div class="small muted">${esc(r.url)} · 저장: <span class="mono">${esc(r.saved_to || '')}</span> · 로그인 ${r.logged_in ? '됨' : '안 됨'} ${r.login_marker ? '· ⚠ 로그인 링크 감지' : ''}</div>
    <div class="grid g2" style="margin-top:10px">
      <div class="card small"><h3>반복 컨테이너 (목록 후보)</h3>${(r.repeated_containers || []).map((c) => `<div><span class="mono">${esc(c.container)}</span> → <span class="mono">${esc(c.child)}</span> ×${c.count}<div class="muted">${esc(c.sample_text)}</div></div>`).join('') || '없음'}</div>
      <div class="card small"><h3>캠페인 링크 ${r.campaign_link_count}개</h3>${(r.campaign_link_samples || []).map((h) => `<div class="mono ellipsis">${esc(h)}</div>`).join('') || '없음'}
        <h3 style="margin-top:8px">메타</h3>${Object.entries(r.meta || {}).map(([k, v]) => `<div><b>${esc(k)}</b>: ${esc(v)}</div>`).join('') || '없음'}
        <h3 style="margin-top:8px">가격/퍼센트/날짜 샘플</h3><div>${esc((r.price_samples || []).join(', '))}</div><div>${esc((r.percent_samples || []).join(', '))}</div><div>${esc((r.date_samples || []).join(', '))}</div></div>
    </div><pre class="json" style="margin-top:10px">${esc(JSON.stringify(r.top_classes?.slice(0, 25) || [], null, 0))}</pre>`;
  const out = $('#probeOut');
  if (out) out.innerHTML = html; else openModal(html);
}

/* ------------------------------------------------------------------ forms */
document.addEventListener('submit', async (ev) => {
  const f = ev.target;
  if (!f.id) return;
  ev.preventDefault();
  const body = formData(f);
  try {
    if (f.id === 'quickRun') { await runJob('/api/pipeline/run', body, '전체 파이프라인'); f.reset(); }
    else if (f.id === 'calcForm') { const r = await api('/api/calculator', { method: 'POST', body }); $('#calcOut').innerHTML = `예상 클릭 <b>${num(r.expected_clicks)}</b> → 주문 <b>${r.expected_orders}</b> → 매출 <b>${won(r.expected_revenue)}</b> → <b style="color:var(--accent)">월 수수료 ${won(r.expected_commission)}</b> (주문당 ${won(r.commission_per_order)})`; }
    else if (f.id === 'crawlForm') { await runJob('/api/brandconnect/crawl', { max_pages: Number(body.max_pages), limit: Number(body.limit), detail_limit: Number(body.detail_limit) }, '캠페인 수집'); }
    else if (f.id === 'probeForm') { await runJob('/api/probe', { url: body.url }, '프로브'); $('#probeOut').innerHTML = '<div class="muted small">실행 중… 완료되면 여기에 표시됩니다.</div>'; }
    else if (f.id === 'importForm') { await runJob('/api/products/import', { url: body.url, capture: body.capture }, 'URL 가져오기'); f.reset(); }
    else if (f.id === 'blogForm') { const id = state.param; const { content } = await api(`/api/contents/${id}`, { method: 'PUT', body }); toast(`저장됨 — SEO ${content.seo_score}점`); render(); }
    else if (f.id === 'scriptForm') {
      const id = state.param; const { content: cur } = await api(`/api/contents/${id}`);
      const scenes = cur.scenes.map((s, i) => ({ ...s, caption: body[`caption_${i}`], narration: body[`narration_${i}`], duration: Number(body[`duration_${i}`]) || s.duration }));
      await api(`/api/contents/${id}`, { method: 'PUT', body: { title: body.title, description: body.description, hashtags: body.hashtags, scenes } }); toast('대본 저장됨'); render();
    }
    else if (f.id === 'earnForm') { await api('/api/earnings', { method: 'POST', body }); toast('추가됨'); render(); }
    else if (f.id === 'csvForm') { const r = await api('/api/earnings/import', { method: 'POST', body }); toast(`${r.imported}건 가져옴`); render(); }
    else if (f.id === 'settingsForm') { await api('/api/settings', { method: 'PUT', body }); toast('설정 저장됨'); loadStatus(); }
    else if (f.id === 'selForm') { await api('/api/settings/selectors', { method: 'PUT', body }); toast('셀렉터 저장됨'); }
  } catch (e) { toast(e.message, 'err'); }
});
document.addEventListener('click', (ev) => {
  const tab = ev.target.closest('.tabs button');
  if (tab) { $$('.tabs button').forEach((b) => b.classList.toggle('active', b === tab)); ['preview', 'edit', 'text'].forEach((t) => { const el = $(`#tab-${t}`); if (el) el.hidden = t !== tab.dataset.tab; }); }
});
document.addEventListener('input', (ev) => {
  if (ev.target.id === 'campFilter' || ev.target.id === 'campType') {
    const q = ($('#campFilter')?.value || '').toLowerCase(); const t = $('#campType')?.value || '';
    $$('#campTable tbody tr').forEach((tr) => { tr.style.display = (!q || tr.dataset.title.includes(q)) && (!t || tr.dataset.type === t) ? '' : 'none'; });
  }
});
document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') closeModal(); });

window.addEventListener('hashchange', route);
loadStatus();
pollJobs();
setInterval(pollJobs, 2500);
setInterval(loadStatus, 30000);
route();
