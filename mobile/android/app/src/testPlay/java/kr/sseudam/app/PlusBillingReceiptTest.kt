package kr.sseudam.app

import com.android.billingclient.api.Purchase
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** No BillingClient is initialized: any accidental local acknowledgement would fail this test. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], manifest = Config.NONE)
class PlusBillingReceiptTest {
    private fun receipt(owner: String? = "account-a", pending: Boolean = false, acknowledged: Boolean = false,
                        product: String = "plus"): Purchase {
        val json = JSONObject().put("productIds", JSONArray(listOf(product)))
            .put("purchaseToken", "synthetic-receipt").put("packageName", "kr.sseudam.app")
            .put("purchaseTime", System.currentTimeMillis() - 4L * 24 * 3600 * 1000)
            .put("purchaseState", if (pending) 4 else 0).put("acknowledged", acknowledged)
        if (owner != null) json.put("obfuscatedAccountId", owner)
        return Purchase(json.toString(), "synthetic-signature")
    }

    @Test fun failedServerVerificationNeverAcknowledgesEvenAfterRepeatedOldPurchaseFailures() = runBlocking {
        val purchase = receipt()
        assertEquals("account-a", purchase.accountIdentifiers?.obfuscatedAccountId)
        var attempts = 0
        repeat(6) { PlusBilling.handle(purchase, currentAccount = "account-a") { attempts++; false } }
        assertEquals(6, attempts)
        assertFalse(Plus.status.value.active)
    }

    @Test fun switchedOrSignedOutAccountNeverSendsReceiptToServer() = runBlocking {
        var calls = 0
        PlusBilling.handle(receipt(), currentAccount = "account-b") { calls++; true }
        PlusBilling.handle(receipt(), currentAccount = null) { calls++; true }
        assertEquals(0, calls)
    }

    @Test fun pendingAndUnrelatedProductsCannotBeGranted() = runBlocking {
        val pending = receipt(pending = true)
        assertEquals(Purchase.PurchaseState.PENDING, pending.purchaseState)
        var calls = 0
        PlusBilling.handle(pending, currentAccount = "account-a") { calls++; true }
        PlusBilling.handle(receipt(product = "unrelated"), currentAccount = "account-a") { calls++; true }
        assertEquals(0, calls)
    }

    @Test fun explicitRestoreReverifiesAnAlreadyAcknowledgedPurchase() = runBlocking {
        val purchase = receipt(acknowledged = true)
        var calls = 0
        PlusBilling.handle(purchase, currentAccount = "account-a") { calls++; true }
        assertEquals(0, calls)
        PlusBilling.handle(purchase, all = true, currentAccount = "account-a") { calls++; true }
        assertEquals(1, calls)
    }

    @Test fun legacyReceiptWithoutOwnerStillRequiresServerVerification() = runBlocking {
        var calls = 0
        PlusBilling.handle(receipt(owner = null), all = true, currentAccount = "account-a") { calls++; false }
        assertEquals(1, calls)
        assertFalse(Plus.status.value.active)
    }
}
