package kr.sseudam.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
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
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.io.File
import java.util.Calendar

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Store.init(this)
        Plus.init(this)
        handleLink(intent)
        enableEdgeToEdge()
        setContent {
            MaterialTheme(colorScheme = lightColorScheme(primary = T.blue, secondary = T.lavender, background = T.bg,
                surface = T.card, surfaceContainerLow = T.card, surfaceContainer = T.card, onSurface = T.ink)) { App() }
        }
        UploadWorker.enqueue(this)
        if (Relay.paired()) UploadWorker.schedulePeriodic(this)
    }

    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); handleLink(intent) }

    private fun handleLink(i: Intent?) {
        // 앱 아이콘 길게 눌러 '녹음 시작' · "헤이 구글, 쓰담에서 녹음 시작" → 손 없이 녹음
        if (HandsFree.isRecordIntent(i)) { HandsFree.request.value = true; return }
        if (i?.action == Intent.ACTION_SEND || i?.action == Intent.ACTION_SEND_MULTIPLE) { handleShare(i); return }
        val data = i?.data?.toString() ?: return
        Relay.parse(data)?.let { Store.pairRelay(it); return }
        Store.parsePairing(data)?.let { (u, t, n) -> Store.pair(u, t, n) }
    }

    /** 다른 녹음 앱에서 '공유 → 쓰담' */
    @Suppress("DEPRECATION")
    private fun handleShare(i: Intent) {
        val uris = if (i.action == Intent.ACTION_SEND_MULTIPLE) i.getParcelableArrayListExtra<android.net.Uri>(Intent.EXTRA_STREAM) ?: arrayListOf()
                   else listOfNotNull(i.getParcelableExtra<android.net.Uri>(Intent.EXTRA_STREAM))
        var n = 0
        for (u in uris) {
            val name = contentResolver.query(u, arrayOf(android.provider.OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst()) c.getString(0) else null } ?: "공유받은 녹음.m4a"
            runCatching { contentResolver.openInputStream(u)?.let { Store.addShared(it, name); n++ } }
        }
        android.widget.Toast.makeText(this, if (n > 0) "녹음 ${n}개를 쓰담에 담았어요" + (if (Store.paired.value) " · 컴퓨터로 보내는 중" else "") else "녹음을 가져오지 못했어요",
            android.widget.Toast.LENGTH_LONG).show()
    }
}

/** 탭 안에서 들어가는 화면 */
sealed interface Route {
    data class Cls(val uid: String) : Route
    data class Stu(val uid: String) : Route
    data class Draft(val classUid: String) : Route
    data class Entry(val id: String) : Route
}

class Nav(val tab: MutableState<Int>, private val stacks: List<androidx.compose.runtime.snapshots.SnapshotStateList<Route>>) {
    val stack get() = stacks[tab.value]
    fun go(r: Route) { stack.add(r) }
    fun back() { if (stack.isNotEmpty()) stack.removeAt(stack.lastIndex) }
    fun switch(t: Int, r: Route? = null) { tab.value = t; if (r != null) { stacks[t].clear(); stacks[t].add(r) } }
}

/** startTab·startRoute 는 스토어 스크린샷(JVM 테스트)에서 특정 화면을 바로 열 때만 쓴다 */
@Composable
fun App(startTab: Int = 0, startRoute: Route? = null) {
    val ctx = LocalContext.current
    val tab = remember { mutableIntStateOf(startTab) }
    val stacks = remember { List(4) { i -> mutableStateListOf<Route>().apply { if (i == startTab && startRoute != null) add(startRoute) } } }
    val nav = remember { Nav(tab, stacks) }
    LaunchedEffect(Unit) { Distribution.onLaunch(ctx) }
    val hfReq by HandsFree.request.collectAsStateWithLifecycle()
    LaunchedEffect(hfReq) { if (hfReq) { tab.intValue = 0; stacks[0].clear() } }   // 손 없이 녹음은 담기 탭에서 시작
    BackHandler(enabled = nav.stack.isNotEmpty()) { nav.back() }

    Scaffold(containerColor = T.bg, bottomBar = {
        NavigationBar(containerColor = T.card) {
            val items = listOf(Triple("담기", Icons.Filled.Mic, 0), Triple("기록함", Icons.Filled.Inventory2, 1),
                Triple("학생", Icons.Filled.People, 2), Triple("연결", Icons.Filled.Sync, 3))
            items.forEach { (label, icon, i) ->
                NavigationBarItem(tab.intValue == i, {
                    if (tab.intValue == i) stacks[i].clear() else tab.intValue = i
                }, { Icon(icon, null) }, label = { Text(label) },
                    colors = NavigationBarItemDefaults.colors(selectedIconColor = T.blue, selectedTextColor = T.blue, indicatorColor = T.blue.copy(alpha = 0.12f)))
            }
        }
    }) { pad ->
        Box(Modifier.padding(pad).fillMaxSize().background(T.bg)) {
            when (val r = nav.stack.lastOrNull()) {
                null -> when (tab.intValue) {
                    0 -> HomeScreen(nav); 1 -> RecordsScreen(nav); 2 -> StudentsScreen(nav); else -> ConnectScreen()
                }
                is Route.Cls -> ClassScreen(nav, r.uid)
                is Route.Stu -> StudentScreen(nav, r.uid)
                is Route.Draft -> ClassDraftScreen(nav, r.classUid)
                is Route.Entry -> EntryScreen(nav, r.id)
            }
        }
    }
}

