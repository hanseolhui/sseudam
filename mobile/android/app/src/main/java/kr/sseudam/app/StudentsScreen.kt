package kr.sseudam.app

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle

private val fieldColors @Composable get() = OutlinedTextFieldDefaults.colors(unfocusedContainerColor = T.bg, focusedContainerColor = T.bg,
    unfocusedBorderColor = Color.Transparent, focusedBorderColor = T.blue.copy(alpha = 0.4f))

// ───────────────────────── 반 목록 ─────────────────────────

@Composable
fun StudentsScreen(nav: Nav) {
    val ctx = LocalContext.current
    val db by DataStore.db.collectAsStateWithLifecycle()
    val splitOn by DataStore.splitOnPhone.collectAsStateWithLifecycle()
    var query by remember { mutableStateOf("") }
    var addingClass by remember { mutableStateOf(false) }
    var showPast by remember { mutableStateOf(false) }
    var menu by remember { mutableStateOf(false) }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        ScreenTitle("학생") {
            IconButton({ addingClass = true }) { Icon(Icons.Filled.Add, "반 만들기", tint = T.blue) }
            Box {
                IconButton({ menu = true }) { Icon(Icons.Filled.MoreVert, "메뉴", tint = T.blue) }
                DropdownMenu(menu, { menu = false }, containerColor = T.card) {
                    DropdownMenuItem({ Text("반 만들기") }, { menu = false; addingClass = true })
                    DropdownMenuItem({ Text("엑셀로 내보내기 (CSV)") }, { menu = false; shareFile(ctx, DataStore.exportCSV(), "text/csv", "학생 기록 CSV") })
                    DropdownMenuItem({ Text("기록 파일 내보내기 · 가져오기") }, { menu = false; nav.switch(3) })
                    DropdownMenuItem({ Text((if (splitOn) "✓ " else "   ") + "폰에서 학생별로 나누기") }, { DataStore.setSplitOnPhone(!splitOn) })
                }
            }
        }
        OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth(), singleLine = true, shape = CircleShape,
            leadingIcon = { Icon(Icons.Filled.Search, null, tint = T.soft) }, placeholder = { Text("학생 이름 찾기") }, colors = fieldColors)

        if (query.isNotBlank()) {
            val list = db.search(query)
            if (list.isEmpty()) Text("‘$query’ 학생을 찾지 못했어요", fontSize = 15.sp, color = T.soft, modifier = Modifier.padding(top = 20.dp))
            list.forEach { s ->
                Row(Modifier.fillMaxWidth().card().clickable { nav.go(Route.Stu(s.uid)) }, verticalAlignment = Alignment.CenterVertically) {
                    StudentChip(s, db); Spacer(Modifier.width(10.dp))
                    Text(db.classOf(s)?.title ?: "", fontSize = 13.sp, color = T.soft, modifier = Modifier.weight(1f))
                    Text("기록 ${db.notesOf(s).size}", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = T.soft)
                }
            }
        } else {
            Row(Modifier.fillMaxWidth().card(), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(42.dp).clip(RoundedCornerShape(13.dp)).background(T.blue.copy(alpha = 0.14f)), contentAlignment = Alignment.Center) { Text("📱") }
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text("이 폰에서 정리 중", fontSize = 15.sp, fontWeight = FontWeight.Bold, color = T.ink)
                    Text("맥과 맞추려면 ‘연결’ 탭의 기록 파일 내보내기·가져오기를 써요 (녹음은 빼고 글만)", fontSize = 12.sp, color = T.soft)
                }
            }
            if (db.activeClasses.isEmpty()) {
                Column(Modifier.fillMaxWidth().card(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Dami(84.dp)
                    Text("학생 명단을 넣어 볼까요?", fontSize = 19.sp, fontWeight = FontWeight.Bold, color = T.ink)
                    Text("반을 만들고 이름을 붙여넣으면, 말한 내용이\n학생별 기록으로 쏙쏙 나뉘어 들어가요.\n맥의 쓰담 기록 파일을 가져와도 돼요.",
                        fontSize = 14.sp, color = T.soft, textAlign = TextAlign.Center)
                    BigButton("+ 반 만들기") { addingClass = true }
                }
            } else {
                db.currentClasses.forEach { c -> ClassRow(c, db) { nav.go(Route.Cls(c.uid)) } }
                if (db.pastClasses.isNotEmpty()) {
                    Text("🗂️ 지난 학기 반 ${db.pastClasses.size}개 " + if (showPast) "▴" else "▾", fontSize = 14.sp, fontWeight = FontWeight.Bold,
                        color = T.soft, modifier = Modifier.clickable { showPast = !showPast }.padding(6.dp))
                    if (showPast) db.pastClasses.forEach { c -> ClassRow(c, db) { nav.go(Route.Cls(c.uid)) } }
                }
            }
        }
        Spacer(Modifier.height(20.dp))
    }
    if (addingClass) AddClassDialog { addingClass = false }
}

