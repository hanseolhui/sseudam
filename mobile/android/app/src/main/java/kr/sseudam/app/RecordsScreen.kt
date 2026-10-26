package kr.sseudam.app

import android.media.MediaPlayer
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private fun dayKey(ms: Long): String {
    if (android.text.format.DateUtils.isToday(ms)) return "오늘"
    if (android.text.format.DateUtils.isToday(ms + 86_400_000L)) return "어제"
    return SimpleDateFormat("M월 d일 EEEE", Locale.KOREA).format(Date(ms))
}

@Composable
fun RecordsScreen(nav: Nav) {
    val items by Store.items.collectAsStateWithLifecycle()
    val db by DataStore.db.collectAsStateWithLifecycle()
    val paired by Store.paired.collectAsStateWithLifecycle()
    var playing by remember { mutableStateOf<String?>(null) }
    val player = remember { MediaPlayer() }
    DisposableEffect(Unit) { onDispose { player.release() } }
    var confirmDelete by remember { mutableStateOf<Recording?>(null) }
    val tf = remember { SimpleDateFormat("a h:mm", Locale.KOREA) }

    Column(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        ScreenTitle("기록함")
        if (items.isEmpty()) {
            Column(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                Dami(90.dp)
                Spacer(Modifier.height(14.dp))
                Text("아직 담은 기록이 없어요", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = T.ink)
                Text("‘담기’에서 녹음하거나 한 줄 메모를 남기면\n여기에 날짜별로 차곡차곡 쌓여요.", fontSize = 15.sp, color = T.soft,
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center)
            }
            return@Column
        }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp), contentPadding = PaddingValues(bottom = 24.dp)) {
            if (!paired) item {
                Text("🔗 ‘연결’ 탭에서 컴퓨터와 연결하면 녹음·메모가 컴퓨터로 자동으로 가요", fontSize = 13.sp, color = T.blue,
                    modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(T.blue.copy(alpha = 0.08f))
                        .clickable { nav.switch(3) }.padding(12.dp))
            }
            val groups = items.groupBy { dayKey(it.createdAt) }
            groups.forEach { (day, list) ->
                item(key = "h-$day") { SoftLabel(day, Modifier.padding(top = 6.dp)) }
                items(list, key = { it.id }) { r ->
                    Column(Modifier.fillMaxWidth().card(12.dp).clickable { nav.go(Route.Entry(r.id)) },
                        verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            if (r.isAudio) IconButton({
                                if (playing == r.id) { player.reset(); playing = null } else runCatching {
                                    player.reset(); player.setDataSource(Store.file(r).absolutePath); player.prepare(); player.start()
                                    player.setOnCompletionListener { playing = null }; playing = r.id
                                }
                            }) { Icon(if (playing == r.id) Icons.Filled.StopCircle else Icons.Filled.PlayCircle, "재생", tint = T.blue, modifier = Modifier.size(36.dp)) }
                            else Box(Modifier.padding(6.dp).size(36.dp).clip(CircleShape).background(T.lavender.copy(alpha = 0.15f)),
                                contentAlignment = Alignment.Center) { Text("✏️") }
                            Column(Modifier.weight(1f).padding(start = 6.dp)) {
                                Text(if (r.isAudio) (r.memo.ifEmpty { "녹음" }) else r.text, fontWeight = FontWeight.SemiBold, color = T.ink,
                                    maxLines = 2, fontSize = 15.sp)
                                Text(tf.format(Date(r.createdAt)) + if (r.isAudio) " · ${timeString((r.durationSec * 1000).toLong())}" else " · 메모",
                                    fontSize = 12.sp, color = T.soft)
                                if (r.google == Sync.FAILED && r.lastError.isNotEmpty()) Text(r.lastError, fontSize = 11.sp, color = T.coral)
                            }
                            Text(when {
                                r.received -> "✓ 컴퓨터가 받음"; r.waiting -> "보냄 · 컴퓨터 대기"
                                else -> when (r.google) { Sync.DONE -> "✓ 보냄"; Sync.PENDING -> "대기"; Sync.FAILED -> "다시 시도"; Sync.OFF -> "" }
                            }, fontSize = 12.sp, color = when {
                                r.received -> T.mint; r.waiting -> T.blue
                                else -> when (r.google) { Sync.DONE -> T.mint; Sync.FAILED -> T.coral; else -> T.soft }
                            })
                            IconButton({ confirmDelete = r }) { Icon(Icons.Filled.DeleteOutline, "지우기", tint = T.soft) }
                        }
                        val names = db.notesForSource(r.fileName).mapNotNull { db.student(it.studentUid)?.displayName }.distinct()
                        if (names.isNotEmpty()) NameChips(names, suffix = if (db.notesForSource(r.fileName).any { db.isUnsure(it) }) "· 확인 필요" else "")
                        else if (!r.isAudio && r.splitNames != null && db.hasRoster) Text("👆 누구 이야기인지 골라 주세요", fontSize = 12.sp, color = Color(0xFFD9A400))
                    }
                }
            }
        }
    }
    confirmDelete?.let { r ->
        ConfirmDialog("이 기록을 지울까요?", if (r.google == Sync.DONE) "컴퓨터에는 이미 보내져 보관되어 있어요. 학생별로 나눈 기록은 그대로 남아요."
            else "아직 컴퓨터로 보내지 않았어요. 지우면 되돌릴 수 없어요.", "지우기", onDismiss = { confirmDelete = null }) { Store.delete(r) }
    }
}