fun timeString(ms: Long): String {
    val s = ms / 1000
    return if (s >= 3600) "%d:%02d:%02d".format(s / 3600, s / 60 % 60, s % 60) else "%02d:%02d".format(s / 60, s % 60)
}

/** 화면 위쪽 뒤로 가기 줄 */
@Composable
fun BackBar(title: String, nav: Nav, trailing: @Composable RowScope.() -> Unit = {}) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        IconButton({ nav.back() }) { Icon(Icons.Filled.ArrowBackIosNew, "뒤로", tint = T.blue) }
        Text(title, fontSize = 18.sp, fontWeight = FontWeight.Bold, color = T.ink, modifier = Modifier.weight(1f), maxLines = 1)
        trailing()
    }
}

// ───────────────────────── 담기 ─────────────────────────

@Composable
fun HomeScreen(nav: Nav) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val recording by RecordService.recording.collectAsStateWithLifecycle()
    val paused by RecordService.paused.collectAsStateWithLifecycle()
    val level by RecordService.level.collectAsStateWithLifecycle()
    val paired by Store.paired.collectAsStateWithLifecycle()
    val items by Store.items.collectAsStateWithLifecycle()
    val db by DataStore.db.collectAsStateWithLifecycle()
    var elapsed by remember { mutableLongStateOf(0L) }
    var pending by remember { mutableStateOf<Triple<File, Long, Long>?>(null) }
    var savedId by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(recording) { while (recording) { elapsed = RecordService.elapsedMs(); delay(100) } }
    // 손 없이 녹음: 어시스턴트·바로가기 요청, 얼굴 가까이 대기(근접 센서) · 손 없이 담은 녹음은 바로 '담았어요' 카드로
    HandsFreeEffect(active = pending == null)
    val hfSaved by RecordService.lastSavedId.collectAsStateWithLifecycle()
    LaunchedEffect(hfSaved) { hfSaved?.let { savedId = it; RecordService.lastSavedId.value = null } }
    val handsFree by RecordService.handsFree.collectAsStateWithLifecycle()

    val perm = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { res ->
        // 알림을 거절해도 녹음은 된다 (알림 막대에 '녹음 중'이 안 보일 뿐)
        if (res[Manifest.permission.RECORD_AUDIO] == true || granted(ctx, Manifest.permission.RECORD_AUDIO)) { savedId = null; RecordService.start(ctx) }
    }
    fun toggle() {
        if (recording) {
            val dur = RecordService.elapsedMs(); val at = RecordService.startedAt
            RecordService.stop(ctx)
            RecordService.lastFile?.let { f -> if (dur >= 1000) pending = Triple(f, dur, at) else f.delete() }
            elapsed = 0
        } else {
            val ask = recordPermissionsToAsk(ctx)
            if (ask.isEmpty()) { savedId = null; RecordService.start(ctx) } else perm.launch(ask)
        }
    }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 18.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        // 머리말
        Row(Modifier.padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Dami(56.dp, listening = recording, happy = !recording)
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                Text(greeting(recording), fontSize = 22.sp, fontWeight = FontWeight.Bold, color = T.ink)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (paired) Pill("✓ 컴퓨터로 자동 전송", T.mint) else Pill("🔗 컴퓨터와 연결하기", T.coral) { nav.switch(3) }
                    val today = items.count { android.text.format.DateUtils.isToday(it.createdAt) }
                    if (today > 0) Pill("✨ 오늘 ${today}개", T.lavender)
                }
            }
        }

        UpdateBanner()

        // 녹음
        Column(Modifier.fillMaxWidth().card(22.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            val pulse by animateFloatAsState(if (recording && !paused) 1f + level * 0.25f else 1f, label = "pulse")
            Box(Modifier.height(200.dp), contentAlignment = Alignment.Center) {
                if (recording && !paused) Box(Modifier.size(150.dp).scale(pulse).clip(CircleShape).background(T.coral.copy(alpha = 0.15f)))
                Box(Modifier.size(148.dp).clip(CircleShape).background(if (recording) T.warm else T.brand).clickable { toggle() },
                    contentAlignment = Alignment.Center) {
                    Icon(if (recording) Icons.Filled.Stop else Icons.Filled.Mic, if (recording) "녹음 끝내기" else "녹음 시작",
                        tint = Color.White, modifier = Modifier.size(56.dp))
                }
            }
            Text(if (recording) timeString(elapsed) else "눌러서 말하기", fontSize = if (recording) 40.sp else 20.sp,
                fontWeight = if (recording) FontWeight.Light else FontWeight.SemiBold, color = T.ink)
            Spacer(Modifier.height(8.dp))
            Text(if (!recording) "학년·반·이름부터 말하면 학생별로 쏙쏙 담겨요 ✨\n“2학년 3반 김민수! 친구 의견 모아 멋지게 발표 🌟”"
                else if (paused) "잠깐 멈췄어요" else if (handsFree) handsFreeHint()
                else "화면을 꺼도 계속 녹음돼요 · 끝나면 한 번 더 누르세요",
                fontSize = 14.sp, color = T.soft, textAlign = TextAlign.Center)
            if (recording && db.hasRoster) {
                Spacer(Modifier.height(12.dp))
                MarkStrip(db)
            }
            if (recording) {
                Spacer(Modifier.height(12.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    PeriodChip()
                    ChipButton(if (paused) "▶ 이어서" else "⏸ 잠깐 멈춤") { RecordService.togglePause(ctx) }
                }
            }
            if (!recording) {
                Spacer(Modifier.height(14.dp))
                HandsFreePanel()
            }
            Spacer(Modifier.height(10.dp))
            Text("🖥️ 녹음은 컴퓨터의 쓰담이 글자로 바꾸고 학생별로 정리해요", fontSize = 12.sp, color = T.soft, textAlign = TextAlign.Center)
        }

        savedId?.let { id -> Store.get(id)?.let { SavedCard(it, db, paired, nav) { savedId = null } } }

        MemoCard(recording) { r -> savedId = r.id }

        // 흐름 안내
        Row(Modifier.fillMaxWidth().card(14.dp), verticalAlignment = Alignment.CenterVertically) {
            listOf("🎙️" to "말하기", "☁️" to "자동 전송", "👥" to "학생별 정리", "📝" to "초안").forEachIndexed { i, (e, t) ->
                if (i > 0) Text("›", color = T.soft)
                Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(e, fontSize = 20.sp); Text(t, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = T.soft, maxLines = 1)
                }
            }
        }
        Spacer(Modifier.height(20.dp))
    }

    pending?.let { (file, dur, at) ->
        var memo by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = {}, containerColor = T.card,
            title = { Text("녹음을 담을까요? (${timeString(dur)})") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(memo, { memo = it }, label = { Text("메모 (선택) 예: 2-3 국어") }, singleLine = true)
                    val marks = RecordService.markers.value
                    val named = marks.count { it.student != null }; val stars = marks.count { it.star }
                    if (named > 0 || stars > 0) Text("👥 이름표 ${named}번 · ⭐ ${stars}번 — 컴퓨터가 이 표시대로 학생별로 나눠요",
                        fontSize = 12.sp, color = T.lavender)
                    Text(if (RecordService.pickedClass.value != null || RecordService.period.value != null) "고른 반·교시로 컴퓨터에 담겨요."
                        else "반은 컴퓨터의 시간표나 녹음 내용으로 자동으로 정해져요.", fontSize = 12.sp, color = T.soft)
                }
            },
            // 상담 유형은 아이폰과 같이 지금은 숨김 (수업 기록 위주)
            confirmButton = { TextButton({ Store.add(file, dur / 1000.0, "수업", memo, at, RecordService.markers.value,
                RecordService.pickedClass.value, RecordService.period.value); pending = null
                savedId = Store.items.value.firstOrNull()?.id }) { Text("담기") } },
            dismissButton = { TextButton({ file.delete(); pending = null }) { Text("버리기", color = T.coral) } },
        )
    }
}