@Composable
private fun ClassRow(c: SClass, db: DB, onClick: () -> Unit) {
    val color = kindColor(c.kind)
    Row(Modifier.fillMaxWidth().card().clickable(onClick = onClick), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(46.dp).clip(RoundedCornerShape(15.dp)).background(color), contentAlignment = Alignment.Center) {
            Text(kindEmoji(c.kind), fontSize = 20.sp)
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(c.title, fontSize = 17.sp, fontWeight = FontWeight.Bold, color = T.ink)
            Text("${c.kind ?: "교과"} · 학생 ${db.studentsIn(c).size}명 · 기록 ${db.noteCount(c)}개", fontSize = 13.sp, color = T.soft)
        }
        Icon(Icons.Filled.ChevronRight, null, tint = T.soft)
    }
}

// ───────────────────────── 반 ─────────────────────────

@Composable
fun ClassScreen(nav: Nav, uid: String) {
    val db by DataStore.db.collectAsStateWithLifecycle()
    val cls = db.cls(uid) ?: run { LaunchedEffect(Unit) { nav.back() }; return }
    var pasting by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<SStudent?>(null) }
    var menu by remember { mutableStateOf(false) }
    val list = db.studentsIn(cls)
    val counts = list.associate { it.uid to db.notesOf(it).size }
    val maxCount = counts.values.maxOrNull() ?: 1

    Column(Modifier.fillMaxSize()) {
        BackBar(cls.title, nav) {
            Box {
                IconButton({ menu = true }) { Icon(Icons.Filled.MoreVert, "메뉴", tint = T.blue) }
                DropdownMenu(menu, { menu = false }, containerColor = T.card) {
                    DropdownMenuItem({ Text("✨ 반 전체 초안 (ChatGPT·Gemini)") }, { menu = false; nav.go(Route.Draft(cls.uid)) })
                    DropdownMenuItem({ Text("학생 더하기 · 명단 붙여넣기") }, { menu = false; pasting = true })
                    DropdownMenuItem({ Text("이 반 지우기", color = T.coral) }, { menu = false; confirmDelete = true })
                }
            }
        }
        LazyColumn(Modifier.fillMaxSize().padding(horizontal = 18.dp), verticalArrangement = Arrangement.spacedBy(10.dp),
            contentPadding = PaddingValues(bottom = 24.dp)) {
            if (list.isEmpty()) item {
                Column(Modifier.fillMaxWidth().card(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    BigButton("📋 명단 붙여넣기", Modifier.fillMaxWidth()) { pasting = true }
                    Text("NEIS나 엑셀에서 번호·이름을 복사해 붙여넣으면 돼요.", fontSize = 13.sp, color = T.soft)
                }
            }
            val quiet = list.filter { (counts[it.uid] ?: 0) == 0 }
            if (list.isNotEmpty() && quiet.isNotEmpty() && quiet.size < list.size) item {
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(T.mint.copy(alpha = 0.1f)).padding(14.dp)) {
                    Text("🌱", fontSize = 20.sp); Spacer(Modifier.width(10.dp))
                    Column {
                        Text("아직 기록이 없는 친구 ${quiet.size}명", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = T.ink)
                        Text(quiet.take(6).joinToString(", ") { it.displayName } + (if (quiet.size > 6) " 외" else "") + " — 다음 수업에 한마디 남겨 볼까요?",
                            fontSize = 12.sp, color = T.soft)
                    }
                }
            }
            if (list.isNotEmpty()) item {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    SoftLabel("학생 ${list.size}명", Modifier.weight(1f))
                    ChipButton("✨ 반 전체 초안", T.lavender) { nav.go(Route.Draft(cls.uid)) }
                }
            }
            items(list, key = { it.uid }) { s ->
                var rowMenu by remember { mutableStateOf(false) }
                Row(Modifier.fillMaxWidth().card(12.dp).clickable { nav.go(Route.Stu(s.uid)) }, verticalAlignment = Alignment.CenterVertically) {
                    Text(s.number?.toString() ?: "–", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = T.soft, modifier = Modifier.width(28.dp))
                    Text(s.displayName, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = T.ink, modifier = Modifier.weight(1f))
                    CountBar(counts[s.uid] ?: 0, maxCount, kindColor(cls.kind))
                    Box {
                        IconButton({ rowMenu = true }, Modifier.size(32.dp)) { Icon(Icons.Filled.MoreVert, "학생 메뉴", tint = T.soft) }
                        DropdownMenu(rowMenu, { rowMenu = false }, containerColor = T.card) {
                            QuickTags.all.forEach { (e, t) -> DropdownMenuItem({ Text("$e $t") }, { rowMenu = false; DataStore.addNote(s, t) }) }
                            HorizontalDivider()
                            DropdownMenuItem({ Text("이름 고치기 · 합치기") }, { rowMenu = false; editing = s })
                            DropdownMenuItem({ Text("지우기", color = T.coral) }, { rowMenu = false; DataStore.deleteStudent(s) })
                        }
                    }
                }
            }
        }
    }
    if (pasting) RosterDialog(cls) { pasting = false }
    editing?.let { s -> StudentEditDialog(s, db, onDismiss = { editing = null }) }
    if (confirmDelete) ConfirmDialog("이 반을 지울까요?", "학생과 학생별 기록도 함께 지워져요. 녹음 원본은 그대로 남아요.", "지우기",
        onDismiss = { confirmDelete = false }) { DataStore.deleteClass(cls); nav.back() }
}

