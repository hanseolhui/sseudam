package kr.sseudam.app

import android.app.Activity
import android.content.Context
import com.android.billingclient.api.BillingClient
import com.android.billingclient.api.BillingClientStateListener
import com.android.billingclient.api.BillingFlowParams
import com.android.billingclient.api.BillingResult
import com.android.billingclient.api.PendingPurchasesParams
import com.android.billingclient.api.ProductDetails
import com.android.billingclient.api.Purchase
import com.android.billingclient.api.QueryProductDetailsParams
import com.android.billingclient.api.QueryPurchasesParams
import com.android.billingclient.api.queryProductDetails
import com.android.billingclient.api.queryPurchasesAsync
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

/**
 * 쓰담 플러스 결제 — 플레이판 (플레이 결제 라이브러리).
 * 정기 결제 상품 "plus" 의 기본 요금제(month · half · year)를 버튼으로 보여 주고,
 * 결제가 끝나면 결제 토큰을 서버(iap-google)로 보낸다. 확인(acknowledge)은 서버가 한다.
 * 직접 설치판은 src/github/…/PlusBilling.kt (결제 없음).
 */
object PlusBilling {
    const val AVAILABLE = true
    private const val PRODUCT = "plus"
    private val _offers = MutableStateFlow<List<PlusOffer>>(emptyList())
    val offers: StateFlow<List<PlusOffer>> = _offers
    private val details = mutableMapOf<String, Pair<ProductDetails, String>>()   // 기본 요금제 → (상품, 혜택 토큰)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private lateinit var client: BillingClient

    fun init(c: Context) {
        if (::client.isInitialized) return
        client = BillingClient.newBuilder(c.applicationContext)
            .setListener { r, purchases -> onPurchases(r, purchases) }
            .enablePendingPurchases(PendingPurchasesParams.newBuilder().enableOneTimeProducts().build())
            .enableAutoServiceReconnection()
            .build()
    }

    private suspend fun connected(): Boolean {
        if (client.isReady) return true
        return suspendCancellableCoroutine { cont ->
            client.startConnection(object : BillingClientStateListener {
                override fun onBillingSetupFinished(r: BillingResult) {
                    if (cont.isActive) cont.resume(r.responseCode == BillingClient.BillingResponseCode.OK)
                }
                override fun onBillingServiceDisconnected() { if (cont.isActive) cont.resume(false) }
            })
        }
    }

    /** 플레이에서 상품·가격 받기 (가격은 기기 나라 통화로) */
    suspend fun loadOffers(basePlans: List<String>) {
        _offers.value = emptyList(); details.clear()
        if (!Plus.SALES_ENABLED || !Plus.salesReady.value || basePlans.isEmpty()) return
        if (!connected()) { Plus.message.value = "플레이 스토어에 연결하지 못했어요. 잠시 후 다시 해 주세요."; return }
        val params = QueryProductDetailsParams.newBuilder().setProductList(listOf(
            QueryProductDetailsParams.Product.newBuilder().setProductId(PRODUCT).setProductType(BillingClient.ProductType.SUBS).build())).build()
        val r = client.queryProductDetails(params)
        if (r.billingResult.responseCode != BillingClient.BillingResponseCode.OK) {
            Plus.message.value = "구독 상품을 확인하지 못했어요. 잠시 후 다시 해 주세요."; return
        }
        val pd = r.productDetailsList?.firstOrNull() ?: return
        val list = mutableListOf<PlusOffer>()
        // 기본 요금제마다 하나: 추가 혜택(offerId 있음)이 아닌 기본 요금제 자체
        for (plan in basePlans) {
            val o = pd.subscriptionOfferDetails?.firstOrNull { it.basePlanId == plan && it.offerId == null } ?: continue
            val phases = o.pricingPhases.pricingPhaseList
            val phase = phases.lastOrNull() ?: continue
            val price = phase.formattedPrice
            val benefit = Plus.planBenefits[plan]
            val breakdown = benefit?.let { recurringPriceBreakdown(
                phase.priceAmountMicros, phase.priceCurrencyCode, phase.billingPeriod,
                phase.recurrenceMode == ProductDetails.RecurrenceMode.INFINITE_RECURRING,
                phases.size, it.months) }
            details[plan] = pd to o.offerToken
            list += PlusOffer(plan, planTitle(plan), price, breakdown?.months, breakdown?.monthlyText,
                if (breakdown != null) benefit.cap else null)
        }
        _offers.value = list
    }

    private fun planTitle(plan: String) = when (plan) {
        "month" -> "쓰담 플러스 1개월"; "half" -> "쓰담 플러스 6개월"; "year" -> "쓰담 플러스 1년"; else -> "쓰담 플러스"
    }