/** 기록 하나 → 학생별 조각 (칩을 눌러 다른 학생으로 옮기기 · 위 조각과 합치기 · 빼기) */
@Composable
fun EntryScreen(nav: Nav, id: String) {
    val items by Store.items.collectAsStateWithLifecycle()
    val db by DataStore.db.collectAsStateWithLifecycle()
    val e = items.firstOrNull { it.id == id } ?: run { LaunchedEffect(Unit) { nav.back() }; return }
    var picking by remember { mutableStateOf<SNote?>(null) }
    var pickingLeftover by remember { mutableStateOf(false) }
    var confirmResplit by remember { mutableStateOf(false) }
    val text = e.text
    val pieces = db.notesForSource(e.fileName).sortedWith(compareBy<SNote>({ n ->
        val c = (n.content ?: "").take(14); val p = if (c.isEmpty()) -1 else text.indexOf(c); if (p < 0) Int.MAX_VALUE else p
    }, { it.updatedAt }))

    Column(Modifier.fillMaxSize()) {
        BackBar(if (e.isAudio) "녹음" else "메모", nav)
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 18.dp, vertical = 6.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Column(Modifier.fillMaxWidth().card(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(SimpleDateFormat("M월 d일 (E) a h:mm", Locale.KOREA).format(Date(e.createdAt)), fontSize = 13.sp, color = T.soft, fontWeight = FontWeight.SemiBold)
                if (e.isAudio) {
                    Text(e.memo.ifEmpty { "녹음 · ${timeString((e.durationSec * 1000).toLong())}" }, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = T.ink)
                    Text("🖥️ 녹음은 컴퓨터의 쓰담이 글자로 바꾸고 학생별로 나눠요. 안드로이드 폰에서는 긴 녹음을 글자로 바꾸지 않아요 (‘한 줄로 남기기’의 🎤는 폰에서 바로 글자가 돼요).",
                        fontSize = 13.sp, color = T.soft)
                } else Text(text, fontSize = 15.sp, color = T.ink)
                if (e.waiting || e.google == Sync.FAILED) Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(if (e.waiting) "컴퓨터가 아직 안 받았어요. 컴퓨터 쓰담이 켜지면 가져가요." else "보내지 못했어요. ${e.lastError}",
                        fontSize = 12.sp, color = if (e.waiting) T.soft else T.coral, modifier = Modifier.weight(1f))
                    TextButton({ Store.resend(e) }) { Text("다시 보내기") }
                } else if (e.received) Text("✓ 컴퓨터의 쓰담이 받았어요", fontSize = 12.sp, color = T.mint)
            }
            if (!e.isAudio) Column(Modifier.fillMaxWidth().card(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("👥 학생별로 나눈 내용", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = T.ink, modifier = Modifier.weight(1f))
                    if (db.hasRoster) TextButton({ if (pieces.isEmpty()) Store.splitToStudents(e, true) else confirmResplit = true }) {
                        Text(if (pieces.isEmpty()) "나누기" else "다시 나누기")
                    }
                }
                if (!db.hasRoster) Text("‘학생’ 탭에 명단을 넣으면 이름이 나온 곳마다 학생별로 나눠 담아요.", fontSize = 13.sp, color = T.soft)
                else if (pieces.isEmpty() && e.splitLeftover.isEmpty()) {
                    Text(if (e.splitNames == null) "아직 나누지 않았어요. ‘나누기’를 누르면 이름이 나온 곳마다 학생별로 담아요."
                        else "명단에 있는 이름을 찾지 못했어요. 아래 칩을 눌러 학생을 골라 주세요.", fontSize = 13.sp, color = T.soft)
                    LeftoverCard(text, whole = true, db, onPick = { pickingLeftover = true }, onDrop = {})
                }
                if (e.splitLeftover.isNotEmpty()) LeftoverCard(e.splitLeftover, whole = false, db, onPick = { pickingLeftover = true }) { Store.dropLeftover(e) }
                pieces.forEachIndexed { i, n -> PieceCard(n, if (i > 0) pieces[i - 1] else null, db) { picking = n } }
            }
        }
    }
    picking?.let { n ->
        StudentPicker("누구 이야기인가요?", db.candidates(n), n.studentUid, db, onDismiss = { picking = null }) { s -> DataStore.moveNote(n, s) }
    }
    if (pickingLeftover) StudentPicker("누구 이야기인가요?", emptyList(), null, db, onDismiss = { pickingLeftover = false }) { s ->
        if (e.splitLeftover.isEmpty()) Store.assignWhole(e, s) else Store.assignLeftover(e, s)
    }
    if (confirmResplit) ConfirmDialog("다시 나눌까요?", "지금 나눠 둔 조각을 지우고 명단으로 처음부터 다시 나눠요. 직접 고친 내용은 사라져요.",
        "다시 나누기", onDismiss = { confirmResplit = false }) { Store.splitToStudents(e, true) }
}