// ───────────────────────── 학생 ─────────────────────────

@Composable
fun StudentScreen(nav: Nav, uid: String) {
    val ctx = LocalContext.current
    val db by DataStore.db.collectAsStateWithLifecycle()
    val student = db.student(uid)?.takeIf { !it.deleted } ?: run { LaunchedEffect(Unit) { nav.back() }; return }
    val cls = db.classOf(student)
    val notes = db.notesOf(student)
    val drafts = db.draftsOf(student)
    var newNote by remember { mutableStateOf("") }
    var editingNote by remember { mutableStateOf<SNote?>(null) }
    var moving by remember { mutableStateOf<SNote?>(null) }
    var editingStudent by remember { mutableStateOf(false) }
    var menu by remember { mutableStateOf(false) }
    var promptCopied by remember { mutableStateOf(false) }
    val defaultArea = Areas.forKind(cls?.kind).firstOrNull() ?: "subject"

    Column(Modifier.fillMaxSize()) {
        BackBar(student.displayName, nav) {
            Box {
                IconButton({ menu = true }) { Icon(Icons.Filled.MoreVert, "학생 메뉴", tint = T.blue) }
                DropdownMenu(menu, { menu = false }, containerColor = T.card) {
                    DropdownMenuItem({ Text("이름·별칭 고치기 · 합치기") }, { menu = false; editingStudent = true })
                    DropdownMenuItem({ Text("기록 모두 복사") }, { menu = false
                        copyText(ctx, notes.reversed().joinToString("\n") { "[${it.date ?: ""}] ${it.content ?: ""}" }) })
                    DropdownMenuItem({ Text("PDF 한 장으로 내보내기") }, { menu = false
                        runCatching { shareFile(ctx, StudentPdf.make(ctx, student, cls, notes, drafts), "application/pdf", "학생 기록 PDF 보내기") }
                            .onFailure { android.widget.Toast.makeText(ctx, "PDF를 만들지 못했어요: ${it.message}", android.widget.Toast.LENGTH_SHORT).show() } })
                }
            }
        }
        LazyColumn(Modifier.fillMaxSize().padding(horizontal = 18.dp), verticalArrangement = Arrangement.spacedBy(14.dp),
            contentPadding = PaddingValues(bottom = 30.dp)) {
            item {
                Row(Modifier.fillMaxWidth().card(), verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(54.dp).clip(CircleShape).background(kindColor(cls?.kind)), contentAlignment = Alignment.Center) {
                        Text(student.displayName.takeLast(2), fontSize = 18.sp, fontWeight = FontWeight.ExtraBold, color = Color.White)
                    }
                    Spacer(Modifier.width(14.dp))
                    Column(Modifier.weight(1f)) {
                        Text(student.displayName, fontSize = 22.sp, fontWeight = FontWeight.Bold, color = T.ink)
                        Text(listOfNotNull(cls?.title, student.number?.let { "${it}번" }).joinToString(" · "), fontSize = 13.sp, color = T.soft)
                    }
                }
            }
            if (notes.isNotEmpty()) item {
                val month = notes.count { (it.date ?: "") >= isoDaysAgo(30) }
                val dates = notes.mapNotNull { it.date }.sorted()
                Column(Modifier.fillMaxWidth().card(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("🔎 한눈에 보기", fontSize = 15.sp, fontWeight = FontWeight.Bold, color = T.ink)
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Stat("${notes.size}", "모인 기록", T.blue, Modifier.weight(1f))
                        Stat("$month", "최근 30일", T.mint, Modifier.weight(1f))
                        Stat("${drafts.size}", "초안", T.lavender, Modifier.weight(1f))
                    }
                    if (dates.isNotEmpty()) Text("${friendlyDate(dates.first())}부터 · 마지막 기록 ${friendlyDate(dates.last())}", fontSize = 12.sp, color = T.soft)
                }
            }
            item {
                Column(Modifier.fillMaxWidth().card(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedTextField(newNote, { newNote = it }, Modifier.fillMaxWidth(), maxLines = 8, shape = RoundedCornerShape(14.dp),
                        placeholder = { Text("${student.displayName} 학생에 대해 한 줄 남기기") }, colors = fieldColors)
                    PhotoTextButtons { t -> newNote = listOf(newNote.trim(), t).filter { it.isNotEmpty() }.joinToString("\n") }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("키보드의 🎤로 말해도 돼요", fontSize = 12.sp, color = T.soft, modifier = Modifier.weight(1f))
                        ChipButton("담기", if (newNote.isBlank()) Color.Gray else T.blue, filled = true) {
                            if (newNote.isNotBlank()) { DataStore.addNote(student, newNote.trim()); newNote = "" }
                        }
                    }
                }
            }
            item {
                Column(Modifier.fillMaxWidth().card(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("톡 눌러 바로 담기", fontSize = 13.sp, fontWeight = FontWeight.Bold, color = T.soft)
                    QuickTagRow(student)
                }
            }
            if (drafts.isNotEmpty()) {
                item { SoftLabel("초안") }
                items(drafts, key = { it.uid }) { d -> DraftCard(d) }
            }
            if (notes.isNotEmpty()) item {
                Column(Modifier.fillMaxWidth().card(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("✨ 초안 도움 받기", fontSize = 15.sp, fontWeight = FontWeight.Bold, color = T.lavender, modifier = Modifier.weight(1f))
                        ChipButton(if (promptCopied) "✓ 복사됐어요" else "요청문 복사", T.lavender) {
                            copyText(ctx, ClassPrompt.forStudent(student, notes, defaultArea), "요청문을 복사했어요"); promptCopied = true
                        }
                    }
                    if (promptCopied) AiOpenRow()
                    Text("기록을 모은 ${Areas.name(defaultArea)} 초안 요청문을 복사해요. 이름은 ‘OO’으로 바꿔 넣으니 ChatGPT·Gemini에 붙여넣고, 나온 글은 꼭 다듬어 주세요. 생기부 내용의 책임은 선생님께 있어요.",
                        fontSize = 12.sp, color = T.soft)
                }
            }
            item { SoftLabel(if (notes.isEmpty()) "아직 기록이 없어요 🌱" else "관찰 기록 ${notes.size}개") }
            items(notes, key = { it.uid }) { n -> NoteCard(n, cls, db, onEdit = { editingNote = n }, onMove = { moving = n }) }
        }
    }
    editingNote?.let { n -> NoteEditDialog(n) { editingNote = null } }
    moving?.let { n -> StudentPicker("누구의 기록인가요?", db.candidates(n), n.studentUid, db, onDismiss = { moving = null }) { s -> DataStore.moveNote(n, s) } }
    if (editingStudent) StudentEditDialog(student, db, onDismiss = { editingStudent = false }, onMerged = { nav.back() })
}

