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

test('iOS fetches store products and authorizes each purchase against the current server/account', () => {
  assert.match(ios, /static let salesEnabled = true/);
  assert.match(ios, /Product.products\(for: config.productIDs\)/);
  const buy = ios.slice(ios.indexOf('    func buy('), ios.indexOf('    /// Finish only'));
  assert.match(buy, /guard let session = token/);
  assert.ok(buy.indexOf('configuration(for: session)') < buy.indexOf('p.purchase('));
  assert.ok(buy.indexOf('config.authorize(') < buy.indexOf('p.purchase('));
  assert.match(buy, /currentSession: token/);
  assert.match(ios, /상품 다시 불러오기/);
  assert.doesNotMatch(ios, /유료 상품 곧 오픈/);
});

test('Android purchases require fresh authorization while direct installs remain store-only', () => {
  assert.match(android, /const val SALES_ENABLED = true/);
  const buy = android.slice(android.indexOf('    suspend fun buy('), android.indexOf('    suspend fun sendPurchase('));
  assert.match(buy, /loadProducts\(/);
  assert.match(play, /Plus.SALES_ENABLED/);
  assert.match(github, /suspend fun launch/);
  assert.match(github, /스토어|Google Play/);
});

test('restore, receipt ingestion, renewals and management remain reachable', () => {
  const restore = ios.slice(ios.indexOf('    func restore()'), ios.indexOf('\nextension ISO8601DateFormatter'));
  assert.doesNotMatch(restore, /salesEnabled/);
  for (const token of ['AppStore.sync()', 'Transaction.currentEntitlements', 'Transaction.updates', 'Transaction.unfinished']) assert.ok(restore.includes(token), token);
  assert.match(ios, /"action": "iap-apple"/);
  assert.match(ios, /AppStore.showManageSubscriptions/);
  assert.match(play, /const val AVAILABLE = true/);
  assert.match(play, /\.setListener \{ r, purchases -> onPurchases\(r, purchases\) \}/);
  assert.match(play, /Plus.sendPurchase\(it\)/);
  assert.match(play, /verifyPurchase\(p.purchaseToken\)/);
  assert.doesNotMatch(play, /acknowledgePurchase|SELF_ACK/);
  assert.match(play, /client.queryPurchasesAsync/);
  assert.match(android, /PlusBilling.resendPurchases\(all = true\); refresh\(\)/);
  assert.match(android, /ChipButton\("구독 관리"\)/);
  assert.match(android, /ChipButton\("구매 복원"/);
  assert.doesNotMatch(play.slice(play.indexOf('    private fun onPurchases')), /SALES_ENABLED/);
});

test('Android restoration keeps account identity independent of new-sale authorization', () => {
  const config = android.slice(android.indexOf('    internal suspend fun refreshPurchaseConfig('), android.indexOf('    suspend fun loadProducts()'));
  const loader = android.slice(android.indexOf('    suspend fun loadProducts()'), android.indexOf('    internal fun canPurchaseFor('));
  assert.match(config, /"iap-config"/);
  assert.match(config, /if \(token != t\)/);
  assert.match(config, /accountToken =/);
  assert.match(loader, /refreshPurchaseConfig\(\)/);
  const restore = android.slice(android.indexOf('    suspend fun restore()'));
  assert.ok(restore.indexOf('refreshPurchaseConfig()') < restore.indexOf('PlusBilling.resendPurchases(all = true)'));
  assert.match(play, /purchaseAccountMismatch\(owner, currentAccount\)/);
  assert.match(android, /if \(_email.value != it\) \{ accountToken = null/);
});

test('iOS never finishes a receipt before verified server delivery to the same account', () => {
  const handle = ios.slice(ios.indexOf('    private func handle('), ios.indexOf('    func restore()'));
  for (const gate of ['case .verified', 'config.validateOwner(transaction.appAccountToken)', '"action": "iap-apple"', 'guard token == session', 'j["ok"] as? Bool == true']) {
    assert.ok(handle.indexOf(gate) >= 0 && handle.indexOf(gate) < handle.indexOf('transaction.finish()'), gate);
  }
  assert.match(ios, /if !\(await handle\(v\)\) \{ return \}/);
  assert.match(ios, /구매를 복원하지 못했어요/);
  assert.match(ios, /복원할 App Store 구독을 찾지 못했어요/);
});

test('desktop explains store subscriptions and school access without obsolete launch or beta claims', () => {
  assert.doesNotMatch(js, /유료 상품 곧 오픈|베타 신청하면 1달|id="plus-beta"/);
  assert.match(js, /앱 스토어 구독 · 학교 이용권 연결/);
  assert.match(js, /App Store·Google Play의 쓰담 앱/);
  assert.match(js, /같은 이메일로 로그인/);
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
    assert.doesNotMatch(b.innerHTML, /유료 상품 곧 오픈/);
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

test('desktop account states explain store purchase and preserve free access and existing entitlements', () => {
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
    assert.doesNotMatch(html, /유료 상품 곧 오픈|id="plus-beta"/);
    if (state.sub?.active) {
      assert.match(html, /기존 이용권/);
      assert.match(html, /id="plus-use"/);
      assert.match(html, /구독·결제 관리/);
      assert.match(html, /구매한 스토어의 쓰담 앱/);
    } else {
      assert.match(html, /무료로 계속|기존 무료 기능/);
      assert.match(html, state.loggedIn ? /id="plus-refresh"/ : /id="plus-login"/);
      assert.match(html, state.loggedIn ? /App Store·Google Play/ : /휴대폰 쓰담 앱에서 구독/);
    }
  }
});

test('active school seats retain school contact and management instructions', () => {
  const start = js.indexOf("    let d = '';", js.indexOf('async function viewSettings('));
  const end = js.indexOf("    $('#ai-detail').innerHTML = d;", start);
  const context = vm.createContext({st: {plus_enabled: true}, choice: 'plus', showPlus: true,
    plusSt: {loggedIn: true, email: 'fixture@example.invalid', sub: {active: true, plan: 'school',
      planName: '가상 학교 이용권', endsAt: '2027-11-13', cap: 6000, used: 10}, devices: [], deviceLimit: 3},
    plusOn: true, esc: String, ymd: String, plusEmail: '', plusCodeSent: false});
  const html = vm.runInContext(js.slice(start, end) + '\nd;', context);
  assert.match(html, /학교 담당 선생님/);
  assert.match(html, /5,990회 남음/);
  assert.doesNotMatch(html, /새 구독과 구매 복원/);
});
