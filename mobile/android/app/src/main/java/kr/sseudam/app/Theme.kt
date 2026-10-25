package kr.sseudam.app

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import kotlinx.coroutines.delay
import java.io.File

/** 쓰담 디자인 (아이폰 Theme.swift 와 같은 색): 크림 배경 · 파스텔 · 부드러운 카드 */
object T {
    val blue = Color(0xFF2E3A8C)
    val lavender = Color(0xFF5A67C9)
    val coral = Color(0xFFFF8C7A)
    val mint = Color(0xFF5FD1A5)
    val butter = Color(0xFFFFD45C)
    val peach = Color(0xFFFFDECC)
    val bg = Color(0xFFFFF8F0)
    val card = Color.White
    val ink = Color(0xFF1F2330)
    val soft = Color(0xFF8A8F9C)
    val brand = Brush.linearGradient(listOf(blue, Color(0xFF4B58B5)))
    val warm = Brush.linearGradient(listOf(coral, Color(0xFFFFA880)))
}

fun Modifier.card(padding: Dp = 16.dp): Modifier = this
    .shadow(6.dp, RoundedCornerShape(22.dp), ambientColor = Color.Black.copy(alpha = 0.05f), spotColor = Color.Black.copy(alpha = 0.08f))
    .clip(RoundedCornerShape(22.dp)).background(T.card).padding(padding)

fun kindColor(k: String?): Color = when (k ?: "교과") {
    "담임" -> T.coral; "동아리" -> T.mint; "기타" -> T.butter; else -> T.blue
}

fun kindEmoji(k: String?): String = when (k ?: "교과") {
    "담임" -> "🏠"; "동아리" -> "⭐"; "기타" -> "✨"; else -> "📘"
}

fun copyText(ctx: Context, text: String, toast: String? = "복사했어요") {
    val cm = ctx.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    cm.setPrimaryClip(ClipData.newPlainText("쓰담", text))
    if (toast != null) Toast.makeText(ctx, toast, Toast.LENGTH_SHORT).show()
}

fun pasteText(ctx: Context): String {
    val cm = ctx.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    return cm.primaryClip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(ctx)?.toString() ?: ""
}

fun openUrl(ctx: Context, url: String) = runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }

