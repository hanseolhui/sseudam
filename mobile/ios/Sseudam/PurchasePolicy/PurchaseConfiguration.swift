import Foundation

/// The server authorizes a sale; StoreKit supplies the actual product and price.
/// This value belongs to the login session which requested it and is never persisted.
struct PlusPurchaseConfiguration {
    static let productIDs = ["kr.sseudam.plus.month", "kr.sseudam.plus.half", "kr.sseudam.plus.year"]
    let accountToken: UUID
    let productIDs: [String]
    let purchasesEnabled: Bool
    let message: String
    struct Allowance { let cap: Int; let months: Int }
    let allowances: [String: Allowance]

    init(response: [String: Any]) throws {
        guard let raw = response["accountToken"] as? String, let account = UUID(uuidString: raw) else {
            throw PurchaseError("계정 정보를 받지 못했어요. 잠시 후 다시 해 주세요.")
        }
        accountToken = account
        purchasesEnabled = response["purchasesEnabled"] as? Bool == true && response["salesPaused"] as? Bool == false
        productIDs = (response["apple"] as? [String] ?? []).filter { Self.productIDs.contains($0) }
        message = response["purchaseMessage"] as? String ?? "지금은 새 구독을 구매할 수 없어요. 기존 구매는 복원할 수 있어요."
        let plans = response["plans"] as? [String: [String: Any]] ?? [:]
        var allowed: [String: Allowance] = [:]
        for id in Self.productIDs {
            let plan = String(id.split(separator: ".").last ?? "")
            if let entry = plans[plan], let cap = entry["cap"] as? Int, cap > 0,
               let months = entry["months"] as? Int, [1, 6, 12].contains(months) {
                allowed[id] = Allowance(cap: cap, months: months)
            }
        }
        allowances = allowed
    }

    func authorize(productID: String, session: String, currentSession: String?) throws -> UUID {
        guard currentSession == session else { throw PurchaseError("로그인 계정이 바뀌었어요. 다시 확인해 주세요.") }
        guard purchasesEnabled else { throw PurchaseError(message) }
        guard productIDs.contains(productID) else { throw PurchaseError("이 상품은 현재 구매할 수 없어요. 상품을 다시 불러와 주세요.") }
        return accountToken
    }

    /// Older transactions may have no account token; the server still checks their recorded owner.
    func validateOwner(_ owner: UUID?) throws {
        if let owner = owner, owner != accountToken { throw PurchaseError("다른 계정의 결제예요. 구매할 때 사용한 쓰담 계정으로 로그인해 주세요.") }
    }

    struct PurchaseError: LocalizedError {
        let message: String
        init(_ message: String) { self.message = message }
        var errorDescription: String? { message }
    }
}
