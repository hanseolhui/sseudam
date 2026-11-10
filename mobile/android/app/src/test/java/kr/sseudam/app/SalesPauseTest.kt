package kr.sseudam.app

import android.app.Activity
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** No account login, Play connection, purchase, or backend request is needed. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], manifest = Config.NONE)
class SalesPauseTest {
    private val staleOffer = PlusOffer("month", "stale offer", "₩11,000")

    @Test fun directPurchaseStopsBeforeReadingAccountOrOpeningStore() = runBlocking {
        assertFalse(Plus.SALES_ENABLED)
        Plus.message.value = ""
        Plus.buy(Activity(), staleOffer)
        assertEquals(Plus.SALES_NOTICE, Plus.message.value)
    }

    @Test fun billingEntryStopsBeforeClientInitialization() = runBlocking {
        assertEquals(Plus.SALES_NOTICE, PlusBilling.launch(Activity(), staleOffer, "fake-account"))
    }

    @Test fun pausedOfferLoadingDoesNotRequireAnInitializedBillingClient() = runBlocking {
        PlusBilling.loadOffers(listOf("month", "half", "year"))
        assertTrue(PlusBilling.offers.value.isEmpty())
    }
}