@Composable
private fun Stat(v: String, label: String, color: Color, modifier: Modifier) {
    Column(modifier.clip(RoundedCornerShape(14.dp)).background(color.copy(alpha = 0.1f)).padding(vertical = 10.dp),
        horizontalAlignment = Alignment.CenterHorizontally) {
        Text(v, fontSize = 22.sp, fontWeight = FontWeight.ExtraBold, color = color)
        Text(label, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = T.soft)
    }
}

@Composable
private fun NoteCard(n: SNote, cls: SClass?, db: DB, onEdit: () -> Unit, onMove: () -> Unit) {
    val ctx = LocalContext.current
    var menu by remember { mutableStateOf(false) }
    var areaMenu by remember { mutableStateOf(false) }
    val area = if (!n.area.isNullOrEmpty()) n.area else Areas.forKind(cls?.kind).firstOrNull()
    Column(Modifier.fillMaxWidth().card(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(friendlyDate(n.date), fontSize = 12.sp, fontWeight = FontWeight.Bold, color = T.soft)
            if (db.isUnsure(n)) Pill("❓ 동명이인 확인", Color(0xFFD9A400), onMove)
            if (n.kind == "상담") Pill("상담", T.lavender)
            Text(Areas.name(area), fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = T.soft)
            Spacer(Modifier.weight(1f))
            if ((n.source ?: "").endsWith(".m4a")) Text("🎙️", fontSize = 11.sp)
            Box {
                IconButton({ menu = true }, Modifier.size(30.dp)) { Icon(Icons.Filled.MoreHoriz, "기록 메뉴", tint = T.soft) }
                DropdownMenu(menu, { menu = false }, containerColor = T.card) {
                    DropdownMenuItem({ Text("고치기") }, { menu = false; onEdit() })
                    DropdownMenuItem({ Text("다른 학생으로 옮기기") }, { menu = false; onMove() })
                    DropdownMenuItem({ Text("영역 바꾸기 ›") }, { menu = false; areaMenu = true })
                    if (db.isUnsure(n)) DropdownMenuItem({ Text("이 학생이 맞아요") }, { menu = false; DataStore.confirmNote(n) })
                    DropdownMenuItem({ Text("복사") }, { menu = false; copyText(ctx, n.content ?: "") })
                    DropdownMenuItem({ Text("지우기", color = T.coral) }, { menu = false; DataStore.deleteNote(n) })
                }
                DropdownMenu(areaMenu, { areaMenu = false }, containerColor = T.card) {
                    Areas.all.forEach { a ->
                        DropdownMenuItem({ Text((if (a.id == area) "✓ " else "   ") + a.name) }, { areaMenu = false; DataStore.setArea(n, a.id) })
                    }
                }
            }
        }
        Text(n.content ?: "", fontSize = 15.sp, color = T.ink)
    }
}

