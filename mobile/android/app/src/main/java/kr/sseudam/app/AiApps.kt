package kr.sseudam.app

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp

/**
 * 내 AI 연결 — 쓰담은 요청문만 만든다. API 키 없이 선생님이 쓰는 ChatGPT·Gemini 앱을 열고, 없으면 웹으로.
 * 앱 찾기는 AndroidManifest 의 <queries><package …/></queries> 덕분에 안드로이드 11+에서도 된다.
 */
object AiApps {
    data class App(val label: String, val pkg: String, val web: String)

    val chatgpt = App("ChatGPT", "com.openai.chatgpt", "https://chatgpt.com/")
    val gemini = App("Gemini", "com.google.android.apps.bard", "https://gemini.google.com/app")
    val all = listOf(chatgpt, gemini)

    fun open(ctx: Context, app: App) {
        val launch = ctx.packageManager.getLaunchIntentForPackage(app.pkg)
        if (launch != null && runCatching { ctx.startActivity(launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }.isSuccess) return
        runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(app.web)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
    }
}

/** "ChatGPT 열기 · Gemini 열기" 버튼 줄 (요청문을 복사한 뒤 보여 줌) */
@Composable
fun AiOpenRow() {
    val ctx = LocalContext.current
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        ChipButton("ChatGPT 열기", T.mint) { AiApps.open(ctx, AiApps.chatgpt) }
        ChipButton("Gemini 열기", T.blue) { AiApps.open(ctx, AiApps.gemini) }
    }
}
