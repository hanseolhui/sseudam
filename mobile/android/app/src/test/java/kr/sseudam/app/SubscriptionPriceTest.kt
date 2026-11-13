package kr.sseudam.app

import java.util.Locale
import org.junit.Assert.*
import org.junit.Test

class SubscriptionPriceTest {
    @Test fun sixMonthsUsesActualTotalAndCurrencyWithoutFixedPrice() {
        val result = recurringPriceBreakdown(42_600_000_000, "KRW", "P6M", true, 1, 6, Locale.KOREA)
        assertEquals(6, result?.months)
        assertTrue(result!!.monthlyText.contains("7,100"))
    }
    @Test fun yearlyTotalIsDividedIntoTwelveNotAssumedMonthlyBilling() {
        val result = recurringPriceBreakdown(59_990_000, "USD", "P1Y", true, 1, 12, Locale.US)
        assertEquals(12, result?.months)
        assertEquals("$5.00", result?.monthlyText)
    }
    @Test fun koreanWonMonthlyEquivalentUsesWholeWonRounding() {
        val result = recurringPriceBreakdown(55_000_000_000, "KRW", "P6M", true, 1, 6, Locale.KOREA)
        assertTrue(result!!.monthlyText.contains("9,167"))
        assertFalse(result.monthlyText.contains(".67"))
    }
    @Test fun twelveMonthIsoPeriodIsAlsoRecognized() {
        assertEquals(12, recurringPriceBreakdown(120_000_000, "EUR", "P12M", true, 1, 12)?.months)
    }
    @Test fun storeAndServerPeriodMismatchDoesNotShowDerivedPrice() {
        assertNull(recurringPriceBreakdown(39_000_000, "USD", "P6M", true, 1, 12))
    }
    @Test fun promotionalPhasesOrPrepaidPlansAreNotPresentedAsSimpleRecurringTotals() {
        assertNull(recurringPriceBreakdown(39_000_000, "USD", "P6M", true, 2, 6))
        assertNull(recurringPriceBreakdown(39_000_000, "USD", "P6M", false, 1, 6))
    }
    @Test fun invalidPricesOrCurrencyHaveNoDerivedLabel() {
        assertNull(recurringPriceBreakdown(0, "USD", "P6M", true, 1, 6))
        assertNull(recurringPriceBreakdown(-1, "USD", "P6M", true, 1, 6))
        assertNull(recurringPriceBreakdown(39_000_000, "invalid", "P6M", true, 1, 6))
        assertNull(recurringPriceBreakdown(39_000_000, "USD", "P4W", true, 1, 1))
    }
    @Test fun largeMicrosDoNotOverflowWhenFormatting() {
        assertNotNull(recurringPriceBreakdown(Long.MAX_VALUE, "USD", "P1Y", true, 1, 12, Locale.US))
    }
}