/** 녹음하면서 톡: 이 학생 이야기 / ⭐ 중요한 순간 (컴퓨터가 누른 시점대로 학생별로 나눈다) */
@Composable
fun MarkStrip(db: DB) {
    val markers by RecordService.markers.collectAsStateWithLifecycle()
    val current by RecordService.currentStudent.collectAsStateWithLifecycle()
    val picked by RecordService.pickedClass.collectAsStateWithLifecycle()
    val prefs = LocalContext.current.getSharedPreferences("sseudam", android.content.Context.MODE_PRIVATE)
    var markClass by remember { mutableStateOf(prefs.getString("markClass", "") ?: "") }
    val cls = db.currentClasses.firstOrNull { it.uid == (picked ?: markClass) } ?: db.currentClasses.firstOrNull() ?: db.activeClasses.firstOrNull()
    var menu by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(T.bg.copy(alpha = 0.6f)).padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("누구 이야기인지 톡", fontSize = 13.sp, fontWeight = FontWeight.Bold, color = T.soft)
            Box {
                Pill((cls?.title ?: "반 고르기") + " ▾", T.blue) { menu = true }
                DropdownMenu(menu, { menu = false }) {
                    db.activeClasses.forEach { c ->
                        DropdownMenuItem({ Text(c.title) }, {
                            markClass = c.uid; prefs.edit().putString("markClass", c.uid).apply()
                            RecordService.pickedClass.value = c.uid; menu = false
                        })
                    }
                }
            }
            Spacer(Modifier.weight(1f))
            ChipButton("⭐ ${markers.count { it.star }}", T.butter) { RecordService.star() }
        }
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            (cls?.let { db.studentsIn(it) } ?: emptyList()).forEach { s ->
                ChipButton(s.displayName, T.blue, filled = current == s.uid) { RecordService.mark(s.uid) }
            }
        }
        db.students.firstOrNull { it.uid == current }?.let {
            Text("지금부터 ${it.displayName} 이야기로 담아요 ✍️", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = T.lavender)
        }
    }
}

