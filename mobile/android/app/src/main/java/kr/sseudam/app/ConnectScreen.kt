package kr.sseudam.app

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

@Composable
fun ConnectScreen() {
    val ctx = LocalContext.current
    val paired by Store.paired.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    var result by remember { mutableStateOf("") }
    var manual by remember { mutableStateOf(false) }
    var code by remember { mutableStateOf("") }
    var syncMsg by remember { mutableStateOf("") }

    fun test() = scope.launch {
        result = "확인 중…"
        result = try {
            if (Relay.paired()) {
                val n = withContext(Dispatchers.IO) { Relay.syncDocs() }
                UploadWorker.enqueue(ctx)
                "✓ 연결되었어요" + if (n > 0) " · 컴퓨터 기록 ${n}개를 받았어요" else ""
            } else {
                withContext(Dispatchers.IO) { UploadWorker.post(Store.googleUrl(), JSONObject().put("action", "ping_phone").put("token", Store.googleToken())) }
                "✓ 연결되었어요"
            }
        } catch (e: Exception) { e.message ?: "연결 실패" }
    }
    fun handle(text: String) {
        Relay.parse(text)?.let { Store.pairRelay(it); UploadWorker.schedulePeriodic(ctx); test(); return }   // 새 QR 연동 (암호화)
        val p = Store.parsePairing(text)                                                                     // 예전 구글 드라이브 연결
        if (p == null) result = "쓰담 연결 QR이 아니에요." else { Store.pair(p.first, p.second, p.third); test() }
    }
    val scan = rememberLauncherForActivityResult(ScanContract()) { r -> r.contents?.let(::handle) }
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        syncMsg = try {
            val text = ctx.contentResolver.openInputStream(uri)!!.use { it.bufferedReader().readText() }
            val n = DataStore.importDoc(text)
            if (n == 0) "✓ 이미 같은 내용이에요" else "✓ 기록 ${n}개를 합쳤어요"
        } catch (e: Exception) { "가져오지 못했어요: ${e.message ?: "쓰담 기록 파일인지 확인해 주세요"}" }
    }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        ScreenTitle("연결")
        Column(Modifier.fillMaxWidth().card(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("🖥️ 컴퓨터와 연결", fontWeight = FontWeight.Bold, color = T.ink, fontSize = 16.sp)
            if (paired) {
                Text("연결됨 · ${Store.teacherName().ifEmpty { if (Relay.paired()) "내 컴퓨터" else "내 구글 드라이브" }}" + if (Relay.paired()) " 🔒" else "",
                    color = T.mint, fontWeight = FontWeight.SemiBold)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ChipButton("연결 확인") { test() }
                    ChipButton("연결 끊기", T.coral) { Store.unpair(); result = "" }
                }
            } else {
                BigButton("📷 컴퓨터 화면의 QR 찍기", Modifier.fillMaxWidth()) {
                    scan.launch(ScanOptions().setPrompt("컴퓨터 화면의 QR을 비춰 주세요").setBeepEnabled(false).setOrientationLocked(true))
                }
                TextButton({ manual = true }) { Text("연결 코드 붙여넣기") }
            }
            if (result.isNotEmpty()) Text(result, fontSize = 13.sp, color = if (result.startsWith("✓")) T.mint else T.coral)
            Text("컴퓨터(맥·윈도우)의 쓰담 → 설정 → 📱 휴대폰 → QR을 찍으세요. 녹음·한 줄 메모·학생 기록이 저절로 오가요. 이 폰과 그 컴퓨터만 아는 열쇠로 암호화돼서, 중간 서버는 내용을 볼 수 없어요.",
                fontSize = 12.sp, color = T.soft)
            Text("📝 한 줄 메모: 홈의 ‘한 줄로 남기기’에 쓰거나 🎤로 말하면 글자로 바뀌어, 녹음처럼 연결된 컴퓨터로 같이 가요. 따로 설정할 건 없어요.",
                fontSize = 12.sp, color = T.ink)
            Text("🎙 다른 녹음 앱(갤럭시 녹음 등)으로 녹음했다면: 그 앱에서 녹음 → 공유 → ‘쓰담’을 고르면 쓰담에 담기고 컴퓨터로 가요.",
                fontSize = 12.sp, color = T.ink)
        }

        // 쓰담 플러스: 계정 · 구독 (컴퓨터 쓰담의 AI 정리·초안)
        PlusCard()

        // 학생 기록(글) 주고받기 — 구글 연결은 '올리기 전용'이라 파일로 옮긴다
        Column(Modifier.fillMaxWidth().card(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("📁 학생 기록 파일 (연결 없이 옮길 때)", fontWeight = FontWeight.Bold, color = T.ink, fontSize = 16.sp)
            Text("위에서 컴퓨터와 연결했다면 학생 기록은 저절로 맞춰져서 이건 필요 없어요. 연결 없이 옮길 때: 반·학생 명단·관찰 기록·초안을 한 파일(.json)로 내보내거나, 맥·아이폰·다른 폰에서 내보낸 파일을 가져와 합쳐요. 녹음은 빠지고 글만 들어가요. 같은 기록은 나중에 고친 쪽이 남아요.",
                fontSize = 12.sp, color = T.soft)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ChipButton("내보내기", T.blue, filled = true) {
                    runCatching { shareFile(ctx, DataStore.exportFile(), "application/json", "쓰담 기록 파일 보내기") }
                        .onFailure { syncMsg = "내보내지 못했어요: ${it.message}" }
                }
                ChipButton("가져오기", T.lavender) { pick.launch(arrayOf("application/json", "text/plain", "application/octet-stream")) }
                ChipButton("엑셀(CSV)", T.mint) { shareFile(ctx, DataStore.exportCSV(), "text/csv", "학생 기록 CSV") }
            }
            if (syncMsg.isNotEmpty()) Text(syncMsg, fontSize = 13.sp, color = if (syncMsg.startsWith("✓")) T.mint else T.coral)
            Text("💡 학생 기록 파일은 학생 이름이 들어 있어요. 내 구글 드라이브나 나에게 보내기처럼 선생님만 볼 수 있는 곳으로 옮겨 주세요.",
                fontSize = 12.sp, color = T.soft)
        }

        // 내 AI 연결 — API 키 없이: 쓰담은 요청문만 만들고(이름은 OO·학생N으로 가림), 선생님의 ChatGPT·Gemini 앱을 연다
        Column(Modifier.fillMaxWidth().card(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("✨ 내 AI 연결 (ChatGPT · Gemini)", fontWeight = FontWeight.Bold, color = T.ink, fontSize = 16.sp)
            Text("학생 화면의 ‘요청문 복사’나 반 화면의 ‘반 전체 초안’을 누르면 이름을 ‘OO·학생1’로 가린 요청문이 복사돼요. 아래 버튼으로 선생님이 쓰는 AI 앱을 열어 붙여넣으세요. 키 입력이 필요 없어요.",
                fontSize = 12.sp, color = T.soft)
            AiOpenRow()
        }

        UpdateSettings()

        Column(Modifier.fillMaxWidth().card(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("🗂️ 녹음 보관", fontWeight = FontWeight.Bold, color = T.ink)
            Text("녹음은 선생님이 지우기 전까지 휴대폰에 그대로 보관돼요. 연결된 컴퓨터의 쓰담에도 원본이 학기말 이후까지 보관돼요.", fontSize = 13.sp, color = T.soft)
        }
        TextButton({ openUrl(ctx, "https://apps.seoriarts.com/sseudam") }) { Text("컴퓨터용 쓰담 설치·사용법") }
        TextButton({ openUrl(ctx, "https://apps.seoriarts.com/sseudam-privacy") }) { Text("개인정보 처리방침") }
        Spacer(Modifier.height(20.dp))
    }
    if (manual) AlertDialog(onDismissRequest = { manual = false }, containerColor = T.card, title = { Text("연결 코드") },
        text = { OutlinedTextField(code, { code = it }, placeholder = { Text("sseudam://pair?…") }) },
        confirmButton = { TextButton({ manual = false; handle(code); code = "" }) { Text("연결") } },
        dismissButton = { TextButton({ manual = false }) { Text("취소") } })
}
