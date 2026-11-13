// Run the production editor handlers with deferred responses and a minimal DOM.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('app/static/app.js', 'utf8');
function block(start, end) {
  const from = source.indexOf(start), to = source.indexOf(end, from);
  assert.ok(from >= 0 && to > from, `Production block is present: ${start}`);
  return source.slice(from, to);
}
function element(props = {}) {
  return {isConnected: true, value: '', innerHTML: '', textContent: '', className: '',
    dataset: {}, disabled: false, addEventListener() {}, ...props};
}
function harness(section) {
  const nodes = new Map();
  const editor = element({value: '가상 관찰 기록'});
  for (const id of ['d-count', 'd-warn', 'd-review', 'd-rate', 'd-final']) nodes.set(`#${id}`, element());
  nodes.set('#d-text', editor);
  const selected = {id: 1, content: editor.value, ai_text: editor.value, rated: false};
  const requests = [], toasts = [];
  let rateButtons = [], modalNodes = [], closed = 0, reloads = 0;
  function detachModal() {
    for (const [id, node] of modalNodes) {
      node.isConnected = false;
      if (nodes.get(id) === node) nodes.delete(id);
    }
    modalNodes = [];
  }
  const context = vm.createContext({
    text: editor, sourceDraft: selected, current: {id: 2, content: editor.value, ai_text: '다른 생성 원문'},
    s: {id: 7, name: '가상학생'}, area: {id: 'subject'}, limit: 1500, FORBIDDEN: [],
    neisBytes: text => Buffer.byteLength(text), esc: value => String(value),
    $: selector => nodes.get(selector),
    $$: (selector, box) => {
      assert.equal(selector, '[data-rate]');
      rateButtons = box.innerHTML.includes('data-rate=') ? ['1', '0'].map(rate => element({dataset: {rate}})) : [];
      return rateButtons;
    },
    api: (path, body) => new Promise((resolve, reject) => requests.push({path, body, resolve, reject})),
    toast: (...args) => toasts.push(args), reload: () => { reloads++; },
    modal: (_html, mounted) => {
      detachModal();
      for (const id of ['draft-rate-send', 'draft-rate-cancel', 'draft-reason']) {
        const node = element({value: id === 'draft-reason' ? 'missing' : ''});
        nodes.set(`#${id}`, node); modalNodes.push([`#${id}`, node]);
      }
      mounted();
    },
    closeModal: () => { closed++; detachModal(); },
  });
  vm.runInContext(block('  const isCurrentEditor = () =>', '  const renderSources = () =>'), context);
  const sections = {
    review: ['  let checkedReview = null;', "  $('#st-edit').onclick"],
    rating: ['  const renderRating = () => {', "  $('#d-save').onclick"],
    confirm: ["  $('#d-final').onclick = async () => {", "  $$('[data-ver]').forEach"],
  };
  vm.runInContext(block(...sections[section]), context);
  return {nodes, editor, selected, requests, toasts, context,
    get rateButtons() {return rateButtons;}, get closed() {return closed;}, get reloads() {return reloads;},
    navigate() {
      for (const node of nodes.values()) node.isConnected = false;
      for (const id of ['d-text', 'd-count', 'd-warn', 'd-rate']) {
        nodes.set(`#${id}`, element({innerHTML: '다음 학생의 화면', textContent: '다음 학생의 수치'}));
      }
    },
    replaceModal() {detachModal(); nodes.set('#unrelated-modal', element({innerHTML: '다른 작업'}));},
  };
}

test('review response after navigation does not overwrite the next student', async () => {
  const h = harness('review'), button = h.nodes.get('#d-review');
  const pending = button.onclick();
  h.navigate();
  h.requests[0].resolve({hasSources: true, review: {missing: ['이전 학생의 점검 결과']}});
  await pending;
  assert.equal(h.nodes.get('#d-warn').innerHTML, '다음 학생의 화면');
  assert.equal(h.nodes.get('#d-count').textContent, '다음 학생의 수치');
  assert.equal(h.toasts.length, 0);
  assert.equal(button.disabled, false);
});