/** 앱 안 파일을 공유 시트로 (구글 드라이브·카카오톡·메일 등) */
fun shareFile(ctx: Context, f: File, mime: String, title: String) {
    val uri = FileProvider.getUriForFile(ctx, ctx.packageName + ".files", f)
    val i = Intent(Intent.ACTION_SEND).setType(mime).putExtra(Intent.EXTRA_STREAM, uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    ctx.startActivity(Intent.createChooser(i, title))
}

@Composable
fun ScreenTitle(text: String, modifier: Modifier = Modifier, trailing: @Composable RowScope.() -> Unit = {}) {
    Row(modifier.fillMaxWidth().padding(top = 12.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(text, fontSize = 28.sp, fontWeight = FontWeight.Bold, color = T.ink, modifier = Modifier.weight(1f))
        trailing()
    }
}

@Composable
fun SoftLabel(text: String, modifier: Modifier = Modifier) =
    Text(text, fontSize = 15.sp, fontWeight = FontWeight.Bold, color = T.soft, modifier = modifier.padding(start = 4.dp))

/** 작은 상태 알약 */
@Composable
fun Pill(text: String, color: Color, onClick: (() -> Unit)? = null) {
    Text(text, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = color,
        modifier = Modifier.clip(CircleShape).background(color.copy(alpha = 0.14f))
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 10.dp, vertical = 5.dp))
}

/** 둥근 버튼 (그라데이션 또는 단색) */
@Composable
fun BigButton(text: String, modifier: Modifier = Modifier, color: Color? = null, enabled: Boolean = true, onClick: () -> Unit) {
    val bg = if (!enabled) Modifier.background(Color.Gray.copy(alpha = 0.25f)) else if (color != null) Modifier.background(color) else Modifier.background(T.brand)
    Box(modifier.clip(CircleShape).then(bg).clickable(enabled = enabled, onClick = onClick).padding(vertical = 13.dp, horizontal = 18.dp),
        contentAlignment = Alignment.Center) {
        Text(text, color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.Bold)
    }
}

@Composable
fun ChipButton(text: String, color: Color = T.blue, filled: Boolean = false, onClick: () -> Unit) {
    Text(text, fontSize = 13.sp, fontWeight = FontWeight.Bold, color = if (filled) Color.White else color,
        modifier = Modifier.clip(CircleShape).background(if (filled) color else color.copy(alpha = 0.13f))
            .clickable(onClick = onClick).padding(horizontal = 13.dp, vertical = 8.dp))
}

/** 마스코트 '담이' — 말풍선 얼굴 */
@Composable
fun Dami(size: Dp = 64.dp, listening: Boolean = false, happy: Boolean = false) {
    val tr = rememberInfiniteTransition(label = "bob")
    val bob by tr.animateFloat(-0.04f, 0.02f, infiniteRepeatable(tween(1600), RepeatMode.Reverse), label = "bob")
    Canvas(Modifier.size(size).offset(y = size * bob)) {
        val s = this.size.width
        drawRoundRect(T.brand, topLeft = Offset(0f, s * 0.09f), size = Size(s, s * 0.82f), cornerRadius = CornerRadius(s * 0.36f))
        val tail = Path().apply { moveTo(s * 0.2f, s * 0.95f); lineTo(s * 0.18f, s * 0.78f); lineTo(s * 0.4f, s * 0.82f); close() }
        drawPath(tail, T.lavender)
        val ey = s * 0.44f
        for (x in listOf(s * 0.39f, s * 0.61f)) {
            if (happy) drawArc(Color.White, 200f, 140f, false, Offset(x - s * 0.06f, ey - s * 0.02f), Size(s * 0.12f, s * 0.1f),
                style = Stroke(s * 0.05f, cap = StrokeCap.Round))
            else drawRoundRect(Color.White, Offset(x - s * 0.045f, ey - s * 0.06f), Size(s * 0.09f, if (listening) s * 0.15f else s * 0.12f),
                CornerRadius(s * 0.05f))
        }
        drawCircle(T.coral.copy(alpha = 0.55f), s * 0.065f, Offset(s * 0.29f, s * 0.6f))
        drawCircle(T.coral.copy(alpha = 0.55f), s * 0.065f, Offset(s * 0.71f, s * 0.6f))
        if (listening) drawCircle(Color.White, s * 0.04f, Offset(s * 0.5f, s * 0.64f))
        else drawArc(Color.White, 20f, 140f, false, Offset(s * 0.42f, s * 0.56f), Size(s * 0.16f, s * 0.1f), style = Stroke(s * 0.045f, cap = StrokeCap.Round))
    }
}

/** 학생 이름 칩 (반 색 + 이름, 동명이인이면 반도 함께) */
@Composable
fun StudentChip(student: SStudent?, db: DB, unsure: Boolean = false, onClick: (() -> Unit)? = null) {
    val c = student?.let { db.classOf(it) }
    val color = if (unsure) T.butter else kindColor(c?.kind)
    Row(Modifier.clip(CircleShape).background(color.copy(alpha = 0.14f))
        .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
        .padding(start = 4.dp, end = 10.dp, top = 4.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(24.dp).clip(CircleShape).background(color), contentAlignment = Alignment.Center) {
            Text(student?.displayName?.takeLast(2) ?: "?", fontSize = 10.sp, fontWeight = FontWeight.ExtraBold, color = Color.White, maxLines = 1)
        }
        Spacer(Modifier.width(6.dp))
        Text(student?.displayName ?: "누구일까요?", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = T.ink)
        if (student != null && c != null && (unsure || db.sameName(student).isNotEmpty())) {
            Spacer(Modifier.width(4.dp)); Text(c.title, fontSize = 11.sp, color = T.soft, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Spacer(Modifier.width(4.dp))
        Text(if (unsure) "?" else "▾", fontSize = 11.sp, fontWeight = FontWeight.Bold, color = if (unsure) T.butter else T.soft)
    }
}

/** 반 안에서 학생별 기록 수 막대 (누가 적은지 한눈에) */
@Composable
fun CountBar(count: Int, maxCount: Int, color: Color) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.width(70.dp).height(8.dp).clip(CircleShape).background(color.copy(alpha = 0.12f))) {
            val frac = if (count == 0) 0.09f else (count.toFloat() / maxOf(1, maxCount)).coerceIn(0.09f, 1f)
            Box(Modifier.fillMaxHeight().fillMaxWidth(frac).clip(CircleShape).background(if (count == 0) T.butter.copy(alpha = 0.5f) else color))
        }
        Spacer(Modifier.width(6.dp))
        Text(if (count == 0) "🌱" else "$count", fontSize = 12.sp, fontWeight = FontWeight.Bold,
            color = if (count == 0) T.butter else color, modifier = Modifier.widthIn(min = 18.dp))
    }
}

