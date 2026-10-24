/* 쓰담 프론트엔드 (외부 라이브러리 없음) */
'use strict';

const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
const view = $('#view');
const state = { settings: null, classes: [], jobsActive: 0, lastJobIds: '', term: null };

// ───────────────────────── 학기 ─────────────────────────
// 학년도는 3월에 시작: 3~8월 = 1학기, 9~2월 = 2학기 (1·2월은 전년도 2학기)
function currentTerm(d) {
  d = d || new Date();
  const m = d.getMonth() + 1, y = d.getFullYear();
  if (m >= 3 && m <= 8) return { year: y, semester: 1 };
  return m >= 9 ? { year: y, semester: 2 } : { year: y - 1, semester: 2 };
}
function nextTerm(t) { return t.semester === 1 ? { year: t.year, semester: 2 } : { year: t.year + 1, semester: 1 }; }
function prevTerm(t) { return t.semester === 2 ? { year: t.year, semester: 1 } : { year: t.year - 1, semester: 2 }; }
function termKey(t) { return t.year + '-' + t.semester; }
function termLabel(t) { return `${t.year}년 ${t.semester}학기`; }
function sameTerm(a, b) { return a && b && +a.year === +b.year && +a.semester === +b.semester; }
function isCurrentTerm(t) { return sameTerm(t || state.term, currentTerm()); }
function inTerm(c, t) { return sameTerm(c, t || state.term); }
function termClasses(t) { return state.classes.filter(c => inTerm(c, t)); }
function store(kind, key, val) {
  try {
    const st = kind === 'session' ? sessionStorage : localStorage;
    if (val === undefined) return st.getItem(key);
    st.setItem(key, val);
  } catch (e) { return null; }
  return null;
}
(function initTerm() {
  const saved = store('session', 'sseudam.term');
  const m = saved && saved.match(/^(\d{4})-([12])$/);
  state.term = m ? { year: +m[1], semester: +m[2] } : currentTerm();
})();
function setTerm(t, go) {
  state.term = { year: +t.year, semester: +t.semester };
  store('session', 'sseudam.term', termKey(state.term));
  renderTermSwitch();
  if (go && location.hash !== go) location.hash = go; else router(!go);
}
function allTerms() {
  const map = {};
  [currentTerm(), state.term].concat(state.classes).forEach(c => { if (c && c.year && c.semester) map[termKey(c)] = { year: +c.year, semester: +c.semester }; });
  return Object.values(map).sort((a, b) => (b.year - a.year) || (b.semester - a.semester));
}
function renderTermSwitch() {
  const sel = $('#term-select'); if (!sel) return;
  const cur = currentTerm();
  sel.innerHTML = allTerms().map(t => `<option value="${termKey(t)}" ${sameTerm(t, state.term) ? 'selected' : ''}>${termLabel(t)}${sameTerm(t, cur) ? ' · 지금' : ''}</option>`).join('')
    + '<option value="archive">지난 학기 모아 보기…</option>';
  const b = $('#term-banner');
  if (isCurrentTerm()) b.classList.add('hidden');
  else {
    b.innerHTML = `<span>📚 <b>${termLabel(state.term)}</b> 기록을 보고 있어요. 대시보드·학급·초안이 이 학기 것만 보여요.</span> <button class="sm" id="tb-back">이번 학기(${termLabel(cur)})로 돌아가기</button>`;
    b.classList.remove('hidden');
    $('#tb-back').onclick = () => setTerm(cur);
  }
}
$('#term-select').addEventListener('change', e => {
  const v = e.target.value;
  if (v === 'archive') { renderTermSwitch(); location.hash = '#/archive'; return; }
  const [y, sm] = v.split('-').map(Number);
  setTerm({ year: y, semester: sm });
});

const CATEGORIES = ['발표', '토론', '탐구', '과제', '수업태도', '협업', '질문', '성장', '상담', '기타'];
const STATUS_COLOR = { '보관됨': 'amber', '대기중': 'blue', '전사중': 'blue', '전사완료': 'blue', '분리중': 'blue',
  '확인필요': 'amber', '완료': 'green', '오류': 'red', '일반메모': 'gray' };

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function neisBytes(t) {
  let n = 0;
  for (const ch of (t || '').replace(/\r\n/g, '\n')) n += ch === '\n' ? 2 : (ch.charCodeAt(0) < 128 ? 1 : 3);
  return n;
}
function today() { return new Date().toISOString().slice(0, 10); }
function nowLocal() {
  const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}
function fmtDate(s) { return s ? String(s).slice(0, 16).replace('T', ' ') : ''; }

async function api(path, body, opts) {
  opts = opts || {};
  const init = { method: body === undefined ? 'GET' : 'POST', headers: { 'X-Seteuk': '1' } };
  if (body !== undefined) {
    if (body instanceof Blob || body instanceof ArrayBuffer) { init.body = body; init.headers['Content-Type'] = 'application/octet-stream'; }
    else { init.body = JSON.stringify(body); init.headers['Content-Type'] = 'application/json'; }
  }
  let res;
  try { res = await fetch(path, init); }
  catch (e) { waitForServer(); throw new Error('프로그램(서버)과 연결이 끊겼습니다. "쓰담 시작"을 다시 실행하세요.'); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { const err = new Error(data.error || ('오류 ' + res.status)); if (!opts.silent) toast(err.message, true); throw err; }
  return data;
}

// 서버가 잠깐 내려가면(업데이트로 다시 켜지는 중) 안내를 띄우고, 다시 응답하면 새로고침
let waitingServer = false, quitting = false;
function waitForServer() {
  if (waitingServer || quitting) return;
  waitingServer = true;
  const ov = document.createElement('div');
  ov.className = 'restart-overlay'; ov.setAttribute('role', 'alertdialog'); ov.setAttribute('aria-live', 'assertive');
  ov.innerHTML = `<div class="restart-box">${MASCOT}<h2>새 버전으로 바꾸는 중…</h2><p class="muted">잠시만요. 끝나면 화면이 저절로 새로고침돼요.</p><span class="dots" aria-hidden="true"><i></i><i></i><i></i></span></div>`;
  setTimeout(() => { if (waitingServer) document.body.appendChild(ov); }, 600);
  const tick = async () => {
    try {
      const r = await fetch('/api/version', { cache: 'no-store' });
      if (r.ok) { location.reload(); return; }
    } catch (e) { /* 아직 */ }
    setTimeout(tick, 2000);
  };
  setTimeout(tick, 1500);
}

let toastTimer;
function toast(msg, isErr, action) {
  const t = $('#toast');
  t.textContent = msg; t.className = 'toast' + (isErr ? ' err' : '');
  if (action) {
    const b = document.createElement('button'); b.type = 'button'; b.textContent = action.label;
    b.onclick = async () => { t.classList.add('hidden'); await action.run(); };
    t.appendChild(b);
  }
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.add('hidden'), isErr ? 6000 : (action ? 6500 : 2600));
}
// 받침에 맞는 조사 (을/를)
function eul(word) {
  const w = String(word || '').replace(/[\s'")\]]+$/, ''), c = w.charCodeAt(w.length - 1);
  if (c >= 0xAC00 && c <= 0xD7A3) return (c - 0xAC00) % 28 ? '을' : '를';
  return /[0-9]$/.test(w) ? '을' : '을(를)';
}
// 휴지통으로 옮긴 뒤 '되돌리기' 버튼이 달린 알림
function trashedToast(what, res, after) {
  if (!res || !res.trash_id) { toast(`${what}${eul(what)} 지웠어요`); return; }
  toast(`${what}${eul(what)} 휴지통으로 옮겼어요`, false, { label: '되돌리기', run: async () => {
    await api('/api/trash/restore', { id: res.trash_id }); toast('되살렸어요'); after ? after() : router(true);
  } });
}

let modalReturnFocus = null;
function modal(html, onMount) {
  const wasOpen = !$('#modal').classList.contains('hidden');
  if (!wasOpen) modalReturnFocus = document.activeElement;
  const box = $('#modal-box');
  box.innerHTML = html;
  const h = $('h2', box);
  if (h) { h.id = 'modal-title'; box.setAttribute('aria-labelledby', 'modal-title'); } else box.removeAttribute('aria-labelledby');
  $('#modal').classList.remove('hidden');
  if (onMount) onMount(box);
  if (!box.contains(document.activeElement)) {
    const f = $('input:not([type=hidden]):not([disabled]), textarea, select, button.primary, button', box);
    if (f) f.focus();
  }
}
function closeModal() {
  if ($('#modal').classList.contains('hidden')) return;
  $('#modal').classList.add('hidden'); $('#modal-box').innerHTML = '';
  if (modalReturnFocus && document.body.contains(modalReturnFocus)) { try { modalReturnFocus.focus(); } catch (e) { /* */ } }
  modalReturnFocus = null;
}
$('#modal').addEventListener('mousedown', e => { if (e.target.id === 'modal') closeModal(); });
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { if (!$('#search').classList.contains('hidden')) closeSearch(); else closeModal(); }
});

function confirmBox(msg) { return window.confirm(msg); }

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); }
  catch (e) {
    const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); ta.remove();
  }
  toast('복사했습니다');
}

async function loadClasses() { state.classes = (await api('/api/classes')).classes; return state.classes; }
function classOptions(selected, allowEmpty) {
  let h = allowEmpty ? `<option value="">${allowEmpty === true ? '학급 미지정' : esc(allowEmpty)}</option>` : '';
  const opt = c => `<option value="${c.id}" ${String(c.id) === String(selected) ? 'selected' : ''}>${esc(c.label)} (${c.year}-${c.semester}학기)</option>`;
  const mine = termClasses(), others = state.classes.filter(c => !inTerm(c));
  if (!others.length) return h + mine.map(opt).join('');
  if (mine.length) h += `<optgroup label="${esc(termLabel(state.term))}">${mine.map(opt).join('')}</optgroup>`;
  return h + `<optgroup label="다른 학기">${others.map(opt).join('')}</optgroup>`;
}
function badge(status) { return `<span class="badge ${STATUS_COLOR[status] || ''}">${status === '일반메모' ? '📝 일반 메모' : esc(status)}</span>`; }
function kindBadge(kind) { return `<span class="badge ${kind === '상담' ? 'violet' : 'blue'}">${esc(kind || '수업')}</span>`; }

// ───────────────────────── AI 실행 (API / 수동) ─────────────────────────

// 쓰담 플러스 정성 초안 횟수 (쓰담 플러스를 쓰는 중일 때만, 아니면 null)
async function plusDeep() {
  try {
    const st = await api('/api/ai/state', undefined, { silent: true });
    if (!st.plus_enabled || st.choice !== 'plus') return null;
    const p = await api('/api/plus?refresh=0', undefined, { silent: true });
    return p.loggedIn && p.sub && p.sub.active ? { deepUsed: p.sub.deepUsed || 0, deepCap: p.sub.deepCap || 0 } : null;
  } catch (e) { return null; }
}

async function runAI(op, params, label, onDone, opts) {
  let res;
  try { res = await api('/api/ai/run', { op, params, label: label || '', manual: !!(opts && opts.manual) }, { silent: true }); }
  catch (e) {
    if (e.message === 'NEED_WHISPER_MODEL') {
      modal(`<h2>받아쓰기 모델이 필요합니다</h2><p>녹음을 이 맥 안에서 글자로 바꾸려면 Whisper 모델(550MB)을 한 번 내려받아야 합니다. 받는 동안 다른 작업을 계속해도 되고, 끝나면 이 녹음이 자동으로 받아써집니다.</p>
        <div class="modal-actions"><button id="m-x">나중에</button><button class="primary" id="m-dl">지금 내려받기</button></div>`, box => {
        $('#m-x', box).onclick = closeModal;
        $('#m-dl', box).onclick = async () => { await api('/api/whisper/download', { id: 'turbo-q5' }); closeModal(); toast('내려받기를 시작했습니다. 진행 상황은 설정 → 받아쓰기 엔진에서 볼 수 있어요.'); };
      });
      return;
    }
    toast(e.message, true); return;
  }
  if (res.manual) return showManual(op, params, res, onDone);
  toast('AI 작업을 시작했습니다. 오른쪽 아래에서 진행 상황을 볼 수 있어요.');
  pollJobs(true);
}

function showManual(op, params, res, onDone) {
  const titles = { transcribe: '받아쓰기 — ChatGPT·Gemini로', segment: '학생별 나누기 — ChatGPT·Gemini로', draft: '📋 세특 초안 — ChatGPT·Gemini로 쓰기', shorten: '초안 줄이기 — ChatGPT·Gemini로' };
  const audioStep = op === 'transcribe'
    ? `<li><b>녹음 파일도 함께 첨부</b>하세요. <button class="sm" id="m-reveal">녹음 파일 위치 열기</button> (Finder에서 파일을 Gemini 창으로 끌어다 놓기)</li>` : '';
  modal(`
    <h2>${titles[op] || 'AI 작업'}</h2>
    <div class="info-box"><ol>
      <li>아래 <b>프롬프트 복사</b> → ChatGPT·Gemini 앱(또는 웹) 새 대화에 붙여넣기 <a href="https://chatgpt.com" target="_blank">ChatGPT 열기</a> · <a href="https://gemini.google.com" target="_blank">Gemini 열기</a></li>
      ${audioStep}
      <li>AI의 답변 전체를 복사해서 아래 <b>결과 붙여넣기</b> 칸에 넣고 <b>적용</b></li>
    </ol></div>
    <div class="section-title" style="margin-top:14px"><h3>프롬프트</h3><button class="primary sm" id="m-copy">프롬프트 복사</button></div>
    <textarea class="prompt-box" readonly>${esc(res.prompt)}</textarea>
    <h3 style="margin-top:14px">결과 붙여넣기</h3>
    <textarea id="m-result" rows="9" placeholder="AI 답변을 여기에 붙여넣으세요"></textarea>
    <div class="modal-actions">
      <button id="m-cancel">닫기</button>
      <button class="primary" id="m-apply">적용</button>
    </div>`, box => {
    $('#m-copy', box).onclick = () => copyText(res.prompt);
    $('#m-cancel', box).onclick = closeModal;
    if ($('#m-reveal', box)) $('#m-reveal', box).onclick = () => api('/api/recordings/reveal', { id: params.recording_id });
    $('#m-apply', box).onclick = async () => {
      const text = $('#m-result', box).value.trim();
      if (!text) return toast('결과를 붙여넣으세요', true);
      const r = await api('/api/ai/apply', { op, params, text });
      closeModal();
      if (r.matched !== undefined) toast(`학생 배정 ${r.matched}건, 미배정 ${r.unmatched}건`);
      else toast('적용했습니다');
      if (onDone) onDone(r);
    };
  });
}

// ───────────────────────── 작업 진행 표시 ─────────────────────────

let AI_GEN = 0, AI_TIMER = null;   // 설정 → AI 화면 갱신 (화면을 다시 열 때마다 새 번호)
let showPlus = false, plusEmail = '', plusCodeSent = false;   // 화면을 다시 그려도(알림·작업 끝남) 쓰담 플러스 칸과 입력한 메일이 남게
let pollTimer;
async function pollJobs(force) {
  clearTimeout(pollTimer);
  try {
    const d = await api('/api/jobs', undefined, { silent: true });
    const prevActive = state.jobsActive;
    state.jobsActive = d.active;
    const fab = $('#jobs-fab');
    const recent = d.jobs.filter(j => j.status !== '완료' || isRecent(j.finished_at));
    if (d.active) {
      fab.innerHTML = `<span class="spinner"></span> AI 작업 ${d.active}개 진행 중`;
      fab.className = 'jobs-fab';
    } else if (d.jobs.length) {
      const failed = d.jobs.filter(j => j.status === '실패' && isRecent(j.finished_at)).length;
      fab.innerHTML = failed ? `⚠︎ 실패한 작업 ${failed}개` : 'AI 작업 기록';
      fab.className = 'jobs-fab idle';
    } else { fab.className = 'jobs-fab hidden'; $('#jobs-panel').classList.add('hidden'); }
    renderJobsPanel(d.jobs);
    const ids = d.jobs.filter(j => j.status === '완료' || j.status === '실패').map(j => j.id).join(',');
    if (state.lastJobIds && ids !== state.lastJobIds) {
      const newest = d.jobs.find(j => (j.status === '완료' || j.status === '실패') && !state.lastJobIds.split(',').includes(String(j.id)));
      if (newest) toast(newest.status === '완료' ? `완료: ${newest.label}` : `실패: ${newest.label} — ${newest.message}`, newest.status === '실패');
      refreshCurrent();
    }
    state.lastJobIds = ids;
    if (prevActive && !d.active) refreshCurrent();
  } catch (e) { /* 서버 재시작 중 */ }
  pollTimer = setTimeout(pollJobs, state.jobsActive ? 2500 : 8000);
}
function isRecent(ts) { return ts && (Date.now() - new Date(ts.replace(' ', 'T')).getTime()) < 30 * 60 * 1000; }

