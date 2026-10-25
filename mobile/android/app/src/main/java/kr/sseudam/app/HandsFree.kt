package kr.sseudam.app

import android.Manifest
import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.compose.currentStateAsState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlin.math.ceil
import kotlin.math.log10

/*
 * '손 없이 녹음' — 아이폰과 같은 사양.
 * - 시작: "헤이 구글, 쓰담에서 녹음 시작"(앱 기능 열기) · 앱 아이콘 길게 눌러 '녹음 시작' · 폰을 얼굴 가까이(근접 센서, 설정에서 켬)
 * - 끝: 말을 멈추면 저절로 (EndDetector) · 근접 센서로 시작했으면 폰을 떼면 · 확인 창 없이 바로 담는다
 * - 마이크는 녹음할 때만 켠다 (상시 듣기 없음). 버튼으로 시작한 녹음에는 적용하지 않는다.
 * - '녹음 끝' 말로 끝내기는 녹음 중 SpeechRecognizer 를 함께 못 써서 안드로이드에는 없다.
 */

/** 말을 멈추면 저절로 끝내는 판정 (0.1초마다 소리 크기 하나). 안드로이드와 상관없는 순수 코드 → HandsFreeTest */
class EndDetector(
    var stopDelayMs: Long,
    private val frameMs: Int = 100,
    calibMs: Int = 500,
    attackMs: Int = 300,
    private val noSpeechMs: Long = 8000,
    private val margin: Float = 12f,
    private val absMin: Float = -48f,
) {
    private val calibFrames = (calibMs / frameMs).coerceAtLeast(1)
    private val attackFrames = ceil(attackMs / frameMs.toDouble()).toInt().coerceAtLeast(1)
    private var frames = 0
    private var calibMin = Float.MAX_VALUE
    /** 바닥 소음 = 처음 0.5초 중 가장 조용한 값 (첫 값 0 같은 무음 읽기는 뺌) */
    var floor: Float? = null; private set
    /** 문턱 위가 0.3초 이어지면 '말함' */
    var spoke = false; private set
    private var above = 0
    private var silence = 0

    val threshold: Float get() = maxOf((floor ?: -100f) + margin, absMin)

    /** true = 이제 녹음을 끝낼 때 */
    fun feed(db: Float): Boolean {
        frames++
        if (frames <= calibFrames) {
            if (db > -99f) calibMin = minOf(calibMin, db)
            if (frames == calibFrames && calibMin != Float.MAX_VALUE) floor = calibMin
            return false
        }
        val th = threshold
        if (!spoke) {
            if (db > th) above++ else above = 0
            if (above >= attackFrames) { spoke = true; return false }
            return frames.toLong() * frameMs >= noSpeechMs   // 처음 8초 동안 말이 없으면 그냥 끝
        }
        // 말한 뒤: (문턱 − 3dB) 아래가 이어지면 조용함으로 쌓고, 문턱을 넘으면 0으로
        if (db > th) silence = 0 else if (db < th - 3f) silence++
        return silence.toLong() * frameMs >= stopDelayMs
    }

    companion object {
        /** MediaRecorder.getMaxAmplitude(0~32767) → dBFS */
        fun dbfs(amp: Int): Float = if (amp <= 0) -100f else (20 * log10(amp / 32767.0)).toFloat().coerceAtLeast(-100f)
    }
}

/** 말 끝나고 멈추기 시간 */
val HF_STOP_DELAYS = listOf(1500L to "1.5초", 2500L to "2.5초", 4000L to "4초")

/** 손 없이 녹음 설정 · 어시스턴트/바로가기 요청 */
object HandsFree {
    val proximity = MutableStateFlow(false)
    val autoEnd = MutableStateFlow(true)
    val stopIdx = MutableStateFlow(1)
    /** 어시스턴트·바로가기로 열렸음 → 담기 탭에서 손 없이 녹음 시작 */
    val request = MutableStateFlow(false)
    private var app: Context? = null
    private val prefs get() = app!!.getSharedPreferences("sseudam", Context.MODE_PRIVATE)