@Composable
private fun PieceCard(n: SNote, above: SNote?, db: DB, onPick: () -> Unit) {
    val unsure = db.isUnsure(n)
    var menu by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(T.bg)
        .border(1.5.dp, if (unsure) T.butter.copy(alpha = 0.6f) else Color.Transparent, RoundedCornerShape(16.dp)).padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            StudentChip(db.student(n.studentUid), db, unsure, onClick = onPick)
            Spacer(Modifier.weight(1f))
            Box {
                IconButton({ menu = true }, Modifier.size(32.dp)) { Icon(Icons.Filled.MoreHoriz, "더보기", tint = T.soft) }
                DropdownMenu(menu, { menu = false }, containerColor = T.card) {
                    DropdownMenuItem({ Text("다른 학생으로 옮기기") }, { menu = false; onPick() })
                    if (above != null) DropdownMenuItem({ Text("위 조각과 합치기") }, { menu = false; DataStore.mergeNotes(n, above) })
                    DropdownMenuItem({ Text("이 조각 빼기", color = T.coral) }, { menu = false; DataStore.deleteNote(n) })
                }
            }
        }
        Text(n.content ?: "", fontSize = 15.sp, color = T.ink)
        if (unsure) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("이름이 같은(또는 비슷한) 학생이 있어요", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFFD9A400), modifier = Modifier.weight(1f))
            ChipButton("맞아요", T.mint) { DataStore.confirmNote(n) }
            ChipButton("다른 학생", Color(0xFFD9A400), onClick = onPick)
        }
    }
}

@Composable
private fun LeftoverCard(text: String, whole: Boolean, db: DB, onPick: () -> Unit, onDrop: () -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(T.bg)
        .border(1.5.dp, T.soft.copy(alpha = 0.4f), RoundedCornerShape(16.dp)).padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            StudentChip(null, db, unsure = true, onClick = onPick)
            Spacer(Modifier.weight(1f))
            if (!whole) ChipButton("학생 얘기 아님", T.soft, onClick = onDrop)
        }
        Text(text, fontSize = 15.sp, color = T.soft, maxLines = if (whole) 6 else Int.MAX_VALUE)
        Text("이름이 안 나온 부분이에요. 칩을 눌러 학생을 골라 주세요.", fontSize = 12.sp, color = T.soft)
    }
}