    /** 결제 화면 열기. 문제가 있으면 안내 문구를 돌려준다 */
    suspend fun launch(activity: Activity, offer: PlusOffer, accountId: String): String? {
        if (!Plus.SALES_ENABLED) return Plus.SALES_NOTICE
        if (!Plus.canPurchaseFor(accountId)) return Plus.purchaseNotice.value.ifEmpty { "로그인 계정과 구독 판매 상태를 다시 확인해 주세요." }
        if (!connected()) return "플레이 스토어에 연결하지 못했어요. 잠시 후 다시 해 주세요."
        // 이미 소유한 상품은 결제창을 다시 열지 않고 현재 쓰담 계정과 대조한다.
        val owned = client.queryPurchasesAsync(QueryPurchasesParams.newBuilder()
            .setProductType(BillingClient.ProductType.SUBS).build())
        if (owned.billingResult.responseCode != BillingClient.BillingResponseCode.OK)
            return "기존 구매를 확인하지 못했어요. 잠시 후 다시 시도해 주세요."
        val existing = owned.purchasesList.filter { PRODUCT in it.products }
        if (existing.isNotEmpty()) {
            existing.forEach { handle(it, all = true) }
            return null
        }
        if (!Plus.canPurchaseFor(accountId)) return "로그인 계정이나 구독 판매 상태가 바뀌었어요. 다시 눌러 주세요."
        val (pd, offerToken) = details[offer.basePlanId] ?: return "상품 정보를 받지 못했어요. 잠시 후 다시 해 주세요."
        val params = BillingFlowParams.newBuilder()
            .setProductDetailsParamsList(listOf(BillingFlowParams.ProductDetailsParams.newBuilder()
                .setProductDetails(pd).setOfferToken(offerToken).build()))
            .setObfuscatedAccountId(accountId)
            .build()
        val r = client.launchBillingFlow(activity, params)
        return when (r.responseCode) {
            BillingClient.BillingResponseCode.OK, BillingClient.BillingResponseCode.USER_CANCELED -> null
            BillingClient.BillingResponseCode.ITEM_ALREADY_OWNED -> { resendPurchases(all = true); null }
            else -> "결제하지 못했어요: ${r.debugMessage.ifEmpty { "오류 ${r.responseCode}" }}"
        }
    }

    private fun onPurchases(r: BillingResult, purchases: List<Purchase>?) {
        when (r.responseCode) {
            BillingClient.BillingResponseCode.OK -> scope.launch { purchases?.forEach { handle(it) } }
            BillingClient.BillingResponseCode.USER_CANCELED -> {}
            BillingClient.BillingResponseCode.ITEM_ALREADY_OWNED -> scope.launch { resendPurchases(all = true) }
            else -> Plus.message.value = "결제하지 못했어요: ${r.debugMessage.ifEmpty { "오류 ${r.responseCode}" }}"
        }
    }

    /** 결제 하나를 서버로. 확인 안 된 것만 (이미 확인된 것은 서버가 받은 것) */
    internal suspend fun handle(p: Purchase, all: Boolean = false, currentAccount: String? = Plus.accountToken,
                                verifyPurchase: suspend (String) -> Boolean = { Plus.sendPurchase(it) }) {
        if (PRODUCT !in p.products) return
        val owner = p.accountIdentifiers?.obfuscatedAccountId
        if (purchaseAccountMismatch(owner, currentAccount)) {
            Plus.message.value = "이 Google Play 구독은 다른 쓰담 계정에 연결되어 있어요. 구매할 때 사용한 쓰담 계정으로 로그인해 주세요. 현재 계정으로 새로 구매하려면 기존 구독이 없는 Play 계정을 사용해 주세요. 중복 결제는 진행하지 않았어요."
            return
        }
        when (p.purchaseState) {
            Purchase.PurchaseState.PENDING -> { Plus.message.value = "결제 승인을 기다리는 중이에요."; return }
            Purchase.PurchaseState.PURCHASED -> {}
            else -> return
        }
        if (p.isAcknowledged && !all) return
        // Only the server validates and acknowledges a purchase. Failure remains retryable;
        // never acknowledge locally to suppress Play's refund before entitlement is verified.
        verifyPurchase(p.purchaseToken)
    }

    /** 앱을 켤 때: 아직 서버에 안 간(확인 안 된) 결제를 다시 보낸다. 구매 복원(all)은 지금 구독 중인 결제를 모두 */
    suspend fun resendPurchases(all: Boolean = false) {
        if (Plus.accountToken == null) { Plus.message.value = "계정 정보를 받지 못했어요. 로그인 상태를 다시 확인해 주세요."; return }
        if (!connected()) { Plus.message.value = "Play 구매 내역에 연결하지 못했어요. 다시 시도해 주세요."; return }
        val r = client.queryPurchasesAsync(QueryPurchasesParams.newBuilder().setProductType(BillingClient.ProductType.SUBS).build())
        if (r.billingResult.responseCode != BillingClient.BillingResponseCode.OK) { Plus.message.value = "Play 구매 내역을 확인하지 못했어요. 다시 시도해 주세요."; return }
        r.purchasesList.forEach { handle(it, all) }
    }
}