@Composable
private fun DraftCard(d: SDraft) {
    val ctx = LocalContext.current
    val text = d.content ?: ""
    val limit = Areas.limit(d.area)
    var confirm by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth().card(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(Areas.name(d.area), fontSize = 14.sp, fontWeight = FontWeight.Bold, color = T.lavender, modifier = Modifier.weight(1f))
            ByteBadge(text, limit)
            IconButton({ copyText(ctx, text) }, Modifier.size(32.dp)) { Icon(Icons.Filled.ContentCopy, "복사", tint = T.soft, modifier = Modifier.size(18.dp)) }
            IconButton({ confirm = true }, Modifier.size(32.dp)) { Icon(Icons.Filled.DeleteOutline, "초안 지우기", tint = T.soft, modifier = Modifier.size(18.dp)) }
        }
        Text(text, fontSize = 15.sp, color = T.ink)
        CheckList(text, limit)
    }
    if (confirm) ConfirmDialog("초안을 지울까요?", "관찰 기록은 그대로 남아요.", "지우기", onDismiss = { confirm = false }) { DataStore.deleteDraft(d) }
}

@Composable
private fun NoteEditDialog(n: SNote, onDismiss: () -> Unit) {
    var text by remember { mutableStateOf(n.content ?: "") }
    AlertDialog(onDismissRequest = onDismiss, containerColor = T.card, title = { Text("기록 고치기") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(text, { text = it }, Modifier.fillMaxWidth().heightIn(min = 140.dp), shape = RoundedCornerShape(14.dp), colors = fieldColors)
                Text("있었던 일 그대로 짧게 고쳐 주세요. 초안은 이 기록을 바탕으로 만들어져요 ✍️ (${text.length}자)", fontSize = 12.sp, color = T.soft)
            }
        },
        confirmButton = { TextButton({ DataStore.editNote(n, text.trim()); onDismiss() }, enabled = text.isNotBlank()) { Text("저장") } },
        dismissButton = { TextButton(onDismiss) { Text("취소") } })
}

