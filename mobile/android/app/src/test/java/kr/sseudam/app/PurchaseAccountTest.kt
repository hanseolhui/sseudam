package kr.sseudam.app

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PurchaseAccountTest {
    @Test fun sameAccountCanRestore() { assertFalse(purchaseAccountMismatch("account-a", "account-a")) }
    @Test fun switchedAccountCannotClaimPurchase() { assertTrue(purchaseAccountMismatch("account-a", "account-b")) }
    @Test fun signedOutCannotClaimBoundPurchase() { assertTrue(purchaseAccountMismatch("account-a", null)) }
    @Test fun legacyReceiptRequiresServerVerification() {
        assertFalse(purchaseAccountMismatch(null, "account-a"))
        assertFalse(purchaseAccountMismatch("", "account-a"))
    }
}