test('review response is discarded when the selected version changes', async () => {
  const h = harness('review');
  const pending = h.nodes.get('#d-review').onclick();
  vm.runInContext('sourceDraft = {...sourceDraft, id: 3}', h.context);
  h.requests[0].resolve({hasSources: true, review: {missing: ['오래된 결과']}});
  await pending;
  assert.equal(h.nodes.get('#d-warn').innerHTML, '');
  assert.match(h.toasts[0][0], /다시 점검/);
});

test('review response for the current text displays its evidence hints', async () => {
  const h = harness('review');
  h.editor.value = '편집한 가상 관찰 기록';
  const pending = h.nodes.get('#d-review').onclick();
  assert.equal(h.requests[0].body.source_draft_id, h.selected.id);
  assert.equal(h.requests[0].body.content, h.editor.value);
  h.requests[0].resolve({hasSources: true, review: {missing: ['확인할 가상 기록']}});
  await pending;
  assert.match(h.nodes.get('#d-warn').innerHTML, /확인할 가상 기록/);
  assert.match(h.nodes.get('#d-count').textContent, /바이트/);
});

test('rating response after navigation cannot render or toast on another student', async () => {
  const h = harness('rating');
  const pending = h.rateButtons[0].onclick();
  h.navigate();
  h.requests[0].resolve({recorded: true});
  await pending;
  assert.equal(h.selected.rated, true);
  assert.equal(h.nodes.get('#d-rate').innerHTML, '다음 학생의 화면');
  assert.equal(h.toasts.length, 0);
});

test('late negative rating does not close a replacement modal', async () => {
  const h = harness('rating');
  await h.rateButtons[1].onclick();
  const pending = h.nodes.get('#draft-rate-send').onclick();
  assert.equal(h.requests[0].body.reason, 'missing');
  h.replaceModal();
  h.requests[0].resolve({recorded: true});
  await pending;
  assert.equal(h.closed, 0);
  assert.equal(h.nodes.get('#unrelated-modal').isConnected, true);
});

test('successful negative rating closes its own modal and marks its version', async () => {
  const h = harness('rating');
  await h.rateButtons[1].onclick();
  const pending = h.nodes.get('#draft-rate-send').onclick();
  h.requests[0].resolve({recorded: true});
  await pending;
  assert.equal(h.closed, 1);
  assert.equal(h.selected.rated, true);
  assert.match(h.nodes.get('#d-rate').innerHTML, /평가를 남긴/);
});

test('failed rating stays available for retry and never reports success', async () => {
  const h = harness('rating'), button = h.rateButtons[0];
  const pending = button.onclick();
  h.requests[0].reject(new Error('statistics unavailable'));
  await assert.rejects(pending, /statistics unavailable/);
  assert.equal(button.disabled, false);
  assert.equal(h.selected.rated, false);
  assert.equal(h.toasts.length, 0);
});

test('confirm uses the selected version when latest text is identical', async () => {
  const h = harness('confirm');
  const pending = h.nodes.get('#d-final').onclick();
  assert.equal(h.requests[0].body.id, 1);
  assert.equal(h.requests[0].body.source_draft_id, 1);
  assert.equal(h.requests[0].body.as_new, false);
  h.requests[0].resolve({ok: true, id: 1});
  await pending;
  assert.equal(h.reloads, 1);
});

test('confirming edited text creates a new version with the selected source', async () => {
  const h = harness('confirm');
  h.editor.value = '교사가 편집한 가상 기록';
  const pending = h.nodes.get('#d-final').onclick();
  assert.equal(h.requests[0].body.id, null);
  assert.equal(h.requests[0].body.source_draft_id, 1);
  assert.equal(h.requests[0].body.as_new, true);
  h.requests[0].resolve({ok: true, id: 3});
  await pending;
});
