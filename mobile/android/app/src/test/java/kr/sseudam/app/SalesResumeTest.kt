package kr.sseudam.app

import android.app.Activity
import android.content.Context
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

/** Synthetic preferences and injected server replies only; no login, Play connection or purchase. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], manifest = Config.NONE)
class SalesResumeTest {
    private val ctx: android.app.Application get() = RuntimeEnvironment.getApplication()
    private val prefs get() = ctx.getSharedPreferences("sseudam_plus", Context.MODE_PRIVATE)
    private val offer = PlusOffer("month", "synthetic offer", "synthetic price")

    @Before fun reset() {
        Plus.init(ctx)
        // Robolectric replaces Application between tests; Kotlin object state survives.
        Plus::class.java.getDeclaredField("ctx").apply { isAccessible = true }.set(null, ctx)
        prefs.edit().clear().commit()
        Plus::class.java.getDeclaredMethod("clear").apply { isAccessible = true }.invoke(Plus)
        Plus.busy.value = false
        Plus.message.value = ""
    }

    private fun login() { prefs.edit().putString("token", "synthetic-login").commit() }
    private fun config(enabled: Boolean = true, paused: Boolean = false) = JSONObject()
        .put("accountToken", "synthetic-account").put("purchasesEnabled", enabled).put("salesPaused", paused)
        .put("purchaseMessage", "synthetic sales pause")
        .put("google", JSONObject().put("product", "plus").put("basePlans", JSONArray(listOf("month", "half", "year"))))
        .put("plans", JSONObject().put("year", JSONObject().put("cap", 4321).put("months", 12)))

    @Test fun enabledSalesStillRequireLoginBeforePurchaseOrRestore() = runBlocking {
        assertTrue(Plus.SALES_ENABLED)
        Plus.buy(Activity(), offer)
        assertEquals("먼저 로그인해 주세요.", Plus.message.value)
        Plus.message.value = ""
        Plus.restore()
        assertEquals("먼저 로그인해 주세요.", Plus.message.value)
        assertFalse(Plus.sendPurchase("synthetic-receipt"))
    }

    @Test fun freshServerConfigurationControlsPurchasesAndReadsActualQuota() = runBlocking {
        login(); var requests = 0
        assertTrue(Plus.refreshPurchaseConfig { requests++; config() })
        assertTrue(Plus.canPurchaseFor("synthetic-account"))
        assertEquals(4321, Plus.planBenefits["year"]?.cap)
        assertTrue(Plus.refreshPurchaseConfig { requests++; config(paused = true) })
        assertEquals(2, requests)
        assertFalse(Plus.canPurchaseFor("synthetic-account"))
        assertEquals("synthetic-account", Plus.accountToken) // Restore still has its verified account identity.
        assertEquals("synthetic sales pause", Plus.purchaseNotice.value)
        PlusBilling.loadOffers(emptyList())
        assertTrue(PlusBilling.offers.value.isEmpty())
    }

    @Test fun absentOrConflictingSalesFieldsDoNotEnablePurchases() = runBlocking {
        login()
        val missing = config().apply { remove("purchasesEnabled") }
        assertTrue(Plus.refreshPurchaseConfig { missing })
        assertFalse(Plus.salesReady.value)
        assertTrue(Plus.refreshPurchaseConfig { config(enabled = false) })
        assertFalse(Plus.salesReady.value)
        assertTrue(Plus.refreshPurchaseConfig { config().apply { remove("salesPaused") } })
        assertFalse(Plus.salesReady.value)
    }

    @Test fun configurationFailureRevokesPreviouslyLoadedPurchaseAccess() = runBlocking {
        login()
        Plus.refreshPurchaseConfig { config() }
        assertTrue(Plus.salesReady.value)
        assertFalse(Plus.refreshPurchaseConfig { throw IllegalStateException("synthetic offline") })
        assertFalse(Plus.salesReady.value)
        assertNull(Plus.accountToken)
    }

    @Test fun withdrawnMissingAndUnknownPlansCannotReusePreviouslyAvailableProducts() = runBlocking {
        login()
        Plus.refreshPurchaseConfig { config() }
        assertTrue(Plus.salesReady.value)
        for (plans in listOf(JSONArray(), JSONArray(listOf("unknown-plan")), null)) {
            Plus.refreshPurchaseConfig { config().apply {
                getJSONObject("google").apply { if (plans == null) remove("basePlans") else put("basePlans", plans) }
            } }
            assertFalse(Plus.salesReady.value)
            assertTrue(Plus.basePlans.isEmpty())
            assertNotNull(Plus.accountToken) // Restoration remains independent of offered plans.
        }
        Plus.refreshPurchaseConfig { config().apply {
            getJSONObject("google").put("basePlans", JSONArray(listOf("half", "unknown", "half")))
        } }
        assertEquals(listOf("half"), Plus.basePlans)
    }

    @Test fun busyPurchaseAndRestoreCannotLaunchAgainOrLogout() = runBlocking {
        login(); Plus.busy.value = true; Plus.message.value = "synthetic in progress"
        Plus.buy(Activity(), offer)
        Plus.restore()
        Plus.logout()
        assertEquals("synthetic in progress", Plus.message.value)
        assertEquals("synthetic-login", prefs.getString("token", null))
    }

    @Test fun accountSwitchDuringConfigurationDiscardsTheOldAccountReply() = runBlocking {
        login()
        assertFalse(Plus.refreshPurchaseConfig {
            prefs.edit().putString("token", "different-synthetic-login").commit()
            config()
        })
        assertNull(Plus.accountToken)
        assertFalse(Plus.salesReady.value)
    }

    @Test fun blockedConfigurationCannotReachStoreEvenFromBillingEntryPoint() = runBlocking {
        login(); Plus.refreshPurchaseConfig { config(paused = true) }
        val result = PlusBilling.launch(Activity(), offer, "synthetic-account")
        assertEquals(if (PlusBilling.AVAILABLE) "synthetic sales pause" else Plus.STORE_PURCHASE_NOTICE, result)
    }

    @Test fun httpSuccessWithoutVerifiedReceiptCannotUnlockPlus() = runBlocking {
        login()
        assertFalse(Plus.sendPurchase("synthetic-receipt") { _, _ ->
            JSONObject().put("sub", JSONObject().put("active", true))
        })
        assertFalse(Plus.status.value.active)
        assertFalse(Plus.sendPurchase("synthetic-receipt") { _, _ -> JSONObject().put("ok", false) })
        assertFalse(Plus.status.value.active)
    }

    @Test fun receiptReplyAfterAccountSwitchCannotApplyEntitlement() = runBlocking {
        login()
        assertFalse(Plus.sendPurchase("synthetic-receipt") { _, _ ->
            prefs.edit().putString("token", "different-synthetic-login").commit()
            JSONObject().put("ok", true).put("sub", JSONObject().put("active", true))
        })
        assertFalse(Plus.status.value.active)
    }
}
