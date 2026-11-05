// Offline regression checks. No store, backend or paid API calls are made.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const read = p => fs.readFileSync(p, 'utf8');
const js = read('app/static/app.js');
const ios = read('mobile/ios/Sseudam/PlusView.swift');
const android = read('mobile/android/app/src/main/java/kr/sseudam/app/Plus.kt');
const play = read('mobile/android/app/src/play/java/kr/sseudam/app/PlusBilling.kt');
const github = read('mobile/android/app/src/github/java/kr/sseudam/app/PlusBilling.kt');

test('iOS rejects direct purchase entry before authentication, config or StoreKit', () => {
  assert.match(ios, /static let salesEnabled = false/);
  assert.match(ios, /func buy\(_ p: Product\) async \{\s*guard Plus.salesEnabled else \{ message = Plus.salesNotice; return \}/);
  assert.match(ios, /func loadProducts\(\) async \{\s*guard Plus.salesEnabled else \{ products = \[\]; return \}/);
  assert.match(ios, /ForEach\(Plus.salesEnabled \? plus.products : \[\]/);
  assert.match(ios, /Text\(Plus.salesNotice\)/);
  assert.match(ios, /유료 상품 곧 오픈/);
});

test('both Android purchase entry points block even stale offers without store calls', () => {
  assert.match(android, /const val SALES_ENABLED = false/);
  assert.match(android, /suspend fun buy\(activity: Activity, offer: PlusOffer\) \{\s*if \(!SALES_ENABLED\) \{ message.value = SALES_NOTICE; return \}/);
  assert.match(play, /suspend fun launch\(activity: Activity, offer: PlusOffer, accountId: String\): String\? \{\s*if \(!Plus.SALES_ENABLED\) return Plus.SALES_NOTICE/);
  assert.match(play, /suspend fun loadOffers\(basePlans: List<String>\) \{\s*if \(!Plus.SALES_ENABLED\) \{ _offers.value = emptyList\(\); details.clear\(\); return \}/);
  assert.match(android, /if \(Plus.SALES_ENABLED\) offers else emptyList\(\)/);
  assert.match(github, /suspend fun launch[^]*=\s*Plus.SALES_NOTICE/);
  assert.match(android, /Text\(Plus.SALES_NOTICE,/);
});

test('restore, receipt ingestion, renewals and management remain reachable', () => {
  const restore = ios.slice(ios.indexOf('    func restore()'), ios.indexOf('\nextension ISO8601DateFormatter'));
  assert.doesNotMatch(restore, /salesEnabled/);
  for (const token of ['AppStore.sync()', 'Transaction.currentEntitlements', 'Transaction.updates', 'Transaction.unfinished']) assert.ok(restore.includes(token), token);
  assert.match(ios, /"action": "iap-apple"/);
  assert.match(ios, /AppStore.showManageSubscriptions/);
  assert.match(play, /const val AVAILABLE = true/);
  assert.match(play, /\.setListener \{ r, purchases -> onPurchases\(r, purchases\) \}/);
  assert.match(play, /Plus.sendPurchase\(p.purchaseToken\)/);
  assert.match(play, /client.queryPurchasesAsync/);
  assert.match(android, /PlusBilling.resendPurchases\(all = true\); refresh\(\)/);
  assert.match(android, /ChipButton\("구독 관리"\)/);
  assert.match(android, /ChipButton\("구매 복원"/);
  assert.doesNotMatch(play.slice(play.indexOf('    private fun onPurchases')), /SALES_ENABLED/);
});

test('desktop no longer advertises new purchases or beta enrollment', () => {
  assert.doesNotMatch(js, /새 구독은|스토어 구매 안내|구매·복원 안내|베타 신청하면 1달|id="plus-beta"/);
  assert.match(js, /유료 상품 곧 오픈/);
  assert.match(js, /이름 기준 기록 정리와 프롬프트 복사·결과 붙여넣기/);
  assert.match(js, /id="plus-use"/);
  assert.match(js, /id="plus-refresh"/);
});

async function banner(sub, loggedIn = true) {
  const b = {innerHTML: '', classList: {add() {}, remove() {}}};
  const close = {};
  const context = vm.createContext({api: async () => ({loggedIn, sub, renewUrl: 'https://unexpected.example/buy'}),
    $: selector => selector === '#plus-banner' ? b : close,
    localStorage: {getItem: () => null, setItem() {}}, Date});
  vm.runInContext(js.slice(js.indexOf('async function checkPlusRenew()'), js.indexOf('// 업데이트 안내 문구')), context);
  await context.checkPlusRenew();
  return {b, close};
}

test('expiring entitlement banner offers free continuation and management, never renewal checkout', async () => {
  for (const daysToEnd of [0, 7]) {
    const {b, close} = await banner({active: true, plan: 'month', daysToEnd, endsAt: '2026-11-10'});
    assert.match(b.innerHTML, /유료 상품 곧 오픈/);
    assert.match(b.innerHTML, /기존 무료 기능/);
    assert.match(b.innerHTML, /구독·결제 관리/);
    assert.doesNotMatch(b.innerHTML, /unexpected.example|구매해/);
    assert.equal(typeof close.onclick, 'function');
    close.onclick();
  }
});

test('no purchase banner for free, logged-out, auto-renewing or staff users', async () => {
  for (const sub of [{active: false}, {active: true, autoRenew: true}, {active: true, plan: 'staff'}, {active: true, daysToEnd: 8}]) {
    assert.equal((await banner(sub)).b.innerHTML, '');
  }
  assert.equal((await banner({active: true, daysToEnd: 1}, false)).b.innerHTML, '');
});

test('mocked desktop account states keep free access and existing entitlements without sale CTAs', () => {
  const start = js.indexOf("    let d = '';", js.indexOf('async function viewSettings('));
  const end = js.indexOf("    $('#ai-detail').innerHTML = d;", start);
  for (const state of [
    {loggedIn: false},
    {loggedIn: true, pay: true},
    {loggedIn: true, pay: false, betaRequested: true},
    {loggedIn: true, pay: false, betaRequested: false},
    {loggedIn: true, sub: {active: true, plan: 'month', planName: '기존 이용권', daysToEnd: 2, endsAt: '2026-11-10'}, devices: [], deviceLimit: 3},
  ]) {
    const context = vm.createContext({st: {plus_enabled: true}, choice: 'manual', showPlus: true,
      plusSt: state, plusOn: !!state.sub?.active, esc: String, ymd: String, plusEmail: '', plusCodeSent: false});
    const html = vm.runInContext(js.slice(start, end) + '\nd;', context);
    assert.match(html, /유료 상품 곧 오픈/);
    assert.doesNotMatch(html, /스토어 구매|구매해 주세요|id="plus-beta"/);
    if (state.sub?.active) {
      assert.match(html, /기존 이용권/);
      assert.match(html, /id="plus-use"/);
      assert.match(html, /구독·결제 관리/);
    } else {
      assert.match(html, /기존 무료 기능/);
      assert.match(html, state.loggedIn ? /id="plus-refresh"/ : /id="plus-login"/);
    }
  }
});