    fun init(c: Context) {
        if (app != null) return
        app = c.applicationContext
        proximity.value = prefs.getBoolean("hfProximity", false)
        autoEnd.value = prefs.getBoolean("hfAutoEnd", true)
        stopIdx.value = prefs.getInt("hfStop", 1).coerceIn(0, HF_STOP_DELAYS.lastIndex)
    }

    fun setProximity(on: Boolean) { proximity.value = on; prefs.edit().putBoolean("hfProximity", on).apply() }
    fun setAutoEnd(on: Boolean) { autoEnd.value = on; prefs.edit().putBoolean("hfAutoEnd", on).apply() }
    fun setStop(i: Int) { stopIdx.value = i; prefs.edit().putInt("hfStop", i).apply() }

    /** 저절로 끝내기가 꺼져 있으면 0 */
    fun stopDelayMs(): Long = if (autoEnd.value) HF_STOP_DELAYS[stopIdx.value].first else 0L

    fun start(c: Context, byProximity: Boolean) {
        init(c)
        RecordService.startHandsFree(c, byProximity, stopDelayMs())
    }

    /** 바로가기(앱 아이콘 길게 누르기)·구글 어시스턴트 '앱 기능 열기'로 들어온 인텐트인지 */
    fun isRecordIntent(i: android.content.Intent?): Boolean =
        i?.action == "kr.sseudam.app.RECORD" || i?.getStringExtra("feature")?.let { it == "record" || "녹음" in it } == true
}

/** 손 없이 녹음 중 안내 한 줄 */
fun handsFreeHint(): String = when {
    RecordService.autoEnds.value && RecordService.byProximity.value -> "🙌 손 없이 녹음 중 · 말을 멈추거나 폰을 떼면 끝나고 담겨요"
    RecordService.autoEnds.value -> "🙌 손 없이 녹음 중 · 말을 멈추면 저절로 끝나고 담겨요"
    RecordService.byProximity.value -> "🙌 손 없이 녹음 중 · 폰을 떼면 끝나고 담겨요"
    else -> "🙌 손 없이 녹음 중 · 끝나면 한 번 더 누르세요"
}

/**
 * 담기 탭에 붙여 두는 손 없이 녹음 연결. active = '담을까요?' 창이 없을 때.
 * - 어시스턴트·바로가기 요청이 오면 화면이 켜진 뒤(ON_RESUME) 녹음 시작 (마이크 포그라운드 서비스 규칙)
 * - 근접 센서: 설정이 켜져 있고 담기 탭이 화면에 있을 때(ON_RESUME~ON_PAUSE)만 듣는다
 */
@Composable
fun HandsFreeEffect(active: Boolean) {
    val ctx = LocalContext.current
    remember { HandsFree.init(ctx) }
    val life by LocalLifecycleOwner.current.lifecycle.currentStateAsState()
    val resumed = life.isAtLeast(Lifecycle.State.RESUMED)
    val req by HandsFree.request.collectAsStateWithLifecycle()
    val prox by HandsFree.proximity.collectAsStateWithLifecycle()

    val perm = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { res ->
        if (res[Manifest.permission.RECORD_AUDIO] == true || granted(ctx, Manifest.permission.RECORD_AUDIO)) HandsFree.start(ctx, false)
    }
    LaunchedEffect(req, resumed, active) {
        if (!req || !resumed || !active) return@LaunchedEffect
        HandsFree.request.value = false
        if (RecordService.recording.value) return@LaunchedEffect
        val ask = recordPermissionsToAsk(ctx)
        if (ask.isEmpty()) HandsFree.start(ctx, false) else perm.launch(ask)
    }

    val listen = prox && resumed && active
    DisposableEffect(listen) {
        val sm = ctx.getSystemService(SensorManager::class.java)
        val sensor = sm?.getDefaultSensor(Sensor.TYPE_PROXIMITY)
        if (!listen || sm == null || sensor == null) return@DisposableEffect onDispose {}
        var last: Boolean? = null
        val l = object : SensorEventListener {
            override fun onSensorChanged(e: SensorEvent) {
                val near = e.values[0] < minOf(sensor.maximumRange, 5f)
                val prev = last; last = near
                if (prev == null || prev == near) return   // 처음 읽은 값(이미 가려진 채 화면을 연 경우)은 무시하고 바뀔 때만
                if (near && !RecordService.recording.value) {
                    if (granted(ctx, Manifest.permission.RECORD_AUDIO)) HandsFree.start(ctx, true)
                    else Toast.makeText(ctx, "마이크를 허용하면 얼굴 가까이 대서 녹음할 수 있어요", Toast.LENGTH_SHORT).show()
                } else if (!near && RecordService.recording.value && RecordService.byProximity.value) {
                    RecordService.finishHandsFree(ctx)   // 멀리서 시작한 녹음은 끄지 않음
                }
            }
            override fun onAccuracyChanged(s: Sensor?, a: Int) {}
        }
        sm.registerListener(l, sensor, SensorManager.SENSOR_DELAY_NORMAL)
        onDispose { sm.unregisterListener(l) }
    }
}

