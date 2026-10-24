package kr.sseudam.app

import android.content.Context
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.launch

/**
 * 배포판별로 다른 부분 — github(직접 설치 APK)판.
 * GitHub 릴리스에서 새 APK를 받아 설치 화면을 띄운다 (REQUEST_INSTALL_PACKAGES 는 이 판의 매니페스트에만 있음).
 * 플레이판은 src/play/…/Distribution.kt (업데이트는 플레이 스토어가 맡음).
 */
object Distribution {
    const val NAME = "github"
    suspend fun onLaunch(ctx: Context) { Updater.check(ctx) }
}

/** 담기 화면 위쪽: 새 버전 카드 */
@Composable
fun UpdateBanner() {
    val update by Updater.available.collectAsStateWithLifecycle()
    update?.let { UpdateCard(it) }
}

@Composable
private fun UpdateCard(r: Updater.Release) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val status by Updater.status.collectAsStateWithLifecycle()
    val busy by Updater.busy.collectAsStateWithLifecycle()
    Column(Modifier.fillMaxWidth().card(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("새 버전 ${r.version}이 나왔어요 ✨", fontSize = 15.sp, fontWeight = FontWeight.Bold, color = T.ink, modifier = Modifier.weight(1f))
            if (busy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
            else ChipButton("업데이트", T.blue, filled = true) { scope.launch { Updater.downloadAndInstall(ctx, r) } }
        }
        Text(status.ifEmpty { "누르면 새 버전을 받아 설치 화면을 열어요. 처음 한 번은 ‘이 출처의 앱 설치 허용’을 켜 주세요. 기록은 그대로 남아요." },
            fontSize = 12.sp, color = T.soft)
    }
}

/** 연결 탭: 자동 업데이트 확인 */
@Composable
fun UpdateSettings() {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var autoUpdate by remember { mutableStateOf(Updater.autoCheck(ctx)) }
    var updateMsg by remember { mutableStateOf("") }
    val update by Updater.available.collectAsStateWithLifecycle()
    Column(Modifier.fillMaxWidth().card(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("✨ 자동으로 새 버전 확인", fontWeight = FontWeight.Bold, color = T.ink, fontSize = 16.sp)
                Text("지금 버전 ${appVersion(ctx)} · 하루에 한 번 확인해요", fontSize = 12.sp, color = T.soft)
            }
            Switch(autoUpdate, { autoUpdate = it; Updater.setAutoCheck(ctx, it) },
                colors = SwitchDefaults.colors(checkedTrackColor = T.blue))
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ChipButton("지금 확인") {
                updateMsg = "확인 중…"
                scope.launch {
                    val r = Updater.check(ctx, force = true)
                    updateMsg = if (Updater.installedFromPlay(ctx)) "플레이 스토어에서 업데이트돼요"
                    else if (r != null) "새 버전 ${r.version}이 있어요 · ‘담기’ 화면에서 업데이트를 눌러 주세요" else "✓ 최신 버전이에요"
                }
            }
            update?.let { u -> ChipButton("업데이트", T.blue, filled = true) { scope.launch { Updater.downloadAndInstall(ctx, u) } } }
        }
        if (updateMsg.isNotEmpty()) Text(updateMsg, fontSize = 13.sp, color = T.soft)
    }
}