@Composable
fun ByteBadge(text: String, limit: Int) {
    val b = neisBytes(text)
    val c = if (b > limit) T.coral else T.mint
    Text("$b/$limit", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = c,
        modifier = Modifier.clip(CircleShape).background(c.copy(alpha = 0.15f)).padding(horizontal = 8.dp, vertical = 3.dp))
}

@Composable
fun CheckList(text: String, limit: Int) {
    val issues = DraftCheck.issues(text, limit)
    if (issues.isEmpty()) Text("✅ 검사 통과", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = T.mint)
    else Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        issues.forEach { Text((if (it.serious) "⚠️ " else "ℹ️ ") + it.text, fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
            color = if (it.serious) T.coral else Color(0xFFD9A400)) }
    }
}

/** 톡 눌러 바로 담기 */
@Composable
fun QuickTagRow(student: SStudent) {
    var popped by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(popped) { if (popped != null) { delay(800); popped = null } }
    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        QuickTags.all.forEach { (emoji, text) ->
            val on = popped == text
            val bg by animateColorAsState(if (on) T.mint.copy(alpha = 0.18f) else T.lavender.copy(alpha = 0.14f), label = "tag")
            Text("$emoji ${if (on) "담았어요!" else text}", fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                color = if (on) T.mint else T.ink,
                modifier = Modifier.clip(CircleShape).background(bg).clickable {
                    DataStore.addNote(student, text); popped = text
                }.padding(horizontal = 12.dp, vertical = 8.dp))
        }
    }
}

/** "담은 학생" 칩 줄 */
@Composable
fun NameChips(names: List<String>, suffix: String = "에게 담았어요") {
    Row(Modifier.horizontalScroll(rememberScrollState()), verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Text("👥", fontSize = 12.sp)
        names.forEach {
            Text(it, fontSize = 13.sp, fontWeight = FontWeight.Bold, color = T.lavender,
                modifier = Modifier.clip(CircleShape).background(T.lavender.copy(alpha = 0.14f)).padding(horizontal = 10.dp, vertical = 4.dp))
        }
        if (suffix.isNotEmpty()) Text(suffix, fontSize = 12.sp, color = T.soft)
    }
}

/** 확인 대화상자 */
@Composable
fun ConfirmDialog(title: String, message: String, confirm: String, danger: Boolean = true, onDismiss: () -> Unit, onConfirm: () -> Unit) {
    AlertDialog(onDismissRequest = onDismiss, title = { Text(title) }, text = { Text(message) },
        confirmButton = { TextButton({ onConfirm(); onDismiss() }) { Text(confirm, color = if (danger) T.coral else T.blue) } },
        dismissButton = { TextButton(onDismiss) { Text("취소") } }, containerColor = T.card)
}
