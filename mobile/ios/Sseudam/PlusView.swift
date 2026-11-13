import AuthenticationServices
import Security
import StoreKit
import SwiftUI

/// 쓰담 플러스 계정 (애플 · 이메일 로그인) 과 App Store 구독.
/// 같은 계정으로 컴퓨터 쓰담에 로그인하면 AI 정리 · 초안을 쓴다. 결제 확인은 서리아트 서버가 애플 서명으로 한다.
@MainActor
final class Plus: ObservableObject {
    // A fresh server configuration must also allow each new purchase. Restore stays available.
    static let salesEnabled = true
    static let salesNotice = "App Store에서 쓰담 플러스 구독하기"
    static let shared = Plus()
    static let api = URL(string: "https://apps.seoriarts.com/api/sseudam-plus")!
    static let productIDs = PlusPurchaseConfiguration.productIDs

    struct Status { var active = false; var planName = ""; var endsAt: Date?; var daysToEnd = 0; var autoRenew = false }

    @Published private(set) var email: String? = Plus.preview ? "teacher@example.com" : UserDefaults.standard.string(forKey: "plusEmail")
    @Published private(set) var status = Status()
    @Published private(set) var products: [Product] = []
    @Published private(set) var allowances: [String: PlusPurchaseConfiguration.Allowance] = [:]
    @Published var busy = false
    @Published var message = ""
    @Published private(set) var loadingProducts = false
    @Published private(set) var productMessage = ""
    private var productLoadID = UUID()
    private var listener: Task<Void, Never>?

    var loggedIn: Bool { token != nil || Plus.preview }
    /// 심사용 스크린샷: 디버그 빌드에서 -plusPreview 로 켜면 로그인된 화면(구독 상품)을 보여 준다
    #if DEBUG
    static let preview = ProcessInfo.processInfo.arguments.contains("-plusPreview")
    #else
    static let preview = false
    #endif

    private var installId: String {
        if let v = UserDefaults.standard.string(forKey: "plusInstall") { return v }
        let v = UUID().uuidString; UserDefaults.standard.set(v, forKey: "plusInstall"); return v
    }

