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
  '확인필요': 'amber', '완료': 'green', '오류': 'red' };

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
function badge(status) { return `<span class="badge ${STATUS_COLOR[status] || ''}">${esc(status)}</span>`; }
function kindBadge(kind) { return `<span class="badge ${kind === '상담' ? 'violet' : 'blue'}">${esc(kind || '수업')}</span>`; }

// ───────────────────────── AI 실행 (API / 수동) ─────────────────────────

async function runAI(op, params, label, onDone) {
  let res;
  try { res = await api('/api/ai/run', { op, params, label: label || '' }, { silent: true }); }
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
  const titles = { transcribe: '전사 (수동)', segment: '학생별 분리 (수동)', draft: '세특 초안 (수동)', shorten: '초안 줄이기 (수동)' };
  const audioStep = op === 'transcribe'
    ? `<li><b>녹음 파일도 함께 첨부</b>하세요. <button class="sm" id="m-reveal">녹음 파일 위치 열기</button> (Finder에서 파일을 Gemini 창으로 끌어다 놓기)</li>` : '';
  modal(`
    <h2>${titles[op] || 'AI 작업'}</h2>
    <div class="info-box"><ol>
      <li>아래 <b>프롬프트 복사</b> → Gemini(gemini.google.com) 또는 ChatGPT 새 대화에 붙여넣기</li>
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
    } else fab.className = 'jobs-fab hidden';
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
      <button class="sm" id="jp-cancel">대기 작업 취소</button> <button class="sm" id="jp-clear">기록 지우기</button></span></div>` +
    (jobs.length ? jobs.map(j => `<div class="job"><div><span class="badge ${{ '완료': 'green', '실패': 'red', '진행중': 'blue' }[j.status] || ''}">${esc(j.status)}</span> ${esc(j.label)}</div>
      ${j.message ? `<div class="msg">${esc(j.message)}</div>` : ''}<div class="msg">${esc(fmtDate(j.created_at))}</div></div>`).join('')
      : '<p class="muted">작업이 없습니다.</p>');
  $('#jp-clear', p).onclick = async () => { await api('/api/jobs/clear', {}); pollJobs(); };
  $('#jp-cancel', p).onclick = async () => { await api('/api/jobs/cancel', {}); pollJobs(); };
}
$('#jobs-fab').onclick = () => $('#jobs-panel').classList.toggle('hidden');

let refreshPending = false;
function refreshCurrent() {
  // 사용자가 입력 중이면 화면을 새로 그리지 않음
  const ae = document.activeElement;
  if (ae && (ae.tagName === 'TEXTAREA' || ae.tagName === 'INPUT') && view.contains(ae) && ae.dataset.dirty) { refreshPending = true; return; }
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
        <div class="card"><b>1</b><h3>설정</h3><p class="muted small">Gemini API 키를 넣거나, 키 없이 '수동 모드'를 선택합니다.</p><a href="#/settings">설정 열기 →</a></div>
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
  const isApi = settings.mode === 'api' && settings.has_key;
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
        <label class="check" style="margin-top:10px"><input type="checkbox" id="up-auto" ${isApi ? 'checked' : 'disabled'}> 올린 뒤 자동으로 전사 → 학생별 분리 ${isApi ? '' : '<span class="muted small">(API 모드에서만 가능)</span>'}</label>
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
  const studentOpts = sel => '<option value="">학생 선택…</option>' + d.students.map(s => `<option value="${s.id}" ${s.id === sel ? 'selected' : ''}>${s.number}번 ${esc(s.name)}</option>`).join('');
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
            <button id="b-rule" ${!r.transcript ? 'disabled' : ''} title="AI 없이 이름이 언급된 위치로 나눕니다">이름 기준 분리(AI 없이)</button></span></div>
          ${!r.class_id ? '<div class="warn">학급을 지정해야 학생 명단과 대조할 수 있습니다. (AI 분리 시 전사문에서 학급을 찾으면 자동 지정)</div>' : ''}
          ${d.notes.length ? '' : '<p class="muted">아직 분리된 내용이 없습니다.</p>'}
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
          <p class="help" style="margin-top:-6px">NEIS나 엑셀에서 <b>${club ? '학번, 이름' : '번호, 이름'}</b> 두 열을 복사해 붙여넣으세요. 같은 번호가 있으면 이름을 덮어씁니다.</p>
          <textarea id="bulk" rows="10" placeholder="${club ? '20315	김민수&#10;10702	이서연' : '1	김민수&#10;2	이서연&#10;3	박지훈'}"></textarea>
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
  $('#bulk').oninput = () => {
    const lines = $('#bulk').value.split('\n').filter(l => l.trim()).length;
    $('#bulk-preview').textContent = lines ? `${lines}줄` : '';
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
          <div class="row" style="margin-top:10px"><button class="primary shrink" id="d-gen" ${notesInArea.length ? '' : 'disabled'}>✨ AI 초안 생성</button><span></span></div>
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
  const isApi = settings.mode === 'api' && settings.has_key;
  view.innerHTML = `
    <div class="page-head"><div><h1>초안</h1><div class="muted">학급 전체의 초안을 만들고 구글시트·엑셀로 내보냅니다.</div></div>
      <div class="actions"><select id="dc" style="width:auto">${classOptions(classId)}</select></div></div>
    ${areas.length > 1 ? `<div class="tabs">${areas.map(a => `<button class="${a.id === area.id ? 'on' : ''}" data-area="${a.id}">${esc(a.name)}</button>`).join('')}</div>` : ''}
    <div class="card">
      <div class="section-title"><h2>${esc(c.label)} · ${esc(area.full)} <span class="muted small">확정 ${done}/${d.students.length}</span></h2>
        <span class="actions" style="display:flex;gap:6px;flex-wrap:wrap">
          <button id="g-missing" ${isApi && missing ? '' : 'disabled'} title="${isApi ? '' : 'API 모드에서만 일괄 생성할 수 있습니다'}">초안 없는 학생 생성 (${missing})</button>
          <button id="g-all" ${isApi && withNotes ? '' : 'disabled'}>기록 있는 학생 전체 생성 (${withNotes})</button>
          <button id="x-copy">표 복사</button>
          <button id="x-csv">CSV</button>
          <button id="x-xlsx">엑셀로 저장</button>
          <button class="primary" id="x-sheet">구글시트 지금 반영</button></span></div>
      ${isApi ? '' : '<p class="help">API 키 없이 쓸 때는 학생 이름을 눌러 한 명씩 만들거나, 왼쪽 <a href="#/prompts">프롬프트 안내</a>대로 Gemini·ChatGPT 웹에서 만드세요.</p>'}
      <details class="lesson-ctx" ${d.context.topic || d.context.competencies || d.context.philosophy ? '' : 'open'}>
        <summary><b>📚 수업 정보</b> <span class="muted small">초안을 만들 때 AI에게 함께 알려 줘요 (${esc(c.label)} · ${esc(area.name)})</span></summary>
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
    $('#ctx-saved').textContent = '저장했어요 ✓ 다음 초안부터 반영돼요';
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
  $('#g-missing').onclick = () => batch(true);
  $('#g-all').onclick = () => batch(false);
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
      <button role="tab" data-stab="basic" id="stab-basic" aria-controls="settings-grid">기본</button>
      <button role="tab" data-stab="adv" id="stab-adv" aria-controls="settings-grid">고급</button></div>
    <div class="grid grid-2" id="settings-grid">
      <div class="card" data-pane="basic">
        <h2>👩‍🏫 선생님</h2>
        <label class="field"><span>선생님 이름 (대시보드 인사·휴대폰 앱에 표시)</span><input id="teacher_name" value="${esc(s.teacher_name)}" placeholder="예: 김쓰담"></label>
        <p class="help">학교급·과목·글자 수 같은 작성 기준은 <b>고급</b> 탭에 있어요.</p>
      </div>
      <div class="card" data-pane="basic" id="trash-card">
        <h2>🗑 휴지통</h2>
        <p class="muted small" style="margin-top:-4px">지운 학급·학생·녹음·관찰기록·초안은 30일 동안 휴지통에 있어요. 실수로 지워도 되살릴 수 있어요.</p>
        <a class="btn" href="#/trash">휴지통 열기</a>
      </div>
      <div class="card" data-pane="adv">
        <h2>AI 사용 방식</h2>
        <label class="check"><input type="radio" name="mode" value="api" ${s.mode === 'api' ? 'checked' : ''}> <b>API 모드</b> — 본인 Gemini API 키로 자동 처리 (권장)</label><br>
        <label class="check" style="margin-top:6px"><input type="radio" name="mode" value="manual" ${s.mode === 'manual' ? 'checked' : ''}> <b>수동 모드</b> — 키 없이, 프롬프트를 Gemini·ChatGPT 웹에 복사해서 사용</label>
        <div class="info-box" style="margin-top:14px">
          <b>Gemini API 키 받는 법 (무료, 1분)</b>
          <ol><li><a href="https://aistudio.google.com/apikey" target="_blank">aistudio.google.com/apikey</a> 접속 → 구글 계정 로그인</li>
            <li><b>API 키 만들기</b> 클릭 → 생성된 키 복사</li><li>아래 칸에 붙여넣고 <b>연결 테스트</b></li></ol>
          <p class="small muted" style="margin:8px 0 0">Gemini 구독(Google AI Pro)과 API 키는 별개이며, 키는 무료 등급으로도 사용 가능합니다. 단, 무료 등급은 입력 내용이 구글 서비스 개선에 쓰일 수 있으니 학생 정보 보호를 위해 AI Studio에서 결제 수단을 등록(유료 등급)하는 것을 권장합니다. 사용량이 적으면 비용은 매우 적습니다.</p>
        </div>
        <label class="field" style="margin-top:14px"><span>Gemini API 키</span>
          <input id="key" type="password" placeholder="${s.has_key ? esc(s.gemini_api_key_masked) + ' (저장됨 — 바꿀 때만 입력)' : 'AIza로 시작하는 키'}" autocomplete="off"></label>
        <div class="row" style="margin-top:8px"><button class="shrink" id="test">연결 테스트</button>${s.has_key ? '<button class="shrink danger" id="clear-key">키 삭제</button>' : ''}<span id="test-result" class="small"></span></div>
        <label class="field" style="margin-top:12px"><span>모델</span>
          <div class="row"><input id="model" value="${esc(s.gemini_model)}" list="model-list"><datalist id="model-list"></datalist></div></label>
        <p class="help">기본값 gemini-2.5-flash. '연결 테스트'를 누르면 쓸 수 있는 모델 목록이 채워집니다. 지정 모델이 없어지면 자동으로 다른 flash 모델로 바뀝니다.</p>
      </div>
      <div class="card" data-pane="adv">
        <h2>작성 기준</h2>
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
      <div class="card" id="import" data-pane="adv" style="grid-column:1 / -1">
        <div class="section-title"><h2>아이폰 기록 가져오기</h2>
          <label class="check"><input type="checkbox" id="auto_process" ${s.auto_process === '1' ? 'checked' : ''}> 들어오면 자동으로 처리 (받아쓰기 → 학생별 분리까지)</label></div>
        <p class="help" style="margin-top:-4px">한 수업에 여러 학생을 한 번에 녹음해도 됩니다. 파일을 학생별로 나누거나 이름을 붙일 필요가 없습니다 — 이름이 언급된 곳을 기준으로 자동으로 나눕니다. 학급은 아래 <b>시간표</b>로 녹음 시각에 맞춰 자동 지정됩니다.</p>
        <div id="src-box"><p class="muted">불러오는 중…</p></div>
      </div>
      <div class="card" data-pane="adv" style="grid-column:1 / -1">
        <div class="section-title"><h2>시간표 (녹음 시각 → 학급 자동 지정)</h2><span class="muted small">수업 시간 중이나 끝난 뒤 15분 안의 녹음·메모는 그 시간 학급으로 들어갑니다</span></div>
        <div class="split" style="grid-template-columns: 180px 1fr">
          <label class="field"><span>교시 시간 (한 줄에 하나)</span><textarea id="period_times" rows="9" style="font-variant-numeric:tabular-nums">${esc(s.period_times)}</textarea></label>
          <div id="tt-box" style="overflow:auto"></div>
        </div>
      </div>
      <div class="card" style="grid-column:1 / -1" id="stt" data-pane="basic">
        <div class="section-title"><h2>받아쓰기(음성 → 글자) 엔진</h2><span id="stt-active" class="small"></span></div>
        <div class="row" style="gap:18px;align-items:center">
          <label class="check shrink"><input type="radio" name="stt_engine" value="whisper" ${s.stt_engine !== 'gemini' ? 'checked' : ''}> <b>내 맥에서 (Whisper)</b> — 권장 · 녹음이 외부로 나가지 않음 · 무료</label>
          <label class="check shrink"><input type="radio" name="stt_engine" value="gemini" ${s.stt_engine === 'gemini' ? 'checked' : ''}> Gemini — 녹음을 구글로 보내서 받아쓰기</label>
        </div>
        <p class="help"><b>Whisper</b>는 오픈AI가 공개한 음성 인식 모델을 이 맥에서 직접 돌립니다. 인터넷·API 키·비용이 없고 <b>녹음이 맥 밖으로 나가지 않아</b> 학생 개인정보에 가장 안전합니다. 처음 한 번 모델을 내려받으세요.</p>
        <div id="wh-box" style="margin-top:10px"><p class="muted">확인 중…</p></div>
      </div>
      <div class="card" style="grid-column:1 / -1" id="localai" data-pane="basic">
        <div class="section-title"><h2>🧠 학생별로 나누는 AI</h2><span id="la-active" class="small"></span></div>
        <p class="help" style="margin-top:-4px">이름이 나온 문장은 그대로 그 학생에게, "그 친구는…", "다만…"처럼 <b>이름 없이 이어지는 문장</b>만 AI가 골라요. 그 녹음에 이름이 나온 학생 중에서만 고르니 없는 학생이 생기지 않아요.</p>
        <div class="seg-engines" style="display:grid;gap:6px;margin-top:6px">
          ${[['auto', '<b>자동</b> (추천) — Gemini 키가 있으면 Gemini, 없으면 내 맥 AI'],
             ['apple', '<b>기기 안 AI</b> (Apple) — 설치 없음 · 무료 · 녹음이 맥 밖으로 안 나감'],
             ['local', '<b>쓰담 AI 모델</b> — 아래에서 받은 모델 (또는 Ollama · LM Studio) · 맥 밖으로 안 나감'],
             ['gemini', 'Gemini — API 키로 (구글 서버에서 처리)'],
             ['rules', 'AI 없이 이름 나온 곳 기준으로만']].map(([v, t]) =>
            `<label class="check"><input type="radio" name="seg_engine" value="${v}" ${(s.seg_engine || 'auto') === v ? 'checked' : ''}> ${t}</label>`).join('')}
        </div>
        <div class="split" style="margin-top:14px">
          <div class="info-box"><b>기기 안 AI (Apple)</b>
            <p id="la-apple" class="small" style="margin:6px 0">확인 중…</p>
            <button class="sm" id="la-test-apple">시험해 보기</button> <span id="la-apple-r" class="small"></span>
            <p class="small muted" style="margin:8px 0 0">macOS 26 이상 · Apple Intelligence가 켜진 맥(M1 이상)에서 돼요. 학생 나누기용이고, 세특 초안은 아래 AI 앱이나 Gemini로 써요.</p></div>
          <div class="info-box"><b>✨ 쓰담 AI 모델 받기</b> <span class="small muted">— 설치 프로그램 없이, 버튼 한 번</span>
            <div id="llm-box" class="small" style="margin-top:8px">확인 중…</div>
            <label class="check" style="margin-top:8px"><input type="checkbox" id="draft_local" ${s.draft_local !== '0' ? 'checked' : ''}> Gemini 키가 없으면 세특 초안도 이 AI로 쓰기</label>
          </div>
        </div>
        <details style="margin-top:12px"><summary class="small">Ollama · LM Studio를 이미 쓰고 있다면 (고급)</summary>
          <div class="info-box" style="margin-top:8px">
            <div id="la-detect" class="small" style="margin:6px 0">찾는 중…</div>
            <label class="field"><span>주소</span><input id="local_ai_url" value="${esc(s.local_ai_url === 'builtin' ? '' : (s.local_ai_url || ''))}" placeholder="http://127.0.0.1:11434/v1"></label>
            <label class="field" style="margin-top:6px"><span>모델</span><input id="local_ai_model" value="${esc(s.local_ai_url === 'builtin' ? '' : (s.local_ai_model || ''))}" list="la-models" placeholder="예: qwen3:8b"><datalist id="la-models"></datalist></label>
            <div class="row" style="margin-top:8px"><button class="sm shrink" id="la-test-local">시험해 보기</button><span id="la-local-r" class="small"></span></div>
            <p class="small muted" style="margin:8px 0 0">주소를 넣으면 위에서 받은 모델 대신 이 앱을 써요. 비우면 쓰담 AI 모델로 돌아가요. 주소는 이 맥(localhost)만 쓸 수 있어요.</p></div>
        </details>      </div>
      <div class="card" style="grid-column:1 / -1" id="google" data-pane="adv">
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
      <div class="card" style="grid-column:1 / -1" id="phone" data-pane="basic">
        <div class="section-title"><h2>📱 휴대폰 '쓰담' 앱 연결</h2><label class="check"><input type="checkbox" id="drive_inbox" ${s.drive_inbox === '1' ? 'checked' : ''}> 휴대폰 녹음 자동으로 가져오기</label></div>
        <div class="split">
          <div class="info-box"><b>아이폰</b> — App Store에서 <b>쓰담</b> 설치 → 녹음하면 <b>iCloud로 자동 연동</b> (같은 Apple ID면 설정 없음)${s.platform === 'win' ? '<br><span class="small muted">윈도우 PC는 iCloud for Windows가 설치돼 있어야 합니다. 없으면 아래 구글 연결을 쓰세요.</span>' : ''}
            <br><br><b>안드로이드(갤럭시) · 아이폰 공통</b> — Play 스토어/App Store에서 <b>쓰담</b> 설치 → 앱의 <b>컴퓨터 연결</b> → 오른쪽 QR 찍기 → 녹음이 <b>내 구글 드라이브</b>를 거쳐 이 컴퓨터로 자동 전송
            <p class="small muted" style="margin:6px 0 0">QR에는 '녹음 올리기'만 가능한 전용 열쇠가 들어 있습니다. 휴대폰을 잃어버려도 기록을 볼 수는 없습니다. <b>고급 → 구글 연동</b>이 먼저 되어 있어야 합니다.</p></div>
          <div style="text-align:center"><div id="qr-box" class="muted small">불러오는 중…</div>
            <button class="sm" id="phone-scan" style="margin-top:8px">휴대폰 녹음 지금 가져오기</button></div>
        </div>
        <div class="source" id="ts-box" style="margin-top:14px"></div>
      </div>
      <div class="card" style="grid-column:1 / -1" id="backup-card" data-pane="basic">
        <div class="section-title"><h2>백업 · 복원 · 엑셀</h2>
          <span style="display:flex;gap:6px;flex-wrap:wrap"><button id="backup">지금 백업 (이 맥)</button><button id="xlsx-all" class="primary">전체 엑셀로 저장</button></span></div>
        <p class="help" style="margin-top:-4px">이 맥에는 매일 자동 백업(30일)됩니다. 구글 드라이브 백업까지 켜 두면 맥이 고장 나도 복원할 수 있습니다. 녹음 원본(오디오)은 용량 때문에 이 맥에만 보관되니, 타임머신 백업을 함께 쓰면 가장 안전합니다.</p>
        <div class="split" style="margin-top:8px">
          <div><h3>복원할 백업 고르기</h3><div id="bk-list" class="small"><p class="muted">불러오는 중…</p></div></div>
          <div><h3>파일로 복원</h3><p class="help">받아 둔 백업 파일(.zip 또는 .db)을 고르세요. 복원 전에 지금 상태를 자동 백업합니다.</p>
            <input type="file" id="restore-file" accept=".zip,.db"></div>
        </div>
      </div>
      <div class="card" data-pane="basic" style="grid-column:1 / -1" id="update-card">
        <div class="section-title"><h2>✨ 프로그램 업데이트</h2>
          <label class="switch"><input type="checkbox" id="auto_update" ${s.auto_update !== '0' ? 'checked' : ''}> 자동으로 업데이트</label></div>
        <p class="muted small" style="margin-top:-4px">새 버전이 나오면 쉬는 틈에 알아서 바꿔요. 학생 기록은 그대로예요.</p>
        <p class="small" id="upd-info">현재 버전 확인 중…</p>
        <div class="row"><button class="shrink" id="upd-check">지금 확인</button>
          <label class="check"><input type="checkbox" id="update_check" ${s.update_check === '1' ? 'checked' : ''}> 새 버전이 있으면 화면 위에 알려 주기</label></div>
        <p class="help">자동 업데이트는 20분 동안 아무 조작이 없고, AI 작업·모델 내려받기가 없을 때만 해요. 바꾸기 직전에 기록을 자동 백업해요.</p>
      </div>
    </div>
    <div style="position:sticky;bottom:0;padding:14px 0;background:linear-gradient(transparent, var(--bg) 30%);display:flex;justify-content:flex-end">
      <button class="primary" id="save" style="padding:10px 28px">설정 저장</button></div>`;
  $('#open-data').onclick = e => { e.preventDefault(); api('/api/open_data', {}); };
  const collect = () => ({
    mode: ($('input[name=mode]:checked') || {}).value || 'api',
    gemini_api_key: $('#key').value, gemini_model: $('#model').value.trim(),
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
    seg_engine: ($('input[name=seg_engine]:checked') || {}).value || 'auto',
    ...($('#local_ai_url').value.trim() ? { local_ai_url: $('#local_ai_url').value.trim(), local_ai_model: $('#local_ai_model').value.trim() }
      : (state.settings.local_ai_url && state.settings.local_ai_url !== 'builtin' ? { local_ai_url: '', local_ai_model: '' } : {})),
    draft_local: $('#draft_local').checked ? '1' : '0',
  });
  const save = async () => { await api('/api/settings', collect()); };
  $('#save').onclick = async () => { await save(); toast('설정을 저장했습니다'); updateModeBadge(); router(true); };
  $('#test').onclick = async () => {
    $('#test-result').textContent = '확인 중…';
    try {
      const r = await api('/api/settings/test', { key: $('#key').value }, { silent: true });
      $('#test-result').innerHTML = `<span style="color:var(--green)">✓ 연결 성공 (모델 ${r.models.length}개)</span>`;
      $('#model-list').innerHTML = r.models.map(m => `<option value="${esc(m.name)}">${esc(m.display)}</option>`).join('');
      if ($('#key').value) { await save(); toast('키를 저장했습니다'); updateModeBadge(); }
    } catch (e) { $('#test-result').innerHTML = `<span style="color:var(--red)">${esc(e.message)}</span>`; }
  };
  if ($('#clear-key')) $('#clear-key').onclick = async () => {
    if (!confirmBox('저장된 API 키를 삭제할까요?')) return;
    await api('/api/settings', { clear_key: true }); router(true); updateModeBadge();
  };
  const engName = { gemini: 'Gemini', apple: '기기 안 AI', rules: '이름 기준',
    get local() { return state.settings.local_ai_url === 'builtin' ? '쓰담 AI 모델' : '내 맥 AI 앱'; } };
  const laLoad = async () => {
    let st;
    try { st = await api('/api/localai/status', undefined, { silent: true }); } catch (e) { $('#la-apple').textContent = e.message; return; }
    $('#la-apple').innerHTML = (st.apple.state === 'ready' ? '<span style="color:var(--green)">✓ </span>' : '') + esc(st.apple.text);
    $('#la-test-apple').disabled = st.apple.state !== 'ready';
    if (st.apple.state === 'notMac') { const box = $('#la-apple').closest('.info-box'); if (box) box.style.display = 'none'; const r = document.querySelector('input[name=seg_engine][value=apple]'); if (r) r.closest('label').style.display = 'none'; }
    $('#la-active').innerHTML = `지금 쓰는 것: <b>${engName[st.seg_engine] || st.seg_engine}</b>`;
    const run = st.detected.filter(d => d.running);
    $('#la-detect').innerHTML = run.length
      ? run.map(d => `<div>✓ <b>${esc(d.name)}</b> 켜져 있음 · 모델 ${d.models.length}개 <button class="sm la-use" data-url="${esc(d.url)}" data-model="${esc(d.models[0] || '')}">이걸로 연결</button></div>`).join('')
      : '<span class="muted">켜진 Ollama · LM Studio가 없어요. 앱을 켜면 여기에 나와요.</span>';
    const models = [...new Set([...(st.local.models || []), ...run.flatMap(d => d.models)])];
    $('#la-models').innerHTML = models.map(m => `<option value="${esc(m)}">`).join('');
    $$('.la-use').forEach(b => b.onclick = () => {
      $('#local_ai_url').value = b.dataset.url;
      if (b.dataset.model && !$('#local_ai_model').value) $('#local_ai_model').value = b.dataset.model;
      const r = document.querySelector('input[name=seg_engine][value=local]'); if (r && (s.seg_engine || 'auto') !== 'auto') r.checked = true;
      toast('주소를 넣었어요. 모델을 고르고 시험해 본 뒤 설정 저장을 눌러 주세요.');
    });
  };
  const laTest = async (engine, out) => {
    out.textContent = '시험하는 중…';
    try {
      const r = await api('/api/localai/test', { engine, local_ai_url: $('#local_ai_url').value.trim(), local_ai_model: $('#local_ai_model').value.trim() }, { silent: true });
      const good = r.correct === r.total;
      out.innerHTML = `<span style="color:var(${good ? '--green' : '--orange, #d97706'})">${good ? '✓ ' : ''}${r.total}문장 중 ${r.correct}개 맞음 · ${r.seconds}초</span>${good ? '' : ' — 더 큰 모델을 쓰면 정확해져요'}`;
    } catch (e) { out.innerHTML = `<span style="color:var(--red)">${esc(e.message)}</span>`; }
  };
  $('#la-test-apple').onclick = () => laTest('apple', $('#la-apple-r'));
  $('#la-test-local').onclick = () => laTest('local', $('#la-local-r'));
  const gb = n => (n / 1e9).toFixed(1) + 'GB';
  let llmTimer = null;
  const llmLoad = async () => {
    let st;
    try { st = await api('/api/localai/models', undefined, { silent: true }); } catch (e) { $('#llm-box').textContent = e.message; return; }
    const cur = state.settings.local_ai_url === 'builtin' ? state.settings.local_ai_model : '';
    const mc = st.machine || {};
    const spec = `<div class="info-box" style="margin:0 0 8px;padding:8px 10px"><b>${mc.os === 'win' ? '💻 이 컴퓨터' : '💻 이 맥'}</b>: ${esc(mc.chip || '')}${mc.ram ? ' · 메모리 ' + mc.ram + 'GB' : ''}
      <div class="small" style="margin-top:4px">${mc.model ? '→ <b>' + esc((st.models.find(m => m.id === mc.model) || {}).name || '') + '</b> 모델을 추천해요. ' : ''}${esc(mc.why || '')}</div></div>`;
    if (st.supported === false) { $('#llm-box').innerHTML = spec; return; }
    if (!st.engine) { $('#llm-box').innerHTML = spec + '<span class="muted">쓰담을 최신 버전으로 업데이트하면 여기서 바로 받을 수 있어요.</span>'; return; }
    $('#llm-box').innerHTML = spec + st.models.map(m => {
      const d = m.download || {}, busy = d.status === 'downloading';
      const pct = busy ? Math.floor(100 * d.done / Math.max(1, d.total)) : 0;
      const tag = m.id === st.recommended ? `<span class="pill" style="background:var(--green);color:#fff;margin-left:4px">${mc.os === 'win' ? '이 컴퓨터' : '이 맥'}에 추천</span>` : '';
      let act;
      if (m.installed) act = m.id === cur ? '<span style="color:var(--green)">✓ 쓰는 중</span> <button class="sm ghost llm-del" data-id="' + m.id + '">지우기</button>'
        : '<button class="sm primary llm-use" data-id="' + m.id + '">이걸로 쓰기</button> <button class="sm ghost llm-del" data-id="' + m.id + '">지우기</button>';
      else if (busy) act = d.stage ? `<span class="muted">${esc(d.stage)}…</span>` : `<progress value="${pct}" max="100" style="width:110px;vertical-align:middle"></progress> ${pct}% <button class="sm ghost llm-stop" data-id="${m.id}">멈춤</button>`;
      else act = `<button class="sm ${m.id === st.recommended ? 'primary' : ''} llm-get" data-id="${m.id}">${m.partial ? '이어 받기' : '받기'} (${gb(m.size)})</button>`;
      const err = d.status === 'error' && d.error ? `<div class="small" style="color:var(--red)">${esc(d.error)}</div>` : '';
      const warn = !m.fits ? '<div class="small" style="color:var(--amber)">이 맥 메모리로는 느리거나 안 될 수 있어요</div>' : '';
      return `<div style="padding:8px 0;border-top:1px solid var(--line)"><b>${esc(m.name)}</b>${tag} · ${esc(m.model)}<div class="muted">${esc(m.desc)}</div>${warn}${err}<div style="margin-top:4px">${act}</div></div>`;
    }).join('') + '<p class="small muted" style="margin:6px 0 0">받은 모델은 이 맥에만 있고, 쓸 때만 켜졌다가 10분 쉬면 꺼져서 메모리를 돌려줘요.</p>';
    $$('.llm-get').forEach(b => b.onclick = async () => { await api('/api/localai/models/download', { id: b.dataset.id }); llmLoad(); });
    $$('.llm-stop').forEach(b => b.onclick = async () => { await api('/api/localai/models/cancel', { id: b.dataset.id }); setTimeout(llmLoad, 800); });
    $$('.llm-use').forEach(b => b.onclick = async () => { await api('/api/localai/models/use', { id: b.dataset.id }); state.settings = await api('/api/settings'); toast('이 모델로 학생을 나눠요 ✨'); llmLoad(); laLoad(); updateModeBadge(); });
    $$('.llm-del').forEach(b => b.onclick = async () => { if (!confirmBox('받은 모델을 지울까요? 다시 쓰려면 또 받아야 해요.')) return; await api('/api/localai/models/delete', { id: b.dataset.id }); state.settings = await api('/api/settings'); llmLoad(); laLoad(); updateModeBadge(); });
    const downloading = st.models.some(m => (m.download || {}).status === 'downloading');
    const justDone = st.models.some(m => (m.download || {}).status === 'done') && !cur;
    if (justDone) state.settings = await api('/api/settings');
    clearTimeout(llmTimer);
    if (downloading && document.body.contains($('#llm-box'))) llmTimer = setTimeout(llmLoad, 1500);
    else if (justDone) { laLoad(); updateModeBadge(); }
  };
  llmLoad();
  laLoad();
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

  // 기본 / 고급 탭
  const showTab = tab => {
    $$('[data-stab]').forEach(b => { const on = b.dataset.stab === tab; b.classList.toggle('on', on); b.setAttribute('aria-selected', on ? 'true' : 'false'); });
    $$('#settings-grid > [data-pane]').forEach(c => c.classList.toggle('hidden', c.dataset.pane !== tab));
    store('local', 'sseudam.settingsTab', tab);
  };
  $$('[data-stab]').forEach(b => b.onclick = () => showTab(b.dataset.stab));
  const target = section && $('#' + section);
  showTab(target && target.dataset.pane ? target.dataset.pane : (store('local', 'sseudam.settingsTab') === 'adv' ? 'adv' : 'basic'));
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
  if (!p || !p.ready) { box.innerHTML = '<div class="warn" style="text-align:left">먼저 <b>고급 → 구글시트 자동 반영 · 드라이브 백업</b>을 연결하세요. 연결하면 여기에 QR이 나타나요.</div>'; return; }
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
        <li>쓰담을 <b>수동 모드</b>로 두면, 녹음·학생 화면의 AI 버튼을 누를 때 명단·기록이 이미 채워진 프롬프트가 자동으로 나옵니다.</li></ol>
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
    3: () => `<h2>🎙 녹음을 글자로 바꾸는 방법</h2>
      <p class="muted">녹음을 <b>이 컴퓨터 안에서</b> 글자로 바꾸는 Whisper 모델(550MB)을 받아 두면, 녹음이 외부로 나가지 않고 비용도 없습니다.</p>
      <div id="ob-wh"></div>`,
    4: () => `<h2>✨ 초안을 만드는 AI</h2>
      <p class="muted">세특 초안 문장은 AI가 써 줍니다. 둘 중 편한 방법을 고르세요. 나중에 설정에서 바꿀 수 있습니다.</p>
      <div class="source"><label class="check"><input type="radio" name="ob-ai" value="manual" checked> <b>지금 쓰는 Gemini·ChatGPT 웹에 복사·붙여넣기</b> (키 필요 없음)</label>
        <p class="small muted">버튼을 누르면 학생 기록이 담긴 문구가 만들어지고, 웹 채팅에 붙여넣은 뒤 답을 다시 붙여넣습니다. '프롬프트 안내' 메뉴에 방법이 있습니다.</p></div>
      <div class="source"><label class="check"><input type="radio" name="ob-ai" value="api"> <b>Gemini API 키로 자동</b> (무료 키, 학급 전체 한 번에 생성 가능)</label>
        <p class="small muted"><a href="https://aistudio.google.com/apikey" target="_blank">aistudio.google.com/apikey</a>에서 '키 만들기' → 복사해서 붙여넣기</p>
        <input id="ob-key" type="password" placeholder="AIza로 시작하는 키 (선택)"></div>`,
  };
  const render = () => {
    modal(`<div class="small muted" style="margin-bottom:6px">${st.step} / 4</div>${steps[st.step]()}
      <div class="modal-actions">${st.step > 1 ? '<button id="ob-back">이전</button>' : '<button id="ob-skip" class="ghost">건너뛰기</button>'}
        <button class="primary" id="ob-next">${st.step === 4 ? '시작하기' : '다음'}</button></div>`, box => {
      if (st.step === 3) whisperBanner($('#ob-wh', box)).then(() => { if (!$('#ob-wh', box).innerHTML) $('#ob-wh', box).innerHTML = '<p class="ok-text">✓ 받아쓰기 준비됨 (또는 이 컴퓨터는 Gemini 받아쓰기를 사용)</p>'; });
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
        if (st.step === 4) {
          const ai = ($('input[name=ob-ai]:checked', box) || {}).value;
          const key = $('#ob-key', box).value.trim();
          const vals = { onboarded: '1', school_level: st.level, teacher_name: st.name || '', teacher_subject: st.subject || '',
            mode: ai === 'api' && key ? 'api' : 'manual' };
          if (key) vals.gemini_api_key = key;
          await api('/api/settings', vals);
          for (const c of st.make) await api('/api/classes/save', Object.assign({ year: y, semester: sem }, c));
          closeModal(); updateModeBadge();
          toast('준비됐습니다! 각 학급에 학생 명단을 붙여넣으세요.');
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
  $('#mode-badge').innerHTML = s.active_seg === 'gemini' ? dot('green') + 'API 모드 · ' + esc(s.gemini_model)
    : s.active_seg === 'apple' ? dot('green') + '기기 안 AI'
    : s.active_seg === 'local' ? dot('green') + (s.local_ai_url === 'builtin' ? '쓰담 AI 모델' : '내 맥 AI · ' + esc(s.local_ai_model || ''))
    : s.mode === 'manual' ? '● 수동 모드' : dot('amber') + 'AI 없음 — <a href="#/settings">설정</a>';
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