function renderJobsPanel(jobs) {
  const p = $('#jobs-panel');
  p.innerHTML = `<div class="section-title"><h3>AI 작업</h3><span>
      <button class="sm" id="jp-cancel">대기 작업 취소</button> <button class="sm" id="jp-clear">기록 지우기</button>
      <button class="sm ghost" id="jp-close" aria-label="닫기">✕</button></span></div>` +
    (jobs.length ? jobs.map(j => `<div class="job"><div><span class="badge ${{ '완료': 'green', '실패': 'red', '진행중': 'blue' }[j.status] || ''}">${esc(j.status)}</span> ${esc(j.label)}</div>
      ${j.message ? `<div class="msg">${esc(j.message)}</div>` : ''}<div class="msg">${esc(fmtDate(j.created_at))}</div></div>`).join('')
      : '<p class="muted">작업이 없습니다.</p>');
  $('#jp-clear', p).onclick = async () => { await api('/api/jobs/clear', {}); pollJobs(); };
  $('#jp-cancel', p).onclick = async () => { await api('/api/jobs/cancel', {}); pollJobs(); };
  $('#jp-close', p).onclick = () => p.classList.add('hidden');
}
$('#jobs-fab').onclick = e => { e.stopPropagation(); $('#jobs-panel').classList.toggle('hidden'); };
// 작업 창 밖을 누르거나 Esc 를 누르면 닫힘 (작업 버튼이 다른 안내에 가려져도 닫을 수 있게)
document.addEventListener('click', e => {
  const p = $('#jobs-panel');
  if (!p.classList.contains('hidden') && !p.contains(e.target) && e.target.id !== 'jobs-fab') p.classList.add('hidden');
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') $('#jobs-panel').classList.add('hidden'); });

let refreshPending = false;
// 나중에 그려진 칸(설정의 메일 칸 등)도 입력하면 '고치는 중'으로 표시
document.addEventListener('input', e => { if (e.target.matches && e.target.matches('input, textarea') && view.contains(e.target)) e.target.dataset.dirty = '1'; });
function refreshCurrent() {
  // 사용자가 입력 중이면 화면을 새로 그리지 않음
  const ae = document.activeElement;
  if (ae && (ae.tagName === 'TEXTAREA' || ae.tagName === 'INPUT') && view.contains(ae) && (ae.dataset.dirty || ae.type === 'email' || ae.closest('#ai-detail'))) { refreshPending = true; return; }
  if (!$('#modal').classList.contains('hidden')) { refreshPending = true; return; }
  router(true);
}

// ───────────────────────── 라우터 ─────────────────────────

async function router(soft) {
  const hash = location.hash.replace(/^#/, '') || '/';
  const parts = hash.split('/').filter(Boolean);
  const nav = { '': 'dashboard', recordings: 'recordings', recording: 'recordings', classes: 'classes', class: 'classes',
    student: 'classes', drafts: 'drafts', settings: 'settings', prompts: 'prompts', trash: 'trash', archive: 'archive' }[parts[0] || ''];
  $$('.sidebar nav a').forEach(a => {
    a.classList.toggle('active', a.dataset.nav === nav);
    if (a.dataset.nav === nav) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  // 메뉴마다 마지막으로 보던 화면 기억 (학생 화면을 보다가 다른 메뉴에 다녀와도 그대로)
  if (nav) { navMemory[nav] = '#' + hash; store('session', 'sseudam.navMemory', JSON.stringify(navMemory)); }
  state.nav = nav;
  // 메뉴 첫 화면 버튼: 그 메뉴의 안쪽 화면(학생·녹음 상세, 설정 탭 등)에 있을 때만 보임
  const navA = nav && $(`.sidebar nav a[data-nav="${nav}"]`), mh = $('#menu-home');
  if (navA && navA.getAttribute('href') !== '#' + hash && '#' + hash !== '#/') {
    mh.href = navA.getAttribute('href');
    $('span', mh).textContent = navA.querySelector('span').textContent + ' 처음으로';
    mh.setAttribute('aria-label', navA.querySelector('span').textContent + ' 첫 화면으로');
    mh.classList.remove('hidden');
  } else mh.classList.add('hidden');
  const scroll = soft ? window.scrollY : 0;
  if (!soft) { view.classList.remove('enter'); void view.offsetWidth; view.classList.add('enter'); }
  try {
    await loadClasses();
    renderTermSwitch();
    switch (parts[0]) {
      case undefined: await viewDashboard(); break;
      case 'recordings': await viewRecordings(parts[1]); break;
      case 'recording': await viewRecording(parts[1]); break;
      case 'classes': await viewClasses(); break;
      case 'class': await viewClass(parts[1]); break;
      case 'student': await viewStudent(parts[1], parts[2]); break;
      case 'drafts': await viewDrafts(parts[1], parts[2]); break;
      case 'settings': await viewSettings(parts[1]); break;
      case 'prompts': await viewPrompts(); break;
      case 'trash': await viewTrash(); break;
      case 'archive': await viewArchive(); break;
      default: await viewDashboard();
    }
  } catch (e) {
    view.innerHTML = `<div class="error-box">${esc(e.message)}</div>`;
  }
  window.scrollTo(0, scroll);
  // 입력 감지: 자동 새로고침이 입력을 지우지 않도록
  $$('textarea, input', view).forEach(el => el.addEventListener('input', () => { el.dataset.dirty = '1'; }));
}
window.addEventListener('hashchange', () => { closeModal(); router(false); });

// 왼쪽 메뉴: 다른 메뉴 → 그 메뉴에서 마지막으로 보던 화면 / 지금 메뉴를 한 번 더 → 그 메뉴 첫 화면 (휴대폰 탭처럼)
const navMemory = (() => { try { return JSON.parse(store('session', 'sseudam.navMemory') || '{}'); } catch (e) { return {}; } })();
document.addEventListener('click', e => {
  const a = e.target.closest('.sidebar nav a[data-nav]');
  if (!a || e.metaKey || e.ctrlKey) return;
  const target = a.dataset.nav === state.nav ? a.getAttribute('href') : (navMemory[a.dataset.nav] || a.getAttribute('href'));
  if (target !== location.hash) { e.preventDefault(); location.hash = target; }
});

// ───────────────────────── 대시보드 ─────────────────────────

const MASCOT = `<svg class="mascot-big" viewBox="0 0 48 48" aria-hidden="true"><defs><linearGradient id="mg2" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#5B7CFA"/><stop offset="1" stop-color="#9B8CF5"/></linearGradient></defs>
  <path d="M24 5c10.5 0 19 7.2 19 16.2S34.5 37.4 24 37.4c-1.6 0-3.1-.2-4.6-.5L11 42.6c-.9.6-2-.2-1.7-1.2l1.8-6.3C7.4 32.2 5 27 5 21.2 5 12.2 13.5 5 24 5z" fill="url(#mg2)"/>
  <circle cx="17.5" cy="20.5" r="2.6" fill="#fff"/><circle cx="30.5" cy="20.5" r="2.6" fill="#fff"/><path d="M19.5 27c2.6 2.4 6.4 2.4 9 0" stroke="#fff" stroke-width="2.4" stroke-linecap="round" fill="none"/>
  <circle cx="13" cy="26" r="2" fill="#FF8A73" opacity=".75"/><circle cx="35" cy="26" r="2" fill="#FF8A73" opacity=".75"/></svg>`;

async function viewDashboard() {
  const d = await api(`/api/dashboard?year=${state.term.year}&semester=${state.term.semester}`);
  const t = d.totals;
  if (!t.classes && t.all_classes) {
    const prev = termClasses(prevTerm(state.term));
    view.innerHTML = `<div class="empty card">${MASCOT}
      <h2>${termLabel(state.term)} 학급이 아직 없어요</h2>
      <p>${prev.length ? `지난 학기(${termLabel(prevTerm(state.term))}) 학급 ${prev.length}개의 명단을 그대로 가져올 수 있어요. 관찰기록은 옮기지 않아요.` : '학급을 만들고 명단을 붙여넣으면 시작할 수 있어요.'}</p>
      <div class="actions" style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap;margin-top:14px">
        ${prev.length ? '<button class="primary" id="dash-prep">✨ 새 학기 준비하기</button>' : ''}
        <a class="btn" href="#/classes">학급 만들기</a><a class="btn" href="#/archive">지난 학기 보기</a></div></div>`;
    if ($('#dash-prep')) $('#dash-prep').onclick = () => newTermModal({ from: prevTerm(state.term), to: state.term });
    return;
  }
  if (!t.classes) {
    view.innerHTML = `<div class="empty card">${MASCOT}
      <h2>쓰담에 오신 것을 환영합니다</h2>
      <p>수업 중 녹음한 학생 평가와 상담 기록을 학생별로 모아 세특 초안까지 만들어 주는 도구입니다.</p>
      <div class="steps">
        <div class="card"><b>1</b><h3>AI 고르기</h3><p class="muted small">설정 → 🧠 AI에서 '쓰담 AI 모델'을 누르면 이 컴퓨터에 맞는 AI를 알아서 받아요.</p><a href="#/settings/ai-card">AI 고르기 →</a></div>
        <div class="card"><b>2</b><h3>학급·명단 등록</h3><p class="muted small">학급을 만들고 NEIS 명단의 '번호, 이름'을 복사해 붙여넣습니다.</p><a href="#/classes">학급 만들기 →</a></div>
        <div class="card"><b>3</b><h3>녹음 올리기</h3><p class="muted small">아이폰 음성메모를 iCloud '쓰담 녹음' 폴더에 저장하거나 끌어다 놓습니다.</p><a href="#/recordings">녹음함 →</a></div>
        <div class="card"><b>4</b><h3>세특 초안</h3><p class="muted small">학생별로 쌓인 관찰기록으로 초안을 만들고 구글시트로 보냅니다.</p><a href="#/drafts">세특 초안 →</a></div>
      </div></div>`;
    return;
  }
  const pct = (a, b) => b ? Math.round(a / b * 100) : 0;
  view.innerHTML = `
    <div class="page-head"><div><h1>${teacherHello()}</h1><div class="muted">${new Date().toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' })} · ${termLabel(state.term)}</div></div>
      <div class="actions"><button id="dash-xlsx">전체 엑셀로 저장</button><a class="btn primary" href="#/recordings">+ 녹음 올리기</a></div></div>
    <div id="wh-banner"></div>
    <div class="stats fun">
      <div class="stat pop" style="--d:0">
        <div class="label">👩‍🎓 학생</div><div class="value" data-count="${t.students}">0</div>
        <div class="sub">${t.classes}개 학급</div>${peopleDots(t.students, t.with_notes)}</div>
      <div class="stat pop" style="--d:1">
        <div class="label">🎙 녹음·기록</div><div class="value" data-count="${t.recordings}">0</div>
        <div class="sub">${t.pending_review ? `<a href="#/recordings">확인 필요 ${t.pending_review}건</a>` : '모두 처리됨 ✓'}</div>${sparkline(d.weeks.map(w => w['수업'] + w['상담']))}</div>
      <div class="stat pop" style="--d:2">
        <div class="label">📝 관찰기록</div><div class="value" data-count="${t.notes}">0</div>
        <div class="sub">학생당 평균 ${t.students ? (t.notes / t.students).toFixed(1) : 0}건</div>${miniBar(t.students ? t.notes / t.students : 0, 10, 'var(--mint)')}</div>
      <div class="stat pop ring-stat" style="--d:3">
        ${donut(pct(t.with_notes, t.students), 'url(#gradBrand)', '기록 있는 학생', `${t.with_notes}/${t.students}명`)}</div>
      <div class="stat pop ring-stat" style="--d:4">
        ${donut(pct(t.drafted, t.students), 'var(--mint)', '세특 초안', `확정 ${t.finalized}명`)}</div>
    </div>
    <div class="grid grid-2">
      <div class="card">
        <div class="section-title"><h2>학급별 진행</h2><div class="legend"><span><i style="background:var(--grad)"></i>기록 있음</span><span><i style="background:var(--mint)"></i>초안 작성</span></div></div>
        <div class="class-progress">${d.classes.map((c, i) => {
          const a = pct(c.with_notes, c.students), b = pct(c.drafted, c.students);
          return `<a class="cp-row" href="#/drafts/${c.id}" style="--d:${i}">
            <div class="cp-head"><b>${esc(c.label)}</b><span class="small muted">학생 ${c.students} · 기록 ${c.notes} · 녹음 ${c.recordings}</span>${a === 100 && c.students ? '<span class="cp-party" title="모든 학생 기록 완료!">🎉</span>' : ''}</div>
            <div class="gbar"><i style="--w:${a}%"></i><em>${a}%</em></div>
            <div class="gbar mint"><i style="--w:${b}%"></i><em>${b}%</em></div></a>`;
        }).join('')}</div>
      </div>
      <div class="card chart">
        <div class="section-title"><h2>주간 관찰기록</h2>${weekCheer(d.weeks)}</div>
        ${weeklyChart(d.weeks)}
        <h3 style="margin-top:16px">영역 분포</h3>
        ${areaBar(d.categories)}
      </div>
      <div class="card">
        <h2>기록이 부족한 학생</h2>
        <p class="help" style="margin-top:-6px;margin-bottom:10px">다음 수업에서 관찰해 보면 좋은 학생들입니다.</p>
        ${d.needy.length ? '' : '<p class="muted small">아직 학생이 없어요</p>'}
        <div class="needy">${d.needy.map((s, i) => `<a class="needy-chip pop" style="--d:${i}" href="#/student/${s.id}" title="${esc(s.label)}${s.last_date ? ' · 최근 ' + esc(s.last_date) : ''}">
          <span class="nc-face">${s.notes ? '🌿' : '🌱'}</span><span><b>${esc(s.name)}</b><small>${esc(s.label)} · ${s.number}번</small></span>
          <span class="nc-count ${s.notes ? '' : 'zero'}">${s.notes}</span></a>`).join('')}</div>
      </div>
      <div class="card">
        <div class="section-title"><h2>최근 녹음</h2><a href="#/recordings" class="small">전체 보기</a></div>
        <table><tbody>${d.recent.map(r => `<tr class="clickable" data-href="#/recording/${r.id}">
          <td class="small muted nowrap">${esc(fmtDate(r.recorded_at))}</td><td>${kindBadge(r.kind)} ${esc(r.title)}<div class="small muted">${esc(r.label)}</div></td>
          <td class="right nowrap">${badge(r.status)}<div class="small muted">학생기록 ${r.notes}</div></td></tr>`).join('') || '<tr><td class="muted">아직 녹음이 없습니다</td></tr>'}</tbody></table>
      </div>
    </div>`;
  bindRowLinks();
  $('#dash-xlsx').onclick = () => exportXlsx(null);
  whisperBanner($('#wh-banner'));
  animateIn(view);
}

// ───────── 귀여운 차트 (SVG + CSS 애니메이션, 외부 라이브러리 없음) ─────────
const REDUCED = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

/** 숫자가 0부터 톡톡 올라가고, 막대·링이 차오르게 */
function animateIn(root) {
  $$('[data-count]', root).forEach(el => {
    const to = +el.dataset.count || 0;
    if (REDUCED || to === 0) { el.textContent = to.toLocaleString(); return; }
    const t0 = performance.now(), dur = 900 + Math.min(600, to * 6);
    const step = now => {
      const k = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      el.textContent = Math.round(to * e).toLocaleString();
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
  requestAnimationFrame(() => requestAnimationFrame(() => root.classList.add('animated')));
}

const SVG_DEFS = `<defs><linearGradient id="gradBrand" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#5B7CFA"/><stop offset="1" stop-color="#9B8CF5"/></linearGradient>
  <linearGradient id="gradCol" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#5B7CFA"/><stop offset="1" stop-color="#9B8CF5"/></linearGradient></defs>`;

/** 도넛 링: 가운데 % 가 함께 올라감 */
function donut(p, color, label, sub) {
  const r = 30, c = 2 * Math.PI * r;
  const face = p >= 100 ? '🎉' : p >= 60 ? '😊' : p >= 30 ? '🙂' : '🌱';
  return `<div class="donut"><svg viewBox="0 0 80 80" aria-hidden="true">${SVG_DEFS}
      <circle cx="40" cy="40" r="${r}" fill="none" stroke="var(--line)" stroke-width="9"/>
      <circle class="ring" cx="40" cy="40" r="${r}" fill="none" stroke="${color}" stroke-width="9" stroke-linecap="round"
        stroke-dasharray="${c}" style="--off:${c * (1 - p / 100)};--full:${c}" transform="rotate(-90 40 40)"/></svg>
      <div class="donut-in"><b data-count="${p}">0</b><small>%</small></div></div>
    <div class="donut-txt"><div class="label">${label} ${face}</div><div class="sub">${sub}</div></div>`;
}

/** 학생 수만큼 동그라미 (기록 있는 학생은 색칠) — 최대 30개 */
function peopleDots(total, filled) {
  const n = Math.min(total, 30);
  if (!n) return '';
  const on = Math.round(filled * n / Math.max(1, total));
  return `<div class="dots" aria-hidden="true">${Array.from({ length: n }, (_, i) => `<i class="${i < on ? 'on' : ''}" style="--i:${i}"></i>`).join('')}</div>`;
}

/** 주간 합계 미니 선 그래프 */
function sparkline(vals) {
  if (!vals.length) return '';
  const W = 120, H = 30, max = Math.max(1, ...vals);
  const pts = vals.map((v, i) => [i * W / (vals.length - 1 || 1), H - 3 - (H - 6) * v / max]);
  const d = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
  const last = pts[pts.length - 1];
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" aria-hidden="true"><path class="spark-line" d="${d}" pathLength="1"/>
    <circle class="spark-dot" cx="${last[0]}" cy="${last[1]}" r="3.2"/></svg>`;
}

function miniBar(v, max, color) {
  return `<div class="minibar" aria-hidden="true"><i style="--w:${Math.min(100, v / max * 100)}%;background:${color}"></i></div>`;
}

/** 이번 주 응원 한마디 */
function weekCheer(weeks) {
  const n = weeks.length ? weeks[weeks.length - 1]['수업'] + weeks[weeks.length - 1]['상담'] : 0;
  const prev = weeks.length > 1 ? weeks[weeks.length - 2]['수업'] + weeks[weeks.length - 2]['상담'] : 0;
  const msg = n === 0 ? '이번 주 첫 기록을 담아 볼까요? 🌱' : n > prev ? `이번 주 ${n}개! 지난주보다 늘었어요 📈` : `이번 주 ${n}개 담았어요 ✨`;
  return `<span class="cheer">${msg}</span>`;
}

/** 영역 분포: 알록달록 한 줄 막대 + 범례 */
function areaBar(cats) {
  if (!cats || !cats.length) return '<span class="muted small">아직 기록이 없습니다</span>';
  const total = cats.reduce((a, c) => a + c.n, 0) || 1;
  const colors = ['var(--accent-fill)', 'var(--violet)', 'var(--mint)', 'var(--butter)', 'var(--coral)', '#7CC4F5', '#C9A7F5'];
  return `<div class="areabar">${cats.map((c, i) => `<i style="--w:${c.n / total * 100}%;background:${colors[i % colors.length]};--i:${i}" title="${esc(c.category)} ${c.n}건"></i>`).join('')}</div>
    <div class="legend wrap">${cats.map((c, i) => `<span><i style="background:${colors[i % colors.length]}"></i>${esc(c.category)} ${c.n}</span>`).join('')}</div>`;
}

function teacherHello() {
  const n = (state.settings && state.settings.teacher_name) || '';
  const h = new Date().getHours();
  const hi = h < 11 ? '좋은 아침이에요' : h < 17 ? '안녕하세요' : '오늘도 수고 많으셨어요';
  return n ? `${esc(n)} 선생님, ${hi}` : `${hi} 👋`;
}

function weeklyChart(weeks) {
  const W = 560, H = 200, pad = { l: 28, r: 8, t: 14, b: 24 };
  const max = Math.max(4, ...weeks.map(w => w['수업'] + w['상담']));
  const step = Math.ceil(max / 4);
  const top = step * 4;
  const bw = (W - pad.l - pad.r) / weeks.length;
  const y = v => pad.t + (H - pad.t - pad.b) * (1 - v / top);
  let s = `<svg class="weekly" viewBox="0 0 ${W} ${H}" role="img" aria-label="주간 관찰기록 수">${SVG_DEFS}`;
  for (let i = 0; i <= 4; i++) {
    const v = step * i;
    s += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)" stroke-width="1" stroke-dasharray="${i ? '3 4' : ''}"/>`;
    s += `<text x="${pad.l - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
  }
  weeks.forEach((w, i) => {
    const x = pad.l + i * bw + bw * 0.2, bwi = bw * 0.6;
    const a = w['수업'], b = w['상담'], tot = a + b;
    const cur = i === weeks.length - 1;
    s += `<g class="col ${cur ? 'cur' : ''}" style="--i:${i};transform-origin:${x + bwi / 2}px ${y(0)}px">`;
    if (a) s += `<rect x="${x}" y="${y(a)}" width="${bwi}" height="${y(0) - y(a)}" rx="${Math.min(8, bwi / 2)}" fill="url(#gradCol)"><title>${w.label} 주 수업 ${a}건</title></rect>`;
    if (b) s += `<rect x="${x}" y="${y(tot)}" width="${bwi}" height="${y(a) - y(tot)}" rx="${Math.min(8, bwi / 2)}" fill="var(--coral)"><title>${w.label} 주 상담 ${b}건</title></rect>`;
    if (!tot) s += `<circle cx="${x + bwi / 2}" cy="${y(0) - 4}" r="2.5" fill="var(--line-strong)"/>`;
    if (tot && cur) s += `<text class="col-num" x="${x + bwi / 2}" y="${y(tot) - 6}" text-anchor="middle">${tot}</text>`;
    s += `</g>`;
    if (i % 2 === weeks.length % 2 || cur) s += `<text x="${x + bwi / 2}" y="${H - 6}" text-anchor="middle" class="${cur ? 'cur-label' : ''}">${cur ? '이번 주' : w.label}</text>`;
  });
  return s + '</svg>';
}

function bindRowLinks(root) {
  $$('tr[data-href]', root).forEach(tr => tr.addEventListener('click', e => {
    if (e.target.closest('button, a, input, select, textarea')) return;
    location.hash = tr.dataset.href;
  }));
}

// ───────────────────────── 녹음함 ─────────────────────────

async function viewRecordings(classFilter) {
  const [recs, settings] = await Promise.all([
    api('/api/recordings' + (classFilter ? '?class_id=' + classFilter : '')), api('/api/settings')]);
  state.settings = settings;
  const isApi = true;   // 받아쓰기(내 컴퓨터)·학생 나누기는 키 없이도 됨
  view.innerHTML = `
    <div class="page-head"><div><h1>녹음함</h1><div class="muted">수업 평가·상담 녹음을 보관하고, 전사·학생별 분리를 진행합니다.</div></div>
      <div class="actions"><a class="btn" href="#/settings/import">가져오기 설정</a><button class="primary" id="btn-scan">아이폰 기록 지금 가져오기</button></div></div>
    <div id="src-line" class="help" style="margin:-10px 0 14px"></div>
    <div id="wh-banner"></div>
    <div class="card">
      <div class="tabs"><button class="on" data-tab="audio">녹음 파일 올리기</button><button data-tab="paste">전사문 붙여넣기</button></div>
      <div class="row" style="margin-bottom:12px">
        <label class="field"><span>학급</span><select id="up-class">${classOptions('', '자동 (파일명·내용에서 추정)')}</select></label>
        <label class="field shrink" style="min-width:120px"><span>유형</span><select id="up-kind"><option value="">자동</option><option>수업</option><option>상담</option></select></label>
        <label class="field"><span>녹음 일시 (비우면 파일 시각)</span><input type="datetime-local" id="up-date"></label>
        <label class="field"><span>제목 (선택)</span><input id="up-title" placeholder="예: 3교시 토론 수업"></label>
      </div>
      <div data-pane="audio">
        <div class="dropzone" id="drop" role="button" tabindex="0" aria-label="녹음 파일 고르기"><strong>여기에 녹음 파일을 끌어다 놓거나 클릭해서 선택</strong>m4a, mp3, wav 등 · 여러 개 가능 · 텍스트(.txt) 전사본도 가능</div>
        <input type="file" id="file" multiple accept="audio/*,.m4a,.txt" class="hidden">
        <label class="check" style="margin-top:10px"><input type="checkbox" id="up-auto" ${isApi ? 'checked' : 'disabled'}> 올린 뒤 자동으로 전사 → 학생별 분리 </label>
      </div>
      <div data-pane="paste" class="hidden">
        <textarea id="paste-text" rows="8" placeholder="클로바노트 등 다른 앱에서 받은 전사문, 또는 직접 정리한 메모를 붙여넣으세요.&#10;예) 3번 김민수 오늘 발표에서 근거 자료를 3가지 제시하며 논리적으로 설명함. 5번 이서연은 모둠 토론에서..."></textarea>
        <div class="row" style="margin-top:10px"><label class="check shrink"><input type="checkbox" id="paste-auto" ${isApi ? 'checked' : ''}> 저장 후 바로 학생별 분리</label><span></span>
          <button class="primary shrink" id="paste-save">저장</button></div>
      </div>
    </div>
    <div class="card">
      <div class="section-title"><h2>보관된 녹음 ${recs.recordings.length}건</h2>
        <select id="rec-filter" style="width:auto">${classOptions(classFilter || '', '전체 학급')}</select></div>
      ${recs.recordings.length ? `<div class="table-wrap"><table>
        <thead><tr><th>일시</th><th>유형</th><th>제목</th><th>학급</th><th>상태</th><th class="right">학생기록</th></tr></thead>
        <tbody>${recs.recordings.map(r => `<tr class="clickable" data-href="#/recording/${r.id}">
          <td class="nowrap small">${esc(fmtDate(r.recorded_at))}</td><td>${kindBadge(r.kind)}</td>
          <td>${esc(r.title)}${r.has_audio ? ' <span class="muted small">🎙</span>' : ''}${r.error ? `<div class="small" style="color:var(--red)">${esc(r.error.slice(0, 80))}</div>` : ''}</td>
          <td class="small">${esc(r.label)}</td><td>${badge(r.status)}</td>
          <td class="num">${r.notes}${r.unmatched ? ` <span class="badge amber">미배정 ${r.unmatched}</span>` : ''}</td></tr>`).join('')}</tbody></table></div>`
      : '<p class="muted">아직 보관된 녹음이 없습니다.</p>'}
      <p class="help">수신 폴더: <code>${esc(settings.inbox_dir)}</code> ${settings.inbox_exists ? '' : '<span class="badge amber">폴더 없음 — 설정에서 만들기</span>'} · 20초마다 자동 확인</p>
    </div>`;
  bindRowLinks();
  $$('.tabs button').forEach(b => b.onclick = () => {
    $$('.tabs button').forEach(x => x.classList.toggle('on', x === b));
    $$('[data-pane]').forEach(p => p.classList.toggle('hidden', p.dataset.pane !== b.dataset.tab));
  });
  whisperBanner($('#wh-banner'));
  $('#rec-filter').onchange = e => { location.hash = '#/recordings' + (e.target.value ? '/' + e.target.value : ''); };
  $('#btn-scan').onclick = async () => {
    $('#btn-scan').disabled = true; $('#btn-scan').textContent = '가져오는 중…';
    try { const r = await api('/api/inbox/scan', {}); toast(r.message, r.errors && r.errors.length); }
    finally { router(true); }
  };
  api('/api/sources', undefined, { silent: true }).then(src => {
    const parts = [];
    if (src.voicememo.enabled) parts.push(`음성메모 자동 ${src.voicememo.access === 'ok' ? '<span class="ok-text">켜짐</span>' : '<span class="bad-text">권한 필요</span>'}`);
    if (src.notes.enabled) parts.push(`메모 앱 '${esc(src.notes.folder)}' 폴더 <span class="ok-text">켜짐</span>`);
    parts.push(`iCloud 쓰담 녹음 폴더 ${src.inbox.exists ? '<span class="ok-text">켜짐</span>' : '없음'}`);
    $('#src-line').innerHTML = '자동 가져오기: ' + parts.join(' · ') + (src.voicememo.enabled || src.notes.enabled ? '' : ' — <a href="#/settings/import">음성메모·메모 앱 자동 가져오기 켜기</a>');
  }).catch(() => {});
  const drop = $('#drop'), file = $('#file');
  drop.onclick = () => file.click();
  drop.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); file.click(); } };
  drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); };
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove('over'); uploadFiles(e.dataTransfer.files); };
  file.onchange = () => uploadFiles(file.files);
  $('#paste-save').onclick = async () => {
    const text = $('#paste-text').value.trim();
    if (!text) return toast('전사문을 붙여넣으세요', true);
    const r = await api('/api/recordings/paste', {
      transcript: text, class_id: $('#up-class').value || null, kind: $('#up-kind').value || '수업',
      title: $('#up-title').value || '붙여넣은 기록', recorded_at: ($('#up-date').value || nowLocal()).replace('T', ' '),
    });
    if ($('#paste-auto').checked) {
      location.hash = '#/recording/' + r.id;
      setTimeout(() => runAI('segment', { recording_id: r.id }, '#' + r.id, () => router(true)), 300);
    } else location.hash = '#/recording/' + r.id;
  };
}

async function uploadFiles(files) {
  if (!files || !files.length) return;
  const q = new URLSearchParams({
    class_id: $('#up-class').value, kind: $('#up-kind').value, title: files.length === 1 ? $('#up-title').value : '',
    recorded_at: ($('#up-date').value || '').replace('T', ' '), auto: $('#up-auto').checked ? '1' : '0',
  });
  let ok = 0;
  for (const f of files) {
    toast(`올리는 중… ${f.name}`);
    q.set('filename', f.name);
    try { await api('/api/recordings/upload?' + q.toString(), f); ok++; } catch (e) { /* toast 표시됨 */ }
  }
  toast(`${ok}개 파일을 보관했습니다`);
  pollJobs(true);
  router(true);
}

// ───────────────────────── 녹음 상세 ─────────────────────────

async function viewRecording(id) {
  const d = await api('/api/recordings/' + id);
  const r = d.recording;
  const byStudent = {};
  d.notes.forEach(n => { (byStudent[n.student_id] = byStudent[n.student_id] || { name: n.name, number: n.number, items: [] }).items.push(n); });
  // 학급을 안 정한 녹음은 이번 학기 모든 반 학생이 반별로 묶여 옴
  const studentOpts = sel => {
    const opt = s => `<option value="${s.id}" ${s.id === sel ? 'selected' : ''}>${s.number != null ? s.number + '번 ' : ''}${esc(s.name)}</option>`;
    if (!d.students.length) return '<option value="">학급·명단이 아직 없어요</option>';
    if (!d.students[0].class_label) return '<option value="">학생 선택…</option>' + d.students.map(opt).join('');
    const groups = {};
    d.students.forEach(s => (groups[s.class_label] = groups[s.class_label] || []).push(s));
    return '<option value="">학생 선택…</option>' + Object.entries(groups).map(([g, ss]) => `<optgroup label="${esc(g)}">${ss.map(opt).join('')}</optgroup>`).join('');
  };
  const busy = ['대기중', '전사중', '분리중'].includes(r.status);
  view.innerHTML = `
    <div class="page-head"><div><a href="#/recordings" class="back-btn" aria-label="녹음함으로 돌아가기"><span aria-hidden="true">←</span> 녹음함</a><h1>${esc(r.title || '녹음')}</h1>
      <div>${kindBadge(r.kind)} ${badge(r.status)} <span class="muted small">${esc(fmtDate(r.recorded_at))} · ${esc(r.original_name || '')}</span></div></div>
      <div class="actions">
        ${r.has_audio ? `<button id="b-reveal">Finder에서 보기</button>` : ''}
        <button class="danger" id="b-del">휴지통으로</button></div></div>
    ${r.error ? `<div class="error-box">${esc(r.error)}</div>` : ''}
    <div class="split">
      <div class="stack">
        <div class="card">
          <h2>기본 정보</h2>
          <div class="row">
            <label class="field"><span>학급</span><select id="r-class">${classOptions(r.class_id, true)}</select></label>
            <label class="field shrink" style="min-width:110px"><span>유형</span><select id="r-kind"><option ${r.kind === '수업' ? 'selected' : ''}>수업</option><option ${r.kind === '상담' ? 'selected' : ''}>상담</option></select></label>
          </div>
          <div class="row" style="margin-top:10px">
            <label class="field"><span>제목</span><input id="r-title" value="${esc(r.title)}"></label>
            <label class="field"><span>일시</span><input type="datetime-local" id="r-date" value="${esc((r.recorded_at || '').replace(' ', 'T').slice(0, 16))}"></label>
            <button class="shrink" id="r-save">저장</button>
          </div>
          ${r.has_audio ? `<audio controls preload="none" src="/audio/${r.id}"></audio>` : ''}
        </div>
        <div class="card">
          <div class="section-title"><h2>전사문</h2>
            <span>${r.has_audio ? `<button class="${r.transcript ? '' : 'primary'}" id="b-trans" ${busy ? 'disabled' : ''}>${r.transcript ? '다시 받아쓰기' : '받아쓰기 시작'}</button>` : ''}</span></div>
          <textarea id="r-transcript" rows="16" placeholder="${r.has_audio ? 'AI 전사 결과가 여기에 표시됩니다. 다른 앱의 전사문을 직접 붙여넣어도 됩니다.' : '전사문'}">${esc(r.transcript)}</textarea>
          <div class="row" style="margin-top:8px"><span class="muted small">${(r.transcript || '').length.toLocaleString()}자 · 이름 오인식은 여기서 고친 뒤 다시 분리하면 정확해집니다</span>
            <button class="shrink" id="b-save-trans">전사문 저장</button></div>
        </div>
      </div>
      <div class="stack">
        <div class="card">
          <div class="section-title"><h2>학생별 분리 결과</h2>
            <span><button class="primary" id="b-seg" ${busy || !r.transcript ? 'disabled' : ''}>${d.notes.length ? 'AI로 다시 분리' : 'AI로 학생별 분리'}</button>
            <button id="b-rule" ${!r.transcript ? 'disabled' : ''} title="AI 없이 이름이 언급된 위치로 나눕니다">이름 기준 분리(AI 없이)</button>
            ${r.status !== '일반메모' ? `<button id="b-general" class="ghost" title="회의·개인 메모처럼 학생 이야기가 아닌 녹음">📝 일반 메모로 표시</button>` : ''}</span></div>
          ${r.status === '일반메모' ? `<div class="general-memo">📝 <b>일반 메모</b> — 학생 이야기가 아니라서 학생 기록에 넣지 않았어요. 녹음과 글은 그대로 남아 있어요.
              <div style="margin-top:8px"><button class="sm" id="b-ungeneral">학생 기록으로 다시 나누기</button></div></div>`
            : (!r.class_id ? '<div class="warn">학급을 지정해야 학생 명단과 대조할 수 있습니다. (AI 분리 시 전사문에서 학급을 찾으면 자동 지정)</div>' : '')}
          ${d.notes.length || r.status === '일반메모' ? '' : '<p class="muted">아직 분리된 내용이 없습니다.</p>'}
          ${Object.entries(byStudent).map(([sid, g]) => `<div class="student-group">
            <h3><a href="#/student/${sid}">${g.number}번 ${esc(g.name)}</a> <span class="badge">${g.items.length}건</span></h3>
            ${g.items.map(n => `<div class="note" data-note="${n.id}">
              <div class="meta"><span class="badge blue">${esc(n.category || '기타')}</span>
                <span class="tools">${d.areas.length > 1 ? `<select class="n-area" style="width:auto;padding:2px 6px;font-size:12px">${areaOptions(d.areas, n.area_eff)}</select>` : ''}<select class="n-move" style="width:auto;padding:2px 6px;font-size:12px">${studentOpts(n.student_id)}</select>
                <button class="sm n-edit">수정</button><button class="sm danger n-del" aria-label="이 관찰기록 휴지통으로">삭제</button></span></div>
              <div class="content">${esc(n.content)}</div>
              ${n.evidence ? `<div class="evidence">${esc(n.evidence)}</div>` : ''}</div>`).join('')}
          </div>`).join('')}
        </div>
        ${d.unmatched.length ? `<div class="card">
          <h2>미배정 언급 ${d.unmatched.length}건</h2>
          <p class="help" style="margin-top:-6px">명단과 일치하지 않은 이름입니다. 학생을 골라 배정하거나 삭제하세요. 자주 틀리는 이름은 학생 '별칭'에 추가해 두면 다음부터 자동 배정됩니다.</p>
          ${d.unmatched.map(u => `<div class="note" data-un="${u.id}">
            <div class="meta"><span class="badge amber">들린 이름: ${esc(u.name_heard || '?')}</span>
              <span class="tools"><select class="u-assign" style="width:auto;padding:2px 6px;font-size:12px">${studentOpts(null)}</select>
              <button class="sm danger u-del">삭제</button></span></div>
            <div class="content">${esc(u.content)}</div>${u.evidence ? `<div class="evidence">${esc(u.evidence)}</div>` : ''}</div>`).join('')}
        </div>` : ''}
        ${r.status === '확인필요' && !d.unmatched.length ? `<button class="primary" id="b-done">확인 완료로 표시</button>` : ''}
      </div>
    </div>`;

  const reload = () => router(true);
  if ($('#b-reveal')) $('#b-reveal').onclick = () => api('/api/recordings/reveal', { id: r.id });
  $('#b-del').onclick = async () => {
    if (!confirmBox('이 녹음을 휴지통으로 옮길까요?\n30일 안에 되살릴 수 있어요. (이 녹음에서 나온 학생 관찰기록은 그대로 남아요)')) return;
    const delAudio = r.has_audio && confirmBox('휴지통을 비울 때 녹음 파일도 함께 지울까요?\n[확인] 파일도 지움  [취소] 파일은 남김');
    const res = await api('/api/recordings/delete', { id: r.id, delete_audio: delAudio });
    location.hash = '#/recordings';
    trashedToast('녹음', res, () => { location.hash = '#/recording/' + r.id; });
  };
  $('#r-save').onclick = async () => {
    await api('/api/recordings/update', { id: r.id, class_id: $('#r-class').value || null, kind: $('#r-kind').value,
      title: $('#r-title').value, recorded_at: $('#r-date').value.replace('T', ' ') });
    toast('저장했습니다'); reload();
  };
  $('#r-class').onchange = $('#r-save').onclick;
  $('#b-save-trans').onclick = async () => {
    await api('/api/recordings/update', { id: r.id, transcript: $('#r-transcript').value });
    toast('전사문을 저장했습니다'); reload();
  };
  if ($('#b-trans')) $('#b-trans').onclick = () => runAI('transcribe', { recording_id: r.id, chain: false }, '#' + r.id, reload);
  $('#b-seg').onclick = async () => {
    if (d.notes.length && !confirmBox('다시 분리하면 이 녹음에서 나온 기존 학생기록(수정 내용 포함)이 새 결과로 바뀝니다. 계속할까요?')) return;
    if ($('#r-transcript').dataset.dirty) await api('/api/recordings/update', { id: r.id, transcript: $('#r-transcript').value });
    runAI('segment', { recording_id: r.id }, '#' + r.id, reload);
  };
  $('#b-rule').onclick = async () => {
    if (d.notes.length && !confirmBox('기존 분리 결과가 바뀝니다. 계속할까요?')) return;
    if ($('#r-transcript').dataset.dirty) await api('/api/recordings/update', { id: r.id, transcript: $('#r-transcript').value });
    const res = await api('/api/recordings/rule_segment', { id: r.id });
    toast(`${res.matched}개 구간으로 나눴습니다. 내용을 확인·수정하세요.`); reload();
  };
  if ($('#b-done')) $('#b-done').onclick = async () => { await api('/api/recordings/mark_done', { id: r.id }); reload(); };
  if ($('#b-general')) $('#b-general').onclick = async () => {
    if (d.notes.length && !confirmBox(`이 녹음에서 나온 학생 기록 ${d.notes.length}개를 휴지통으로 옮기고 일반 메모로 표시할까요?\n(30일 안에 휴지통에서 되살릴 수 있어요)`)) return;
    const res = await api('/api/recordings/mark_general', { id: r.id, general: true });
    toast(res.moved ? `📝 일반 메모로 표시했어요 · 학생 기록 ${res.moved}개는 휴지통으로` : '📝 일반 메모로 표시했어요'); reload();
  };
  if ($('#b-ungeneral')) $('#b-ungeneral').onclick = async () => {
    await api('/api/recordings/mark_general', { id: r.id, general: false });
    toast('학생 기록으로 다시 나누는 중이에요'); setTimeout(reload, 1200);
  };
  $$('[data-note]').forEach(el => {
    const nid = +el.dataset.note, n = d.notes.find(x => x.id === nid);
    $('.n-del', el).onclick = async () => { const res = await api('/api/notes/delete', { id: nid }); trashedToast('관찰기록', res); reload(); };
    $('.n-move', el).onchange = async e => {
      if (!e.target.value) return;
      await api('/api/notes/save', { ...n, student_id: +e.target.value, use_in_draft: !!n.use_in_draft }); toast('학생을 변경했습니다'); reload();
    };
    $('.n-edit', el).onclick = () => editNoteModal(n, reload, n.student_id, d.areas);
    if ($('.n-area', el)) $('.n-area', el).onchange = async e => { await api('/api/notes/save', { ...n, area: e.target.value, use_in_draft: !!n.use_in_draft }); toast('기재 영역을 바꿨습니다'); };
  });
  $$('[data-un]').forEach(el => {
    const uid = +el.dataset.un;
    $('.u-del', el).onclick = async () => { await api('/api/unmatched/delete', { id: uid }); reload(); };
    $('.u-assign', el).onchange = async e => {
      if (!e.target.value) return;
      await api('/api/unmatched/assign', { id: uid, student_id: +e.target.value }); toast('배정했습니다'); reload();
    };
  });
}

function areaOptions(areas, sel) {
  return areas.map(a => `<option value="${a.id}" ${a.id === sel ? 'selected' : ''}>${esc(a.name)}</option>`).join('');
}

function editNoteModal(n, onSaved, studentId, areas) {
  const isNew = !n;
  areas = areas || [];
  n = n || { date: today(), kind: '수업', category: '', content: '', use_in_draft: 1, student_id: studentId, area: '' };
  const cur = n.area || n.area_eff || (areas[0] && areas[0].id) || '';
  modal(`<h2>${isNew ? '관찰기록 추가' : '관찰기록 수정'}</h2>
    <div class="row">
      <label class="field"><span>날짜</span><input type="date" id="e-date" value="${esc(n.date || today())}"></label>
      <label class="field"><span>유형</span><select id="e-kind"><option ${n.kind === '수업' ? 'selected' : ''}>수업</option><option ${n.kind === '상담' ? 'selected' : ''}>상담</option></select></label>
      ${areas.length > 1 ? `<label class="field"><span>기재 영역</span><select id="e-area">${areaOptions(areas, cur)}</select></label>` : ''}
      <label class="field"><span>분류</span><select id="e-cat">${CATEGORIES.map(c => `<option ${c === n.category ? 'selected' : ''}>${c}</option>`).join('')}</select></label>
    </div>
    <label class="field" style="margin-top:10px"><span>내용</span><textarea id="e-content" rows="6">${esc(n.content)}</textarea></label>
    <label class="check" style="margin-top:8px"><input type="checkbox" id="e-use" ${n.use_in_draft ? 'checked' : ''}> 초안 생성에 사용</label>
    <div class="modal-actions"><button id="e-cancel">취소</button><button class="primary" id="e-save">저장</button></div>`, box => {
    $('#e-content', box).focus();
    $('#e-cancel', box).onclick = closeModal;
    $('#e-save', box).onclick = async () => {
      await api('/api/notes/save', { id: n.id, student_id: n.student_id, recording_id: n.recording_id, date: $('#e-date', box).value,
        kind: $('#e-kind', box).value, category: $('#e-cat', box).value, content: $('#e-content', box).value,
        use_in_draft: $('#e-use', box).checked, area: $('#e-area', box) ? $('#e-area', box).value : (n.area || '') });
      closeModal(); toast('저장했습니다'); onSaved && onSaved();
    };
  });
}

// ───────────────────────── 학급 ─────────────────────────

const KIND_HELP = {
  '교과': '수업하는 반 (과목별). 교과 세특을 씁니다.',
  '담임': '담임 학급. 행동특성 및 종합의견, 자율·자치, 진로활동, 개인별 세특을 씁니다.',
  '동아리': '여러 반 학생이 모인 동아리. 명단은 학번(예: 20315)으로 넣으세요.',
  '기타': '방과후·모둠 등. 모든 영역을 쓸 수 있습니다.',
};

function classFormFields(c) {
  const kind = c.kind || '교과';
  const named = kind === '동아리' || kind === '기타';
  return `
    <label class="field shrink" style="min-width:110px"><span>유형</span><select id="c-kind">${['교과', '담임', '동아리', '기타'].map(k => `<option ${k === kind ? 'selected' : ''}>${k}</option>`).join('')}</select></label>
    <label class="field"><span>연도</span><input id="c-year" type="number" value="${c.year}"></label>
    <label class="field"><span>학기</span><select id="c-sem"><option value="1" ${c.semester == 1 ? 'selected' : ''}>1학기</option><option value="2" ${c.semester == 2 ? 'selected' : ''}>2학기</option></select></label>
    <label class="field ${named ? 'hidden' : ''}" data-f="grade"><span>학년</span><input id="c-grade" type="number" min="1" max="6" value="${c.grade ?? ''}" placeholder="2"></label>
    <label class="field ${named ? 'hidden' : ''}" data-f="no"><span>반</span><input id="c-no" type="number" min="1" value="${c.class_no ?? ''}" placeholder="3"></label>
    <label class="field ${kind === '담임' ? 'hidden' : ''}" data-f="subj"><span id="c-subj-l">${named ? (kind === '동아리' ? '동아리 이름' : '이름') : '과목'}</span><input id="c-subj" value="${esc(c.subject || '')}" placeholder="${named ? '예: 로봇탐구반' : '예: 국어'}"></label>`;
}

function bindClassForm() {
  const upd = () => {
    const k = $('#c-kind').value, named = k === '동아리' || k === '기타';
    $('[data-f=grade]').classList.toggle('hidden', named);
    $('[data-f=no]').classList.toggle('hidden', named);
    $('[data-f=subj]').classList.toggle('hidden', k === '담임');
    $('#c-subj-l').textContent = named ? (k === '동아리' ? '동아리 이름' : '이름') : '과목';
    $('#c-kind-help').textContent = KIND_HELP[k];
  };
  $('#c-kind').onchange = upd; upd();
}

function classFormValues() {
  return { kind: $('#c-kind').value, year: $('#c-year').value, semester: $('#c-sem').value, grade: $('#c-grade').value,
    class_no: $('#c-no').value, subject: $('#c-subj').value };
}

async function viewClasses() {
  const y = state.term.year, sem = state.term.semester;
  const list = termClasses();
  const prevList = termClasses(prevTerm(state.term));
  const others = state.classes.length - list.length;
  view.innerHTML = `
    <div class="page-head"><div><h1>학급·학생</h1><div class="muted">${termLabel(state.term)} · 수업하는 반, 담임 학급, 동아리를 관리해요. 과목이 다르면 같은 반도 따로 만드세요.</div></div>
      <div class="actions"><button id="c-prep">✨ 새 학기 준비</button><a class="btn" href="#/archive">지난 학기</a></div></div>
    ${!list.length && prevList.length ? `<div class="card" style="border-color:var(--accent-fill)">
      <div class="section-title"><h2>지난 학기 명단을 가져올까요?</h2><button class="primary" id="c-prep2">명단 가져오기</button></div>
      <p class="muted small" style="margin:0">${termLabel(prevTerm(state.term))}의 학급 ${prevList.length}개(${prevList.slice(0, 4).map(c => esc(c.label)).join(', ')}${prevList.length > 4 ? ' …' : ''})를 ${termLabel(state.term)}로 복사해요. 학생 번호·이름·별칭만 옮기고 관찰기록은 옮기지 않아요.</p></div>` : ''}
    <div class="card">
      <h2>새 학급</h2>
      <div class="row">${classFormFields({ year: y, semester: sem, kind: '교과' })}
        <button class="primary shrink" id="c-add">추가</button>
      </div>
      <p class="help" id="c-kind-help"></p>
    </div>
    <div class="card">
      <div class="section-title"><h2>${termLabel(state.term)} 학급 ${list.length}개</h2>${others ? `<a class="small" href="#/archive">다른 학기 학급 ${others}개 보기 →</a>` : ''}</div>
      ${list.length ? `<div class="table-wrap"><table><thead><tr><th>학급</th><th>유형</th><th class="right">학생 수</th><th class="right">관찰기록</th><th></th></tr></thead><tbody>
        ${list.map(c => `<tr class="clickable" data-href="#/class/${c.id}"><td><b>${esc(c.label)}</b></td><td><span class="badge ${{ '담임': 'violet', '동아리': 'green', '기타': 'amber' }[c.kind] || 'blue'}">${esc(c.kind || '교과')}</span></td>
          <td class="num">${c.students}</td><td class="num">${c.notes || 0}</td><td class="right"><a href="#/drafts/${c.id}" class="small">초안 →</a></td></tr>`).join('')}
      </tbody></table></div>` : '<p class="muted">이 학기 학급이 아직 없어요. 위에서 만들거나 지난 학기 명단을 가져오세요.</p>'}
    </div>`;
  bindRowLinks();
  bindClassForm();
  $('#c-prep').onclick = () => (list.length || !prevList.length)
    ? newTermModal({ from: state.term, to: nextTerm(state.term) })
    : newTermModal({ from: prevTerm(state.term), to: state.term });
  if ($('#c-prep2')) $('#c-prep2').onclick = () => newTermModal({ from: prevTerm(state.term), to: state.term });
  $('#c-add').onclick = async () => {
    const v = classFormValues();
    const r = await api('/api/classes/save', v);
    toast('만들었어요. 명단을 붙여넣으세요.');
    if (!sameTerm({ year: +v.year, semester: +v.semester }, state.term)) setTerm({ year: +v.year, semester: +v.semester }, '#/class/' + r.id);
    else location.hash = '#/class/' + r.id;
  };
}

async function viewClass(id) {
  const d = await api('/api/classes/' + id);
  const c = d.class;
  const club = c.kind === '동아리';
  view.innerHTML = `
    <div class="page-head"><div><a href="#/classes" class="back-btn" aria-label="학급 목록으로 돌아가기"><span aria-hidden="true">←</span> 학급 목록</a><h1>${esc(c.label)}</h1><div class="muted">${esc(c.kind || '교과')} · ${c.year}년 ${c.semester}학기 · 학생 ${d.students.length}명 · 기재 영역: ${d.areas.map(a => esc(a.name)).join(', ')}</div></div>
      <div class="actions"><button id="c-copy" title="이 명단으로 다른 학기 학급 만들기">다음 학기로 명단 복사</button><a class="btn" href="#/recordings/${c.id}">이 학급 녹음</a><a class="btn" href="#/drafts/${c.id}">초안</a></div></div>
    <div class="split">
      <div class="card">
        <div class="section-title"><h2>학생 명단</h2><button class="sm" id="s-add">+ 학생 추가</button></div>
        ${d.students.length ? `<div class="table-wrap"><table><thead><tr><th>${club ? '학번' : '번호'}</th><th>이름</th><th>별칭 (전사 오인식 대비)</th><th class="right">기록</th><th></th></tr></thead><tbody>
          ${d.students.map(s => `<tr class="clickable" data-href="#/student/${s.id}" data-sid="${s.id}">
            <td class="num">${s.number ?? ''}</td><td><b>${esc(s.name)}</b></td><td class="small muted">${esc(s.aliases)}</td>
            <td class="num">${s.notes}</td>
            <td class="right nowrap"><button class="sm s-edit">수정</button></td></tr>`).join('')}
        </tbody></table></div>` : '<p class="muted">오른쪽에 명단을 붙여넣으세요.</p>'}
      </div>
      <div class="stack">
        <div class="card">
          <h2>명단 일괄 붙여넣기</h2>
          <p class="help" style="margin-top:-6px"><b>이름만 한 줄에 한 명씩</b> 붙여넣어도 번호가 차례로 붙어요(이미 있는 이름은 건너뜀). NEIS·엑셀에서 <b>${club ? '학번, 이름' : '번호, 이름'}</b> 두 열을 복사해도 돼요 — 같은 번호가 있으면 이름을 바꿔요.</p>
          <textarea id="bulk" rows="10" placeholder="${club ? '20315	김민수&#10;10702	이서연' : '김민수&#10;이서연&#10;박지훈'}"></textarea>
          <div id="bulk-plan" class="bulk-plan hidden"></div>
          <div class="row" style="margin-top:8px"><span id="bulk-preview" class="muted small"></span><button class="primary shrink" id="bulk-save">명단 저장</button></div>
        </div>
        <div class="card">
          <h2>학급 정보</h2>
          <div class="row">${classFormFields(c)}</div>
          <p class="help" id="c-kind-help"></p>
          <div class="row" style="margin-top:10px"><span></span><button class="shrink" id="c-save">저장</button><button class="shrink danger" id="c-del">학급 지우기</button></div>
        </div>
      </div>
    </div>`;
  bindRowLinks();
  bindClassForm();
  const reload = () => router(true);
  // 붙여넣은 명단이 몇 번 누구로 들어갈지 미리 보기
  let bulkT;
  $('#bulk').oninput = () => {
    clearTimeout(bulkT);
    bulkT = setTimeout(async () => {
      const text = $('#bulk').value, box = $('#bulk-plan');
      if (!text.trim()) { box.classList.add('hidden'); $('#bulk-preview').textContent = ''; return; }
      const { plan } = await api('/api/students/bulk_preview', { class_id: c.id, text }, { silent: true }).catch(() => ({ plan: [] }));
      const n = k => plan.filter(p => p.action === k).length;
      $('#bulk-preview').textContent = plan.length ? `추가 ${n('add')}명` + (n('update') ? ` · 이름 바꿈 ${n('update')}명` : '') + (n('renumber') ? ` · 번호 바꿈 ${n('renumber')}명` : '') + (n('skip') ? ` · 이미 있음 ${n('skip')}명` : '') : '읽을 수 있는 이름이 없어요';
      box.innerHTML = plan.map(p => `<div class="bp ${p.action}"><b>${p.number ?? ''}</b><span>${esc(p.name)}</span><small>${
        p.action === 'skip' ? '이미 있음' : p.action === 'update' ? esc(p.old) + ' → 바꿈' : p.action === 'renumber' ? p.old + '번 → 번호 바꿈' : ''}</small></div>`).join('');
      box.classList.toggle('hidden', !plan.length);
    }, 250);
  };
  $('#bulk-save').onclick = async () => {
    const r = await api('/api/students/bulk', { class_id: c.id, text: $('#bulk').value });
    toast(`추가 ${r.added}명, 수정 ${r.updated}명`); $('#bulk').value = ''; delete $('#bulk').dataset.dirty; reload();
  };
  $('#s-add').onclick = () => editStudentModal({ class_id: c.id, number: club ? '' : (d.students.at(-1)?.number || 0) + 1 }, reload);
  $$('.s-edit').forEach(b => b.onclick = () => editStudentModal(d.students.find(s => s.id === +b.closest('tr').dataset.sid), reload));
  $('#c-save').onclick = async () => { await api('/api/classes/save', Object.assign({ id: c.id }, classFormValues())); toast('저장했습니다'); reload(); };
  $('#c-copy').onclick = () => { const from = { year: +c.year, semester: +c.semester }; newTermModal({ from, to: nextTerm(from), only: c.id }); };
  $('#c-del').onclick = async () => {
    if (!confirmBox(`${c.label}와 학생 ${d.students.length}명의 관찰기록·초안을 휴지통으로 옮길까요?\n30일 안에는 휴지통에서 그대로 되살릴 수 있어요.`)) return;
    const res = await api('/api/classes/delete', { id: c.id }); location.hash = '#/classes';
    trashedToast(c.label, res, () => { location.hash = '#/class/' + c.id; });
  };
}

// ───────────────────────── 새 학기 준비 ─────────────────────────

function newTermModal(opt) {
  const terms = allTerms().filter(t => state.classes.some(c => inTerm(c, t)));
  let from = opt.from && terms.some(t => sameTerm(t, opt.from)) ? opt.from : (terms[0] || state.term);
  const cur = currentTerm();
  const targetsFor = f => {
    const m = {};
    [opt.to, nextTerm(f), cur, nextTerm(cur), state.term].forEach(t => { if (t && !sameTerm(t, f)) m[termKey(t)] = t; });
    return Object.values(m).sort((a, b) => (b.year - a.year) || (b.semester - a.semester));
  };
  const render = () => {
    const src = termClasses(from);
    const targets = targetsFor(from);
    const to = opt.to && !sameTerm(opt.to, from) ? opt.to : nextTerm(from);
    modal(`<h2>✨ 새 학기 준비</h2>
      <p class="muted" style="margin-top:0">학급 명단(번호·이름·별칭)을 다른 학기로 복사해요. <b>관찰기록과 초안은 옮기지 않아요.</b> 이미 같은 학급이 있으면 빠진 학생만 더해요.</p>
      <div class="row">
        <label class="field"><span>어느 학기에서</span><select id="nt-from">${terms.map(t => `<option value="${termKey(t)}" ${sameTerm(t, from) ? 'selected' : ''}>${termLabel(t)}</option>`).join('')}</select></label>
        <label class="field"><span>어느 학기로</span><select id="nt-to">${targets.map(t => `<option value="${termKey(t)}" ${sameTerm(t, to) ? 'selected' : ''}>${termLabel(t)}${sameTerm(t, cur) ? ' (지금)' : ''}</option>`).join('')}</select></label>
      </div>
      <h3 style="margin-top:16px">가져올 학급</h3>
      ${src.length ? `<div class="table-wrap"><table><thead><tr><th style="width:36px"><span class="sr-only">선택</span></th><th>학급</th><th style="width:90px">학년</th><th style="width:90px">반</th><th>과목·이름</th><th class="right">학생</th></tr></thead><tbody>
        ${src.map(c => { const named = c.kind === '동아리' || c.kind === '기타'; return `<tr data-cid="${c.id}">
          <td><input type="checkbox" class="nt-on" aria-label="${esc(c.label)} 가져오기" ${!opt.only || opt.only === c.id ? 'checked' : ''}></td>
          <td><b>${esc(c.label)}</b><div class="small muted">${esc(c.kind || '교과')}</div></td>
          <td>${named ? '' : `<input type="number" class="nt-grade" min="1" max="6" value="${c.grade ?? ''}" aria-label="학년">`}</td>
          <td>${named ? '' : `<input type="number" class="nt-no" min="1" value="${c.class_no ?? ''}" aria-label="반">`}</td>
          <td>${c.kind === '담임' ? '' : `<input class="nt-subj" value="${esc(c.subject || '')}" aria-label="과목 또는 이름">`}</td>
          <td class="num">${c.students}명</td></tr>`; }).join('')}</tbody></table></div>` : '<p class="muted">이 학기에는 학급이 없어요.</p>'}
      <label class="check" style="margin-top:10px"><input type="checkbox" id="nt-memo"> 학생별 교사 메모도 함께 복사</label>
      <p class="help">새 학년도로 넘어갈 때는 학년·반을 바꿔 주세요. 담임 학급은 학년도마다 학생이 달라지니 새 명단을 붙여넣는 편이 정확해요.</p>
      <div class="modal-actions"><button id="nt-x">닫기</button><button class="primary" id="nt-go" ${src.length ? '' : 'disabled'}>명단 복사하기</button></div>`, box => {
      $('#nt-x', box).onclick = closeModal;
      $('#nt-from', box).onchange = e => { const [y, m] = e.target.value.split('-').map(Number); from = { year: y, semester: m }; opt.only = null; opt.to = null; render(); };
      $('#nt-go', box).onclick = async () => {
        const [ty, ts] = $('#nt-to', box).value.split('-').map(Number);
        const items = $$('tr[data-cid]', box).filter(tr => $('.nt-on', tr).checked).map(tr => {
          const it = { id: +tr.dataset.cid };
          if ($('.nt-grade', tr)) it.grade = $('.nt-grade', tr).value;
          if ($('.nt-no', tr)) it.class_no = $('.nt-no', tr).value;
          if ($('.nt-subj', tr)) it.subject = $('.nt-subj', tr).value;
          return it;
        });
        if (!items.length) return toast('가져올 학급을 골라 주세요', true);
        const r = await api('/api/classes/copy', { year: ty, semester: ts, items, memo: $('#nt-memo', box).checked });
        closeModal();
        toast(`${termLabel({ year: ty, semester: ts })}에 학급 ${r.classes}개, 학생 ${r.students}명을 준비했어요`);
        setTerm({ year: ty, semester: ts }, '#/classes');
      };
    });
  };
  render();
}

// ───────────────────────── 지난 학기 ─────────────────────────

async function viewArchive() {
  const cur = currentTerm();
  const terms = allTerms().filter(t => state.classes.some(c => inTerm(c, t)));
  const past = terms.filter(t => !sameTerm(t, cur));
  view.innerHTML = `
    <div class="page-head"><div><h1>지난 학기</h1><div class="muted">예전 학기의 학급과 기록을 그대로 꺼내 볼 수 있어요. 학기를 고르면 대시보드·학급·초안이 그 학기로 바뀌어요.</div></div>
      <div class="actions"><button id="ar-prep">✨ 새 학기 준비</button></div></div>
    ${past.length ? past.map(t => {
      const list = termClasses(t);
      const st = list.reduce((a, c) => a + (c.students || 0), 0), nt = list.reduce((a, c) => a + (c.notes || 0), 0);
      return `<div class="card term-card">
        <div class="section-title"><h2>${termLabel(t)} ${sameTerm(t, state.term) ? '<span class="badge blue">보는 중</span>' : ''} ${t.year > cur.year || (t.year === cur.year && t.semester > cur.semester) ? '<span class="badge violet">다음 학기</span>' : ''}</h2>
          <span class="muted small">학급 ${list.length} · 학생 ${st}명 · 관찰기록 ${nt}건 <button class="sm" data-term="${termKey(t)}">이 학기 보기</button></span></div>
        <div class="class-tiles">${list.map(c => `<a class="class-tile" href="#/class/${c.id}"><b>${esc(c.label)}</b><span class="small muted">${esc(c.kind || '교과')} · 학생 ${c.students}명 · 기록 ${c.notes || 0}건</span></a>`).join('')}</div>
      </div>`;
    }).join('') : `<div class="empty card">${MASCOT}<h2>지난 학기 기록이 아직 없어요</h2><p>학기가 바뀌면 여기에서 예전 학급을 찾아볼 수 있어요.</p></div>`}`;
  $$('[data-term]').forEach(b => b.onclick = () => { const [y, m] = b.dataset.term.split('-').map(Number); setTerm({ year: y, semester: m }, '#/'); });
  $('#ar-prep').onclick = () => newTermModal({ from: prevTerm(cur), to: cur });
}

// ───────────────────────── 휴지통 ─────────────────────────

async function viewTrash() {
  const d = await api('/api/trash');
  const icon = { class: '🏫', student: '🧑‍🎓', recording: '🎙', note: '📝', draft: '📄' };
  view.innerHTML = `
    <div class="page-head"><div><h1>휴지통</h1><div class="muted">지운 학급·학생·녹음·관찰기록·초안은 ${d.keep_days}일 동안 여기 있어요. 그 뒤엔 자동으로 비워져요.</div></div>
      <div class="actions">${d.items.length ? '<button class="danger" id="tr-empty">휴지통 비우기</button>' : ''}</div></div>
    <div class="card">
      ${d.items.length ? d.items.map(t => `<div class="trash-item" data-tid="${t.id}">
        <span class="badge ${{ class: 'violet', student: 'blue', recording: 'amber', note: 'green', draft: '' }[t.kind] || ''}"><span aria-hidden="true">${icon[t.kind] || ''}</span> ${esc(t.kind_name)}</span>
        <div class="body"><div class="title">${esc(t.title)}</div><div class="small muted">${esc(t.detail)} · ${esc(fmtDate(t.deleted_at))}에 지움 · <span class="${t.days_left <= 3 ? 'bad-text' : ''}">${t.days_left}일 남음</span></div></div>
        <div class="actions"><button class="sm primary tr-restore">되살리기</button><button class="sm danger tr-del">영구 삭제</button></div></div>`).join('')
      : `<div class="empty">${MASCOT}<h2>휴지통이 비어 있어요</h2><p>실수로 지워도 걱정 마세요. ${d.keep_days}일 동안은 여기서 되살릴 수 있어요.</p></div>`}
    </div>`;
  $$('[data-tid]').forEach(el => {
    const t = d.items.find(x => x.id === +el.dataset.tid);
    $('.tr-restore', el).onclick = async () => {
      const r = await api('/api/trash/restore', { id: t.id });
      const go = r.id && { class: '#/class/', student: '#/student/', recording: '#/recording/' }[r.kind];
      toast(`'${t.title}'${eul(t.title)} 되살렸어요`, false, go ? { label: '보러 가기', run: () => { location.hash = go + r.id; } } : null);
      router(true);
    };
    $('.tr-del', el).onclick = async () => {
      if (!confirmBox(`'${t.title}'${eul(t.title)} 영구 삭제할까요?\n다시는 되살릴 수 없어요.`)) return;
      await api('/api/trash/delete', { id: t.id }); toast('영구 삭제했어요'); router(true);
    };
  });
  if ($('#tr-empty')) $('#tr-empty').onclick = async () => {
    if (!confirmBox(`휴지통의 ${d.items.length}개 항목을 모두 영구 삭제할까요?\n다시는 되살릴 수 없어요.`)) return;
    await api('/api/trash/empty', {}); toast('휴지통을 비웠어요'); router(true);
  };
}

// ───────────────────────── 검색 (⌘K) ─────────────────────────

const searchState = { timer: null, seq: 0, hits: [], sel: 0, returnFocus: null };
function openSearch() {
  searchState.returnFocus = document.activeElement;
  $('#search').classList.remove('hidden');
  const q = $('#search-q'); q.focus(); q.select();
  if (!q.value) renderSearch(null);
}
function closeSearch() {
  $('#search').classList.add('hidden');
  if (searchState.returnFocus && document.body.contains(searchState.returnFocus)) { try { searchState.returnFocus.focus(); } catch (e) { /* */ } }
}
function hl(text, q) {
  const t = String(text || ''); if (!q) return esc(t);
  const i = t.toLowerCase().indexOf(q.toLowerCase());
  return i < 0 ? esc(t) : esc(t.slice(0, i)) + '<mark>' + esc(t.slice(i, i + q.length)) + '</mark>' + esc(t.slice(i + q.length));
}
function renderSearch(d) {
  const box = $('#search-results');
  if (!d) {
    box.innerHTML = `<div class="none">학생 이름·별칭, 관찰기록 내용, 녹음 제목·전사문을 모든 학기에서 찾아요.<br><span class="small">↑↓로 고르고 Enter로 열어요</span></div>`;
    searchState.hits = []; return;
  }
  const q = d.q, hits = [];
  const term = r => r.year ? `${r.year}-${r.semester}학기` : '';
  const groups = [
    ['학급', d.classes, c => ({ href: '#/class/' + c.id, ico: '🏫', t: hl(c.label, q), s: `${term(c)} · 학생 ${c.students}명` })],
    ['학생', d.students, x => ({ href: '#/student/' + x.id, ico: '🧑‍🎓', t: `${x.number ?? ''}${x.number != null ? '번 ' : ''}${hl(x.name, q)}`, s: `${esc(x.label)} · ${term(x)} · 기록 ${x.notes}건${x.aliases ? ' · 별칭 ' + hl(x.aliases, q) : ''}` })],
    ['관찰기록', d.notes, n => ({ href: '#/student/' + n.student_id, ico: '📝', t: `${esc(n.name)} <span class="small muted">${esc(n.label)} · ${esc(n.date || '')}</span>`, s: hl(n.snippet, q) })],
    ['녹음', d.recordings, r => ({ href: '#/recording/' + r.id, ico: '🎙', t: hl(r.title || '녹음', q), s: `${esc(fmtDate(r.recorded_at))} · ${esc(r.label)}${r.snippet ? ' · ' + hl(r.snippet, q) : ''}` })],
  ];
  let h = '';
  groups.forEach(([name, list, fn]) => {
    if (!list.length) return;
    h += `<h4>${name} ${list.length}</h4>`;
    list.forEach(item => { const x = fn(item); h += `<a class="hit" role="option" id="hit-${hits.length}" href="${x.href}" data-i="${hits.length}"><span class="ico" aria-hidden="true">${x.ico}</span><span><div class="t">${x.t}</div><div class="s">${x.s}</div></span></a>`; hits.push(x.href); });
  });
  box.innerHTML = h || `<div class="none">‘${esc(q)}’에 맞는 결과가 없어요</div>`;
  searchState.hits = hits; searchState.sel = 0; markSel();
  $$('.hit', box).forEach(a => {
    a.onclick = () => closeSearch();
    a.onmouseenter = () => { searchState.sel = +a.dataset.i; markSel(); };
  });
}
function markSel() {
  $$('#search-results .hit').forEach(a => a.classList.toggle('sel', +a.dataset.i === searchState.sel));
  const cur = $(`#hit-${searchState.sel}`);
  $('#search-q').setAttribute('aria-activedescendant', cur ? cur.id : '');
  if (cur) cur.setAttribute('aria-selected', 'true');
  if (cur) cur.scrollIntoView({ block: 'nearest' });
}
$('#search-q').addEventListener('input', e => {
  clearTimeout(searchState.timer);
  const q = e.target.value.trim();
  if (!q) { renderSearch(null); return; }
  searchState.timer = setTimeout(async () => {
    const seq = ++searchState.seq;
    const d = await api('/api/search?q=' + encodeURIComponent(q), undefined, { silent: true }).catch(() => null);
    if (d && seq === searchState.seq) renderSearch(d);
  }, 180);
});
$('#search-q').addEventListener('keydown', e => {
  const n = searchState.hits.length;
  if (e.key === 'ArrowDown' && n) { e.preventDefault(); searchState.sel = (searchState.sel + 1) % n; markSel(); }
  else if (e.key === 'ArrowUp' && n) { e.preventDefault(); searchState.sel = (searchState.sel - 1 + n) % n; markSel(); }
  else if (e.key === 'Enter' && n) { e.preventDefault(); const href = searchState.hits[searchState.sel]; closeSearch(); location.hash = href; }
});
$('#search').addEventListener('mousedown', e => { if (e.target.id === 'search') closeSearch(); });
$('#search-open').onclick = openSearch;
if (!/Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)) $('#search-kbd').textContent = 'Ctrl K';
document.addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
    e.preventDefault();
    if ($('#search').classList.contains('hidden')) openSearch(); else closeSearch();
  }
});

function editStudentModal(s, onSaved) {
  modal(`<h2>${s.id ? '학생 정보 수정' : '학생 추가'}</h2>
    <div class="row"><label class="field shrink" style="width:90px"><span>번호</span><input id="st-no" type="number" value="${s.number ?? ''}"></label>
      <label class="field"><span>이름</span><input id="st-name" value="${esc(s.name || '')}"></label></div>
    <label class="field" style="margin-top:10px"><span>별칭 (쉼표로 구분)</span><input id="st-al" value="${esc(s.aliases || '')}" placeholder="예: 민수, 김민서, 민쑤"></label>
    <p class="help">음성 인식이 이름을 다르게 적는 경우(예: '김민수'→'김민서')를 적어두면 자동 배정됩니다.</p>
    <label class="field" style="margin-top:10px"><span>교사 메모 (세특 생성 시 참고)</span><textarea id="st-memo" rows="3" placeholder="예: 진로 희망 - 환경공학">${esc(s.memo || '')}</textarea></label>
    <div class="modal-actions">${s.id ? '<button class="danger" id="st-del" style="margin-right:auto">학생 지우기</button>' : ''}<button id="st-cancel">취소</button><button class="primary" id="st-save">저장</button></div>`, box => {
    $('#st-name', box).focus();
    $('#st-cancel', box).onclick = closeModal;
    $('#st-save', box).onclick = async () => {
      await api('/api/students/save', { id: s.id, class_id: s.class_id, number: $('#st-no', box).value, name: $('#st-name', box).value,
        aliases: $('#st-al', box).value, memo: $('#st-memo', box).value });
      closeModal(); toast('저장했습니다'); onSaved && onSaved();
    };
    if ($('#st-del', box)) $('#st-del', box).onclick = async () => {
      if (!confirmBox(`${s.name} 학생을 관찰기록·초안과 함께 휴지통으로 옮길까요?\n30일 안에 되살릴 수 있어요.`)) return;
      const res = await api('/api/students/delete', { id: s.id }); closeModal();
      const back = '#/class/' + s.class_id;
      if (location.hash.startsWith('#/student/')) location.hash = back; else onSaved && onSaved();
      trashedToast(s.name + ' 학생', res);
    };
  });
}

// ───────────────────────── 학생 상세 ─────────────────────────

async function viewStudent(id, areaParam) {
  const d = await api('/api/students/' + id);
  const s = d.student, c = d.class, areas = d.areas;
  const area = areas.find(a => a.id === areaParam) || areas[0];
  const limit = area.limit, multi = areas.length > 1;
  const idx = d.siblings.findIndex(x => x.id === s.id);
  const prev = d.siblings[idx - 1], next = d.siblings[idx + 1];
  const drafts = d.drafts.filter(x => (x.area || 'subject') === area.id);
  const current = drafts.find(x => x.status === '확정') || drafts[0];
  const notesInArea = d.notes.filter(n => n.area_eff === area.id);
  const sib = x => `#/student/${x.id}${multi ? '/' + area.id : ''}`;
  view.innerHTML = `
    <div class="page-head"><div><a href="#/class/${c.id}" class="back-btn" aria-label="${esc(c.label)}(으)로 돌아가기"><span aria-hidden="true">←</span> ${esc(c.label)}</a>
      <h1>${s.number ?? ''}${c.kind === '동아리' ? ' ' : '번 '}${esc(s.name)}</h1><div class="muted small">${s.aliases ? '별칭: ' + esc(s.aliases) + ' · ' : ''}${s.memo ? '메모: ' + esc(s.memo) : ''}</div></div>
      <div class="actions">
        ${prev ? `<a class="btn" href="${sib(prev)}">← ${esc(prev.name)}</a>` : ''}
        ${next ? `<a class="btn" href="${sib(next)}">${esc(next.name)} →</a>` : ''}
        <button id="st-edit">학생 정보</button></div></div>
    ${multi ? `<div class="tabs">${areas.map(a => `<button class="${a.id === area.id ? 'on' : ''}" data-area="${a.id}">${esc(a.name)} <span class="muted small">${d.notes.filter(n => n.area_eff === a.id).length}</span></button>`).join('')}</div>` : ''}
    <div class="split">
      <div class="card">
        <div class="section-title"><h2>${multi ? esc(area.name) + ' ' : ''}관찰기록 ${notesInArea.length}건</h2><span><button class="sm" id="n-copy" title="Gemini·ChatGPT에 붙여넣을 수 있게 복사">관찰기록 복사</button> <button class="sm" id="n-add">+ 직접 추가</button></span></div>
        ${notesInArea.length ? '' : `<p class="muted">이 영역의 기록이 없습니다. 녹음을 올리거나 직접 추가하세요.${multi ? ' 다른 영역 기록은 수정 → 기재 영역에서 옮길 수 있습니다.' : ''}</p>`}
        ${notesInArea.map(n => `<div class="note ${n.use_in_draft ? '' : 'off'}" data-note="${n.id}">
          <div class="meta">${esc(n.date || '')} ${kindBadge(n.kind)} <span class="badge">${esc(n.category || '기타')}</span>
            ${n.recording_id ? `<a href="#/recording/${n.recording_id}" class="small">${n.has_audio ? '🎙 ' : ''}${esc(n.rec_title || '원본')}</a>` : '<span class="small">직접 입력</span>'}
            <span class="tools"><label class="check small" title="초안 생성에 사용"><input type="checkbox" class="n-use" ${n.use_in_draft ? 'checked' : ''}>초안에 사용</label>
            <button class="sm n-edit">수정</button><button class="sm danger n-del" aria-label="이 관찰기록 휴지통으로">삭제</button></span></div>
          <div class="content">${esc(n.content)}</div>
          ${n.evidence ? `<div class="evidence">${esc(n.evidence)}</div>` : ''}</div>`).join('')}
      </div>
      <div class="stack">
        <div class="card">
          <div class="section-title"><h2>${esc(area.full)}</h2>${current ? `<span class="badge ${current.status === '확정' ? 'green' : 'blue'}">${current.status}</span>` : ''}</div>
          <label class="field"><span>이번 초안에서 강조할 점 (선택)</span><input id="d-extra" placeholder="예: 탐구 보고서의 문제해결 과정, 진로(환경공학) 연계"></label>
          <div class="row" style="margin-top:10px;gap:8px;flex-wrap:wrap"><button class="primary shrink" id="d-gen" ${notesInArea.length ? '' : 'disabled'}>✨ AI 초안 생성</button>
            <button class="shrink hidden" id="d-deep" ${notesInArea.length ? '' : 'disabled'} title="쓰담 플러스: 더 깊게 쓰는 AI로 한 번 더">💜 정성 초안</button>
            <button class="shrink" id="d-ext" ${notesInArea.length ? '' : 'disabled'} title="프롬프트를 복사해서 ChatGPT·Gemini 앱에서 쓰고, 답을 붙여넣어 저장">📋 ChatGPT·Gemini로 쓰기</button><span id="d-deep-left" class="small muted"></span></div>
          <textarea id="d-text" rows="12" style="margin-top:12px" placeholder="AI 초안이 여기에 표시됩니다. 직접 작성·수정해도 됩니다.">${esc(current ? current.content : '')}</textarea>
          <div class="row" style="margin-top:6px;align-items:center"><span class="counter" id="d-count"></span><span></span>
            <button class="shrink sm" id="d-short">AI로 줄이기</button><button class="shrink sm" id="d-copy">복사</button></div>
          <div id="d-warn"></div>
          <div class="row" style="margin-top:12px"><span></span><button class="shrink" id="d-save">새 버전으로 저장</button><button class="shrink primary" id="d-final">확정</button></div>
        </div>
        ${drafts.length ? `<div class="card"><h3>버전 기록 ${drafts.length}개</h3>
          ${drafts.map(v => `<div class="version" data-ver="${v.id}"><div class="section-title" style="margin:0"><span>${esc(fmtDate(v.created_at))} · ${v.bytes}B ${v.status === '확정' ? '<span class="badge green">확정</span>' : ''}</span>
            <button class="link v-del" aria-label="이 버전 휴지통으로">삭제</button></div><div class="preview">${esc(v.content)}</div></div>`).join('')}</div>` : ''}
      </div>
    </div>`;
  const reload = () => router(true);
  $$('[data-area]').forEach(b => b.onclick = () => { location.hash = `#/student/${s.id}/${b.dataset.area}`; });
  const text = $('#d-text');
  const update = () => {
    const b = neisBytes(text.value);
    $('#d-count').className = 'counter' + (b > limit ? ' over' : '');
    $('#d-count').textContent = `${b.toLocaleString()} / ${limit.toLocaleString()} 바이트 · ${text.value.length}자`;
    const found = FORBIDDEN.filter(w => text.value.toLowerCase().includes(w.toLowerCase()));
    const nameHit = text.value.includes(s.name);
    let warn = '';
    if (found.length) warn += `<div class="warn">기재 금지 가능성이 있는 표현: <b>${found.map(esc).join(', ')}</b> — 학생부 기재요령을 확인하세요.</div>`;
    if (nameHit) warn += `<div class="warn">본문에 학생 이름이 들어 있습니다. 학생부에는 이름을 쓰지 않습니다.</div>`;
    if (b > limit) warn += `<div class="warn">${(b - limit).toLocaleString()}바이트 초과 — 'AI로 줄이기'를 사용하거나 직접 다듬으세요.</div>`;
    $('#d-warn').innerHTML = warn;
  };
  text.addEventListener('input', update); update();
  $('#st-edit').onclick = () => editStudentModal(s, reload);
  $('#n-add').onclick = () => editNoteModal({ date: today(), kind: '수업', category: '', content: '', use_in_draft: 1, student_id: s.id, area: multi ? area.id : '' }, reload, s.id, areas);
  $('#n-copy').onclick = async () => { const t = await api(`/api/students/${s.id}/notes_text?area=${area.id}`); copyText(t.text); };
  $$('[data-note]').forEach(el => {
    const n = d.notes.find(x => x.id === +el.dataset.note);
    $('.n-edit', el).onclick = () => editNoteModal(n, reload, s.id, areas);
    $('.n-del', el).onclick = async () => { const res = await api('/api/notes/delete', { id: n.id }); trashedToast('관찰기록', res); reload(); };
    $('.n-use', el).onchange = async e => { await api('/api/notes/save', { ...n, use_in_draft: e.target.checked }); reload(); };
  });
  $('#d-gen').onclick = () => {
    if (text.value.trim() && text.dataset.dirty && !confirmBox('저장하지 않은 수정 내용이 있습니다. 새 초안을 만들까요? (지금 내용은 사라집니다)')) return;
    delete text.dataset.dirty;
    runAI('draft', { student_id: s.id, extra: $('#d-extra').value, area: area.id }, `${area.name} ${s.name}`, reload);
  };
  $('#d-ext').onclick = () => runAI('draft', { student_id: s.id, extra: $('#d-extra').value, area: area.id }, `${area.name} ${s.name}`, reload, { manual: true });
  // 쓰담 플러스를 쓰는 중이면: 정성 초안 버튼 + 남은 횟수
  plusDeep().then(p => {
    if (!p || !$('#d-deep')) return;
    const left = Math.max(0, p.deepCap - p.deepUsed);
    $('#d-deep').classList.remove('hidden');
    $('#d-deep-left').textContent = p.deepCap >= 1e8 ? '정성 초안 무제한' : `정성 초안 ${left}회 남음`;
    if (!left) $('#d-deep').disabled = true;
    $('#d-deep').onclick = () => runAI('draft', { student_id: s.id, extra: $('#d-extra').value, area: area.id, deep: true }, `정성 초안 ${area.name} ${s.name}`, reload);
  });
  $('#d-short').onclick = () => {
    if (!text.value.trim()) return toast('줄일 내용이 없습니다', true);
    delete text.dataset.dirty;
    runAI('shorten', { student_id: s.id, text: text.value, area: area.id }, `${area.name} ${s.name}`, reload);
  };
  $('#d-copy').onclick = () => copyText(text.value);
  $('#d-save').onclick = async () => {
    await api('/api/drafts/save', { student_id: s.id, content: text.value, status: '초안', area: area.id });
    delete text.dataset.dirty; toast('저장했습니다'); reload();
  };
  $('#d-final').onclick = async () => {
    const same = current && current.content === text.value.trim();
    await api('/api/drafts/save', { student_id: s.id, content: text.value, status: '확정', id: same ? current.id : null, as_new: !same, area: area.id });
    delete text.dataset.dirty; toast('확정했습니다'); reload();
  };
  $$('[data-ver]').forEach(el => {
    const v = drafts.find(x => x.id === +el.dataset.ver);
    el.onclick = e => {
      if (e.target.classList.contains('v-del')) return;
      text.value = v.content; text.dataset.dirty = '1'; update(); toast('이 버전을 편집기에 불러왔습니다');
    };
    $('.v-del', el).onclick = async () => { const res = await api('/api/drafts/delete', { id: v.id }); trashedToast('초안 버전', res); reload(); };
  });
}

const FORBIDDEN = ['토익', 'TOEIC', '토플', 'TOEFL', '텝스', 'TEPS', 'HSK', 'JLPT', 'IELTS', '교외', '올림피아드', '경시대회', '공모전',
  '수상', '입상', '논문', '학회', '특허', '출판', '저서', '해외', '어학연수', '유학', '부모', '아버지', '어머니', '학원', '과외', '인강'];

// ───────────────────────── 세특 초안 (학급) ─────────────────────────

async function viewDrafts(classId, areaParam) {
  if (!classId) {
    const list = termClasses();
    if (list.length) { location.replace('#/drafts/' + list[0].id); return; }
    view.innerHTML = `<div class="empty card">${MASCOT}<h2>${termLabel(state.term)} 학급이 없어요</h2><p>학급을 만들거나 지난 학기 명단을 가져오세요.</p><a class="btn primary" href="#/classes">학급 만들기 →</a></div>`;
    return;
  }
  const [d, settings] = await Promise.all([api('/api/classes/' + classId + (areaParam ? '?area=' + areaParam : '')), api('/api/settings')]);
  const c = d.class, limit = d.byte_limit, areas = d.areas, area = areas.find(a => a.id === d.area);
  const withNotes = d.students.filter(s => s.area_notes).length;
  const missing = d.students.filter(s => s.area_notes && !s.draft_status).length;
  const done = d.students.filter(s => s.draft_status === '확정').length;
  const isApi = settings.active_draft === 'gemini' || settings.active_draft === 'local';   // 반 전체를 AI로 바로 만들 수 있음
  const ctxPreview = [d.context.topic, d.context.competencies, d.context.philosophy].filter(x => (x || '').trim()).join(' · ');
  view.innerHTML = `
    <div class="page-head"><div><h1>초안</h1><div class="muted">학급 전체의 초안을 만들고 구글시트·엑셀로 내보냅니다.</div></div>
      <div class="actions"><select id="dc" style="width:auto">${classOptions(classId)}</select></div></div>
    ${areas.length > 1 ? `<div class="tabs">${areas.map(a => `<button class="${a.id === area.id ? 'on' : ''}" data-area="${a.id}">${esc(a.name)}</button>`).join('')}</div>` : ''}
    <div class="card">
      <div class="section-title"><h2>${esc(c.label)} · ${esc(area.full)} <span class="muted small">확정 ${done}/${d.students.length}</span></h2>
        <span class="actions" style="display:flex;gap:6px;flex-wrap:wrap">
          ${isApi ? `<button class="primary" id="g-missing" ${missing ? '' : 'disabled'}>✨ 초안 없는 학생 생성 (${missing})</button>
          <button id="g-all" ${withNotes ? '' : 'disabled'}>기록 있는 학생 전체 생성 (${withNotes})</button>` : ''}
          <button class="${isApi ? '' : 'primary'}" id="g-prompt" ${withNotes ? '' : 'disabled'} title="ChatGPT·Gemini 앱에 붙여넣을 반 전체 프롬프트">📋 반 전체 프롬프트 복사 (${missing || withNotes}명)</button>
          <button id="g-paste" ${withNotes ? '' : 'disabled'}>📥 AI 답 붙여넣기</button>
          <button id="x-copy">표 복사</button>
          <button id="x-csv">CSV</button>
          <button id="x-xlsx">엑셀로 저장</button>
          <button class="primary" id="x-sheet">구글시트 지금 반영</button></span></div>
      <p class="help">${isApi ? '<b>✨</b>는 이 컴퓨터의 AI로 바로 만들어요. 더 다듬고 싶으면 ' : ''}<b>📋 반 전체 프롬프트 복사</b> → ChatGPT·Gemini 앱에 붙여넣기 → 나온 답을 통째로 <b>📥 AI 답 붙여넣기</b>에 넣으면 학생마다 초안이 한꺼번에 들어가요.</p>
      <details class="lesson-ctx" id="lesson-ctx" ${ctxPreview ? '' : 'open'}>
        <summary class="ctx-toggle"><span class="ctx-title">📚 수업 정보</span>
          <span class="ctx-preview">${ctxPreview ? esc(ctxPreview.length > 70 ? ctxPreview.slice(0, 70) + '…' : ctxPreview) : '종목·역량·교사 철학을 적어 두면 초안이 수업에 맞게 나와요'}</span>
          <span class="ctx-chev"><span class="when-closed">펼치기 ▾</span><span class="when-open">접기 ▴</span></span></summary>
        <div class="ctx-grid">
          <label class="field"><span>수업 내용 (종목·단원)</span><textarea id="ctx-topic" rows="2" placeholder="예: 농구 — 드리블·패스·레이업, 3대3 리그전">${esc(d.context.topic)}</textarea></label>
          <label class="field"><span>이 수업에서 기르는 역량</span><textarea id="ctx-comp" rows="2" placeholder="예: 협력적 의사소통, 경기 전략 수립, 자기 주도적 연습">${esc(d.context.competencies)}</textarea></label>
          <label class="field"><span>교사의 수업 철학</span><textarea id="ctx-phil" rows="2" placeholder="예: 잘하는 학생보다 끝까지 도전하는 학생을 기록하고 싶다">${esc(d.context.philosophy)}</textarea></label>
        </div>
        <div class="row" style="justify-content:flex-end;gap:8px"><span class="muted small" id="ctx-saved"></span><button class="primary sm" id="ctx-save" style="width:auto;flex:none;padding:8px 22px">저장</button></div>
      </details>
      <div class="table-wrap" style="margin-top:8px"><table>
        <thead><tr><th style="width:60px">${c.kind === '동아리' ? '학번' : '번호'}</th><th style="width:90px">이름</th><th class="right" style="width:60px">기록</th><th>초안</th><th class="right" style="width:110px" title="학생마다 초안 분량을 정할 수 있어요. 비우면 기본 ${limit.toLocaleString()}바이트">목표 바이트</th><th class="right" style="width:90px">바이트</th><th style="width:70px">상태</th></tr></thead>
        <tbody>${d.students.map(s => `<tr class="clickable" data-href="#/student/${s.id}${areas.length > 1 ? '/' + area.id : ''}">
          <td class="num">${s.number ?? ''}</td><td><b>${esc(s.name)}</b></td>
          <td class="num">${s.area_notes ? s.area_notes : '<span class="badge red">0</span>'}</td>
          <td class="small">${s.draft ? esc(s.draft.length > 140 ? s.draft.slice(0, 140) + '…' : s.draft) : '<span class="muted">-</span>'}</td>
          <td class="right"><input class="target-in" type="number" min="100" max="6000" step="50" data-sid="${s.id}" value="${s.byte_target || ''}" placeholder="${limit}" aria-label="${esc(s.name)} 목표 바이트"></td>
          <td class="num ${s.draft_bytes > (s.byte_target || limit) ? 'counter over' : ''}">${s.draft_bytes ? s.draft_bytes.toLocaleString() : ''}</td>
          <td>${s.draft_status ? `<span class="badge ${s.draft_status === '확정' ? 'green' : 'blue'}">${s.draft_status}</span>` : ''}</td></tr>`).join('')}
        </tbody></table></div>
      <p class="help">한도 ${limit.toLocaleString()}바이트 (설정에서 영역별로 바꿀 수 있음). 구글시트를 연결해 두면 자동으로 반영됩니다. 내보낼 때는 확정본이 있으면 확정본을, 없으면 최신 초안을 씁니다.</p>
    </div>`;
  bindRowLinks();
  $('#ctx-save').onclick = async () => {
    await api('/api/classes/context', { class_id: c.id, area: area.id, topic: $('#ctx-topic').value, competencies: $('#ctx-comp').value, philosophy: $('#ctx-phil').value });
    const pv = [$('#ctx-topic').value, $('#ctx-comp').value, $('#ctx-phil').value].filter(x => x.trim()).join(' · ');
    $('.ctx-preview').textContent = pv ? (pv.length > 70 ? pv.slice(0, 70) + '…' : pv) : '종목·역량·교사 철학을 적어 두면 초안이 수업에 맞게 나와요';
    $('#ctx-saved').textContent = '저장했어요 ✓ 다음 초안부터 반영돼요';
    toast('수업 정보를 저장했어요 ✓ 위 "📚 수업 정보"를 누르면 언제든 다시 열어요');
    setTimeout(() => { $('#lesson-ctx').open = false; }, 900);
  };
  $$('.target-in').forEach(inp => {
    inp.onclick = e => e.stopPropagation();
    inp.onchange = async () => {
      const r = await api('/api/students/target', { student_id: +inp.dataset.sid, area: area.id, bytes: inp.value });
      toast(r.bytes ? `목표 ${(+r.bytes).toLocaleString()}바이트로 정했어요` : '기본 분량으로 되돌렸어요');
    };
  });
  $$('[data-area]').forEach(b => b.onclick = () => { location.hash = `#/drafts/${c.id}/${b.dataset.area}`; });
  $('#dc').onchange = e => { location.hash = '#/drafts/' + e.target.value; };
  const batch = async onlyMissing => {
    const n = onlyMissing ? missing : withNotes;
    if (!confirmBox(`${n}명의 '${area.name}' 초안을 AI로 생성합니다. 무료 등급은 분당 요청 수 제한이 있어 몇 분 걸릴 수 있습니다. 진행할까요?`)) return;
    const r = await api('/api/drafts/batch', { class_id: c.id, only_missing: onlyMissing, area: area.id });
    toast(`${r.count}명 초안 생성을 대기열에 넣었습니다`); pollJobs(true);
  };
  if ($('#g-missing')) $('#g-missing').onclick = () => batch(true);
  if ($('#g-all')) $('#g-all').onclick = () => batch(false);
  if ($('#g-prompt')) $('#g-prompt').onclick = async () => {
    const r = await api('/api/drafts/batch_prompt', { class_id: c.id, area: area.id, only_missing: missing > 0 });
    copyText(r.prompt);
    toast(`${r.count}명 프롬프트를 복사했어요 ✓ ChatGPT·Gemini 앱에 붙여넣으세요`);
  };
  if ($('#g-paste')) $('#g-paste').onclick = () => modal(`<h2>📥 AI 답 붙여넣기</h2>
      <p class="muted">ChatGPT·Gemini가 쓴 답을 <b>통째로</b> 붙여넣으세요. "[3번] …" 줄마다 그 학생 초안으로 저장해요.</p>
      <textarea id="bp-text" rows="14" placeholder="[1번] 토론 수업에서 …&#10;[2번] 실험 활동에서 …"></textarea>
      <div class="modal-actions"><button id="bp-x">닫기</button><button class="primary" id="bp-go">학생별로 저장</button></div>`, box => {
    $('#bp-x', box).onclick = closeModal;
    $('#bp-go', box).onclick = async () => {
      const r = await api('/api/drafts/batch_apply', { class_id: c.id, area: area.id, text: $('#bp-text', box).value });
      closeModal();
      toast(`${r.saved}명 초안을 저장했어요 ✓` + (r.missing.length ? ` (명단에 없는 번호: ${r.missing.join(', ')})` : ''));
      router(true);
    };
  });
  $('#x-copy').onclick = async () => { const t = await api('/api/export/table?class_id=' + c.id); copyText(t.tsv); };
  $('#x-xlsx').onclick = () => exportXlsx(c.id);
  $('#x-csv').onclick = async () => { const r = await api('/api/export/csv', { class_id: c.id }); toast(`다운로드 폴더에 저장했습니다: ${r.name}`); };
  $('#x-sheet').onclick = async () => {
    if (!settings.sheets_url) { toast('설정에서 구글시트 연결을 먼저 해주세요', true); location.hash = '#/settings/google'; return; }
    const r = await api('/api/export/sheets', {});
    toast(`구글시트에 반영했습니다 (시트 ${r.sheets}개)`);
  };
}

// ───────────────────────── 설정 ─────────────────────────

async function viewSettings(section) {
  const s = await api('/api/settings');
  state.settings = s;
  view.innerHTML = `
    <div class="page-head"><div><h1>설정</h1><div class="muted">모든 데이터는 이 컴퓨터의 <a href="#" id="open-data">data 폴더</a>에만 저장돼요.</div></div></div>
    <div class="tabs settings-tabs" role="tablist" aria-label="설정 종류">
      <button role="tab" data-stab="me" aria-controls="settings-grid">👩‍🏫 선생님</button>
      <button role="tab" data-stab="ai" aria-controls="settings-grid">🧠 AI</button>
      <button role="tab" data-stab="phone" aria-controls="settings-grid">📱 휴대폰</button>
      <button role="tab" data-stab="data" aria-controls="settings-grid">💾 백업·업데이트</button></div>
    <div class="grid grid-2" id="settings-grid">
      <div class="card" data-pane="me" style="grid-column:1 / -1">
        <h2>👩‍🏫 선생님</h2>
        <label class="field"><span>선생님 이름 (대시보드 인사·휴대폰 앱에 표시)</span><input id="teacher_name" value="${esc(s.teacher_name)}" placeholder="예: 김쓰담"></label>
        <p class="help">휴대폰 앱과 대시보드 인사에 이 이름이 나와요.</p>
      </div>
      <div class="card" data-pane="data" id="help-card" style="grid-column:1 / -1;order:4">
        <div class="section-title"><h2>📮 도움 · 소식 받기</h2></div>
        <p class="help" style="margin-top:-4px">문제가 생겼을 때 도와드리고 업데이트를 맞춰 드리려고, 하루 한 번 <b>컴퓨터 사양과 쓰담 사용 정보</b>를 보내요. <b>학생 이름·기록·녹음은 절대 보내지 않아요.</b> <a href="https://hanseolhui.github.io/sseudam/privacy.html" target="_blank">개인정보 처리방침</a></p>
        <label class="check"><input type="checkbox" id="telemetry" ${s.telemetry !== '0' ? 'checked' : ''}> 사용 정보 보내기 (익명 · 컴퓨터 사양 · 버전 · 고른 AI · 학급·학생·기록 개수)</label>
        <div class="row" style="margin-top:10px">
          <label class="field"><span>이메일 (선택)</span><input id="contact_email" type="email" value="${esc(s.contact_email || '')}" placeholder="업데이트·문제 해결 안내를 받을 주소"></label>
          <label class="field"><span>학교 (선택)</span><input id="school_name" value="${esc(s.school_name || '')}" placeholder="예: 쓰담고등학교"></label></div>
        <label class="check" style="margin-top:8px"><input type="checkbox" id="share_info" ${s.share_info === '1' ? 'checked' : ''}> 이름(${esc(s.teacher_name || '선생님 탭의 이름')}) · 학교 · 이메일도 함께 보내기</label>
        <div style="margin-top:8px"><button class="sm ghost" id="tm-preview">보내는 내용 그대로 보기</button></div>
        <pre id="tm-out" class="small hidden" style="white-space:pre-wrap;background:var(--bg-2, var(--panel));padding:10px;border-radius:10px;margin-top:8px"></pre>
      </div>
      <div class="card" data-pane="data" id="fb-card" style="grid-column:1 / -1;order:3">
        <div class="section-title"><h2>💬 아이디어 · 오류 보내기</h2></div>
        <p class="help" style="margin-top:-4px">쓰면서 불편한 점, 있으면 좋겠는 기능, 오류를 알려 주세요. 개발자에게 바로 가고, 적은 이메일로 답장드려요.</p>
        <div class="seg-pick" role="radiogroup" aria-label="종류">
          <label class="check shrink"><input type="radio" name="fb_kind" value="idea" checked> 아이디어 제안</label>
          <label class="check shrink"><input type="radio" name="fb_kind" value="bug"> 오류 보고</label>
          <label class="check shrink"><input type="radio" name="fb_kind" value="other"> 기타</label></div>
        <label class="field" style="margin-top:8px"><span>내용</span><textarea id="fb-msg" rows="4" placeholder="예: 반 전체 초안을 한 번에 엑셀로 받고 싶어요 / 녹음을 넣었는데 '분리중'에서 멈춰요"></textarea></label>
        <div class="row" style="margin-top:8px"><label class="field"><span>답장 받을 이메일</span><input id="fb-email" type="email" value="${esc(s.contact_email || s.plus_email || '')}" placeholder="이메일 주소"></label></div>
        <label class="check" style="margin-top:6px"><input type="checkbox" id="fb-diag" checked> 진단 정보 함께 보내기 (컴퓨터 사양 · 설정 · 최근 오류, <b>학생 이름은 가려서</b>) <button class="sm ghost" id="fb-preview" type="button">미리 보기</button></label>
        <pre id="fb-out" class="small hidden" style="white-space:pre-wrap;background:var(--bg-2, var(--panel));padding:10px;border-radius:10px;margin-top:8px;max-height:240px;overflow:auto"></pre>
        <div class="row" style="margin-top:10px"><button class="primary shrink" id="fb-send" type="button">보내기</button><span id="fb-r" class="small"></span></div>
      </div>
      <div class="card" data-pane="data" id="trash-card" style="order:9">
        <h2>🗑 휴지통</h2>
        <p class="muted small" style="margin-top:-4px">지운 학급·학생·녹음·관찰기록·초안은 30일 동안 휴지통에 있어요. 실수로 지워도 되살릴 수 있어요.</p>
        <a class="btn" href="#/trash">휴지통 열기</a>
      </div>
      <div class="card" data-pane="me" style="grid-column:1 / -1">
        <h2>✍️ 작성 기준</h2>
        <div class="row">
          <label class="field"><span>학교급</span><select id="school_level">${['고등학교', '중학교', '초등학교'].map(x => `<option ${x === s.school_level ? 'selected' : ''}>${x}</option>`).join('')}</select></label>
          <label class="field"><span>기본 과목</span><input id="teacher_subject" value="${esc(s.teacher_subject)}" placeholder="학급에 과목이 없을 때 사용"></label>
        </div>
        <h3 style="margin-top:14px">영역별 NEIS 바이트 한도</h3>
        <div class="table-wrap"><table><tbody>${s.areas.map(a => `<tr><td>${esc(a.full)}</td>
          <td style="width:120px"><input type="number" class="area-limit" data-area="${a.id}" value="${a.limit}" style="padding:4px 8px"></td>
          <td class="small muted" style="width:90px">≈ ${Math.round(a.limit / 3)}자</td></tr>`).join('')}</tbody></table></div>
        <p class="help">한글 3바이트, 영문·숫자·공백 1바이트, 줄바꿈 2바이트. 기재요령은 학년도·학교급마다 다를 수 있으니 우리 학교 기준에 맞게 고치세요.</p>
        <label class="field" style="margin-top:12px"><span>추가 작성 지침</span>
          <textarea id="draft_guidance" rows="4" placeholder="예: 성취기준과 연결해서 쓰기, 마지막 문장은 성장 가능성으로 마무리">${esc(s.draft_guidance)}</textarea></label>
        <label class="field" style="margin-top:12px"><span>내 문체 예시 (예전에 쓴 세특 2~3개 붙여넣기)</span>
          <textarea id="style_examples" rows="6" placeholder="AI가 이 문체를 따라 씁니다. 학생 이름은 지우고 넣으세요.">${esc(s.style_examples)}</textarea></label>
      </div>
      <div class="card" id="import" data-pane="phone" style="grid-column:1 / -1;order:2">
        <div class="section-title"><h2>📥 녹음 가져오기</h2>
          <label class="check"><input type="checkbox" id="auto_process" ${s.auto_process === '1' ? 'checked' : ''}> 들어오면 자동으로 처리 (받아쓰기 → 학생별 분리까지)</label></div>
        <p class="help" style="margin-top:-4px">한 수업에 여러 학생을 한 번에 녹음해도 됩니다. 파일을 학생별로 나누거나 이름을 붙일 필요가 없습니다 — 이름이 언급된 곳을 기준으로 자동으로 나눕니다. 학급은 아래 <b>시간표</b>로 녹음 시각에 맞춰 자동 지정됩니다.</p>
        <div id="src-box"><p class="muted">불러오는 중…</p></div>
      </div>
      <div class="card" data-pane="phone" id="timetable-card" style="grid-column:1 / -1;order:3">
        <div class="section-title"><h2>🗓 시간표 (녹음 시각 → 학급 자동 지정)</h2><span class="muted small">수업 시간 중이나 끝난 뒤 15분 안의 녹음·메모는 그 시간 학급으로 들어갑니다</span></div>
        <div class="split" style="grid-template-columns: 180px 1fr">
          <label class="field"><span>교시 시간 (한 줄에 하나)</span><textarea id="period_times" rows="9" style="font-variant-numeric:tabular-nums">${esc(s.period_times)}</textarea></label>
          <div id="tt-box" style="overflow:auto"></div>
        </div>
      </div>
      <div class="card" style="grid-column:1 / -1;order:2" id="stt" data-pane="ai">
        <div class="section-title"><h2>받아쓰기(음성 → 글자) 엔진</h2><span id="stt-active" class="small"></span></div>
        <div class="row" style="gap:18px;align-items:center">
          <label class="check shrink"><input type="radio" name="stt_engine" value="whisper" ${s.stt_engine !== 'gemini' ? 'checked' : ''}> <b>내 맥에서 (Whisper)</b> — 권장 · 녹음이 외부로 나가지 않음 · 무료</label>
          <label class="check shrink"><input type="radio" name="stt_engine" value="gemini" ${s.stt_engine === 'gemini' ? 'checked' : ''}> Gemini — 녹음을 구글로 보내서 받아쓰기</label>
        </div>
        <p class="help"><b>Whisper</b>는 오픈AI가 공개한 음성 인식 모델을 이 맥에서 직접 돌립니다. 인터넷·API 키·비용이 없고 <b>녹음이 맥 밖으로 나가지 않아</b> 학생 개인정보에 가장 안전합니다. 처음 한 번 모델을 내려받으세요.</p>
        <div id="wh-box" style="margin-top:10px"><p class="muted">확인 중…</p></div>
      </div>
      <div class="card" style="grid-column:1 / -1;order:1" id="ai-card" data-pane="ai">
        <div class="section-title"><h2>🧠 AI</h2><span id="ai-now" class="small"></span></div>
        <p class="help" style="margin-top:-4px">학생별로 나누고 세특 초안을 쓰는 AI를 골라요. <b>누르면 바로 바뀌어요.</b> 어떤 걸 골라도 초안 화면의 <b>📋 ChatGPT·Gemini로 쓰기</b>로 외부 AI에서 쓸 수 있어요.</p>
        <div class="ai-tiles" id="ai-tiles"></div>
        <div id="ai-detail" class="ai-detail"></div>
        <details id="ai-ext" style="margin-top:12px"><summary class="small">고급 — 외부 AI 연결 (Gemini · ChatGPT · Claude API 키 · Ollama · LM Studio)</summary>
          <div id="ai-gemini" class="info-box" style="margin-top:8px"><b>외부 AI API 키</b> <span class="small muted">— 이 컴퓨터 AI 대신 Gemini · ChatGPT · Claude로 나누고 초안 쓰기</span>
          <div class="seg-pick" role="radiogroup" aria-label="외부 AI 고르기" style="margin-top:8px">${Object.entries(s.api_keys).filter(([p]) => p !== 'plus').map(([p, k]) =>
            `<label class="check shrink"><input type="radio" name="api_prov" value="${p}" ${(s.api_provider || 'gemini') === p ? 'checked' : ''}> ${esc(k.label)}${k.has ? ' <span class="ok-text small">✓ 키 있음</span>' : ''}</label>`).join('')}</div>
          <div id="api-fields"></div>
        </div>

          <div class="info-box" style="margin-top:8px">
            <div id="la-detect" class="small" style="margin:6px 0">찾는 중…</div>
            <label class="field"><span>주소</span><input id="local_ai_url" value="${esc(s.local_ai_url === 'builtin' ? '' : (s.local_ai_url || ''))}" placeholder="http://127.0.0.1:11434/v1"></label>
            <label class="field" style="margin-top:6px"><span>모델</span><input id="local_ai_model" value="${esc(s.local_ai_url === 'builtin' ? '' : (s.local_ai_model || ''))}" list="la-models" placeholder="예: qwen3:8b"><datalist id="la-models"></datalist></label>
            <div class="row" style="margin-top:8px"><button class="sm shrink" id="la-test-local">시험해 보기</button><button class="sm primary shrink" id="la-use-ext">이 앱으로 쓰기</button><span id="la-local-r" class="small"></span></div>
          </div>
        </details>
      </div>
      <div class="card" style="grid-column:1 / -1;order:2" id="google" data-pane="data">
        <div class="section-title"><h2>구글시트 자동 반영 · 구글 드라이브 백업</h2><span id="g-status" class="small"></span></div>
        <p class="help" style="margin-top:-4px">한 번 연결해 두면 <b>기록이 바뀔 때마다 5분 안에 구글시트에 자동 반영</b>되고, <b>하루 한 번 전체 기록이 구글 드라이브에 백업</b>됩니다. 직접 파일을 올리거나 덮어쓸 일이 없습니다. (시트는 보기용 사본 — 수정은 쓰담에서)</p>
        <div class="split">
          <div class="info-box"><b>연결 방법 (5분, 한 번만)</b><ol>
            <li><a href="https://sheets.new" target="_blank">sheets.new</a> 로 새 구글시트 만들기 (이름 예: 쓰담)</li>
            <li>시트 메뉴 <b>확장 프로그램 › Apps Script</b> → 원래 있던 내용 지우기</li>
            <li><button class="sm primary" id="copy-gs">스크립트 복사</button> → 붙여넣기 → 저장(⌘S)</li>
            <li><b>배포 › 새 배포</b> → 톱니바퀴 <b>웹 앱</b> → 실행: <b>나</b> · 액세스: <b>모든 사용자</b> → 배포</li>
            <li>권한 검토 → 내 계정 → (경고가 뜨면 <b>고급 → 이동</b>) → <b>허용</b></li>
            <li>나온 <b>웹 앱 URL</b>을 오른쪽에 붙여넣고 <b>연결 확인</b></li></ol>
            <p class="small muted" style="margin:6px 0 0">'스크립트 복사'에는 이 맥 전용 보안 토큰이 들어 있어서, 주소를 알아도 다른 사람은 기록에 접근할 수 없습니다.</p></div>
          <div>
            <label class="field"><span>웹 앱 URL</span><input id="sheets_url" value="${esc(s.sheets_url)}" placeholder="https://script.google.com/macros/s/…/exec"></label>
            <div class="row" style="margin-top:8px"><button class="shrink" id="g-test">연결 확인</button><span id="g-test-r" class="small"></span></div>
            <label class="check" style="margin-top:12px"><input type="checkbox" id="sheets_auto" ${s.sheets_auto === '1' ? 'checked' : ''}> 구글시트에 자동 반영 (바뀐 내용이 있을 때 5분마다)</label><br>
            <label class="check" style="margin-top:6px"><input type="checkbox" id="drive_backup" ${s.drive_backup === '1' ? 'checked' : ''}> 하루 한 번 구글 드라이브에 전체 백업 (최근 30개 보관)</label>
            <div class="row" style="margin-top:12px"><button class="shrink" id="g-sync">지금 시트에 반영</button><button class="shrink" id="g-backup">지금 드라이브 백업</button></div>
            <p class="help" id="g-last"></p>
          </div>
        </div>
      </div>
      <div class="card" style="grid-column:1 / -1;order:0" id="qr-link" data-pane="phone">
        <div class="section-title"><h2>📱 휴대폰 연결 — QR 한 번</h2><span id="rl-state" class="small"></span></div>
        <p class="help" style="margin-top:-4px">아이폰·안드로이드 어떤 폰이든, 맥·윈도우 어떤 컴퓨터든 이어져요. 휴대폰 쓰담 앱 → <b>컴퓨터 연결</b> → 아래 QR을 찍으면 끝. 녹음과 학생 기록이 저절로 오가요.</p>
        <div class="split">
          <div style="text-align:center"><div id="rl-qr" class="muted small">불러오는 중…</div></div>
          <div>
            <div class="info-box small"><b>🔒 안전하게</b><br>녹음과 기록은 이 컴퓨터와 연결한 폰만 아는 열쇠로 <b>암호화</b>돼서 건너가요. 중간 서버는 내용을 볼 수 없고, 받자마자 지워져요.</div>
            <div id="rl-devs" class="small" style="margin-top:10px"></div>
            <div class="row" style="margin-top:10px;gap:8px;flex-wrap:wrap"><button class="sm" id="rl-poll">지금 받기</button><button class="sm ghost" id="rl-new">새 QR 만들기</button><button class="sm ghost danger" id="rl-off">연결 끊기</button></div>
            <p class="small muted" style="margin:8px 0 0">아이폰과 맥이 같은 Apple ID면 QR 없이도 iCloud로 이어져요. 둘 다 써도 괜찮아요.</p>
          </div>
        </div>
        <div class="info-box" id="pc-sync" style="margin-top:14px"><b>💜 다른 컴퓨터와 자동 맞추기</b> <span class="small muted">— 쓰담 플러스</span>
          <div class="small muted" style="margin-top:4px">집 맥과 학교 윈도우처럼 컴퓨터 두 대 이상에서 학급·학생·관찰 기록·초안이 저절로 같아져요. 휴대폰 녹음은 먼저 켜진 컴퓨터가 받고, 정리된 기록은 다른 컴퓨터에도 가요. 모두 암호화돼서 건너가요.</div>
          <div id="pc-sync-body" style="margin-top:8px"></div>
        </div>
      </div>
      <div class="card" style="grid-column:1 / -1;order:1" id="phone" data-pane="phone">
        <div class="section-title"><h2>구글 드라이브로 연결 (예전 방식)</h2><label class="check"><input type="checkbox" id="drive_inbox" ${s.drive_inbox === '1' ? 'checked' : ''}> 휴대폰 녹음 자동으로 가져오기</label></div>
        <div class="split">
          <div class="info-box"><b>아이폰</b> — App Store에서 <b>쓰담</b> 설치 → 녹음하면 <b>iCloud로 자동 연동</b> (같은 Apple ID면 설정 없음)${s.platform === 'win' ? '<br><span class="small muted">윈도우 PC는 iCloud for Windows가 설치돼 있어야 합니다. 없으면 아래 구글 연결을 쓰세요.</span>' : ''}
            <br><br><b>안드로이드(갤럭시) · 아이폰 공통</b> — Play 스토어/App Store에서 <b>쓰담</b> 설치 → 앱의 <b>컴퓨터 연결</b> → 오른쪽 QR 찍기 → 녹음이 <b>내 구글 드라이브</b>를 거쳐 이 컴퓨터로 자동 전송
            <p class="small muted" style="margin:6px 0 0">QR에는 '녹음 올리기'만 가능한 전용 열쇠가 들어 있습니다. 휴대폰을 잃어버려도 기록을 볼 수는 없습니다. <b>💾 백업·업데이트 → 구글 연결</b>이 먼저 되어 있어야 해요.</p></div>
          <div style="text-align:center"><div id="qr-box" class="muted small">불러오는 중…</div>
            <button class="sm" id="phone-scan" style="margin-top:8px">휴대폰 녹음 지금 가져오기</button></div>
        </div>
        <div class="source" id="ts-box" style="margin-top:14px"></div>
      </div>
      <div class="card" style="grid-column:1 / -1;order:1" id="backup-card" data-pane="data">
        <div class="section-title"><h2>백업 · 복원 · 엑셀</h2>
          <span style="display:flex;gap:6px;flex-wrap:wrap"><button id="backup">지금 백업 (이 맥)</button><button id="xlsx-all" class="primary">전체 엑셀로 저장</button></span></div>
        <p class="help" style="margin-top:-4px">이 맥에는 매일 자동 백업(30일)됩니다. 구글 드라이브 백업까지 켜 두면 맥이 고장 나도 복원할 수 있습니다. 녹음 원본(오디오)은 용량 때문에 이 맥에만 보관되니, 타임머신 백업을 함께 쓰면 가장 안전합니다.</p>
        <div class="split" style="margin-top:8px">
          <div><h3>복원할 백업 고르기</h3><div id="bk-list" class="small"><p class="muted">불러오는 중…</p></div></div>
          <div><h3>파일로 복원</h3><p class="help">받아 둔 백업 파일(.zip 또는 .db)을 고르세요. 복원 전에 지금 상태를 자동 백업합니다.</p>
            <input type="file" id="restore-file" accept=".zip,.db"></div>
        </div>
      </div>
      <div class="card" data-pane="data" style="grid-column:1 / -1;order:3" id="update-card">
        <div class="section-title"><h2>✨ 프로그램 업데이트</h2>
          <label class="switch"><input type="checkbox" id="auto_update" ${s.auto_update !== '0' ? 'checked' : ''}> 자동으로 업데이트</label></div>
        <p class="muted small" style="margin-top:-4px">새 버전이 나오면 쉬는 틈에 알아서 바꿔요. 학생 기록은 그대로예요.</p>
        <p class="small" id="upd-info">현재 버전 확인 중…</p>
        <div class="row"><button class="shrink" id="upd-check">지금 확인</button>
          <label class="check"><input type="checkbox" id="update_check" ${s.update_check === '1' ? 'checked' : ''}> 새 버전이 있으면 화면 위에 알려 주기</label></div>
        <p class="help">자동 업데이트는 20분 동안 아무 조작이 없고, AI 작업·모델 내려받기가 없을 때만 해요. 바꾸기 직전에 기록을 자동 백업해요.</p>
      </div>
    </div>
    <div style="position:sticky;bottom:0;padding:14px 0;background:linear-gradient(transparent, var(--bg) 30%);display:flex;justify-content:flex-start">
      <span class="save-chip" id="save-chip">바꾸면 바로 저장돼요</span></div>`;
  $('#open-data').onclick = e => { e.preventDefault(); api('/api/open_data', {}); };
  const collect = () => ({
    [apiProv() + '_api_key']: $('#key').value, [apiProv() + '_model']: $('#model').value.trim(),
    area_limits: JSON.stringify(Object.fromEntries($$('.area-limit').map(i => [i.dataset.area, +i.value || 0]))),
    byte_limit: ($('.area-limit[data-area=subject]') || {}).value || s.byte_limit, school_level: $('#school_level').value, teacher_subject: $('#teacher_subject').value,
    draft_guidance: $('#draft_guidance').value, style_examples: $('#style_examples').value,
    auto_process: $('#auto_process').checked ? '1' : '0',
    sheets_url: $('#sheets_url').value.trim(),
    sheets_auto: $('#sheets_auto').checked ? '1' : '0', drive_backup: $('#drive_backup').checked ? '1' : '0',
    stt_engine: ($('input[name=stt_engine]:checked') || {}).value || 'whisper',
    period_times: $('#period_times').value, timetable: JSON.stringify(timetable),
    update_check: $('#update_check').checked ? '1' : '0',
    drive_inbox: $('#drive_inbox').checked ? '1' : '0', teacher_name: $('#teacher_name').value.trim(),
    auto_update: $('#auto_update').checked ? '1' : '0',
    ...($('#draft_local') ? { draft_local: $('#draft_local').checked ? '1' : '0' } : {}),
    telemetry: $('#telemetry').checked ? '1' : '0', share_info: $('#share_info').checked ? '1' : '0',
    contact_email: $('#contact_email').value.trim(), school_name: $('#school_name').value.trim(),
  });
  const save = async () => { await api('/api/settings', collect()); };
  // 자동 저장: 무엇이든 바꾸면 바로 저장하고, 바꾼 칸과 아래 표시가 초록으로 반짝
  const chip = $('#save-chip');
  const flashSaved = el => {
    chip.textContent = '✓ 저장됐어요'; chip.classList.add('on');
    clearTimeout(chip._t); chip._t = setTimeout(() => { chip.classList.remove('on'); chip.textContent = '바꾸면 바로 저장돼요'; }, 1800);
    const c = el && el.closest('.card'); if (c) { c.classList.remove('saved-flash'); void c.offsetWidth; c.classList.add('saved-flash'); }
  };
  let saveT = null;
  $('#settings-grid').addEventListener('change', e => {
    const el = e.target;
    if (!el.matches('input, select, textarea') || el.closest('#ai-ext') || el.closest('#ai-detail') || el.closest('#fb-card') || el.name === 'stt_engine' || el.id === 'restore-file' || el.id === 'key') return;
    clearTimeout(saveT);
    saveT = setTimeout(async () => { try { await save(); flashSaved(el); updateModeBadge(); } catch (err) { /* toast 표시됨 */ } }, 250);
  });
  // 외부 AI API: Gemini · ChatGPT · Claude 중 하나 골라 키·모델 넣기
  const apiProv = () => ($('input[name=api_prov]:checked') || {}).value || 'gemini';
  const API_HELP = {
    gemini: { ph: 'AIza로 시작하는 키', get: '키 받기', note: '녹음 글이 구글 서버로 가요. 무료 등급은 구글이 서비스 개선에 쓸 수 있어서, AI Studio에서 결제 수단을 등록(유료 등급)하는 걸 권해요.' },
    openai: { ph: 'sk-로 시작하는 키', get: '키 받기', note: '녹음 글이 OpenAI 서버로 가요. ChatGPT 구독(Plus)과 API는 따로라서, platform.openai.com 에서 결제(크레딧)를 넣어야 써요. API로 보낸 내용은 기본적으로 학습에 쓰이지 않아요.' },
    claude: { ph: 'sk-ant-로 시작하는 키', get: '키 받기', note: '녹음 글이 Anthropic 서버로 가요. Claude 구독(Pro)과 API는 따로라서, console.anthropic.com 에서 결제(크레딧)를 넣어야 써요. API로 보낸 내용은 기본적으로 학습에 쓰이지 않아요.' },
  };
  const renderApiFields = () => {
    const p = apiProv(), k = s.api_keys[p], h = API_HELP[p];
    $('#api-fields').innerHTML = `
      <label class="field" style="margin-top:8px"><span>${esc(k.label)} API 키 <a href="${esc(k.site)}" target="_blank" class="small">${h.get} ↗</a></span>
        <input id="key" type="password" placeholder="${k.has ? esc(k.masked) + ' (저장됨 — 바꿀 때만 입력)' : h.ph}" autocomplete="off"></label>
      <div class="row" style="margin-top:8px"><button class="shrink" id="test">연결 확인</button><button class="shrink primary" id="use-gemini">${esc(k.label)}로 쓰기</button>${k.has ? '<button class="shrink danger" id="clear-key">키 삭제</button>' : ''}<span id="test-result" class="small"></span></div>
      <label class="field" style="margin-top:10px"><span>모델 <span class="small muted">— 연결 확인을 누르면 고를 수 있는 목록이 나와요${p === 'openai' ? ' (비워 두면 가장 좋은 모델)' : ''}</span></span><input id="model" value="${esc(k.model)}" list="model-list"><datalist id="model-list"></datalist></label>
      <p class="help">${h.note}</p>`;
    $('#test').onclick = async () => {
      $('#test-result').textContent = '확인 중…';
      try {
        const r = await api('/api/settings/test', { provider: p, key: $('#key').value }, { silent: true });
        $('#test-result').innerHTML = `<span style="color:var(--green)">✓ 연결 성공 (모델 ${r.models.length}개)</span>`;
        $('#model-list').innerHTML = r.models.map(m => `<option value="${esc(m.name)}">${esc(m.display)}</option>`).join('');
        if ($('#key').value) { await save(); k.has = true; flashSaved($('#key')); toast('키를 저장했어요 ✓'); updateModeBadge(); aiLoad(); }
      } catch (e) { $('#test-result').innerHTML = `<span style="color:var(--red)">${esc(e.message)}</span>`; }
    };
    if ($('#clear-key')) $('#clear-key').onclick = async () => {
      if (!confirmBox(`저장된 ${k.label} API 키를 삭제할까요?`)) return;
      await api('/api/settings', { clear_key: p }); router(true); updateModeBadge();
    };
    $('#use-gemini').onclick = async () => {
      if ($('#key').value.trim() || $('#model').value.trim() !== k.model) { await save(); }
      await aiChoose('gemini', null, p);
    };
  };
  renderApiFields();
  $$('input[name=api_prov]').forEach(r => r.addEventListener('change', e => { e.stopPropagation(); renderApiFields(); }));
  // ── 🧠 AI 카드: 하나 고르면 바로 바뀜 ──
  const gb = n => (n / 1e9).toFixed(1) + 'GB';
  const ENG_NAME = { plus: '쓰담 플러스로', builtin: '쓰담 AI 모델로', apple: '기기 안 AI로', gemini: '외부 AI API로', external: '내 맥 AI 앱으로', manual: 'AI 없이 쓰기로' };
  let aiSt = null;
  const aiGen = ++AI_GEN;   // 설정 화면을 다시 열면 예전 화면의 갱신은 멈춤 (두 갱신이 번갈아 그려 깜빡이지 않게)
  const tileHtml = (id, icon, title, sub, status, on, disabled) => `
    <button class="ai-tile${on ? ' on' : ''}${disabled ? ' off' : ''}" data-choice="${id}" ${disabled ? 'aria-disabled="true"' : ''}>
      <span class="ai-tile-check">${on ? '✓ 사용 중' : ''}</span>
      <span class="ai-tile-icon">${icon}</span><b>${title}</b><span class="small muted">${sub}</span>
      <span class="ai-tile-status small">${status}</span></button>`;
  const modelName = id => ((aiSt.builtin.models.find(m => m.id === id) || {}).model || id);
  let plusSt = { loggedIn: false }, plusFresh = false;
  const dlPct = dd => Math.floor(100 * dd.done / Math.max(1, dd.total));
  const dlAct = (m) => {
    const dd = m.download || {}, pct = dlPct(dd);
    return dd.stage ? `<span class="muted">${esc(dd.stage)}…</span>` : `<span class="bar wide"><i style="width:${pct}%"></i></span> ${pct}% · ${gb(dd.done)} / ${gb(dd.total)} <button class="sm ghost llm-stop" data-id="${m.id}">멈춤</button>`;
  };
  const bindStop = () => $$('.llm-stop').forEach(x => x.onclick = async () => { await api('/api/localai/models/cancel', { id: x.dataset.id }); toast('멈췄어요. 다시 누르면 이어서 받아요'); setTimeout(aiLoad, 800); });
  const aiLoad = async (tick) => {
    if (aiGen !== AI_GEN || !document.body.contains($('#ai-tiles'))) return;
    try { aiSt = await api('/api/ai/state', undefined, { silent: true }); } catch (e) { $('#ai-detail').textContent = e.message; return; }
    if (aiGen !== AI_GEN) return;
    // 모델 받는 중의 주기 갱신: 진행 막대만 바꿈 (화면 전체를 다시 그리면 입력 중인 칸·스크롤이 튐)
    const dlNow = aiSt.builtin.models.find(m => (m.download || {}).status === 'downloading');
    if (tick && dlNow) {
      const pct = dlPct(dlNow.download);
      const ts = $('.ai-tile[data-choice="builtin"] .ai-tile-status');
      if (ts) ts.innerHTML = `<span class="bar"><i style="width:${pct}%"></i></span> 받는 중 ${pct}%`;
      const row = $(`.llm-act[data-id="${dlNow.id}"]`);
      if (row) { row.innerHTML = dlAct(dlNow); bindStop(); }
      clearTimeout(AI_TIMER);
      AI_TIMER = setTimeout(() => aiLoad(true), 1500);
      return;
    }
    plusSt = aiSt.plus_enabled ? await api('/api/plus?refresh=' + (plusFresh ? '0' : '1'), undefined, { silent: true }).catch(() => ({ loggedIn: false })) : { loggedIn: false };
    plusFresh = true;
    if (aiGen !== AI_GEN) return;
    const st = aiSt, b = st.builtin, mc = b.machine || {}, choice = st.choice;
    const plusOn = !!(plusSt.loggedIn && plusSt.sub && plusSt.sub.active);
    const ymd = d => d ? new Date(d).toLocaleDateString('ko-KR', { month: 'long', day: 'numeric' }) : '';
    const dl = b.models.find(m => (m.download || {}).status === 'downloading');
    const inst = b.models.filter(m => m.installed);
    const usingId = st.local_ai_url === 'builtin' ? st.local_ai_model : '';
    let bStatus;
    if (!b.supported) bStatus = '<span class="muted">이 컴퓨터는 지원 안 함</span>';
    else if (dl) bStatus = `<span class="bar"><i style="width:${Math.floor(100 * dl.download.done / Math.max(1, dl.download.total))}%"></i></span> 받는 중 ${Math.floor(100 * dl.download.done / Math.max(1, dl.download.total))}%`;
    else if (usingId && inst.some(m => m.id === usingId)) bStatus = '✓ ' + esc(modelName(usingId));
    else if (inst.length) bStatus = '받아 둠 · ' + esc(modelName(inst[0].id));
    else bStatus = mc.model ? `누르면 추천 모델 받기 (${gb((b.models.find(m => m.id === mc.model) || {}).size || 0)})` : '';
    const isMac = mc.os === 'mac';
    $('#ai-tiles').innerHTML =
      (st.plus_enabled ? tileHtml('plus', '💜', '쓰담 플러스 <small class="muted">베타</small>', '키·설치 없이 · 녹음만 하면 끝까지', plusOn ? `✓ ${esc(plusSt.sub.planName)} · ${ymd(plusSt.sub.endsAt)}까지` : (plusSt.loggedIn ? (plusSt.betaRequested ? '베타 신청함 · 승인 기다리는 중' : '베타 신청하면 1달 무상') : '로그인하면 시작'), choice === 'plus', false) : '') +
      tileHtml('builtin', '✨', '쓰담 AI 모델', '이 컴퓨터 안에서 · 무료 · 추천', bStatus, choice === 'builtin', !b.supported) +
      (isMac ? tileHtml('apple', '🍎', '기기 안 AI', '설치 없음 · 학생 나누기만', st.apple.state === 'ready' ? '✓ 바로 쓸 수 있어요' : '<span class="muted">이 맥에선 안 돼요</span>', choice === 'apple', st.apple.state !== 'ready') : '') +
      tileHtml('manual', '✋', 'AI 없이', '이름 기준 나누기 · 초안은 프롬프트 복사', '', choice === 'manual', false) +
      (choice === 'gemini' ? tileHtml('gemini', '🔑', esc(st.provider_label) + ' (외부 API)', '고급에서 연결함', st.has_key ? '✓ 키 연결됨' + (st.api_model ? ' · ' + esc(st.api_model) : '') : '키를 넣어야 해요', true, false) : '') +
      (choice === 'external' ? tileHtml('external', '🖥️', '내 맥 AI 앱', 'Ollama · LM Studio', '✓ ' + esc(st.local_ai_model), true, false) : '');
    const draftTxt = { gemini: choice === 'plus' ? '쓰담 플러스' : st.provider_label, local: choice === 'external' ? '내 맥 AI 앱' : '쓰담 AI 모델', manual: '프롬프트 복사(ChatGPT·Gemini 앱)' }[st.draft] || st.draft;
    const segTxt = { gemini: choice === 'plus' ? '쓰담 플러스' : st.provider_label, local: choice === 'external' ? '내 맥 AI 앱' : '쓰담 AI 모델', apple: '기기 안 AI', rules: '이름 기준' }[st.active_seg] || st.active_seg;
    $('#ai-now').innerHTML = `학생 나누기: <b>${segTxt}</b> · 세특 초안: <b>${draftTxt}</b>`;
    // 고른 것에 맞는 설명·설정
    if (choice === 'gemini' || choice === 'external') $('#ai-ext').open = true;
    let d = '';
    if (st.plus_enabled && (choice === 'plus' || showPlus)) {
      if (!plusSt.loggedIn) {
        d = `<div class="spec">💜 <b>쓰담 플러스</b> — 녹음만 하면 받아쓰기 → 학생별 분리 → 세특 초안까지 앱이 한 번에 해요. API 키도 모델 설치도 필요 없어요.
          <div class="small muted" style="margin-top:4px">학생 이름은 이 컴퓨터에서 '학생1'처럼 가린 뒤 보내요. 서리아트 서버는 내용을 저장하지 않아요.</div>
          <div class="row" style="margin-top:10px"><input id="plus-email" type="email" placeholder="이메일 주소" value="${esc(plusEmail)}" style="max-width:260px"><button class="sm primary shrink" id="plus-send">인증번호 받기</button></div>
          <div class="row${plusCodeSent ? '' : ' hidden'}" id="plus-code-row" style="margin-top:8px"><input id="plus-code" inputmode="numeric" placeholder="메일로 온 인증번호" style="max-width:180px"><button class="sm primary shrink" id="plus-login">로그인</button></div>
          <div id="plus-r" class="small" style="margin-top:6px">${plusSt.error ? esc(plusSt.error) : ''}</div></div>`;
      } else if (plusOn) {
        const u = plusSt.sub;
        d = `<div class="spec">💜 <b>${esc(plusSt.email)}</b> · ${esc(u.planName)} · <b>${ymd(u.endsAt)}</b>까지 (${u.daysLeft}일 남음)
          <div class="small muted" style="margin-top:4px">초안 · 분리 무제한 · 정성 초안 ${(u.deepCap || 0) >= 1e8 ? '무제한' : Math.max(0, (u.deepCap || 0) - (u.deepUsed || 0)) + '회 남음'} · 등록된 컴퓨터 ${plusSt.devices.length}/${plusSt.deviceLimit}대 (${plusSt.devices.map(x => esc(x.device_name)).join(', ')})${plusSt.offline ? ' · 지금은 서버 확인이 안 돼서 마지막 상태를 보여요' : ''}</div>
          <div class="row" style="margin-top:8px">${choice !== 'plus' ? '<button class="sm primary shrink" id="plus-use">쓰담 플러스로 쓰기</button>' : ''}<a class="btn sm shrink" href="https://apps.seoriarts.com/sseudam/plus" target="_blank">구독·결제 관리 ↗</a><button class="sm ghost shrink" id="plus-out">이 컴퓨터 로그아웃</button></div></div>`;
      } else {
        d = plusSt.pay
          ? `<div class="spec">💜 <b>${esc(plusSt.email)}</b>로 로그인했어요. 지금은 구독 기간이 아니에요.
          <div class="small muted" style="margin-top:4px">월 9,900원 · 반년 29,000원 · 1년 49,000원. 카드를 등록하면 처음 1주는 체험이에요(계정당 한 번 · 체험 중 기본 AI 200회 · 정성 초안 10회).</div>
          <div class="row" style="margin-top:8px"><a class="btn sm primary shrink" href="https://apps.seoriarts.com/sseudam/plus" target="_blank">구독 시작하기 ↗</a><button class="sm shrink" id="plus-refresh">구독 다시 확인</button><button class="sm ghost shrink" id="plus-out">이 컴퓨터 로그아웃</button></div></div>`
          : plusSt.betaRequested
          ? `<div class="spec">💜 <b>${esc(plusSt.email)}</b> · <b>베타 신청을 받았어요.</b>
          <div class="small muted" style="margin-top:4px">승인되면 메일로 알려 드리고, 1달 동안 결제 없이 쓰실 수 있어요. 승인 메일을 받으면 아래 '구독 다시 확인'을 눌러 주세요.</div>
          <div class="row" style="margin-top:8px"><button class="sm primary shrink" id="plus-refresh">구독 다시 확인</button><button class="sm ghost shrink" id="plus-out">이 컴퓨터 로그아웃</button></div></div>`
          : `<div class="spec">💜 <b>${esc(plusSt.email)}</b>로 로그인했어요. 쓰담 플러스는 지금 <b>베타</b>예요.
          <div class="small muted" style="margin-top:4px">신청하시면 확인 후 <b>1달 동안 결제 없이</b> 써 보실 수 있어요. 대신 쓰면서 느낀 점을 '아이디어 · 오류 보내기'로 알려 주세요.</div>
          <label class="field" style="margin-top:8px"><span>하고 싶은 말 (선택)</span><input id="plus-beta-msg" placeholder="예: 고2 과학 4개 반, 세특 정리에 쓰고 싶어요"></label>
          <div class="row" style="margin-top:8px"><button class="sm primary shrink" id="plus-beta">베타 신청하기</button><button class="sm ghost shrink" id="plus-out">이 컴퓨터 로그아웃</button><span id="plus-r" class="small"></span></div></div>`;
      }
    } else if (choice === 'builtin') {
      const spec = `<div class="spec">💻 <b>${isMac ? '이 맥' : '이 컴퓨터'}</b>: ${esc(mc.chip || '')}${mc.ram ? ' · 메모리 ' + mc.ram + 'GB' : ''}<div class="small">${mc.model ? '→ <b>' + esc((b.models.find(m => m.id === mc.model) || {}).name) + '</b> 모델 추천 · ' : ''}${esc(mc.why || '')}</div></div>`;
      d = spec + b.models.map(m => {
        const dd = m.download || {}, busy = dd.status === 'downloading', pct = busy ? Math.floor(100 * dd.done / Math.max(1, dd.total)) : 0;
        const tag = m.id === b.recommended ? `<span class="pill rec">추천</span>` : '';
        let act;
        if (m.installed) act = m.id === usingId ? '<span class="ok-text">✓ 쓰는 중</span> <button class="sm ghost llm-del" data-id="' + m.id + '">지우기</button>'
          : '<button class="sm primary llm-use" data-id="' + m.id + '">이걸로 쓰기</button> <button class="sm ghost llm-del" data-id="' + m.id + '">지우기</button>';
        else if (busy) act = dlAct(m);
        else act = `<button class="sm ${m.id === b.recommended ? 'primary' : ''} llm-get" data-id="${m.id}">${m.partial ? '이어 받기' : '받기'} (${gb(m.size)})</button>`;
        const err = dd.status === 'error' && dd.error ? `<div class="small bad-text">${esc(dd.error)}</div>` : '';
        const warn = !m.fits ? '<div class="small" style="color:var(--amber)">이 컴퓨터 메모리로는 느리거나 안 될 수 있어요</div>' : '';
        return `<div class="llm-row${m.id === usingId && m.installed ? ' using' : ''}"><div><b>${esc(m.name)}</b>${tag} · ${esc(m.model)}<div class="small muted">${esc(m.desc)}</div>${warn}${err}</div><div class="llm-act" data-id="${m.id}">${act}</div></div>`;
      }).join('') + ((st.light || []).includes(usingId)
        ? `<label class="check" style="margin-top:10px"><input type="checkbox" id="draft_light" ${st.draft_light_ok === '1' ? 'checked' : ''}> 세특 초안도 이 가벼운 모델로 쓰기</label>
           <p class="small" style="margin:4px 0 0;color:var(--amber)">가벼운 모델은 기록에 없는 내용을 지어낼 수 있어요. 끄면 초안은 <b>ChatGPT·Gemini로 쓰기</b>(프롬프트 복사)로 해요. 메모리 16GB 이상이면 '추천' 모델이 훨씬 정확해요.</p>`
        : `<label class="check" style="margin-top:10px"><input type="checkbox" id="draft_local" ${st.draft_local !== '0' ? 'checked' : ''}> 세특 초안도 이 모델로 쓰기</label>`) + `
        <p class="small muted" style="margin:6px 0 0">모델은 이 컴퓨터에만 있고, 쓸 때만 켜졌다가 10분 쉬면 꺼져서 메모리를 돌려줘요.</p>`;
    } else if (choice === 'apple') {
      d = `<div class="spec">🍎 ${esc(st.apple.text)} <button class="sm" id="la-test-apple">시험해 보기</button> <span id="la-apple-r" class="small"></span>
        <div class="small muted" style="margin-top:4px">학생 나누기에만 써요. 세특 초안은 쓰담 AI 모델을 받아 두면 그걸로, 아니면 프롬프트 복사로 써요.</div></div>`;
    } else if (choice === 'manual') {
      d = `<div class="spec">✋ 이름이 나온 곳을 기준으로 나눠요. 세특 초안은 <b>프롬프트 복사</b> 버튼을 눌러 ChatGPT·Gemini 앱에 붙여넣으면 돼요.</div>`;
    } else if (choice === 'gemini' && !st.has_key) {
      d = `<div class="spec">🔑 아래에 키를 넣고 <b>연결 확인</b>을 누르면 바로 써요. 키가 없는 동안엔 이름 기준으로 나눠요.</div>`;
    }
    $('#ai-detail').innerHTML = d;
    // 엔터 = 옆 버튼 누르기 (설정 저장이 아니라 인증번호 받기 · 로그인 · 베타 신청)
    [['#plus-email', '#plus-send'], ['#plus-code', '#plus-login'], ['#plus-beta-msg', '#plus-beta']].forEach(([i, btn]) => {
      if ($(i)) $(i).onkeydown = e => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); $(btn) && $(btn).click(); } };
    });
    if ($('#plus-email')) $('#plus-email').oninput = e => { plusEmail = e.target.value.trim(); };
    if ($('#plus-send')) $('#plus-send').onclick = async () => {
      plusEmail = $('#plus-email').value.trim();
      // 기다리는 사이 화면이 다시 그려질 수 있어서 결과를 쓸 때마다 칸을 새로 찾음
      const say = h => { const el = $('#plus-r'); if (el) el.innerHTML = h; };
      say('보내는 중…');
      try {
        await api('/api/plus/start', { email: plusEmail }, { silent: true });
        plusCodeSent = true;
        say('메일을 보냈어요. 15분 안에 인증번호를 넣어 주세요.');
        const row = $('#plus-code-row'); if (row) row.classList.remove('hidden');
        if ($('#plus-code')) $('#plus-code').focus();
      } catch (e) { say(`<span class="bad-text">${esc(e.message)}</span>`); }
    };
    if ($('#plus-login')) $('#plus-login').onclick = async () => {
      const say = h => { const el = $('#plus-r'); if (el) el.innerHTML = h; };
      say('확인 중…');
      try {
        const r = await api('/api/plus/verify', { email: plusEmail, code: ($('#plus-code') || {}).value || '' }, { silent: true });
        plusCodeSent = false;
        toast(r.sub && r.sub.active ? '쓰담 플러스로 바꿨어요 ✓ 이제 녹음만 하면 돼요' : '로그인했어요 ✓');
        flashSaved($('#ai-tiles')); aiLoad(); updateModeBadge();
      } catch (e) { say(`<span class="bad-text">${esc(e.message)}</span>`); }
    };
    if ($('#plus-use')) $('#plus-use').onclick = () => aiChoose('plus', $('.ai-tile[data-choice=plus]'));
    if ($('#plus-refresh')) $('#plus-refresh').onclick = () => { plusFresh = false; aiLoad(); };
    if ($('#plus-beta')) $('#plus-beta').onclick = async () => {
      try { await api('/api/plus/beta', { message: $('#plus-beta-msg').value }, { silent: true }); toast('베타 신청을 받았어요. 승인되면 메일로 알려 드려요 ✓'); plusFresh = false; aiLoad(); }
      catch (e) { $('#plus-r').innerHTML = `<span class="bad-text">${esc(e.message)}</span>`; }
    };
    if ($('#plus-out')) $('#plus-out').onclick = async () => {
      if (!confirmBox('이 컴퓨터에서 쓰담 플러스 로그아웃할까요?')) return;
      await api('/api/plus/logout', {}); showPlus = false; toast('로그아웃했어요'); aiLoad(); updateModeBadge();
    };
    if ($('#la-test-apple')) $('#la-test-apple').onclick = () => laTest('apple', $('#la-apple-r'));
    $$('.ai-tile').forEach(t => t.onclick = () => aiChoose(t.dataset.choice, t));
    $$('.llm-get').forEach(x => x.onclick = async () => { await api('/api/localai/models/download', { id: x.dataset.id }); toast('받기 시작했어요. 다 받으면 자동으로 써요 ✨'); aiLoad(); });
    bindStop();
    $$('.llm-use').forEach(x => x.onclick = async () => { await api('/api/localai/models/use', { id: x.dataset.id }); await api('/api/ai/choose', { choice: 'builtin' }); toast(modelName(x.dataset.id) + '(으)로 바꿨어요 ✓'); flashSaved(x); aiLoad(); updateModeBadge(); });
    $$('.llm-del').forEach(x => x.onclick = async () => { if (!confirmBox('받은 모델을 지울까요? 다시 쓰려면 또 받아야 해요.')) return; await api('/api/localai/models/delete', { id: x.dataset.id }); toast('지웠어요'); aiLoad(); updateModeBadge(); });
    if ($('#draft_local')) $('#draft_local').onchange = async e => { await api('/api/settings', { draft_local: e.target.checked ? '1' : '0' }); flashSaved(e.target); aiLoad(); };
    if ($('#draft_light')) $('#draft_light').onchange = async e => { await api('/api/settings', { draft_light_ok: e.target.checked ? '1' : '0', draft_local: '1' }); flashSaved(e.target); toast(e.target.checked ? '초안도 가벼운 모델로 써요' : '초안은 ChatGPT·Gemini로 쓰기로 해요 ✓'); aiLoad(); };
    clearTimeout(AI_TIMER);
    if (dl && document.body.contains($('#ai-tiles'))) AI_TIMER = setTimeout(() => aiLoad(true), 1500);
    else if (b.models.some(m => (m.download || {}).status === 'done')) updateModeBadge();
  };
  const aiChoose = async (choice, tile, provider) => {
    if (choice === 'plus' && !(plusSt.loggedIn && plusSt.sub && plusSt.sub.active)) { showPlus = true; aiLoad(); setTimeout(() => $('#plus-email') && $('#plus-email').focus(), 200); return; }
    showPlus = false;
    if (tile && tile.classList.contains('off')) { toast(tile.querySelector('.ai-tile-status').textContent || '이 컴퓨터에선 쓸 수 없어요', true); return; }
    $$('.ai-tile').forEach(t => t.classList.toggle('on', t === tile));
    if (tile) { tile.classList.remove('pop'); void tile.offsetWidth; tile.classList.add('pop'); }
    try {
      const r = await api('/api/ai/choose', { choice, provider });
      const nm = choice === 'gemini' ? r.provider_label + '(으)로' : ENG_NAME[choice];
      toast(r.started ? `${nm} 바꿨어요 ✓ 이 컴퓨터에 맞는 모델(${modelName(r.started)})을 받기 시작했어요` : `${nm} 바꿨어요 ✓`);
      flashSaved(tile);
      if (choice === 'gemini' && !r.has_key) setTimeout(() => $('#key') && $('#key').focus(), 300);
    } catch (e) { /* 오류 토스트 */ }
    aiLoad(); updateModeBadge();
  };
  const laTest = async (engine, out) => {
    out.textContent = '시험하는 중…';
    try {
      const r = await api('/api/localai/test', { engine, local_ai_url: $('#local_ai_url').value.trim(), local_ai_model: $('#local_ai_model').value.trim() }, { silent: true });
      const good = r.correct === r.total;
      out.innerHTML = `<span class="${good ? 'ok-text' : ''}">${good ? '✓ ' : ''}${r.total}문장 중 ${r.correct}개 맞음 · ${r.seconds}초</span>${good ? '' : ' — 더 큰 모델이 더 정확해요'}`;
    } catch (e) { out.innerHTML = `<span class="bad-text">${esc(e.message)}</span>`; }
  };
  // Ollama · LM Studio (고급)
  const extLoad = async () => {
    let st; try { st = await api('/api/localai/status', undefined, { silent: true }); } catch (e) { return; }
    const run = st.detected.filter(d => d.running);
    $('#la-detect').innerHTML = run.length
      ? run.map(d => `<div>✓ <b>${esc(d.name)}</b> 켜져 있음 · 모델 ${d.models.length}개 <button class="sm la-fill" data-url="${esc(d.url)}" data-model="${esc(d.models[0] || '')}">주소 넣기</button></div>`).join('')
      : '<span class="muted">켜진 Ollama · LM Studio가 없어요. 앱을 켜면 여기에 나와요.</span>';
    $('#la-models').innerHTML = [...new Set(run.flatMap(d => d.models))].map(m => `<option value="${esc(m)}">`).join('');
    $$('.la-fill').forEach(x => x.onclick = () => { $('#local_ai_url').value = x.dataset.url; if (!$('#local_ai_model').value) $('#local_ai_model').value = x.dataset.model; });
  };
  $('#la-test-local').onclick = () => laTest('local', $('#la-local-r'));
  $('#la-use-ext').onclick = async () => {
    try { await api('/api/ai/choose', { choice: 'external', url: $('#local_ai_url').value.trim(), model: $('#local_ai_model').value.trim() }); toast('내 맥 AI 앱으로 바꿨어요 ✓'); flashSaved($('#la-use-ext')); aiLoad(); updateModeBadge(); } catch (e) { /* */ }
  };
  $('#ai-ext').addEventListener('toggle', () => { if ($('#ai-ext').open) extLoad(); });
  aiLoad();
  // 📱 QR 연동
  const rlDraw = async (r) => {
    r = r || await api('/api/relay', undefined, { silent: true }).catch(() => null);
    if (!r) return;
    pcDraw(r);
    if (!r.paired) {
      $('#rl-qr').innerHTML = '<button class="primary" id="rl-make">QR 만들기</button>';
      $('#rl-make').onclick = async () => { rlDraw(await api('/api/relay/pair', {})); };
      $('#rl-state').textContent = ''; $('#rl-devs').textContent = '';
      ['rl-poll', 'rl-new', 'rl-off'].forEach(id => $('#' + id).classList.add('hidden'));
      return;
    }
    ['rl-poll', 'rl-new', 'rl-off'].forEach(id => $('#' + id).classList.remove('hidden'));
    const qr = qrcode(0, 'M'); qr.addData(r.qr); qr.make();
    $('#rl-qr').innerHTML = `<div style="background:#fff;display:inline-block;padding:10px;border-radius:12px">${qr.createSvgTag({ cellSize: 4, margin: 2 })}</div><div class="small muted" style="margin-top:6px">휴대폰 쓰담 → 컴퓨터 연결 → QR 찍기</div>`;
    $('#rl-state').innerHTML = r.devices.length ? '<span class="ok-text">✓ 연결됨</span>' : '<span class="muted">휴대폰이 찍기를 기다리는 중</span>';
    $('#rl-devs').innerHTML = r.devices.length ? '연결된 휴대폰: <b>' + r.devices.map(esc).join(', ') + '</b>' + (r.last ? ` · 마지막 확인 ${new Date(r.last * 1000).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}` : '') : '';
  };
  // 💜 컴퓨터끼리 자동 맞추기 (쓰담 플러스)
  const pcDraw = (r) => {
    const box = $('#pc-sync-body'); if (!box) return;
    if (!r.peer_enabled) {
      box.innerHTML = r.paired
        ? `<div class="small">쓰담 플러스를 쓰는 중일 때 켜져요. <a href="#/settings" id="pc-go-plus">설정 → AI → 쓰담 플러스</a></div>
           <div class="row" style="margin-top:6px"><input id="pc-code" placeholder="다른 컴퓨터의 연결 코드 붙여넣기" style="flex:1 1 260px"><button class="sm shrink" id="pc-join">이 컴퓨터를 연결</button></div>`
        : `<div class="small">먼저 위에서 QR을 만들거나, 다른 컴퓨터의 연결 코드를 붙여넣어 주세요.</div>
           <div class="row" style="margin-top:6px"><input id="pc-code" placeholder="다른 컴퓨터의 연결 코드 붙여넣기" style="flex:1 1 260px"><button class="sm shrink" id="pc-join">이 컴퓨터를 연결</button></div>`;
    } else {
      box.innerHTML = `<div class="small">${r.peers ? `<span class="ok-text">✓ 다른 컴퓨터 ${r.peers}대와 맞추는 중</span>` : '<span class="muted">다른 컴퓨터를 기다리는 중</span>'}</div>
        <div class="row" style="margin-top:6px;gap:8px;flex-wrap:wrap"><button class="sm primary shrink" id="pc-copy">연결 코드 복사</button><span class="small muted">→ 다른 컴퓨터의 쓰담 → 설정 → 휴대폰 → 여기에 붙여넣기</span></div>
        <div class="row" style="margin-top:6px"><input id="pc-code" placeholder="또는: 다른 컴퓨터의 연결 코드 붙여넣기" style="flex:1 1 260px"><button class="sm shrink" id="pc-join">이 컴퓨터를 연결</button></div>`;
    }
    if ($('#pc-copy')) $('#pc-copy').onclick = async () => { try { await navigator.clipboard.writeText(r.qr); toast('연결 코드를 복사했어요. 다른 컴퓨터에 붙여넣어 주세요 ✓'); } catch (e) { prompt('아래 코드를 복사해 주세요', r.qr); } };
    if ($('#pc-join')) $('#pc-join').onclick = async () => {
      const code = $('#pc-code').value.trim(); if (!code) return toast('연결 코드를 붙여넣어 주세요', true);
      if (r.paired && !confirmBox('이 컴퓨터를 다른 컴퓨터와 같은 연결로 바꿔요. 이 컴퓨터에 따로 연결했던 휴대폰은 다른 컴퓨터의 QR로 다시 찍어야 해요. 계속할까요?')) return;
      try { const x = await api('/api/relay/join', { code }); toast('다른 컴퓨터와 연결했어요 ✓ 기록이 곧 맞춰져요'); rlDraw(x); } catch (e) { /* 토스트 */ }
    };
  };
  $('#rl-poll').onclick = async () => { const r = await api('/api/relay/poll', {}); toast(r.received ? `휴대폰에서 ${r.received}개를 받았어요 ✓` : '새로 온 건 없어요'); rlDraw(); };
  $('#rl-new').onclick = async () => { if (!confirmBox('새 QR을 만들면 지금 연결된 휴대폰은 끊겨요. 다시 찍어야 해요. 계속할까요?')) return; rlDraw(await api('/api/relay/pair', { new: true })); toast('새 QR을 만들었어요'); };
  $('#rl-off').onclick = async () => { if (!confirmBox('휴대폰 연결을 끊을까요?')) return; await api('/api/relay/unpair', {}); toast('연결을 끊었어요'); rlDraw(); };
  rlDraw();
  // 💬 아이디어 · 오류 보내기
  $('#fb-preview').onclick = async e => {
    e.preventDefault();
    const box = $('#fb-out');
    if (!box.classList.contains('hidden')) { box.classList.add('hidden'); return; }
    try { box.textContent = (await api('/api/feedback/preview')).text; box.classList.remove('hidden'); } catch (err) { /* */ }
  };
  $('#fb-send').onclick = async () => {
    const r = $('#fb-r'), btn = $('#fb-send');
    btn.disabled = true; r.textContent = '보내는 중…';
    try {
      await api('/api/feedback/send', { kind: ($('input[name=fb_kind]:checked') || {}).value || 'other', message: $('#fb-msg').value,
        email: $('#fb-email').value, diag: $('#fb-diag').checked }, { silent: true });
      r.innerHTML = '<span class="ok-text">✓ 보냈어요. 고맙습니다!</span>'; $('#fb-msg').value = ''; toast('보냈어요. 답장은 메일로 드릴게요 ✓');
    } catch (err) { r.innerHTML = `<span class="bad-text">${esc(err.message)}</span>`; }
    btn.disabled = false;
  };
  $('#tm-preview').onclick = async () => {
    const out = $('#tm-out'); out.classList.toggle('hidden');
    if (!out.classList.contains('hidden')) out.textContent = JSON.stringify(await api('/api/telemetry/preview'), null, 2);
  };
  $('#contact_email').addEventListener('change', e => { if (e.target.value.trim() && !$('#share_info').checked) { $('#share_info').checked = true; } });
  $('#copy-gs').onclick = async () => { const t = await (await fetch('/google_apps_script.gs')).text(); copyText(t); };
  $('#backup').onclick = async () => { await api('/api/backup', {}); toast('백업했습니다'); renderBackups(); };
  $('#xlsx-all').onclick = () => exportXlsx(null);
  $$('input[name=stt_engine]').forEach(r => r.onchange = async () => { await api('/api/settings', { stt_engine: r.value }); renderWhisper(); });
  $('#g-test').onclick = async () => {
    await api('/api/settings', { sheets_url: $('#sheets_url').value.trim() });
    $('#g-test-r').textContent = '확인 중…';
    try { const r = await api('/api/sheets/test', {}, { silent: true }); $('#g-test-r').innerHTML = `<span class="ok-text">✓ 연결됨</span> <a href="${esc(r.url)}" target="_blank">시트 열기</a>`; }
    catch (e) { $('#g-test-r').innerHTML = `<span class="bad-text">${esc(e.message)}</span>`; }
  };
  $('#g-sync').onclick = async () => { await save(); const r = await api('/api/export/sheets', {}); toast(`구글시트에 ${r.sheets}개 시트를 반영했습니다`); renderGoogle(); };
  $('#g-backup').onclick = async () => { await save(); $('#g-backup').disabled = true; try { const r = await api('/api/drive/backup', {}); toast(`드라이브에 백업했습니다 (${Math.round(r.size / 1024)}KB)`); } finally { $('#g-backup').disabled = false; renderGoogle(); renderBackups(); } };
  $('#restore-file').onchange = async e => {
    const f = e.target.files[0]; if (!f) return;
    if (!confirmBox(`'${f.name}' 백업으로 지금 기록을 바꿀까요?\n(지금 상태는 자동으로 따로 백업됩니다)`)) { e.target.value = ''; return; }
    const r = await api('/api/restore/upload', f);
    toast(`복원했습니다 — 학급 ${r.counts.classes}, 학생 ${r.counts.students}, 기록 ${r.counts.notes}`); router(true);
  };
  renderWhisper(); renderGoogle(); renderBackups(); renderPairing();
  $('#phone-scan').onclick = async () => { const r = await api('/api/phone/scan', {}); toast(`휴대폰 녹음 ${r.imported}개를 가져왔습니다`); };
  if (s.platform !== 'mac') $$('[data-maconly]').forEach(e => e.classList.add('hidden'));

  // 시간표
  let timetable = {};
  try { timetable = JSON.parse(s.timetable || '{}'); } catch (e) { timetable = {}; }
  const drawTT = () => {
    const periods = $('#period_times').value.split('\n').filter(l => l.trim());
    const days = ['월', '화', '수', '목', '금'];
    const setIds = new Set(Object.values(timetable).map(String));
    const ttClasses = state.classes.filter(c => inTerm(c, currentTerm()) || inTerm(c) || setIds.has(String(c.id)));
    const opts = sel => '<option value="">-</option>' + ttClasses.map(c => `<option value="${c.id}" ${String(c.id) === String(sel) ? 'selected' : ''}>${esc(c.grade + '-' + c.class_no + (c.subject ? ' ' + c.subject : ''))}</option>`).join('');
    $('#tt-box').innerHTML = ttClasses.length ? `<table class="tt"><thead><tr><th>교시</th>${days.map(d => `<th>${d}</th>`).join('')}</tr></thead><tbody>
      ${periods.map((p, i) => `<tr><th>${i + 1}<div class="muted" style="font-weight:400">${esc(p.trim())}</div></th>
        ${days.map((d, j) => { const k = `${j + 1}-${i + 1}`; return `<td class="${timetable[k] ? 'set' : ''}"><select data-k="${k}">${opts(timetable[k])}</select></td>`; }).join('')}</tr>`).join('')}
      </tbody></table><p class="help">바꾼 뒤 아래 <b>설정 저장</b>을 누르세요.</p>` : '<p class="muted">먼저 학급을 만들어야 시간표를 채울 수 있습니다.</p>';
    $$('#tt-box select').forEach(sel => sel.onchange = () => {
      if (sel.value) timetable[sel.dataset.k] = +sel.value; else delete timetable[sel.dataset.k];
      sel.parentElement.classList.toggle('set', !!sel.value);
    });
  };
  drawTT();
  $('#period_times').addEventListener('change', drawTT);

  // 카테고리 탭 (선생님 · AI · 휴대폰 · 백업·업데이트)
  const showTab = tab => {
    $$('[data-stab]').forEach(b => { const on = b.dataset.stab === tab; b.classList.toggle('on', on); b.setAttribute('aria-selected', on ? 'true' : 'false'); });
    $$('#settings-grid > [data-pane]').forEach(c => c.classList.toggle('hidden', c.dataset.pane !== tab));
    store('local', 'sseudam.settingsTab', tab);
  };
  $$('[data-stab]').forEach(b => b.onclick = () => showTab(b.dataset.stab));
  const target = section && $('#' + section);
  const savedTab = store('local', 'sseudam.settingsTab');
  showTab(target && target.dataset.pane ? target.dataset.pane : (['me', 'ai', 'phone', 'data'].includes(savedTab) ? savedTab : 'ai'));
  $('#auto_update').onchange = async e => { await api('/api/settings', { auto_update: e.target.checked ? '1' : '0' }); toast(e.target.checked ? '자동 업데이트를 켰어요' : '자동 업데이트를 껐어요'); };
  renderTextSync();

  // 가져오기 경로
  renderSources().then(() => { if (target) target.scrollIntoView({ behavior: 'smooth' }); });

  // 업데이트
  const showUpd = async force => {
    const v = await api('/api/version');
    let txt = `현재 버전 <b>${esc(v.version)}</b>`;
    if (v.auto && v.auto.pending) txt += ` · <span class="muted">자동 업데이트: ${esc(v.auto.state)}</span>`;
    if (!v.repo) { $('#upd-info').innerHTML = txt + ' · 업데이트 저장소가 지정되지 않았습니다.'; return; }
    const u = await api('/api/update/check' + (force ? '?force=1' : ''), undefined, { silent: true }).catch(e => ({ error: e.message }));
    if (u.available) txt += ` · <b class="ok-text">새 버전 ${esc(u.latest)} 있음</b> <button class="sm primary" id="upd-go">지금 업데이트</button>`;
    else if (u.error) txt += ` · <span class="bad-text">${esc(u.error)}</span>`;
    else if (u.message) txt += ` · ${esc(u.message)}`;
    else if (u.latest) txt += ' · 최신 버전입니다';
    $('#upd-info').innerHTML = txt;
    if ($('#upd-go')) $('#upd-go').onclick = () => runUpdate(u);
  };
  showUpd(false);
  $('#upd-check').onclick = () => showUpd(true);
}

async function renderPairing() {
  const box = $('#qr-box'); if (!box) return;
  const p = await api('/api/phone/pairing', undefined, { silent: true }).catch(() => null);
  if (!p || !p.ready) { box.innerHTML = '<div class="warn" style="text-align:left">먼저 <b>💾 백업·업데이트 → 구글시트·드라이브</b>를 연결하세요. 연결하면 여기에 QR이 나타나요.</div>'; return; }
  const qr = qrcode(0, 'M'); qr.addData(p.payload); qr.make();
  box.innerHTML = `<div style="background:#fff;display:inline-block;padding:10px;border-radius:10px">${qr.createSvgTag({ cellSize: 5, margin: 2 })}</div>
    <div class="small muted" style="margin-top:6px">휴대폰 '쓰담' 앱 → 컴퓨터 연결 → QR 찍기</div>`;
}

async function renderGoogle() {
  if (!$('#g-last')) return;
  const s = await api('/api/settings', undefined, { silent: true }).catch(() => null);
  if (!s) return;
  const parts = [];
  parts.push(s.sheets_last_sync ? `시트 마지막 반영: ${esc(s.sheets_last_sync)}` : '시트 반영 기록 없음');
  parts.push(s.drive_last_backup ? `드라이브 마지막 백업: ${esc(s.drive_last_backup)}` : '드라이브 백업 기록 없음');
  $('#g-last').innerHTML = parts.join(' · ') + (s.sheets_last_error ? `<br><span class="bad-text">최근 오류: ${esc(s.sheets_last_error)}</span>` : '');
  $('#g-status').innerHTML = s.sheets_url ? (s.sheets_last_error ? '<span class="badge red">오류</span>' : '<span class="badge green">연결됨</span>') : '<span class="badge">연결 안 됨</span>';
}

async function renderBackups() {
  const box = $('#bk-list'); if (!box) return;
  const d = await api('/api/backups', undefined, { silent: true }).catch(e => ({ local: [], drive: [], drive_error: e.message }));
  const kb = n => n > 1048576 ? (n / 1048576).toFixed(1) + 'MB' : Math.round(n / 1024) + 'KB';
  const row = (kind, id, name, time, size) => `<tr><td>${kind === 'drive' ? '<span class="badge blue">드라이브</span>' : '<span class="badge">이 맥</span>'}</td>
    <td>${esc(time)}</td><td class="muted">${esc(name)}</td><td class="num">${kb(size)}</td><td class="right"><button class="sm bk-go" data-kind="${kind}" data-id="${esc(id)}" data-name="${esc(name)}">복원</button></td></tr>`;
  const rows = d.drive.slice(0, 10).map(f => row('drive', f.id, f.name, (f.time || '').replace('T', ' ').slice(0, 16), f.size))
    .concat(d.local.slice(0, 10).map(f => row('local', f.name, f.name, f.time, f.size)));
  box.innerHTML = (rows.length ? `<div class="table-wrap" style="max-height:260px"><table><tbody>${rows.join('')}</tbody></table></div>` : '<p class="muted">아직 백업이 없습니다.</p>')
    + (d.drive_error ? `<p class="bad-text small">드라이브 목록을 못 불러옴: ${esc(d.drive_error)}</p>` : '');
  $$('.bk-go', box).forEach(b => b.onclick = async () => {
    if (!confirmBox(`'${b.dataset.name}' 백업으로 지금 기록을 바꿀까요?\n(지금 상태는 자동으로 따로 백업됩니다)`)) return;
    b.disabled = true; b.textContent = '복원 중…';
    const r = await api('/api/restore', { kind: b.dataset.kind, id: b.dataset.id, name: b.dataset.name });
    toast(`복원했습니다 — 학급 ${r.counts.classes}, 학생 ${r.counts.students}, 기록 ${r.counts.notes}`); router(true);
  });
}

let whTimer;
async function renderWhisper() {
  const box = $('#wh-box'); if (!box) return;
  clearTimeout(whTimer);
  const w = await api('/api/whisper', undefined, { silent: true }).catch(() => null);
  if (!w) return;
  const hasModel = w.models.some(m => m.installed);
  $('#stt-active').innerHTML = w.engine === 'gemini' || !w.supported ? '<span class="badge amber">지금: Gemini로 받아쓰기 (외부 전송)</span>'
    : hasModel ? '<span class="badge green">지금: 내 맥 안에서 받아쓰기 — 외부 전송 없음</span>' : '<span class="badge red">모델을 내려받아야 받아쓰기가 됩니다</span>';
  if (!w.supported) { box.innerHTML = '<div class="warn">이 맥은 Intel 칩이라 Whisper를 쓸 수 없습니다. Gemini 받아쓰기를 사용하세요.</div>'; return; }
  if (!w.binary) { box.innerHTML = '<div class="warn">Whisper 실행 파일이 없습니다. 쓰담을 최신 설치 파일로 다시 설치하세요.</div>'; return; }
  let downloading = false;
  box.innerHTML = '<div class="table-wrap"><table><tbody>' + w.models.map(m => {
    const dl = m.download && m.download.status === 'downloading' ? m.download : null;
    if (dl) downloading = true;
    const pct = dl ? Math.floor(dl.done / dl.total * 100) : 0;
    let action;
    if (m.installed) action = `<span class="badge green">설치됨</span> <button class="sm wh-del" data-id="${m.id}">삭제</button>`;
    else if (dl) action = `<div class="bar" style="width:160px;display:inline-flex"><div class="b1" style="width:${pct}%"></div></div> ${pct}% <button class="sm wh-cancel" data-id="${m.id}">취소</button>`;
    else action = `<button class="sm ${m.id === 'turbo-q5' ? 'primary' : ''} wh-dl" data-id="${m.id}">내려받기</button>`;
    const err = m.download && m.download.status === 'error' ? `<div class="bad-text small">${esc(m.download.error)}</div>` : '';
    return `<tr><td style="width:110px"><b>${esc(m.label)}</b></td><td class="small">${esc(m.desc)}${err}</td><td class="right nowrap">${action}</td></tr>`;
  }).join('') + '</tbody></table></div><p class="help">모델은 한 개만 있으면 됩니다. 와이파이에서 내려받으세요.</p>';
  $$('.wh-dl', box).forEach(b => b.onclick = async () => { await api('/api/whisper/download', { id: b.dataset.id }); renderWhisper(); });
  $$('.wh-cancel', box).forEach(b => b.onclick = async () => { await api('/api/whisper/cancel', { id: b.dataset.id }); setTimeout(renderWhisper, 500); });
  $$('.wh-del', box).forEach(b => b.onclick = async () => { if (confirmBox('이 모델을 삭제할까요?')) { await api('/api/whisper/delete', { id: b.dataset.id }); renderWhisper(); } });
  if (downloading) whTimer = setTimeout(renderWhisper, 1500);
}

async function whisperBanner(el) {
  if (!el) return;
  const w = await api('/api/whisper', undefined, { silent: true }).catch(() => null);
  if (!w || !w.supported || !w.binary || w.engine === 'gemini' || w.models.some(m => m.installed)) { el.innerHTML = ''; return; }
  const m = w.models.find(x => x.id === 'turbo-q5');
  const dl = m.download && m.download.status === 'downloading' ? m.download : null;
  const pct = dl ? Math.floor(dl.done / dl.total * 100) : 0;
  el.innerHTML = `<div class="card" style="border-color:var(--accent);margin-bottom:16px">
    <div class="section-title"><h2>🎙 받아쓰기 모델 설치 (처음 한 번)</h2>
      ${dl ? `<span class="small"><div class="bar" style="width:200px;display:inline-flex"><div class="b1" style="width:${pct}%"></div></div> ${pct}% 내려받는 중</span>`
           : `<button class="primary" id="wb-go">지금 내려받기 (550MB)</button>`}</div>
    <p class="muted small" style="margin:0">녹음을 <b>이 맥 안에서</b> 글자로 바꾸는 Whisper 모델입니다. 인터넷·API 키·비용 없이 동작하고 녹음이 외부로 나가지 않습니다.
    ${m.download && m.download.status === 'error' ? `<br><span class="bad-text">${esc(m.download.error)}</span>` : ''} 설치가 끝나면 기다리던 녹음이 자동으로 받아써집니다.</p></div>`;
  if ($('#wb-go', el)) $('#wb-go', el).onclick = async () => { await api('/api/whisper/download', { id: 'turbo-q5' }); whisperBanner(el); };
  if (dl) setTimeout(() => { if (document.body.contains(el)) whisperBanner(el); }, 1500);
}

async function exportXlsx(classId) {
  toast('엑셀 파일을 만드는 중…');
  const r = await api('/api/export/xlsx', { class_id: classId });
  toast(`다운로드 폴더에 저장했습니다: ${r.name}`);
}

async function renderSources() {
  const box = $('#src-box');
  if (!box) return;
  const src = await api('/api/sources');
  const vm = src.voicememo, nt = src.notes;
  const appName = src.app_name;
  const vmState = !vm.enabled ? '' : vm.access === 'ok' ? '<span class="badge green">작동 중</span>'
    : vm.access === 'no_permission' ? '<span class="badge red">권한 필요</span>' : '<span class="badge amber">음성메모 보관함 없음</span>';
  const mac = (state.settings || {}).platform !== 'win' && (state.settings || {}).platform !== 'other';
  box.innerHTML = (mac ? `
    <div class="source">
      <div class="source-head"><h3>① 음성메모 자동 가져오기 <span class="badge blue">가장 편함</span> ${vmState}</h3>
        <label class="switch"><input type="checkbox" id="vm-on" ${vm.enabled ? 'checked' : ''}> 사용</label></div>
      <p>아이폰 <b>음성메모</b>로 녹음만 하면 끝. 저장·공유·파일 이름 정하기가 필요 없습니다. iCloud로 이 맥에 넘어온 녹음을 자동으로 가져옵니다.
        아이폰이 이미 받아쓴 전사문이 있으면 그대로 써서 AI 전사도 건너뜁니다.</p>
      ${vm.enabled && vm.access === 'no_permission' ? `<div class="warn">맥이 음성메모 보관함을 막고 있습니다. <b>시스템 설정 → 개인정보 보호 및 보안 → 전체 디스크 접근 권한</b>에서 목록 아래 <b>＋</b> 버튼 → <b>응용 프로그램</b> → <b>${esc(appName)}</b>을 골라 추가하고 스위치를 켜 주세요. (맥은 처음엔 목록에 보이지 않아 직접 추가해야 해요) 켠 뒤 쓰담을 ⌘Q로 껐다 켜야 적용됩니다.
        <div style="margin-top:6px"><button class="sm" id="vm-perm">설정 화면 열기</button></div></div>` : ''}
      ${vm.enabled && vm.access === 'not_found' ? `<div class="warn">이 맥에서 음성메모 보관함을 찾지 못했습니다. 맥의 <b>음성 메모</b> 앱을 한 번 열고, 아이폰과 맥 모두 <b>설정 → [내 이름] → iCloud → 음성 메모</b>가 켜져 있는지 확인하세요.</div>` : ''}
      ${vm.enabled ? `<div class="row" style="margin-top:10px">
        <label class="field"><span>이 시각 이후 녹음만</span><input type="datetime-local" id="vm-since" value="${esc((vm.since || '').replace(' ', 'T'))}"></label>
        <label class="field"><span>제목에 이 단어가 있는 것만 (비우면 전부)</span><input id="vm-kw" value="${esc(vm.keyword)}" placeholder="예: 수업"></label>
        <button class="shrink" id="vm-save">적용</button></div>
        <p class="help">지금까지 ${vm.count}개 가져옴 · 개인 녹음이 섞이면 제목 단어 필터를 쓰거나, 녹음함에서 지우면 됩니다.</p>` : ''}
      <details style="margin-top:8px"><summary class="small">처음 설정 방법</summary><ol class="small">
        <li>아이폰: <b>설정 → [내 이름] → iCloud → 모두 보기 → 음성 메모</b> 켜기</li>
        <li>맥: <b>시스템 설정 → [내 이름] → iCloud → 음성 메모</b> 켜기, 맥의 <b>음성 메모</b> 앱을 한 번 열어 동기화 확인</li>
        <li>위 <b>사용</b> 체크 → <b>전체 디스크 접근 권한</b> 화면에서 <b>＋</b> 눌러 <b>쓰담</b> 추가·켜기 → 쓰담 다시 실행</li><li>쓰담 앱으로 녹음하면 이 권한 없이도 자동으로 넘어와요 (음성메모 앱을 쓸 때만 필요)</li></ol></details>
    </div>
    <div class="source">
      <div class="source-head"><h3>② 메모 앱 받아쓰기 <span class="badge green">AI 키 없이 무료 전사</span> ${nt.enabled ? '<span class="badge green">작동 중</span>' : ''}</h3>
        <label class="switch"><input type="checkbox" id="nt-on" ${nt.enabled ? 'checked' : ''}> 사용</label></div>
      <p>아이폰 <b>메모</b> 앱의 <b>'${esc(nt.folder)}'</b> 폴더에 메모를 만들고 키보드의 <b>🎤 마이크</b>로 말하면 아이폰이 바로 글자로 바꿉니다.
        그 메모를 자동으로 가져와 학생별로 나눕니다. 같은 메모에 이어서 말하면 <b>덧붙인 부분만</b> 새 기록으로 들어옵니다.</p>
      <div class="row" style="margin-top:10px"><label class="field"><span>메모 폴더 이름</span><input id="nt-folder" value="${esc(nt.folder)}"></label>
        <button class="shrink" id="nt-save">적용</button><span class="muted small">지금까지 ${nt.count}개 가져옴 · 마지막 수정 5분 뒤에 가져옴 (받아쓰는 중 보호)</span></div>
      <details style="margin-top:8px"><summary class="small">처음 설정 방법</summary><ol class="small">
        <li>아이폰·맥 모두 <b>iCloud → 메모</b> 켜기 (보통 켜져 있음)</li>
        <li>아이폰 메모 앱에서 <b>새 폴더 '${esc(nt.folder)}'</b> 만들기 (iCloud 계정 아래)</li>
        <li>위 <b>사용</b> 체크 → "메모를 제어하려고 합니다" 창이 뜨면 <b>허용</b></li>
        <li>사용 팁: 메모 제목에 <b>2-3</b> 같은 학급을 쓰거나, 시간표를 채워 두면 학급이 자동 지정됩니다</li></ol></details>
    </div>
` : '<p class="muted small">아이폰 음성메모·메모 앱 자동 가져오기는 맥에서만 됩니다. 윈도우에서는 휴대폰 \'쓰담\' 앱(아래)이나 iCloud 폴더를 쓰세요.</p>') + `
    <div class="source">
      <div class="source-head"><h3>AirDrop · 퀵 셰어로 받기 <span class="badge blue">맥·윈도우</span> ${src.downloads.enabled ? '<span class="badge green">작동 중</span>' : ''}</h3>
        <label class="switch"><input type="checkbox" id="dl-on" ${src.downloads.enabled ? 'checked' : ''}> 사용</label></div>
      <p>휴대폰 쓰담 앱에서 <b>보내기 → AirDrop</b>(맥)이나 <b>퀵 셰어</b>(갤럭시 → 윈도우)로 보내면 <b>다운로드</b> 폴더에 들어온 <b>‘쓰담 …’ 파일</b>을 자동으로 가져옵니다. 맥에서는 AirDrop으로 받은 음성메모도 가져와요.
        다운로드 폴더의 다른 파일은 건드리지 않고, 원본은 그대로 남겨 둡니다. <span class="muted small">(지금까지 ${src.downloads.count}개)</span></p>
    </div>
    <div class="source">
      <div class="source-head"><h3>③ iCloud '쓰담 녹음' 폴더 / 단축어 ${src.inbox.exists ? '<span class="badge green">작동 중</span>' : ''}</h3>
        <button class="sm" id="inbox-open">${src.inbox.exists ? 'Finder에서 열기' : '폴더 만들기'}</button></div>
      <p>이 폴더에 들어온 오디오·텍스트(.txt)를 자동으로 가져옵니다. 아이폰 <b>단축어</b>로 '한 번 눌러 녹음 → 자동 저장' 버튼을 만들 때 사용합니다 (사용설명서 참고).</p>
      <p class="muted small">${esc(src.inbox.dir)}</p>
    </div>`;
  const setVM = async (extra) => {
    const r = await api('/api/sources/voicememo', Object.assign({ enabled: $('#vm-on').checked }, extra || {}));
    if ($('#vm-on').checked && r.access === 'no_permission') toast('전체 디스크 접근 권한이 필요합니다. 안내를 따라 주세요.', true);
    renderSources();
  };
  $('#dl-on').onchange = async e => { await api('/api/settings', { downloads_import: e.target.checked ? '1' : '0', downloads_since: '' }); renderSources(); };
  if (!mac) { $('#inbox-open').onclick = async () => { await api('/api/inbox/create', {}); renderSources(); }; return; }
  $('#vm-on').onchange = () => setVM();
  if ($('#vm-perm')) $('#vm-perm').onclick = () => api('/api/open_privacy', { pane: 'fda' });
  if ($('#vm-save')) $('#vm-save').onclick = () => setVM({ since: $('#vm-since').value, keyword: $('#vm-kw').value }).then(() => toast('적용했습니다'));
  const setNT = async () => {
    try {
      const r = await api('/api/sources/notes', { enabled: $('#nt-on').checked, folder: $('#nt-folder').value }, { silent: true });
      if (r.found !== undefined) toast(`메모 앱 연결됨 — '${$('#nt-folder').value}' 폴더 메모 ${r.found}개`);
    } catch (e) {
      toast(e.message, true);
      if (/권한/.test(e.message)) api('/api/open_privacy', { pane: 'automation' });
    }
    renderSources();
  };
  $('#nt-on').onchange = setNT;
  $('#nt-save').onclick = setNT;
  $('#inbox-open').onclick = async () => { await api('/api/inbox/create', {}); renderSources(); };
}

async function runUpdate(u) {
  if (!confirmBox(`쓰담 ${u.latest} 버전으로 업데이트할까요?\n학생 기록은 그대로 유지되며, 업데이트 전에 자동 백업합니다.`)) return;
  modal(`<h2>업데이트 중…</h2><p>새 버전을 내려받아 설치하고 있습니다. 끝나면 화면이 자동으로 새로고침됩니다.</p>`);
  try { await api('/api/update/apply', {}); }
  catch (e) { closeModal(); return; }
  const target = u.latest;
  for (let i = 0; i < 60; i++) {
    await new Promise(r => setTimeout(r, 1000));
    try { const v = await api('/api/version', undefined, { silent: true }); if (v.version === target) { location.reload(); return; } } catch (e) { /* 재시작 중 */ }
  }
  modal(`<h2>업데이트 확인 필요</h2><p>새 버전이 시작되지 않았습니다. 쓰담을 종료 후 다시 실행해 주세요.</p><div class="modal-actions"><button onclick="location.reload()">새로고침</button></div>`);
}

async function checkUpdateBanner() {
  try {
    const v = await api('/api/version?notice=1', undefined, { silent: true });
    $('#ver-badge').textContent = 'v' + v.version;
    if (v.just_updated) {
      const j = v.just_updated, b0 = $('#update-banner');
      b0.innerHTML = `<b>${j.app ? '쓰담 앱이 새 버전으로 바뀌었어요 ✨' : `쓰담이 ${esc(j.from)} → ${esc(j.to)}으로 업데이트됐어요 ✨`}</b>
        ${j.url ? `<a href="${esc(j.url)}" target="_blank" rel="noopener">무엇이 바뀌었나요?</a>` : ''} <button class="sm ghost" id="ub-x">닫기</button>
        ${j.notes ? `<div class="notes">${esc(j.notes)}</div>` : ''}`;
      b0.classList.remove('hidden');
      $('#ub-x').onclick = () => b0.classList.add('hidden');
      toast(j.app ? '새 버전으로 업데이트됐어요 ✨' : `새 버전 ${j.to}으로 업데이트됐어요 ✨`);
      return;
    }
    const u = await api('/api/update/check', undefined, { silent: true });
    const b = $('#update-banner');
    if (v.shell_outdated && !u.available) {
      b.innerHTML = `<b>새 쓰담 앱이 나왔어요 ✨</b> 키 없이 맥 안에서 학생을 나누는 AI가 들어 있어요. 기록은 그대로예요.
        <button class="sm primary" id="ub-app">지금 바꾸기</button> <button class="sm ghost" id="ub-x">나중에</button>`;
      b.classList.remove('hidden');
      $('#ub-x').onclick = () => b.classList.add('hidden');
      $('#ub-app').onclick = async () => {
        modal('<h2>새 앱 설치 중…</h2><p>잠시 후 쓰담이 새 창으로 다시 열립니다. 이 브라우저 창은 닫아도 됩니다.</p>');
        try { await api('/api/update/install_app', {}); } catch (e) { closeModal(); }
      };
      return;
    }
    if (u.available) {
      b.innerHTML = `<b>새 버전 ${esc(u.latest)}이(가) 나왔습니다.</b> <button class="sm primary" id="ub-go">지금 업데이트</button> <button class="sm ghost" id="ub-x">나중에</button>
        ${u.notes ? `<div class="notes">${esc(u.notes)}</div>` : ''}`;
      b.classList.remove('hidden');
      $('#ub-go').onclick = () => runUpdate(u);
      $('#ub-x').onclick = () => b.classList.add('hidden');
    }
  } catch (e) { /* 오프라인 */ }
}

async function viewPrompts() {
  const d = await api('/api/prompts');
  view.innerHTML = `
    <div class="page-head"><div><h1>프롬프트 안내</h1><div class="muted">Gemini·ChatGPT 웹 화면에서 직접 쓸 때 복사해서 붙여넣는 문구입니다. API 키가 없어도 쓸 수 있습니다.</div></div></div>
    <div class="info-box" style="margin-bottom:16px"><b>가장 쉬운 방법</b>
      <ol><li>아래 <b>①</b>로 Gemini 'Gem'(또는 ChatGPT 'GPT')을 한 번만 만들어 둡니다.</li>
        <li>학생 화면에서 <b>관찰기록 복사</b> → Gem에 "세특 써줘"와 함께 붙여넣기 → 결과를 학생 화면 편집창에 붙여넣기.</li>
        <li>설정 → 🧠 AI에서 <b>AI 없이</b>를 고르면, 녹음·학생 화면의 AI 버튼을 누를 때 명단·기록이 이미 채워진 프롬프트가 자동으로 나와요.</li></ol>
      <p class="small muted" style="margin:6px 0 0">아래 문구의 <b>[대괄호]</b> 부분만 실제 내용으로 바꾸면 됩니다. 설정의 바이트 한도·추가 지침이 반영되어 있습니다.</p></div>
    ${d.templates.map((t, i) => `<div class="card">
      <div class="section-title"><h2>${esc(t.title)}</h2><button class="primary sm p-copy" data-i="${i}">프롬프트 복사</button></div>
      <p class="muted small" style="margin-top:-4px">${esc(t.when)}</p>
      <ol class="small">${t.steps.map(x => `<li>${esc(x)}</li>`).join('')}</ol>
      <details><summary class="small">프롬프트 내용 보기</summary><textarea class="prompt-box" readonly style="max-height:340px;margin-top:8px">${esc(t.prompt)}</textarea></details>
    </div>`).join('')}`;
  $$('.p-copy').forEach(b => b.onclick = () => copyText(d.templates[+b.dataset.i].prompt));
}

// ───────────────────────── 첫 실행 안내 ─────────────────────────

async function maybeOnboard() {
  const s = await api('/api/settings', undefined, { silent: true }).catch(() => null);
  if (!s || s.onboarded === '1') return;
  await loadClasses();
  if (state.classes.length) { api('/api/settings', { onboarded: '1' }); return; }
  showOnboarding(s);
}

function showOnboarding(s) {
  const { year: y, semester: sem } = currentTerm();
  const st = { step: 1 };
  const steps = {
    1: () => `<h2>👋 쓰담에 오신 것을 환영합니다</h2><p style="margin:-4px 0 8px;color:var(--accent);font-weight:600">말로 담고, 글로 씁니다</p>
      <p class="muted">수업·상담 중 말로 남긴 관찰을 학생별로 모아, 학기말 세특·행동특성·창체 초안을 빠르게 만드는 도구입니다. 1분이면 준비됩니다.</p>
      <div class="row" style="margin-top:12px">
        <label class="field"><span>학교급</span><select id="ob-level">${['고등학교', '중학교', '초등학교'].map(x => `<option ${x === s.school_level ? 'selected' : ''}>${x}</option>`).join('')}</select></label>
        <label class="field"><span>선생님 이름 (선택)</span><input id="ob-name" value="${esc(s.teacher_name || '')}" placeholder="예: 김쓰담"></label>
      </div>`,
    2: () => `<h2>어떤 기록을 쓰시나요?</h2><p class="muted">해당하는 것을 모두 고르세요. 학급이 자동으로 만들어집니다. (나중에 학급·학생 메뉴에서 더 추가 가능)</p>
      <div class="source"><label class="check"><input type="checkbox" id="ob-subj-on" checked> <b>교과 세특</b> — 수업하는 반</label>
        <div class="row" style="margin-top:8px"><label class="field"><span>과목</span><input id="ob-subj" value="${esc(s.teacher_subject || '')}" placeholder="예: 국어"></label>
          <label class="field" style="flex:2"><span>수업하는 반 (쉼표로)</span><input id="ob-classes" placeholder="예: 2-1, 2-3, 2-5"></label></div></div>
      <div class="source"><label class="check"><input type="checkbox" id="ob-home-on"> <b>담임</b> — 행동특성 및 종합의견 · 자율·자치 · 진로 · 개인별 세특</label>
        <div class="row" style="margin-top:8px"><label class="field"><span>담임 학급</span><input id="ob-home" placeholder="예: 2-3"></label><span></span></div></div>
      <div class="source"><label class="check"><input type="checkbox" id="ob-club-on"> <b>동아리</b> — 동아리활동 특기사항</label>
        <div class="row" style="margin-top:8px"><label class="field"><span>동아리 이름</span><input id="ob-club" placeholder="예: 로봇탐구반"></label><span></span></div></div>`,
    3: () => `<h2>✨ 한 번에 준비할게요</h2>
      <p class="muted">아래 버튼 하나면 끝이에요. 받는 동안 바로 쓰기 시작해도 되고, 다 받으면 알아서 켜져요.</p>
      <div class="source" style="line-height:1.9">
        ✓ <b>받아쓰기</b> — 녹음을 이 컴퓨터 안에서 글자로 (Whisper, 550MB)<br>
        ✓ <b>학생 나누기·세특 초안 AI</b> — <span id="ob-ai-pick">이 컴퓨터에 맞는 모델 고르는 중…</span><br>
        ✓ <b>자동 업데이트</b> — 새 버전이 나오면 쉬는 틈에 알아서
      </div>
      <div class="row" style="margin-top:12px">
        <label class="field"><span>이메일 (선택)</span><input id="ob-email" type="email" placeholder="업데이트·문제 해결 안내를 받을 주소"></label>
        <label class="field"><span>학교 (선택)</span><input id="ob-school" placeholder="예: 쓰담고등학교"></label></div>
      <p class="small muted" style="margin:4px 0 0">적어 주시면 문제가 생겼을 때 도와드릴 수 있어요. 학생 정보는 보내지 않아요.</p>
      <details style="margin-top:10px"><summary class="small">Gemini API 키가 이미 있어요</summary>
        <input id="ob-key" type="password" placeholder="AIza로 시작하는 키" style="margin-top:8px">
        <p class="small muted">넣으면 학생 나누기·초안을 Gemini로 해요. 비워 두면 이 컴퓨터 안의 AI를 써요.</p></details>`,
  };
  const render = () => {
    modal(`<div class="small muted" style="margin-bottom:6px">${st.step} / 3</div>${steps[st.step]()}
      <div class="modal-actions">${st.step > 1 ? '<button id="ob-back">이전</button>' : '<button id="ob-skip" class="ghost">건너뛰기</button>'}
        <button class="primary" id="ob-next">${st.step === 3 ? '✨ 한 번에 준비하기' : '다음'}</button></div>`, box => {
      if (st.step === 3) api('/api/ai/state', undefined, { silent: true }).then(a => {
        const mc = a.builtin.machine || {}, m = a.builtin.models.find(x => x.id === mc.model);
        st.aiPick = m ? 'builtin' : (a.apple.state === 'ready' ? 'apple' : 'manual');
        $('#ob-ai-pick', box).innerHTML = m ? `<b>${esc(m.model)}</b> (${(m.size / 1e9).toFixed(1)}GB · ${esc(mc.chip || '')}${mc.ram ? ' · ' + mc.ram + 'GB' : ''}에 추천)`
          : st.aiPick === 'apple' ? '기기 안 AI (설치 없음)' : '이 컴퓨터는 이름 기준으로 나누고, 초안은 프롬프트 복사로 써요';
      }).catch(() => { st.aiPick = 'manual'; });
      if ($('#ob-skip', box)) $('#ob-skip', box).onclick = async () => { await api('/api/settings', { onboarded: '1' }); closeModal(); };
      if ($('#ob-back', box)) $('#ob-back', box).onclick = () => { st.step--; render(); };
      $('#ob-next', box).onclick = async () => {
        if (st.step === 1) { st.level = $('#ob-level', box).value; st.name = $('#ob-name', box).value.trim(); }
        if (st.step === 2) {
          const mk = [];
          if ($('#ob-subj-on', box).checked) {
            const subj = $('#ob-subj', box).value.trim();
            ($('#ob-classes', box).value.match(/\d+\s*-\s*\d+/g) || []).forEach(x => { const [g, c] = x.split('-').map(v => +v.trim()); mk.push({ kind: '교과', grade: g, class_no: c, subject: subj }); });
            st.subject = subj;
          }
          if ($('#ob-home-on', box).checked) {
            const m = $('#ob-home', box).value.match(/(\d+)\s*-\s*(\d+)/);
            if (m) mk.push({ kind: '담임', grade: +m[1], class_no: +m[2] });
          }
          if ($('#ob-club-on', box).checked && $('#ob-club', box).value.trim()) mk.push({ kind: '동아리', subject: $('#ob-club', box).value.trim() });
          if (!mk.length) return toast('학급을 하나 이상 입력하세요 (예: 2-3)', true);
          st.make = mk;
        }
        if (st.step === 3) {
          const key = ($('#ob-key', box).value || '').trim();
          $('#ob-next', box).disabled = true; $('#ob-next', box).textContent = '준비하는 중…';
          const email = ($('#ob-email', box).value || '').trim(), school = ($('#ob-school', box).value || '').trim();
          const vals = { onboarded: '1', school_level: st.level, teacher_name: st.name || '', teacher_subject: st.subject || '', auto_update: '1', auto_process: '1',
            contact_email: email, school_name: school, share_info: email || school ? '1' : '0' };
          if (key) vals.gemini_api_key = key;
          await api('/api/settings', vals);
          for (const c of st.make) await api('/api/classes/save', Object.assign({ year: y, semester: sem }, c));
          // 받아쓰기 모델 + AI를 한 번에 (실패해도 계속)
          await api('/api/whisper/download', { id: 'turbo-q5' }, { silent: true }).catch(() => null);
          let pick = key ? 'gemini' : (st.aiPick || 'manual');
          for (const c of [pick, 'apple', 'manual']) {
            try { await api('/api/ai/choose', { choice: c }, { silent: true }); pick = c; break; } catch (e) { /* 다음 후보 */ }
          }
          closeModal(); updateModeBadge();
          toast(pick === 'builtin' ? '준비 시작! 받아쓰기·AI 모델을 받는 동안 학생 명단을 붙여넣어 주세요 ✨' : '준비됐어요! 각 학급에 학생 명단을 붙여넣어 주세요 ✨');
          await loadClasses();
          location.hash = state.classes.length ? '#/class/' + state.classes[0].id : '#/classes';
          return;
        }
        st.step++; render();
      };
    });
  };
  render();
}

async function updateModeBadge() {
  const s = await api('/api/settings', undefined, { silent: true }).catch(() => null);
  if (!s) return;
  state.settings = s;
  const dot = c => `<span style="color:var(--${c})">●</span> `;
  $('#mode-badge').innerHTML = s.active_seg === 'gemini' ? dot('green') + esc((s.api_keys[s.api_provider || 'gemini'] || {}).label || 'API') + ' · ' + esc((s.api_keys[s.api_provider || 'gemini'] || {}).model || '자동')
    : s.active_seg === 'apple' ? dot('green') + '기기 안 AI'
    : s.active_seg === 'local' ? dot('green') + (s.local_ai_url === 'builtin' ? '쓰담 AI 모델' : '내 맥 AI · ' + esc(s.local_ai_model || ''))
    : s.ai_choice === 'builtin' ? dot('amber') + '쓰담 AI 모델 준비 중'
    : s.ai_choice === 'plus' ? dot('amber') + '쓰담 플러스 구독 확인 필요 — <a href="#/settings/ai">설정</a>'
    : s.ai_choice === 'gemini' ? dot('amber') + esc((s.api_keys[s.api_provider || 'gemini'] || {}).label || 'API') + ' 키 필요 — <a href="#/settings/ai">설정</a>'
    : s.ai_choice === 'manual' || s.mode === 'manual' ? dot('muted') + 'AI 없이 (프롬프트 복사)' : dot('amber') + 'AI 없음 — <a href="#/settings">설정</a>';
}

async function updatePending() {
  try {
    const d = await api('/api/dashboard', undefined, { silent: true });
    const p = $('#nav-pending');
    p.textContent = d.totals.pending_review; p.classList.toggle('hidden', !d.totals.pending_review);
  } catch (e) { /* */ }
}

$('#btn-quit').onclick = async () => {
  if (!confirmBox('쓰담을 종료할까요? (진행 중인 AI 작업은 중단됩니다)')) return;
  quitting = true;
  try { await api('/api/shutdown', {}); } catch (e) { /* */ }
  document.body.innerHTML = '<div class="empty"><h2>종료했습니다</h2><p>이 창을 닫아도 됩니다. 다시 쓰려면 "쓰담 시작"을 실행하세요.</p></div>';
};

document.addEventListener('focusout', () => {
  if (refreshPending && $('#modal').classList.contains('hidden')) {
    setTimeout(() => {
      const ae = document.activeElement;
      // 설정 → AI 칸(쓰담 플러스 로그인 등) 안에서 옮겨 다니는 중이면 새로 그리지 않음
      if (ae && ae.closest && ae.closest('#ai-detail, #ai-tiles')) return;
      if (!ae || !(ae.dataset && ae.dataset.dirty)) { refreshPending = false; router(true); }
    }, 200);
  }
});

if (navigator.userAgent.includes('SeteukApp')) document.documentElement.classList.add('native');
window.addEventListener('dragover', e => e.preventDefault());
window.addEventListener('drop', e => e.preventDefault());

updateModeBadge();
checkUpdateBanner();
maybeOnboard();
updatePending();
setInterval(updatePending, 30000);
router(false);
pollJobs();


// 휴대폰·다른 기기와 글 기록 맞추기 (녹음은 빼고 학급·학생·관찰기록·초안만)
async function renderTextSync() {
  const box = $('#ts-box'); if (!box) return;
  const st = await api('/api/sync/text');
  const on = st.state !== '꺼짐';
  const last = st.last ? new Date(st.last * 1000).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }) : '';
  const badge = st.state === '정상' ? '<span class="badge green">작동 중</span>' : st.state === '오류' ? '<span class="badge red">오류</span>' : '';
  box.innerHTML = `<div class="source-head"><h3>휴대폰과 기록 맞추기 <span class="badge blue">글만 · 녹음 제외</span> ${badge}</h3>
      <label class="switch"><input type="checkbox" id="ts-on" ${on ? 'checked' : ''}> 사용</label></div>
    <p>같은 Apple ID의 아이폰·아이패드 쓰담과 <b>학급·학생 명단·학생별 기록·초안</b>을 주고받습니다. 맥에서 정리하면 폰에서도 보이고, 폰에서 고친 것도 맥에 들어와요. 녹음 파일은 오가지 않아요.</p>
    <p class="muted small">${st.state === 'iCloud 쓰담 폴더 없음' ? '아이폰에 쓰담 앱을 설치하고 한 번 열면 iCloud 폴더가 생겨요.' :
      st.state === '정상' ? `마지막으로 맞춘 시각 ${last}${st.devices && st.devices.length ? ' · 함께 쓰는 기기: ' + st.devices.map(esc).join(', ') : ' · 아직 다른 기기 없음'}` :
      st.state === '오류' ? '오류: ' + esc(st.error || '') : esc(st.state || '')}</p>`;
  $('#ts-on').onchange = async e => { await api('/api/sync/text', { enabled: e.target.checked }); renderTextSync(); };
}