    // 로그인 토큰은 키체인에
    private var token: String? {
        get {
            let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "kr.sseudam.plus",
                                    kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
            var out: AnyObject?
            guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data else { return nil }
            return String(data: d, encoding: .utf8)
        }
        set {
            products = []; allowances = [:]; productLoadID = UUID(); loadingProducts = false
            let base: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "kr.sseudam.plus"]
            SecItemDelete(base as CFDictionary)
            if let v = newValue, let d = v.data(using: .utf8) {
                var add = base; add[kSecValueData as String] = d
                add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
                SecItemAdd(add as CFDictionary, nil)
            }
            objectWillChange.send()
        }
    }

    private func post(_ body: [String: Any]) async throws -> [String: Any] {
        var req = URLRequest(url: Plus.api)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        req.timeoutInterval = 30
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let j = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            throw PlusPurchaseConfiguration.PurchaseError("서버 응답을 확인하지 못했어요. 잠시 후 다시 시도해 주세요.")
        }
        if (resp as? HTTPURLResponse)?.statusCode != 200 {
            if j["loggedOut"] as? Bool == true, let requestToken = body["token"] as? String, requestToken == token { token = nil }
            throw NSError(domain: "plus", code: 1, userInfo: [NSLocalizedDescriptionKey: j["error"] as? String ?? "서버에 연결하지 못했어요."])
        }
        return j
    }

    private func apply(_ j: [String: Any]) {
        if let e = j["email"] as? String { email = e; UserDefaults.standard.set(e, forKey: "plusEmail") }
        if let t = j["token"] as? String { token = t }
        if let s = j["sub"] as? [String: Any] {
            var st = Status()
            st.active = s["active"] as? Bool ?? false
            st.planName = s["planName"] as? String ?? ""
            st.daysToEnd = s["daysToEnd"] as? Int ?? 0
            st.autoRenew = s["autoRenew"] as? Bool ?? false
            if let e = s["endsAt"] as? String { st.endsAt = ISO8601DateFormatter.plus.date(from: e) }
            status = st
        }
    }

    private var device: String { String(UIDevice.current.name.prefix(40)) }

    // MARK: 로그인
    func signInApple(_ result: Result<ASAuthorization, Error>) async {
        guard case .success(let auth) = result, let c = auth.credential as? ASAuthorizationAppleIDCredential,
              let tok = c.identityToken, let id = String(data: tok, encoding: .utf8) else {
            if case .failure(let e) = result, (e as? ASAuthorizationError)?.code != .canceled { message = "애플 로그인을 하지 못했어요." }
            return
        }
        await run { try await self.post(["action": "social", "provider": "apple", "idToken": id, "installId": self.installId,
                                         "phone": true, "deviceName": self.device]) }
        if loggedIn { UserDefaults.standard.set("apple", forKey: "plusProvider") }
    }

    var appleLogin: Bool { UserDefaults.standard.string(forKey: "plusProvider") == "apple" }

    /// 계정 삭제 — 로그인 · 기기 · 선생님 정보를 서버에서 지운다. 애플로 로그인했다면 애플 로그인 연결도 끊는다(authorizationCode).
    func deleteAccount(appleCode: String? = nil) async -> Bool {
        guard !busy, let t = token else { return false }
        busy = true; defer { busy = false }
        do {
            var body: [String: Any] = ["action": "delete-account", "token": t]
            if let c = appleCode { body["appleCode"] = c }
            _ = try await post(body)
            token = nil; email = nil; status = Status()
            UserDefaults.standard.removeObject(forKey: "plusEmail"); UserDefaults.standard.removeObject(forKey: "plusProvider")
            message = "계정을 지웠어요."
            return true
        } catch { message = error.localizedDescription; return false }
    }

    func sendCode(_ mail: String) async -> Bool {
        guard !busy else { return false }
        busy = true; defer { busy = false }
        do { _ = try await post(["action": "start", "email": mail.lowercased(), "installId": installId]); message = "메일로 온 인증번호를 넣어 주세요."; return true }
        catch { message = error.localizedDescription; return false }
    }

    func verify(_ mail: String, code: String) async {
        await run { try await self.post(["action": "verify", "email": mail.lowercased(), "code": code, "installId": self.installId,
                                         "phone": true, "deviceName": self.device]) }
    }

    func refresh() async {
        guard let t = token else { return }
        if let j = try? await post(["action": "status", "token": t]), token == t { apply(j) }
    }

    func logout() async {
        guard !busy else { return }
        let previous = token
        token = nil; email = nil; status = Status(); productMessage = ""; message = ""
        UserDefaults.standard.removeObject(forKey: "plusEmail"); UserDefaults.standard.removeObject(forKey: "plusProvider")
        if let t = previous { _ = try? await post(["action": "logout", "token": t]) }
    }

    private func run(_ f: @escaping () async throws -> [String: Any]) async {
        guard !busy else { return }
        busy = true; defer { busy = false }
        do { apply(try await f()); message = ""; await loadProducts() } catch { message = error.localizedDescription }
    }

    // MARK: 구독 (StoreKit 2)
    private func configuration(for session: String) async throws -> PlusPurchaseConfiguration {
        let j = try await post(["action": "iap-config", "token": session])
        guard token == session else { throw PlusPurchaseConfiguration.PurchaseError("로그인 계정이 바뀌었어요. 다시 확인해 주세요.") }
        return try PlusPurchaseConfiguration(response: j)
    }

    func loadProducts() async {
        guard Plus.salesEnabled else { products = []; return }
        guard let session = token else { products = []; return }
        let request = UUID(); productLoadID = request
        loadingProducts = true; productMessage = ""
        defer { if productLoadID == request { loadingProducts = false } }
        do {
            let config = try await configuration(for: session)
            guard productLoadID == request else { return }
            guard config.purchasesEnabled else { products = []; productMessage = config.message; return }
            let loaded = try await Product.products(for: config.productIDs)
            guard token == session, productLoadID == request else { return }
            products = loaded.filter { config.productIDs.contains($0.id) }.sorted { $0.price < $1.price }
            allowances = config.allowances
            if products.isEmpty { productMessage = "App Store 상품을 불러오지 못했어요. 잠시 후 다시 시도해 주세요." }
        } catch {
            guard token == session, productLoadID == request else { return }
            products = []; productMessage = "상품을 불러오지 못했어요: \(error.localizedDescription)"
        }
    }

    func buy(_ p: Product) async {
        guard Plus.salesEnabled else { message = Plus.salesNotice; return }
        guard !busy else { return }
        guard let session = token else { message = "먼저 로그인해 주세요."; return }
        busy = true; message = ""; defer { busy = false }
        do {
            // Never reuse a previous account's token or a stale sale-enabled response.
            let config = try await configuration(for: session)
            let acc = try config.authorize(productID: p.id, session: session, currentSession: token)
            switch try await p.purchase(options: [.appAccountToken(acc)]) {
            case .success(let v):
                guard token == session else { message = "로그인 계정이 바뀌었어요. 구매한 계정으로 로그인해 구매를 복원해 주세요."; return }
                _ = await handle(v)
            case .pending: message = "결제 승인을 기다리는 중이에요."
            case .userCancelled: break
            @unknown default: message = "결제 상태를 확인하지 못했어요. 구매 복원으로 다시 확인해 주세요."
            }
        } catch { if token == session { message = "결제하지 못했어요: \(error.localizedDescription)" } }
    }

    /// Finish only after the server has verified and saved this transaction for the same account.
    @discardableResult
    private func handle(_ v: VerificationResult<StoreKit.Transaction>) async -> Bool {
        guard let session = token else { return false }
        guard case .verified(let transaction) = v else { message = "App Store 결제를 확인하지 못했어요. 구매 복원으로 다시 시도해 주세요."; return false }
        guard Plus.productIDs.contains(transaction.productID) else { return false }
        do {
            let config = try await configuration(for: session)
            try config.validateOwner(transaction.appAccountToken)
            let j = try await post(["action": "iap-apple", "token": session, "signedTransaction": v.jwsRepresentation])
            guard token == session else { return false }
            guard j["ok"] as? Bool == true else { throw PlusPurchaseConfiguration.PurchaseError("결제 확인을 완료하지 못했어요. 구매 복원으로 다시 시도해 주세요.") }
            apply(j)
            await transaction.finish()
            guard token == session else { return false }
            message = status.active ? "쓰담 플러스가 확인됐어요. 컴퓨터 쓰담에서 같은 계정으로 로그인하세요." : "결제 내역을 확인했어요. 현재 이용권 상태를 확인해 주세요."
            return true
        } catch { if token == session { message = error.localizedDescription }; return false }
    }

    func restore() async {
        guard !busy else { return }
        guard let session = token else { message = "먼저 로그인해 주세요."; return }
        busy = true; message = ""; defer { busy = false }
        do { try await AppStore.sync() }
        catch { if token == session { message = "구매를 복원하지 못했어요: \(error.localizedDescription)" }; return }
        var found = false
        for await v in StoreKit.Transaction.currentEntitlements {
            guard token == session else { return }
            found = true
            if !(await handle(v)) { return } // Preserve verification failures instead of reporting success.
        }
        guard token == session else { return }
        await refresh()
        if !found, token == session { message = "이 Apple ID에서 복원할 App Store 구독을 찾지 못했어요. 결제한 Apple ID인지 확인해 주세요." }
    }

    /// 앱이 켜져 있지 않을 때 끝난 결제 · 갱신도 받는다
    func listen() {
        guard listener == nil else { return }
        listener = Task {
            for await v in StoreKit.Transaction.updates { await self.handle(v) }
        }
        Task { for await v in StoreKit.Transaction.unfinished { await self.handle(v) } }
    }
}