/** 녹음 카드 안 '손 없이 녹음' 접이식 부분 */
@Composable
fun HandsFreePanel() {
    val ctx = LocalContext.current
    remember { HandsFree.init(ctx) }
    val prox by HandsFree.proximity.collectAsStateWithLifecycle()
    val autoEnd by HandsFree.autoEnd.collectAsStateWithLifecycle()
    val stopIdx by HandsFree.stopIdx.collectAsStateWithLifecycle()
    var open by remember { mutableStateOf(false) }
    val hasSensor = remember { ctx.getSystemService(SensorManager::class.java)?.getDefaultSensor(Sensor.TYPE_PROXIMITY) != null }

    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(T.bg.copy(alpha = 0.6f)).padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(Modifier.clickable { open = !open }, verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text("🙌 손 없이 녹음", fontSize = 15.sp, fontWeight = FontWeight.Bold, color = T.ink)
                Text("“헤이 구글, 쓰담에서 녹음 시작” 하면 시작하고, 말을 멈추면 끝나요", fontSize = 12.sp, color = T.soft)
            }
            Text(if (open) "▴" else "▾", fontSize = 14.sp, color = T.blue, modifier = Modifier.padding(start = 8.dp))
        }
        AnimatedVisibility(open) {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                if (hasSensor) SwitchRow("폰을 얼굴 가까이 대면 녹음", "떼면 끝나고 담겨요 · 담기 화면이 켜져 있을 때만", prox) { HandsFree.setProximity(it) }
                SwitchRow("말을 멈추면 저절로 끝내기", "끝나면 확인 없이 바로 담아요", autoEnd) { HandsFree.setAutoEnd(it) }
                if (autoEnd) {
                    Text("말 끝나고 멈추기", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = T.soft)
                    Segmented(HF_STOP_DELAYS.map { it.second }, stopIdx) { HandsFree.setStop(it) }
                }
                Text("🔒 마이크는 녹음할 때만 켜져요 · 앱 아이콘을 길게 눌러 ‘녹음 시작’을 골라도 돼요", fontSize = 11.sp, color = T.soft)
            }
        }
    }
}

@Composable
private fun SwitchRow(title: String, sub: String, on: Boolean, onChange: (Boolean) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = T.ink)
            Text(sub, fontSize = 11.sp, color = T.soft)
        }
        Switch(on, onChange, colors = SwitchDefaults.colors(checkedTrackColor = T.blue))
    }
}

/** 둥근 고르기 버튼 줄 */
@Composable
private fun Segmented(options: List<String>, selected: Int, onSelect: (Int) -> Unit) {
    Row(Modifier.fillMaxWidth().clip(CircleShape).background(T.soft.copy(alpha = 0.12f)).padding(3.dp)) {
        options.forEachIndexed { i, label ->
            Text(label, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.Center, maxLines = 1,
                color = if (i == selected) Color.White else T.ink,
                modifier = Modifier.weight(1f).clip(CircleShape).background(if (i == selected) T.blue else Color.Transparent)
                    .clickable { onSelect(i) }.padding(vertical = 7.dp))
        }
    }
}
