package kr.sseudam.app

import java.math.BigDecimal
import java.math.RoundingMode
import java.text.NumberFormat
import java.util.Currency
import java.util.Locale

internal data class RecurringPriceBreakdown(val months: Int, val monthlyText: String)

/** Derived display only: the charged total remains Play's formattedPrice. Never compare plans
 * as equivalent discounts, because their included AI quotas are different. */
internal fun recurringPriceBreakdown(amountMicros: Long, currencyCode: String, billingPeriod: String,
                                     recurring: Boolean, phaseCount: Int, expectedMonths: Int,
                                     locale: Locale = Locale.getDefault()): RecurringPriceBreakdown? {
    val actualMonths = when (billingPeriod) { "P1M" -> 1; "P6M" -> 6; "P1Y", "P12M" -> 12; else -> return null }
    if (!recurring || phaseCount != 1 || amountMicros <= 0 || actualMonths != expectedMonths) return null
    val currency = runCatching { Currency.getInstance(currencyCode) }.getOrNull() ?: return null
    if (currency.defaultFractionDigits < 0) return null
    val monthly = BigDecimal.valueOf(amountMicros).movePointLeft(6)
        .divide(BigDecimal.valueOf(actualMonths.toLong()), currency.defaultFractionDigits, RoundingMode.HALF_UP)
    val format = NumberFormat.getCurrencyInstance(locale).apply {
        this.currency = currency
        minimumFractionDigits = currency.defaultFractionDigits
        maximumFractionDigits = currency.defaultFractionDigits
    }
    return RecurringPriceBreakdown(actualMonths, format.format(monthly))
}