extension ISO8601DateFormatter {
    static let plus: ISO8601DateFormatter = { let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]; return f }()
}

/// 연결 탭의 쓰담 플러스 카드
struct PlusCard: View {
    @ObservedObject var plus = Plus.shared
    @Environment(\.colorScheme) private var scheme
    @State private var mail = ""
    @State private var code = ""
    @State private var codeSent = false
    @State private var showEmail = false
    @State private var confirmDelete = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("쓰담 플러스", systemImage: "sparkles").font(Theme.font(17, .bold)).foregroundStyle(Theme.lavender)
            Text(Plus.salesNotice).font(Theme.font(14, .semibold))
            Text("녹음과 기록은 무료로 이용할 수 있어요. 쓰담 플러스는 컴퓨터에서 AI 정리와 초안을 만들 때 쓰며, 결제한 계정으로 컴퓨터 쓰담에 로그인하면 함께 적용돼요.")
                .font(Theme.font(12)).foregroundStyle(Theme.soft).fixedSize(horizontal: false, vertical: true)
            if plus.loggedIn { account } else { login }
            if !plus.message.isEmpty {
                Text(plus.message).font(Theme.font(12, .semibold)).foregroundStyle(Theme.coral).fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
        .task { await plus.refresh(); await plus.loadProducts() }
    }