// ───────────────────────── 반 만들기 · 명단 · 학생 고치기 ─────────────────────────

@Composable
fun AddClassDialog(onDismiss: () -> Unit) {
    var kind by remember { mutableStateOf("교과") }
    var grade by remember { mutableIntStateOf(1) }
    var classNo by remember { mutableIntStateOf(1) }
    var subject by remember { mutableStateOf("") }
    var names by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = onDismiss, containerColor = T.card, title = { Text("반 만들기") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("교과", "담임", "동아리", "기타").forEach { k -> ChipButton(k, kindColor(k), filled = kind == k) { kind = k } }
                }
                if (kind != "동아리") {
                    Stepper("${grade}학년", { if (grade > 1) grade-- }, { if (grade < 6) grade++ })
                    Stepper("${classNo}반", { if (classNo > 1) classNo-- }, { if (classNo < 20) classNo++ })
                }
                if (kind != "담임") OutlinedTextField(subject, { subject = it }, singleLine = true, shape = RoundedCornerShape(14.dp), colors = fieldColors,
                    placeholder = { Text(if (kind == "동아리") "동아리 이름" else "과목 (예: 국어)") })
                Text("학생 명단 (나중에 넣어도 돼요)", fontSize = 13.sp, fontWeight = FontWeight.Bold, color = T.soft)
                OutlinedTextField(names, { names = it }, Modifier.fillMaxWidth().heightIn(min = 110.dp), shape = RoundedCornerShape(14.dp),
                    colors = fieldColors, placeholder = { Text("1 김민수\n2 이서연\n3 박지훈") })
                Text("NEIS·엑셀에서 번호와 이름을 복사해 붙여넣으세요. 한 줄에 한 명, 번호는 없어도 돼요.", fontSize = 12.sp, color = T.soft)
            }
        },
        confirmButton = {
            TextButton({
                val c = DataStore.addClass(if (kind == "동아리") null else grade, if (kind == "동아리") null else classNo,
                    if (kind == "담임") "" else subject.trim(), kind)
                if (names.isNotBlank()) DataStore.addStudents(names, c)
                onDismiss()
            }, enabled = !(kind == "동아리" && subject.isBlank())) { Text("만들기") }
        },
        dismissButton = { TextButton(onDismiss) { Text("취소") } })
}

@Composable
private fun Stepper(label: String, minus: () -> Unit, plus: () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(label, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = T.ink, modifier = Modifier.weight(1f))
        ChipButton("－", T.blue, onClick = minus); Spacer(Modifier.width(8.dp)); ChipButton("＋", T.blue, onClick = plus)
    }
}

@Composable
fun RosterDialog(cls: SClass, onDismiss: () -> Unit) {
    val ctx = LocalContext.current
    var names by remember { mutableStateOf("") }
    var result by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = onDismiss, containerColor = T.card, title = { Text("${cls.title} 명단") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(names, { names = it }, Modifier.fillMaxWidth().heightIn(min = 160.dp), shape = RoundedCornerShape(14.dp),
                    colors = fieldColors, placeholder = { Text("1 김민수\n2 이서연\n3 박지훈") })
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("한 줄에 한 명. 이미 있는 이름은 건너뛰어요.", fontSize = 12.sp, color = T.soft, modifier = Modifier.weight(1f))
                    ChipButton("붙여넣기") { names = pasteText(ctx) }
                }
                if (result.isNotEmpty()) Text(result, fontSize = 13.sp, color = T.mint)
            }
        },
        confirmButton = { TextButton({ DataStore.addStudents(names, cls); onDismiss() }, enabled = names.isNotBlank()) { Text("넣기") } },
        dismissButton = { TextButton(onDismiss) { Text("취소") } })
}

