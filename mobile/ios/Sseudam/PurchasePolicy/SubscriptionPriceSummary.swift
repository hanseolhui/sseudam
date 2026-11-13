import Foundation

/// Divides the actual recurring StoreKit total, without implying equal AI allowances between plans.
struct SubscriptionPriceSummary {
    let monthlyEquivalent: Decimal
    init?(totalPrice: Decimal, months: Int) {
        guard [6, 12].contains(months), totalPrice > 0, !totalPrice.isNaN else { return nil }
        monthlyEquivalent = totalPrice / Decimal(months)
    }
}