    var login: some View {
        VStack(alignment: .leading, spacing: 10) {
            SignInWithAppleButton(.signIn) { r in r.requestedScopes = [.email] } onCompletion: { r in Task { await plus.signInApple(r) } }
                .signInWithAppleButtonStyle(scheme == .dark ? .white : .black)
                .frame(height: 46).clipShape(Capsule()).disabled(plus.busy)
            Button(showEmail ? "이메일 로그인 닫기" : "이메일 인증번호로 로그인") { withAnimation { showEmail.toggle() } }.font(Theme.font(13, .semibold))
            if showEmail {
                TextField("이메일 주소", text: $mail).keyboardType(.emailAddress).textInputAutocapitalization(.never).autocorrectionDisabled()
                    .padding(10).background(Theme.bg, in: RoundedRectangle(cornerRadius: 12))
                if codeSent {
                    TextField("인증번호", text: $code).keyboardType(.numberPad)
                        .padding(10).background(Theme.bg, in: RoundedRectangle(cornerRadius: 12))
                    Button("로그인") { Task { await plus.verify(mail, code: code) } }.buttonStyle(.borderedProminent).disabled(code.isEmpty || plus.busy)
                } else {
                    Button("인증번호 받기") { Task { codeSent = await plus.sendCode(mail) } }.buttonStyle(.bordered).disabled(!mail.contains("@") || plus.busy)
                }
            }
        }
    }

    private func subscriptionMonths(_ p: Product) -> Int? {
        guard p.type == .autoRenewable, let period = p.subscription?.subscriptionPeriod else { return nil }
        switch period.unit {
        case .month: return period.value
        case .year: return period.value * 12
        default: return nil
        }
    }

    private func allowance(for p: Product) -> PlusPurchaseConfiguration.Allowance? {
        guard let value = plus.allowances[p.id], value.months == subscriptionMonths(p) else { return nil }
        return value
    }

    private func billingPeriod(for p: Product) -> String {
        guard let months = subscriptionMonths(p) else { return "구독 기간 총액 · 자동 갱신" }
        return "\(months)개월 총액 · \(months)개월마다 결제·자동 갱신"
    }