/** 몇 교시 수업인지 (컴퓨터 시간표로 반을 정확히 찾게 · 고르지 않으면 녹음 시각으로 찾음) */
@Composable
fun PeriodChip() {
    val period by RecordService.period.collectAsStateWithLifecycle()
    var menu by remember { mutableStateOf(false) }
    Box {
        ChipButton("🕘 " + (period?.let { "${it}교시" } ?: "교시"), T.lavender, filled = period != null) { menu = true }
        DropdownMenu(menu, { menu = false }) {
            DropdownMenuItem({ Text("안 정함") }, { RecordService.period.value = null; menu = false })
            (1..9).forEach { p -> DropdownMenuItem({ Text("${p}교시") }, { RecordService.period.value = p; menu = false }) }
        }
    }
}

fun granted(ctx: android.content.Context, p: String) = ContextCompat.checkSelfPermission(ctx, p) == PackageManager.PERMISSION_GRANTED

/**
 * 녹음 전에 물어볼 권한: 마이크(필수) + 알림(안드로이드 13+, 녹음 중 표시용 · 한 번만 물음).
 * 마이크 포그라운드 서비스는 RECORD_AUDIO 가 허용된 상태에서 앱이 화면에 있을 때만 시작한다 (안드로이드 14+ 규칙).
 */
fun recordPermissionsToAsk(ctx: android.content.Context): Array<String> {
    val out = mutableListOf<String>()
    if (!granted(ctx, Manifest.permission.RECORD_AUDIO)) out += Manifest.permission.RECORD_AUDIO
    if (Build.VERSION.SDK_INT >= 33 && !granted(ctx, Manifest.permission.POST_NOTIFICATIONS)) {
        val prefs = ctx.getSharedPreferences("sseudam", android.content.Context.MODE_PRIVATE)
        if (!prefs.getBoolean("askedNotif", false)) {
            prefs.edit().putBoolean("askedNotif", true).apply()
            out += Manifest.permission.POST_NOTIFICATIONS
        }
    }
    return out.toTypedArray()
}

/** 앱 버전 (연결 탭 표시용) */
fun appVersion(ctx: android.content.Context): String =
    runCatching { ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName }.getOrNull() ?: ""

private fun greeting(recording: Boolean): String {
    if (recording) return "잘 듣고 있어요"
    val h = Calendar.getInstance().get(Calendar.HOUR_OF_DAY)
    return if (h < 12) "좋은 아침이에요!" else if (h < 17) "오늘 수업, 한마디 남겨요" else "오늘도 수고하셨어요"
}