@Composable
fun StudentEditDialog(student: SStudent, db: DB, onDismiss: () -> Unit, onMerged: () -> Unit = {}) {
    var name by remember { mutableStateOf(student.displayName) }
    var number by remember { mutableStateOf(student.number?.toString() ?: "") }
    var aliases by remember { mutableStateOf(student.aliases ?: "") }
    var merging by remember { mutableStateOf(false) }
    var mergeTarget by remember { mutableStateOf<SStudent?>(null) }
    AlertDialog(onDismissRequest = onDismiss, containerColor = T.card, title = { Text("학생 정보") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(name, { name = it }, label = { Text("이름") }, singleLine = true, shape = RoundedCornerShape(14.dp), colors = fieldColors)
                OutlinedTextField(number, { number = it.filter(Char::isDigit) }, label = { Text("번호") }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), shape = RoundedCornerShape(14.dp), colors = fieldColors)
                OutlinedTextField(aliases, { aliases = it }, label = { Text("다르게 불리는 이름") }, placeholder = { Text("예) 민수, 김민쑤") },
                    singleLine = true, shape = RoundedCornerShape(14.dp), colors = fieldColors)
                Text("별명이나 받아쓰기가 자주 잘못 적는 이름을 쉼표로 적어 두면, 그 말이 나와도 이 학생 기록으로 담아요.", fontSize = 12.sp, color = T.soft)
                ChipButton("👥 다른 학생과 합치기", T.lavender) { merging = true }
                Text("같은 학생이 두 번 들어갔을 때 써요. 이 학생의 기록이 고른 학생에게 옮겨 가고, 이 이름은 별칭으로 남아요.", fontSize = 12.sp, color = T.soft)
            }
        },
        confirmButton = { TextButton({ DataStore.updateStudent(student, name, number.toIntOrNull(), aliases); onDismiss() },
            enabled = name.trim().length >= 2) { Text("저장") } },
        dismissButton = { TextButton(onDismiss) { Text("취소") } })
    if (merging) StudentPicker("어느 학생과 합칠까요?", db.sameName(student), student.uid, db, onDismiss = { merging = false }) { s ->
        if (s.uid != student.uid) mergeTarget = s
    }
    mergeTarget?.let { t ->
        ConfirmDialog("${student.displayName} → ${t.displayName}", "기록을 모두 옮기고 ‘${student.displayName}’ 항목은 없앨까요?", "합치기",
            onDismiss = { mergeTarget = null }) { DataStore.mergeStudent(student, t); onDismiss(); onMerged() }
    }
}

/** 학생 고르기: 검색 + 반별 목록. 추천(동명이인 후보)이 있으면 맨 위에. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StudentPicker(title: String, suggested: List<SStudent>, current: String?, db: DB, onDismiss: () -> Unit, onPick: (SStudent) -> Unit) {
    var query by remember { mutableStateOf("") }
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = T.card) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 18.dp)) {
            Text(title, fontSize = 18.sp, fontWeight = FontWeight.Bold, color = T.ink)
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth(), singleLine = true, shape = CircleShape,
                leadingIcon = { Icon(Icons.Filled.Search, null, tint = T.soft) }, placeholder = { Text("이름 찾기") }, colors = fieldColors)
            LazyColumn(Modifier.fillMaxWidth().heightIn(max = 480.dp), contentPadding = PaddingValues(vertical = 8.dp)) {
                if (suggested.isNotEmpty() && query.isEmpty()) {
                    item { SoftLabel("이 중 누구인가요?", Modifier.padding(top = 8.dp)) }
                    items(suggested, key = { "s" + it.uid }) { s -> PickRow(s, true, current, db) { onPick(s); onDismiss() } }
                }
                db.activeClasses.forEach { c ->
                    val list = db.studentsIn(c).filter { query.isEmpty() || it.displayName.contains(query) || (it.aliases ?: "").contains(query) }
                    if (list.isNotEmpty()) {
                        item(key = "h" + c.uid) { SoftLabel(c.title, Modifier.padding(top = 10.dp)) }
                        items(list, key = { c.uid + it.uid }) { s -> PickRow(s, false, current, db) { onPick(s); onDismiss() } }
                    }
                }
            }
            Spacer(Modifier.height(16.dp))
        }
    }
}

@Composable
private fun PickRow(s: SStudent, showClass: Boolean, current: String?, db: DB, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).clickable(onClick = onClick).padding(vertical = 10.dp, horizontal = 6.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text(s.number?.toString() ?: "–", fontSize = 13.sp, fontWeight = FontWeight.Bold, color = T.soft, modifier = Modifier.width(28.dp))
        Text(s.displayName, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = T.ink)
        if (showClass || db.sameName(s).isNotEmpty()) db.classOf(s)?.let { Spacer(Modifier.width(8.dp)); Text(it.title, fontSize = 12.sp, color = T.soft) }
        Spacer(Modifier.weight(1f))
        if (s.uid == current) Icon(Icons.Filled.Check, null, tint = T.blue)
    }
}