    var account: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(plus.email ?? "").font(Theme.font(14, .semibold))
                Spacer()
                Button("로그아웃") { Task { await plus.logout() } }.font(Theme.font(13)).disabled(plus.busy)
            }
            if plus.status.active {
                Pill(text: "\(plus.status.planName) · \(plus.status.daysToEnd)일 남음", icon: "checkmark.seal.fill", color: Theme.mint)
            } else {
                Text("지금은 구독 중이 아니에요.").font(Theme.font(13)).foregroundStyle(Theme.soft)
            }
            if plus.loadingProducts { ProgressView("구독 상품을 불러오는 중이에요.").font(Theme.font(12)) }
            if !plus.productMessage.isEmpty {
                Text(plus.productMessage).font(Theme.font(12)).foregroundStyle(Theme.soft)
                Button("상품 다시 불러오기") { Task { await plus.loadProducts() } }.disabled(plus.busy || plus.loadingProducts)
            }
            ForEach(Plus.salesEnabled ? plus.products : [], id: \.id) { p in
                Button { Task { await plus.buy(p) } } label: {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(p.displayName).font(Theme.font(15, .bold))
                            Text(p.description).font(Theme.font(11)).foregroundStyle(.white.opacity(0.85)).lineLimit(2)
                            if let limits = allowance(for: p) {
                                Text("기간 전체 AI \(limits.cap)회").font(Theme.font(11, .semibold))
                                if let summary = SubscriptionPriceSummary(totalPrice: p.price, months: limits.months) {
                                    Text("월 환산 약 \(summary.monthlyEquivalent.formatted(p.priceFormatStyle)) · 월별 청구 아님")
                                        .font(Theme.font(11, .semibold)).fixedSize(horizontal: false, vertical: true)
                                }
                            }
                            Text(billingPeriod(for: p)).font(Theme.font(10)).foregroundStyle(.white.opacity(0.85))
                        }
                        Spacer()
                        Text(p.displayPrice).font(Theme.font(15, .bold)).fixedSize()
                    }
                    .padding(.horizontal, 16).padding(.vertical, 11)
                    .background(Theme.brand, in: RoundedRectangle(cornerRadius: 16, style: .continuous)).foregroundStyle(.white)
                }
                .buttonStyle(Squishy()).disabled(plus.busy)
            }
            HStack(spacing: 16) {
                Button("구독 관리") {
                    Task { if let s = UIApplication.shared.connectedScenes.first as? UIWindowScene { try? await AppStore.showManageSubscriptions(in: s) } }
                }
                Button("구매 복원") { Task { await plus.restore() } }
            }.font(Theme.font(13, .semibold)).disabled(plus.busy)
            Text("Apple ID로 결제되고, 기간이 끝나기 24시간 전까지 끄지 않으면 같은 기간으로 자동 갱신돼요. 설정 → Apple ID → 구독에서 언제든 끌 수 있어요.")
                .font(Theme.font(11)).foregroundStyle(Theme.soft).fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 14) {
                Link("이용약관", destination: URL(string: "https://www.apple.com/legal/internet-services/itunes/dev/stdeula/")!)
                Link("개인정보 처리방침", destination: URL(string: "https://apps.seoriarts.com/sseudam-privacy")!)
                Spacer()
                Button("계정 삭제", role: .destructive) { confirmDelete = true }.disabled(plus.busy)
            }.font(Theme.font(11, .semibold))
        }
        .confirmationDialog("쓰담 플러스 계정을 지울까요?", isPresented: $confirmDelete, titleVisibility: .visible) {
            if plus.appleLogin {
                Button("애플 로그인 확인하고 지우기", role: .destructive) { AppleReauth.shared.run { code in Task { _ = await plus.deleteAccount(appleCode: code) } } }
            } else {
                Button("계정 지우기", role: .destructive) { Task { _ = await plus.deleteAccount() } }
            }
            Button("취소", role: .cancel) {}
        } message: {
            Text("로그인 정보와 등록된 기기, 선생님 정보가 지워지고 되돌릴 수 없어요. 휴대폰과 컴퓨터에 있는 학생 기록은 그대로예요. App Store 구독은 계정을 지워도 자동으로 해지되지 않으니, 먼저 ‘구독 관리’에서 해지해 주세요.")
        }
    }
}

/// 계정 삭제 전 애플 로그인을 한 번 더 받아 authorizationCode를 얻는다 (서버가 애플 로그인 연결을 끊는 데 씀)
final class AppleReauth: NSObject, ASAuthorizationControllerDelegate, ASAuthorizationControllerPresentationContextProviding {
    static let shared = AppleReauth()
    private var done: ((String?) -> Void)?

    func run(_ f: @escaping (String?) -> Void) {
        done = f
        let req = ASAuthorizationAppleIDProvider().createRequest()
        let c = ASAuthorizationController(authorizationRequests: [req])
        c.delegate = self; c.presentationContextProvider = self
        c.performRequests()
    }
    func authorizationController(controller: ASAuthorizationController, didCompleteWithAuthorization a: ASAuthorization) {
        let code = (a.credential as? ASAuthorizationAppleIDCredential)?.authorizationCode.flatMap { String(data: $0, encoding: .utf8) }
        done?(code); done = nil
    }
    func authorizationController(controller: ASAuthorizationController, didCompleteWithError error: Error) {
        done = nil   // 취소하면 지우지 않음
    }
    func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        UIApplication.shared.connectedScenes.compactMap { ($0 as? UIWindowScene)?.keyWindow }.first ?? ASPresentationAnchor()
    }
}
