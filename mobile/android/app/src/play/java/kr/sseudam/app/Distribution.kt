package kr.sseudam.app

import android.content.Context
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * 배포판별로 다른 부분 — 플레이 스토어판.
 * 앱 업데이트는 플레이 스토어가 맡는다: 자체 업데이트 코드·REQUEST_INSTALL_PACKAGES 권한이 없다 (플레이 정책).
 * 직접 설치(APK)판은 src/github/…/Distribution.kt.
 */
object Distribution {
    const val NAME = "play"
    @Suppress("UNUSED_PARAMETER")
    suspend fun onLaunch(ctx: Context) {}
}

/** 플레이판은 새 버전 카드가 없다 */
@Composable
fun UpdateBanner() {}

/** 연결 탭: 버전 표시만 */
@Composable
fun UpdateSettings() {
    val ctx = LocalContext.current
    Column(Modifier.fillMaxWidth().card(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text("📱 앱 버전 ${appVersion(ctx)}", fontWeight = FontWeight.Bold, color = T.ink, fontSize = 16.sp)
        Text("새 버전은 플레이 스토어에서 받아요.", fontSize = 12.sp, color = T.soft)
    }
}
