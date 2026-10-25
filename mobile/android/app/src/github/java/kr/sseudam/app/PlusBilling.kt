package kr.sseudam.app

import android.app.Activity
import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * 쓰담 플러스 결제 — github(직접 설치 APK)판: 플레이 결제가 없다.
 * 로그인·구독 상태만 보이고, 구독은 플레이 스토어판이나 웹(apps.seoriarts.com/sseudam/plus)에서 한다.
 * 플레이판은 src/play/…/PlusBilling.kt.
 */
object PlusBilling {
    const val AVAILABLE = false
    val offers: StateFlow<List<PlusOffer>> = MutableStateFlow(emptyList())
    @Suppress("UNUSED_PARAMETER") fun init(ctx: Context) {}
    @Suppress("UNUSED_PARAMETER") suspend fun loadOffers(basePlans: List<String>) {}
    @Suppress("UNUSED_PARAMETER") suspend fun launch(activity: Activity, offer: PlusOffer, accountId: String): String? =
        "구독은 플레이 스토어판 쓰담이나 apps.seoriarts.com/sseudam/plus에서 할 수 있어요."
    @Suppress("UNUSED_PARAMETER") suspend fun resendPurchases(all: Boolean = false) {}
}