/** 방금 담은 기록 카드 */
@Composable
fun SavedCard(e: Recording, db: DB, paired: Boolean, nav: Nav, onClose: () -> Unit) {
    Column(Modifier.fillMaxWidth().card(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("✅ " + if (e.isAudio) "녹음을 담았어요 · ${timeString((e.durationSec * 1000).toLong())}" else "메모를 담았어요",
                fontSize = 16.sp, fontWeight = FontWeight.Bold, color = T.ink, modifier = Modifier.weight(1f))
            IconButton(onClose, Modifier.size(28.dp)) { Icon(Icons.Filled.Close, "닫기", tint = T.soft) }
        }
        val names = e.splitNames
        if (names != null) {
            if (names.isNotEmpty()) NameChips(names)
            if (e.splitUnsure > 0 || e.splitLeftover.isNotEmpty() || names.isEmpty()) {
                Text("👆 " + when {
                    names.isEmpty() -> "누구 이야기인지 골라 주세요"
                    e.splitUnsure > 0 -> "이름이 같은 학생이 있어요 · 눌러서 확인"
                    else -> "이름이 안 나온 부분이 있어요 · 눌러서 정리"
                }, fontSize = 13.sp, fontWeight = FontWeight.Bold, color = Color(0xFFD9A400),
                    modifier = Modifier.clickable { nav.switch(1, Route.Entry(e.id)) })
            }
        } else if (!e.isAudio && !db.hasRoster) {
            Text("‘학생’ 탭에 명단을 넣으면 이름이 나온 곳마다 학생별로 나눠 담아요.", fontSize = 12.sp, color = T.soft)
        }
        Text(if (paired) "☁️ 구글 드라이브로 보내요 · 컴퓨터 쓰담이 켜지면 가져가요"
            else "📱 휴대폰에 보관했어요 · ‘연결’에서 컴퓨터와 연결하면 보내져요", fontSize = 12.sp, color = T.soft)
    }
}

/** 한 줄로 남기기 — 글로 쓰거나, 🎤로 말하면 기기 받아쓰기로 글자가 된다 */
@Composable
fun MemoCard(recording: Boolean, onSaved: (Recording) -> Unit) {
    val ctx = LocalContext.current
    var memo by remember { mutableStateOf("") }
    var base by remember { mutableStateOf("") }
    val dict = remember {
        Dictation(ctx, onPartial = { p -> memo = (base + " " + p).trim() }, onFinal = { f -> memo = (base + " " + f).trim(); base = memo })
    }
    DisposableEffect(Unit) { onDispose { dict.destroy() } }
    val listening by dict.listening.collectAsStateWithLifecycle()
    val err by dict.error.collectAsStateWithLifecycle()
    val perm = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok -> if (ok) { base = memo; dict.start() } }

    Column(Modifier.fillMaxWidth().card(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("✏️ 한 줄로 남기기", fontSize = 17.sp, fontWeight = FontWeight.Bold, color = T.ink)
        OutlinedTextField(memo, { memo = it; base = it }, modifier = Modifier.fillMaxWidth(), minLines = 2, maxLines = 5,
            placeholder = { Text("예) 2학년 3반 이서연, 발표 자료를 꼼꼼하게 준비해 옴 🌱", color = T.soft) },
            shape = RoundedCornerShape(14.dp),
            colors = OutlinedTextFieldDefaults.colors(unfocusedContainerColor = T.bg, focusedContainerColor = T.bg,
                unfocusedBorderColor = Color.Transparent, focusedBorderColor = T.blue.copy(alpha = 0.4f)))
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (dict.available()) {
                Box(Modifier.size(40.dp).clip(CircleShape).background(if (listening) T.coral else T.blue.copy(alpha = 0.12f))
                    .clickable(enabled = !recording) {
                        if (listening) dict.stop()
                        else if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) { base = memo; dict.start() }
                        else perm.launch(Manifest.permission.RECORD_AUDIO)
                    }, contentAlignment = Alignment.Center) {
                    Icon(if (listening) Icons.Filled.Stop else Icons.Filled.Mic, "말로 받아쓰기", tint = if (listening) Color.White else T.blue)
                }
                Spacer(Modifier.width(8.dp))
            }
            Text(when {
                recording -> "녹음 중에는 글로 남겨 주세요"
                listening -> "듣고 있어요… 말을 멈추면 글자가 돼요"
                err.isNotEmpty() -> err
                else -> "🎤를 누르거나 키보드의 🎤로 말해도 돼요"
            }, fontSize = 12.sp, color = if (err.isNotEmpty() && !listening) T.coral else T.soft, modifier = Modifier.weight(1f))
            Spacer(Modifier.width(8.dp))
            ChipButton("담기", if (memo.isBlank()) Color.Gray else T.blue, filled = true) {
                if (memo.isBlank()) return@ChipButton
                dict.destroy()
                Store.addText(memo)?.let(onSaved)
                memo = ""; base = ""
            }
        }
    }
}
