package kr.sseudam.app

import android.app.Activity
import android.content.Context
import com.android.billingclient.api.AcknowledgePurchaseParams
import com.android.billingclient.api.BillingClient
import com.android.billingclient.api.BillingClientStateListener
import com.android.billingclient.api.BillingFlowParams
import com.android.billingclient.api.BillingResult
import com.android.billingclient.api.PendingPurchasesParams
import com.android.billingclient.api.ProductDetails
import com.android.billingclient.api.Purchase
import com.android.billingclient.api.QueryProductDetailsParams
import com.android.billingclient.api.QueryPurchasesParams
import com.android.billingclient.api.acknowledgePurchase
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
    /** 서버가 계속 실패할 때만: 3일 안에 확인하지 않으면 플레이가 자동 환불하므로, 이틀 지난 결제는 폰에서 확인해 둔다 */
    private const val SELF_ACK_AFTER_MS = 2L * 24 * 3600 * 1000
    private const val SELF_ACK_FAILS = 5

    private val _offers = MutableStateFlow<List<PlusOffer>>(emptyList())
    val offers: StateFlow<List<PlusOffer>> = _offers
    private val details = mutableMapOf<String, Pair<ProductDetails, String>>()   // 기본 요금제 → (상품, 혜택 토큰)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private lateinit var ctx: Context
    private lateinit var client: BillingClient

    fun init(c: Context) {
        if (::client.isInitialized) return
        ctx = c.applicationContext
        client = BillingClient.newBuilder(ctx)
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
        if (!connected()) return
        val params = QueryProductDetailsParams.newBuilder().setProductList(listOf(
            QueryProductDetailsParams.Product.newBuilder().setProductId(PRODUCT).setProductType(BillingClient.ProductType.SUBS).build())).build()
        val r = client.queryProductDetails(params)
        val pd = r.productDetailsList?.firstOrNull() ?: return
        val list = mutableListOf<PlusOffer>()
        details.clear()
        // 기본 요금제마다 하나: 추가 혜택(offerId 있음)이 아닌 기본 요금제 자체
        for (plan in basePlans) {
            val o = pd.subscriptionOfferDetails?.filter { it.basePlanId == plan }?.let { l -> l.firstOrNull { it.offerId == null } ?: l.firstOrNull() } ?: continue
            val price = o.pricingPhases.pricingPhaseList.lastOrNull()?.formattedPrice ?: continue
            details[plan] = pd to o.offerToken
            list += PlusOffer(plan, planTitle(plan), price)
        }
        _offers.value = list
    }

    private fun planTitle(plan: String) = when (plan) {
        "month" -> "쓰담 플러스 1개월"; "half" -> "쓰담 플러스 6개월"; "year" -> "쓰담 플러스 1년"; else -> "쓰담 플러스"
    }

    /** 결제 화면 열기. 문제가 있으면 안내 문구를 돌려준다 */
    suspend fun launch(activity: Activity, offer: PlusOffer, accountId: String): String? {
        if (!connected()) return "플레이 스토어에 연결하지 못했어요. 잠시 후 다시 해 주세요."
        val (pd, offerToken) = details[offer.basePlanId] ?: return "상품 정보를 받지 못했어요. 잠시 후 다시 해 주세요."
        val params = BillingFlowParams.newBuilder()
            .setProductDetailsParamsList(listOf(BillingFlowParams.ProductDetailsParams.newBuilder()
                .setProductDetails(pd).setOfferToken(offerToken).build()))
            .setObfuscatedAccountId(accountId)
            .build()
        val r = client.launchBillingFlow(activity, params)
        return when (r.responseCode) {
            BillingClient.BillingResponseCode.OK, BillingClient.BillingResponseCode.USER_CANCELED -> null
            BillingClient.BillingResponseCode.ITEM_ALREADY_OWNED -> { resendPurchases(); "이미 구독 중이에요. 구독 상태를 다시 확인했어요." }
            else -> "결제하지 못했어요: ${r.debugMessage.ifEmpty { "오류 ${r.responseCode}" }}"
        }
    }

    private fun onPurchases(r: BillingResult, purchases: List<Purchase>?) {
        when (r.responseCode) {
            BillingClient.BillingResponseCode.OK -> scope.launch { purchases?.forEach { handle(it) } }
            BillingClient.BillingResponseCode.USER_CANCELED -> {}
            else -> Plus.message.value = "결제하지 못했어요: ${r.debugMessage.ifEmpty { "오류 ${r.responseCode}" }}"
        }
    }

    /** 결제 하나를 서버로. 확인 안 된 것만 (이미 확인된 것은 서버가 받은 것) */
    private suspend fun handle(p: Purchase, all: Boolean = false) {
        when (p.purchaseState) {
            Purchase.PurchaseState.PENDING -> { Plus.message.value = "결제 승인을 기다리는 중이에요."; return }
            Purchase.PurchaseState.PURCHASED -> {}
            else -> return
        }
        if (p.isAcknowledged && !all) return
        val prefs = ctx.getSharedPreferences("sseudam_plus", Context.MODE_PRIVATE)
        val key = "iapFail_" + p.purchaseToken.hashCode()
        if (Plus.sendPurchase(p.purchaseToken)) { prefs.edit().remove(key).apply(); return }
        // 서버에 못 보냄: 확인하지 않고 둔다 (다음 실행 때 다시 보내고, 서버도 플레이 알림으로 처리)
        val fails = prefs.getInt(key, 0) + 1
        prefs.edit().putInt(key, fails).apply()
        if (fails >= SELF_ACK_FAILS && System.currentTimeMillis() - p.purchaseTime > SELF_ACK_AFTER_MS) {
            val ack = client.acknowledgePurchase(AcknowledgePurchaseParams.newBuilder().setPurchaseToken(p.purchaseToken).build())
            if (ack.responseCode == BillingClient.BillingResponseCode.OK) prefs.edit().remove(key).apply()
        }
    }

    /** 앱을 켤 때: 아직 서버에 안 간(확인 안 된) 결제를 다시 보낸다. 구매 복원(all)은 지금 구독 중인 결제를 모두 */
    suspend fun resendPurchases(all: Boolean = false) {
        if (!connected()) return
        val r = client.queryPurchasesAsync(QueryPurchasesParams.newBuilder().setProductType(BillingClient.ProductType.SUBS).build())
        if (r.billingResult.responseCode != BillingClient.BillingResponseCode.OK) return
        r.purchasesList.forEach { handle(it, all) }
    }
}
