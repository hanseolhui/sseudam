package kr.sseudam.app

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle

/**
 * 반 전체 초안 — ChatGPT·Gemini(선생님 구독)로 한 번에: 요청문 복사 → 답 붙여넣기 → 학생별 초안 저장.
 * 이름은 '학생1, 학생2…'로 가려서 보내고, 돌아온 답에서 다시 학생을 찾는다. 서버 비용 없음.
 */
@Composable
fun ClassDraftScreen(nav: Nav, classUid: String) {
    val ctx = LocalContext.current
    val db by DataStore.db.collectAsStateWithLifecycle()
    val cls = db.cls(classUid) ?: run { LaunchedEffect(Unit) { nav.back() }; return }
    val areas = Areas.forKind(cls.kind)
    var area by remember { mutableStateOf(areas.firstOrNull() ?: "subject") }
    var copied by remember { mutableStateOf(false) }
    var answer by remember { mutableStateOf("") }
    var parsed by remember { mutableStateOf<List<Pair<ClassPrompt.Item, String>>>(emptyList()) }
    var saved by remember { mutableStateOf(false) }
    val items = ClassPrompt.items(cls, db)

    Column(Modifier.fillMaxSize()) {
        BackBar("반 전체 초안", nav)
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 18.dp, vertical = 6.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Column(Modifier.fillMaxWidth().card(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("① 요청문 복사", fontSize = 17.sp, fontWeight = FontWeight.Bold, color = T.ink)
                if (areas.size > 1) Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    areas.forEach { a -> ChipButton(Areas.name(a), T.lavender, filled = area == a) { area = a; copied = false } }
                }
                Text("기록이 있는 학생 ${items.size}명의 기록을 한 번에 담아요. 이름은 ‘학생1, 학생2…’로 가려서 복사돼요.", fontSize = 13.sp, color = T.soft)
                BigButton(if (copied) "✓ 복사됐어요!" else "요청문 복사하기", Modifier.fillMaxWidth(), enabled = items.isNotEmpty()) {
                    copyText(ctx, ClassPrompt.build(items, area), null); copied = true
                }
                if (copied) {
                    AiOpenRow()
                    Text("새 대화에 붙여넣고 보내세요. 학생이 많으면 ‘계속’이라고 하면 이어서 써 줘요.", fontSize = 12.sp, color = T.soft)
                } else {
                    Text("복사하면 ChatGPT·Gemini 앱을 바로 여는 버튼이 나와요.", fontSize = 12.sp, color = T.soft)
                }
            }
            Column(Modifier.fillMaxWidth().card(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("② 답 붙여넣기", fontSize = 17.sp, fontWeight = FontWeight.Bold, color = T.ink)
                Text("AI가 쓴 답을 통째로 복사해 와서 아래 버튼을 누르면, 학생마다 초안으로 나눠 담아요.", fontSize = 13.sp, color = T.soft)
                BigButton("복사한 답 붙여넣기", Modifier.fillMaxWidth(), color = T.mint) {
                    answer = pasteText(ctx); parsed = ClassPrompt.parse(answer, items); saved = false
                }
                if (answer.isNotEmpty() && parsed.isEmpty())
                    Text("‘[학생1]’ 같은 머리말을 찾지 못했어요. AI 답을 처음부터 끝까지 복사했는지 확인해 주세요.", fontSize = 12.sp,
                        fontWeight = FontWeight.SemiBold, color = T.coral)
            }
            if (parsed.isNotEmpty()) Column(Modifier.fillMaxWidth().card(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("${parsed.size}명 초안 확인", fontSize = 16.sp, fontWeight = FontWeight.Bold, color = T.ink, modifier = Modifier.weight(1f))
                    ChipButton(if (saved) "✓ 저장했어요" else "모두 저장", if (saved) T.mint else T.blue, filled = true) {
                        if (!saved) { parsed.forEach { (item, t) -> DataStore.addDraft(item.student, area, t) }; saved = true }
                    }
                }
                parsed.forEach { (item, t) ->
                    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(T.bg).padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            StudentChip(item.student, db); Spacer(Modifier.weight(1f)); ByteBadge(t, Areas.limit(area))
                        }
                        Text(t, fontSize = 14.sp, color = T.ink)
                        CheckList(t, Areas.limit(area))
                    }
                }
                Text("AI 초안은 다듬기 보조예요. 내용과 책임은 선생님께 있으니 꼭 읽고 고쳐 주세요.", fontSize = 12.sp, color = T.soft)
            }
            Spacer(Modifier.height(20.dp))
        }
    }
}
