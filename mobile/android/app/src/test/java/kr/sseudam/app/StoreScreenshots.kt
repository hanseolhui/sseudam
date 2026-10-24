package kr.sseudam.app

import android.app.Application
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.performScrollTo
import android.content.ClipData
import android.content.ClipboardManager
import androidx.test.core.app.ApplicationProvider
import androidx.work.testing.WorkManagerTestInitHelper
import com.github.takahirom.roborazzi.captureRoboImage
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

/**
 * 플레이 스토어 스크린샷 (가상의 학생 이름만 사용). 평소에는 건너뛰고,
 *   ./gradlew :app:recordStoreScreenshots
 * 로 돌리면 mobile/android/store/screenshots/ 에 1080×1920(9:16) PNG를 만든다.
 * (플레이 스크린샷은 긴 변이 짧은 변의 2배를 넘으면 안 돼서 1080×2340 대신 9:16)
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [35], qualifiers = "w360dp-h640dp-xxhdpi")
class StoreScreenshots {
    @get:Rule val rule = createAndroidComposeRule<ComponentActivity>()

    private val day = 86_400_000L

    companion object {
        /** AI가 돌려준 답 예시 (이름은 가려진 채로 옴) */
        const val SAMPLE_ANSWER = """[학생1]
모둠 토론에서 친구들의 의견을 차례로 정리하고 공통점을 찾아 발표하는 등 협력적 의사소통 능력이 돋보임. 시 감상 활동에서 비유 표현을 자신의 경험과 연결해 설명함.

[학생2]
발표 자료를 꼼꼼하게 준비하고 모둠원에게 역할을 나누어 협업을 이끎. 논설문 쓰기에서 근거 세 가지를 들어 주장을 논리적으로 뒷받침함.

[학생3]
질문 만들기 활동에서 글의 숨은 뜻을 묻는 질문을 만들어 친구들의 호응을 얻음. 실험 보고서를 끝까지 꼼꼼하게 고쳐 쓰는 성실함을 보임."""
    }

    private fun seed(): Triple<SClass, List<SStudent>, String> {
        val ctx = ApplicationProvider.getApplicationContext<Application>()
        WorkManagerTestInitHelper.initializeTestWorkManager(ctx)
        Store.init(ctx)
        val cls = DataStore.addClass(2, 3, "국어", "교과")
        DataStore.addStudents("1 김민수\n2 이서연\n3 박지훈", cls)
        val db = DataStore.db.value
        val (minsu, seoyeon, jihun) = db.studentsIn(cls).sortedBy { it.number ?: 0 }.let { Triple(it[0], it[1], it[2]) }
        val now = System.currentTimeMillis()
        DataStore.addNote(minsu, "모둠 토론에서 친구들의 의견을 차례로 정리해 칠판에 적고, 서로 다른 생각의 공통점을 찾아 발표함.", now - 20 * day)
        DataStore.addNote(minsu, "시 감상 활동에서 비유 표현을 찾아 자신의 경험과 연결해 설명함.", now - 12 * day)
        DataStore.addNote(minsu, "독서 기록장에 읽은 책의 인상 깊은 문장과 그 까닭을 꾸준히 적어 옴.", now - 5 * day)
        DataStore.addNote(seoyeon, "발표 자료를 꼼꼼하게 준비해 와 모둠원에게 역할을 나누어 줌.", now - 9 * day)
        DataStore.addNote(seoyeon, "논설문 쓰기에서 근거 세 가지를 들어 주장을 뒷받침함.", now - 3 * day)
        DataStore.addNote(jihun, "질문 만들기 활동에서 글의 숨은 뜻을 묻는 질문을 만들어 친구들의 호응을 얻음.", now - 7 * day)
        DataStore.addDraft(minsu, "subject",
            "모둠 토론에서 친구들의 의견을 차례로 정리하고 공통점을 찾아 발표하는 등 협력적 의사소통 능력이 돋보임. " +
                "시 감상 활동에서 비유 표현을 자신의 경험과 연결해 설명하며 작품을 깊이 있게 이해함. " +
                "독서 기록장에 인상 깊은 문장과 그 까닭을 꾸준히 기록하는 성실한 독서 습관을 지님.")
        // 기록함: 오늘 남긴 메모 한 줄 → 폰에서 학생별로 나눔
        val memo = Store.addText("2학년 3반 김민수, 친구 의견을 모아 멋지게 발표함. 이서연은 발표 자료를 정리해 모둠원에게 나눠 줌. 박지훈 질문이 날카로웠음.")!!
        Store.addText("박지훈 실험 보고서를 끝까지 꼼꼼하게 고쳐 씀.", at = now - day)
        val students = listOf(minsu, seoyeon, jihun)
        return Triple(cls, students, memo.id)
    }

    @Test
    fun capture() {
        assumeTrue("스크린샷은 recordStoreScreenshots 로만", System.getProperty("sseudam.screenshots") == "true")
        val out = File(System.getProperty("sseudam.screenshotDir") ?: "build/store-screenshots").apply { mkdirs() }
        val (cls, students, memoId) = seed()

        data class Shot(val file: String, val tab: Int, val route: Route?)
        val shots = listOf(
            Shot("01_담기.png", 0, null),
            Shot("02_기록함_조각.png", 1, Route.Entry(memoId)),
            Shot("03_학생.png", 2, Route.Cls(cls.uid)),
            Shot("04_학생_상세.png", 2, Route.Stu(students[0].uid)),
            Shot("05_반전체_초안.png", 2, Route.Draft(cls.uid)),
            Shot("06_연결.png", 3, null),
        )
        var current by mutableStateOf(shots.first())
        rule.mainClock.autoAdvance = false   // 마스코트 흔들림(무한 애니메이션) 때문에 시계를 직접 돌림
        rule.setContent {
            MaterialTheme(colorScheme = lightColorScheme(primary = T.blue, secondary = T.lavender, background = T.bg,
                surface = T.card, surfaceContainerLow = T.card, surfaceContainer = T.card, onSurface = T.ink)) {
                key(current) { App(current.tab, current.route) }
            }
        }
        // 스크롤은 애니메이션이라 그동안만 시계를 자동으로 (이 화면들엔 무한 애니메이션이 없음)
        fun scrollTo(text: String) {
            rule.mainClock.autoAdvance = true
            rule.onNodeWithText(text, substring = true).performScrollTo()
            rule.waitForIdle()
            rule.mainClock.autoAdvance = false
        }
        for (s in shots) {
            rule.runOnUiThread { current = s }
            rule.waitForIdle()
            repeat(5) { rule.mainClock.advanceTimeByFrame() }
            rule.mainClock.advanceTimeBy(1600)
            rule.waitForIdle()
            if (s.tab == 3) scrollTo("쓰담 플러스 · 준비 중")   // 연결: 내 AI 연결 · 쓰담 플러스(준비 중)
            if (s.route is Route.Draft) {
                // ① 요청문 복사 → ChatGPT·Gemini 버튼, ② AI 답(예시) 붙여넣기 → 학생별 초안
                rule.onNodeWithText("요청문 복사하기").performSemanticsAction(SemanticsActions.OnClick)
                rule.mainClock.advanceTimeBy(500); rule.waitForIdle()
                val cm = rule.activity.getSystemService(ClipboardManager::class.java)
                rule.runOnUiThread { cm.setPrimaryClip(ClipData.newPlainText("ai", SAMPLE_ANSWER)) }
                rule.onNodeWithText("복사한 답 붙여넣기").performSemanticsAction(SemanticsActions.OnClick)
                rule.mainClock.advanceTimeBy(800); rule.waitForIdle()
                scrollTo("AI 초안은 다듬기 보조예요")
            }
            rule.mainClock.advanceTimeBy(400); rule.waitForIdle()
            rule.onRoot().captureRoboImage(File(out, s.file).absolutePath)
        }
    }
}
