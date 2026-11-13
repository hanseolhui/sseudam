import XCTest
@testable import SseudamPurchasePolicy

final class PurchaseConfigurationTests: XCTestCase {
    let owner = UUID(uuidString: "00000000-0000-4000-8000-000000000001")!
    let product = "kr.sseudam.plus.month"
    func response(_ overrides: [String: Any] = [:]) -> [String: Any] {
        var value: [String: Any] = ["accountToken": owner.uuidString, "purchasesEnabled": true, "salesPaused": false,
                                    "apple": PlusPurchaseConfiguration.productIDs]
        value.merge(overrides) { _, new in new }; return value
    }
    func testAllExistingProductsUseVerifiedAccountWithoutChangingPrices() throws {
        let config = try PlusPurchaseConfiguration(response: response())
        for id in PlusPurchaseConfiguration.productIDs {
            XCTAssertEqual(try config.authorize(productID: id, session: "A", currentSession: "A"), owner)
        }
    }
    func testPausedAndInconsistentFlagsBlockNewPurchasesButKeepRestoreIdentity() throws {
        for overrides in [["purchasesEnabled": false], ["salesPaused": true], ["purchasesEnabled": true, "salesPaused": true]] {
            let config = try PlusPurchaseConfiguration(response: response(overrides))
            XCTAssertThrowsError(try config.authorize(productID: product, session: "A", currentSession: "A"))
            XCTAssertNoThrow(try config.validateOwner(owner))
        }
    }
    func testMissingFlagsFailClosed() throws {
        for key in ["purchasesEnabled", "salesPaused"] {
            var value = response(); value.removeValue(forKey: key)
            let config = try PlusPurchaseConfiguration(response: value)
            XCTAssertThrowsError(try config.authorize(productID: product, session: "A", currentSession: "A"))
        }
    }
    func testAccountSwitchOrLogoutRejectsPreviouslyLoadedConfiguration() throws {
        let config = try PlusPurchaseConfiguration(response: response())
        for session in ["B", nil] as [String?] {
            XCTAssertThrowsError(try config.authorize(productID: product, session: "A", currentSession: session))
        }
    }
    func testRemovedOrUnexpectedProductsCannotBePurchased() throws {
        let config = try PlusPurchaseConfiguration(response: response(["apple": ["kr.sseudam.plus.year", "unexpected.product"]]))
        XCTAssertEqual(config.productIDs, ["kr.sseudam.plus.year"])
        for id in [product, "unexpected.product"] {
            XCTAssertThrowsError(try config.authorize(productID: id, session: "A", currentSession: "A"))
        }
    }
    func testMissingOrMalformedAccountIdentityCannotReachStoreKit() {
        for raw in ["", "invalid"] { XCTAssertThrowsError(try PlusPurchaseConfiguration(response: response(["accountToken": raw]))) }
        var value = response(); value.removeValue(forKey: "accountToken")
        XCTAssertThrowsError(try PlusPurchaseConfiguration(response: value))
    }
    func testReceiptForOtherAccountIsRejectedAndLegacyReceiptGoesToServer() throws {
        let config = try PlusPurchaseConfiguration(response: response())
        XCTAssertThrowsError(try config.validateOwner(UUID()))
        XCTAssertNoThrow(try config.validateOwner(owner))
        XCTAssertNoThrow(try config.validateOwner(nil))
    }
}
