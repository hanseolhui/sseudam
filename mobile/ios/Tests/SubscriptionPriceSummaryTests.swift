import XCTest
@testable import SseudamPurchasePolicy

final class SubscriptionPriceSummaryTests: XCTestCase {
    func testActualTotalIsDividedWithoutAssumingEqualAIQuotas() throws {
        XCTAssertEqual(try XCTUnwrap(SubscriptionPriceSummary(totalPrice: 39000, months: 6)).monthlyEquivalent, 6500)
        XCTAssertEqual(try XCTUnwrap(SubscriptionPriceSummary(totalPrice: 66000, months: 12)).monthlyEquivalent, 5500)
        XCTAssertEqual(try XCTUnwrap(SubscriptionPriceSummary(totalPrice: 480, months: 6)).monthlyEquivalent, 80)
        XCTAssertEqual(try XCTUnwrap(SubscriptionPriceSummary(totalPrice: 99000, months: 12)).monthlyEquivalent, 8250)
        let updatedHalf = try XCTUnwrap(SubscriptionPriceSummary(totalPrice: 55000, months: 6))
        XCTAssertEqual(updatedHalf.monthlyEquivalent.formatted(.currency(code: "KRW").locale(Locale(identifier: "ko_KR"))), "₩9,167")
    }
    func testInvalidPriceAndUnexpectedPeriodHaveNoSummary() {
        for amount in [Decimal(0), Decimal(-1), Decimal.nan] {
            XCTAssertNil(SubscriptionPriceSummary(totalPrice: amount, months: 6))
        }
        for months in [0, 1, 3, 24] { XCTAssertNil(SubscriptionPriceSummary(totalPrice: 50, months: months)) }
    }
    func testServerAllowancesAreOptionalAndNeverInvented() throws {
        let config = try PlusPurchaseConfiguration(response: ["accountToken": UUID().uuidString, "plans": [
            "month": ["cap": 500, "months": 1], "half": ["cap": 1500, "months": 6], "year": ["cap": 3000, "months": 12]]])
        XCTAssertEqual(config.allowances["kr.sseudam.plus.half"]?.cap, 1500)
        XCTAssertEqual(config.allowances["kr.sseudam.plus.year"]?.months, 12)
        XCTAssertEqual(config.allowances["kr.sseudam.plus.month"]?.cap, 500)
        let missing = try PlusPurchaseConfiguration(response: ["accountToken": UUID().uuidString])
        XCTAssertTrue(missing.allowances.isEmpty)
    }
}
