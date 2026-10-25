package kr.sseudam.app

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.MediaMuxer
import android.media.MediaRecorder
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
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import java.io.File
import java.nio.ByteOrder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.ceil
import kotlin.math.log10
import kotlin.math.sqrt

/*
 * '말하면 담기' — 앱이 화면에 떠 있는 동안(담기 탭) 말소리가 들리면 저절로 녹음하고, 말이 멈추면 끝내 기록함에 담는다.
 * 아이폰(같은 사양)과 동작을 똑같이 맞춘다.
 * - 배터리: 포그라운드 서비스·웨이크락 없음. 16kHz 모노 PCM 을 100ms 씩 읽어 소리 크기(dBFS)만 잰다. 듣지 않을 땐 마이크를 놓는다.
 * - 판정(AutoVad)은 안드로이드와 상관없는 순수 코드라 JVM 단위 테스트로 확인한다 (AutoRecordTest).
 */

/** 감도: 바닥 소음보다 몇 dB 커야 말소리로 볼지 + 아무리 조용해도 이보다는 커야 함 */
enum class AutoSens(val label: String, val margin: Float, val absMin: Float) {
    QUIET("조용한 곳", 10f, -50f), NORMAL("보통", 14f, -45f), LOUD("시끄러운 곳", 20f, -38f)
}

/** 말이 끝나고 이만큼 조용하면 녹음을 끝낸다 */
val AUTO_STOP_DELAYS = listOf(1500L to "1.5초", 2500L to "2.5초", 4000L to "4초")

/** 판정기가 소리 조각(프레임)을 넘기는 곳 — 앱에서는 AAC 인코더, 테스트에서는 가짜 */
interface ClipSink<F> {
    /** 녹음 시작: 말 시작 전 1초(프리롤) + 시작을 확인한 프레임들 */
    fun begin(preRoll: List<F>)
    fun write(frame: F)
    /** 녹음 끝: keep=false 면 기침·문소리처럼 너무 짧아 버림 */
    fun end(keep: Boolean, voicedMs: Long, clipMs: Long)
}

/**
 * 말소리 판정 상태 기계 (프레임마다 dBFS 하나씩).
 * 대기: 처음 1초 평균으로 바닥 소음을 잡고, 이후 조용해지면 빨리(0.9/0.1)·시끄러워지면 천천히(0.995/0.005) 따라간다.
 *       문턱 = max(바닥 + 여유, 최소값). 문턱을 250ms 연속 넘으면 녹음 시작 (프리롤 1초 포함).
 * 녹음: 바닥은 고정. (문턱 − 3dB) 아래가 이어지면 조용함으로 쌓고, 멈춤 시간이 차면 끝. 문턱을 다시 넘으면 조용함을 0으로.
 *       조용한 프레임은 모아 뒀다가 다시 소리가 나면 쓰고, 끝날 때는 앞 0.5초만 쓴다 (꼬리 자르기 · clipMs = 실제로 쓴 길이).
 *       말소리(문턱 위) 합이 1초 미만이면 버림. 10분이 차면 끊어 담고 바로 이어서 듣는다.
 */
class AutoVad<F>(
    var sens: AutoSens,
    var stopDelayMs: Long,
    private val sink: ClipSink<F>,
    private val frameMs: Int = 100,
    attackMs: Int = 250,
    preRollMs: Int = 1000,
    calibMs: Int = 1000,
    private val minVoicedMs: Long = 1000,
    private val maxClipMs: Long = 10 * 60_000L,
    tailMs: Int = 500,
) {
    private val tailFrames = tailMs / frameMs
    private val attackFrames = ceil(attackMs / frameMs.toDouble()).toInt().coerceAtLeast(1)
    private val calibFrames = (calibMs / frameMs).coerceAtLeast(1)
    private val ringCap = preRollMs / frameMs + attackFrames
    private val ring = ArrayDeque<F>()
    /** 담는 중 조용한 프레임은 바로 쓰지 않고 모아 둔다 → 끝의 조용한 꼬리를 0.5초만 남기고 자르려고 */
    private val held = ArrayList<F>()
    private var writtenFrames = 0L

    /** 바닥 소음 (dBFS) · 처음 1초 동안은 null */
    var floor: Float? = null; private set
    private var calibSum = 0f
    private var calibN = 0
    private var above = 0
    var capturing = false; private set
    private var clipFrames = 0L
    private var voicedFrames = 0L
    private var silenceFrames = 0L

    val threshold: Float get() = maxOf((floor ?: -100f) + sens.margin, sens.absMin)

    fun feed(db: Float, frame: F) {
        if (!capturing) idle(db, frame) else capture(db, frame)
    }

    private fun idle(db: Float, frame: F) {
        ring.addLast(frame)
        while (ring.size > ringCap) ring.removeFirst()
        val f = floor
        if (f == null) {   // 처음 1초: 바닥 소음 잡기 (이 동안은 시작하지 않음)
            calibSum += db; calibN++
            if (calibN >= calibFrames) floor = calibSum / calibN
            return
        }
        if (db > threshold) above++ else above = 0
        if (above >= attackFrames) {
            capturing = true
            clipFrames = ring.size.toLong(); writtenFrames = clipFrames; voicedFrames = above.toLong(); silenceFrames = 0; above = 0
            sink.begin(ring.toList()); ring.clear()
            return
        }
        floor = if (db < f) f * 0.9f + db * 0.1f else f * 0.995f + db * 0.005f
    }

    private fun capture(db: Float, frame: F) {
        clipFrames++
        val th = threshold
        if (db < th - 3f) { silenceFrames++; held.add(frame) }
        else {
            // 조용함이 끝났으면 모아 둔 것부터 쓰고 이 프레임을 쓴다
            held.forEach { sink.write(it) }; writtenFrames += held.size; held.clear()
            sink.write(frame); writtenFrames++
            if (db > th) { voicedFrames++; silenceFrames = 0 }
        }
        if (silenceFrames * frameMs >= stopDelayMs) { endClip(); return }
        if (clipFrames * frameMs >= maxClipMs) {
            val speaking = silenceFrames == 0L
            endClip()
            // 말하는 중에 10분이 찼으면 끊김 없이 다음 녹음으로 이어 간다
            if (speaking) { capturing = true; clipFrames = 0; writtenFrames = 0; voicedFrames = 0; silenceFrames = 0; sink.begin(emptyList()) }
        }
    }

    private fun endClip() {
        capturing = false
        // 끝의 조용한 꼬리는 앞 0.5초만 남기고 버림
        val tail = held.take(tailFrames)
        tail.forEach { sink.write(it) }; writtenFrames += tail.size; held.clear()
        val voiced = voicedFrames * frameMs
        sink.end(voiced >= minVoicedMs, voiced, writtenFrames * frameMs)
        clipFrames = 0; writtenFrames = 0; voicedFrames = 0; silenceFrames = 0; above = 0
        ring.clear()
    }

    /** 듣기를 멈출 때: 담는 중이던 녹음은 마무리 (짧으면 버림) */
    fun finish() { if (capturing) endClip() }
}

/** '말하면 담기' 실행부: 마이크(AudioRecord) 읽기 스레드 + Compose 가 보는 상태 */
object AutoRecorder {
    enum class Phase { OFF, LISTENING, CAPTURING }

    private const val RATE = 16000
    private const val FRAME = RATE / 10   // 100ms

    val phase = MutableStateFlow(Phase.OFF)
    val levelDb = MutableStateFlow(-90f)
    val thresholdDb = MutableStateFlow(-45f)
    /** 지금 담는 녹음 길이 (프리롤 포함) */
    val clipMs = MutableStateFlow(0L)
    /** 마지막으로 담은 때 ('방금 담았어요 ✓') */
    val savedAt = MutableStateFlow(0L)
    val todayCount = MutableStateFlow(0)
    val enabled = MutableStateFlow(false)
    val sens = MutableStateFlow(AutoSens.NORMAL)
    val stopIdx = MutableStateFlow(1)
    /** '한 줄로 남기기' 받아쓰기가 마이크를 쓰는 동안은 쉰다 */
    val dictating = MutableStateFlow(false)

    private var app: Context? = null
    private val prefs get() = app!!.getSharedPreferences("sseudam", Context.MODE_PRIVATE)
    @Volatile private var running = false
    private var thread: Thread? = null
    @Volatile private var vad: AutoVad<ShortArray>? = null

    fun init(c: Context) {
        if (app != null) return
        app = c.applicationContext
        val p = prefs
        enabled.value = p.getBoolean("autoOn", false)
        sens.value = AutoSens.entries.getOrElse(p.getInt("autoSens", 1)) { AutoSens.NORMAL }
        stopIdx.value = p.getInt("autoStop", 1).coerceIn(0, AUTO_STOP_DELAYS.lastIndex)
        todayCount.value = if (p.getString("autoDay", "") == today()) p.getInt("autoCount", 0) else 0
    }

    private fun today() = SimpleDateFormat("yyyyMMdd", Locale.KOREA).format(Date())

    fun noticed(): Boolean = prefs.getBoolean("autoNoticed", false)
    fun markNoticed() = prefs.edit().putBoolean("autoNoticed", true).apply()

    fun setEnabled(on: Boolean) { enabled.value = on; prefs.edit().putBoolean("autoOn", on).apply() }
    fun setSens(s: AutoSens) { sens.value = s; vad?.sens = s; prefs.edit().putInt("autoSens", s.ordinal).apply() }
    fun setStop(i: Int) { stopIdx.value = i; vad?.stopDelayMs = AUTO_STOP_DELAYS[i].first; prefs.edit().putInt("autoStop", i).apply() }

    /** 듣기 시작 (담기 탭이 화면에 있을 때만 부른다) */
    @SuppressLint("MissingPermission")
    fun start(c: Context) {
        init(c)
        if (running) return
        if (!granted(c, Manifest.permission.RECORD_AUDIO)) { setEnabled(false); return }
        val min = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val rec = runCatching {
            AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, RATE, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT, maxOf(min, FRAME * 2 * 2))
        }.getOrNull()
        if (rec == null || rec.state != AudioRecord.STATE_INITIALIZED) { rec?.release(); return }
        runCatching { rec.startRecording() }.onFailure { rec.release(); return }
        running = true
        phase.value = Phase.LISTENING
        thread = Thread({ loop(rec) }, "sseudam-auto").apply { start() }
    }

    /** 듣기 멈춤: 담는 중이던 녹음은 저장하고 마이크를 놓는다 (마이크를 바로 넘길 수 있게 잠깐 기다림) */
    fun stop() {
        if (!running) return
        running = false
        thread?.let { runCatching { it.join(2000) } }
        thread = null
    }

    private fun loop(rec: AudioRecord) {
        val sink = EncoderSink()
        val v = AutoVad(sens.value, AUTO_STOP_DELAYS[stopIdx.value].first, sink)
        vad = v
        val buf = ShortArray(FRAME)
        try {
            while (running) {
                var n = 0
                while (n < FRAME && running) {
                    val r = rec.read(buf, n, FRAME - n)
                    if (r <= 0) break
                    n += r
                }
                if (n < FRAME) { if (running) Thread.sleep(50); continue }
                val db = dbfs(buf)
                v.feed(db, buf.copyOf())
                levelDb.value = db; thresholdDb.value = v.threshold
            }
        } catch (_: Throwable) {
        } finally {
            runCatching { v.finish() }
            runCatching { rec.stop() }; rec.release()
            vad = null
            running = false
            phase.value = Phase.OFF; levelDb.value = -90f; clipMs.value = 0
        }
    }

    /** 소리 크기 (RMS → dBFS). 배터리를 아끼려고 두 샘플에 하나만 본다 */
    fun dbfs(pcm: ShortArray): Float {
        var sum = 0.0; var n = 0
        var i = 0
        while (i < pcm.size) { val s = pcm[i] / 32768.0; sum += s * s; n++; i += 2 }
        if (n == 0) return -100f
        val rms = sqrt(sum / n)
        return if (rms <= 1e-5) -100f else (20 * log10(rms)).toFloat()
    }

    /** 녹음 조각을 바로바로 AAC(m4a)로 → 끝나면 손으로 녹음한 것과 같은 Store.add 로 담는다 */
    private class EncoderSink : ClipSink<ShortArray> {
        private var enc: AacWriter? = null
        private var file: File? = null
        private var at = 0L

        override fun begin(preRoll: List<ShortArray>) {
            val c = app ?: return
            at = System.currentTimeMillis() - preRoll.size * 100L
            val f = File(c.cacheDir, "auto-${System.currentTimeMillis()}.m4a")
            file = f
            enc = runCatching { AacWriter(f, RATE) }.getOrNull()
            clipMs.value = 0
            preRoll.forEach { write(it) }
            phase.value = Phase.CAPTURING
        }

        override fun write(frame: ShortArray) {
            val e = enc ?: return
            runCatching { e.write(frame) }.onFailure { enc = null; runCatching { e.close() } }
            clipMs.value += frame.size * 1000L / RATE
        }

        override fun end(keep: Boolean, voicedMs: Long, clipMs: Long) {
            val e = enc; val f = file
            enc = null; file = null
            val ok = e != null && runCatching { e.finish() }.getOrDefault(false)
            if (keep && ok && f != null && f.length() > 0) {
                val cls = RecordService.pickedClass.value ?: prefs.getString("markClass", "")?.ifEmpty { null }
                    ?.takeIf { uid -> DataStore.db.value.activeClasses.any { it.uid == uid } }
                runCatching { Store.add(f, e!!.samples / RATE.toDouble(), "수업", "", at, emptyList(), cls, RecordService.period.value) }
                    .onSuccess { counted() }
                    .onFailure { f.delete() }
            } else f?.delete()
            AutoRecorder.clipMs.value = 0
            if (running) phase.value = Phase.LISTENING
        }

        private fun counted() {
            val d = today()
            val n = if (prefs.getString("autoDay", "") == d) prefs.getInt("autoCount", 0) + 1 else 1
            prefs.edit().putString("autoDay", d).putInt("autoCount", n).apply()
            todayCount.value = n
            savedAt.value = System.currentTimeMillis()
        }
    }
}

/** PCM16 모노 → AAC-LC m4a (MediaCodec + MediaMuxer, 32kbps · 손녹음과 같은 형식) */
private class AacWriter(file: File, private val rate: Int) {
    private val codec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_AUDIO_AAC)
    private val muxer = MediaMuxer(file.path, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
    private val info = MediaCodec.BufferInfo()
    private var track = -1
    private var started = false
    var samples = 0L; private set

    init {
        val fmt = MediaFormat.createAudioFormat(MediaFormat.MIMETYPE_AUDIO_AAC, rate, 1)
        fmt.setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecProfileLevel.AACObjectLC)
        fmt.setInteger(MediaFormat.KEY_BIT_RATE, 32000)
        fmt.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 16384)
        codec.configure(fmt, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        codec.start()
    }

    private fun pts() = samples * 1_000_000L / rate

    fun write(pcm: ShortArray) {
        var off = 0
        while (off < pcm.size) {
            val idx = codec.dequeueInputBuffer(10_000)
            if (idx < 0) { drain(false); continue }
            val ib = codec.getInputBuffer(idx)!!
            ib.clear(); ib.order(ByteOrder.LITTLE_ENDIAN)
            val n = minOf(pcm.size - off, ib.remaining() / 2)
            ib.asShortBuffer().put(pcm, off, n)
            codec.queueInputBuffer(idx, 0, n * 2, pts(), 0)
            samples += n; off += n
            drain(false)
        }
    }

    private fun drain(eos: Boolean) {
        var tries = 0
        while (true) {
            val o = codec.dequeueOutputBuffer(info, if (eos) 10_000 else 0)
            when {
                o == MediaCodec.INFO_TRY_AGAIN_LATER -> { if (!eos || ++tries > 100) return }
                o == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> { track = muxer.addTrack(codec.outputFormat); muxer.start(); started = true }
                o >= 0 -> {
                    val ob = codec.getOutputBuffer(o)!!
                    if (info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0) info.size = 0
                    if (info.size > 0 && started) {
                        ob.position(info.offset); ob.limit(info.offset + info.size)
                        muxer.writeSampleData(track, ob, info)
                    }
                    codec.releaseOutputBuffer(o, false)
                    if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) return
                }
            }
        }
    }

    /** 마무리 · 실제로 소리가 들어갔으면 true */
    fun finish(): Boolean {
        var idx = -1; var tries = 0
        while (idx < 0 && tries++ < 50) { idx = codec.dequeueInputBuffer(10_000); if (idx < 0) drain(false) }
        if (idx >= 0) codec.queueInputBuffer(idx, 0, 0, pts(), MediaCodec.BUFFER_FLAG_END_OF_STREAM)
        drain(true)
        val ok = started
        close()
        return ok
    }

    fun close() {
        runCatching { codec.stop() }; runCatching { codec.release() }
        runCatching { if (started) muxer.stop() }; runCatching { muxer.release() }
        started = false
    }
}

// ───────────────────────── 화면 ─────────────────────────

/**
 * 담기 탭에 붙여 두는 듣기 스위치. active = 손녹음 중이 아니고 '담을까요?' 창도 없을 때.
 * 앱이 화면에 있을 때(ON_RESUME~ON_PAUSE)만 듣고, 화면을 떠나거나 꺼지면 바로 멈추며 담는 중이던 것을 저장한다.
 */
@Composable
fun AutoRecordEffect(active: Boolean) {
    val ctx = LocalContext.current
    remember { AutoRecorder.init(ctx) }
    val on by AutoRecorder.enabled.collectAsStateWithLifecycle()
    val dict by AutoRecorder.dictating.collectAsStateWithLifecycle()
    val life by LocalLifecycleOwner.current.lifecycle.currentStateAsState()
    val listen = active && on && !dict && life.isAtLeast(Lifecycle.State.RESUMED)
    DisposableEffect(listen) {
        if (listen) AutoRecorder.start(ctx)
        onDispose { AutoRecorder.stop() }
    }
}

/** 녹음 카드 안 '말하면 담기' 부분 (스위치 · 상태 · 소리 막대 · 자세히) */
@Composable
fun AutoRecordPanel() {
    val ctx = LocalContext.current
    remember { AutoRecorder.init(ctx) }
    val on by AutoRecorder.enabled.collectAsStateWithLifecycle()
    val phase by AutoRecorder.phase.collectAsStateWithLifecycle()
    val db by AutoRecorder.levelDb.collectAsStateWithLifecycle()
    val th by AutoRecorder.thresholdDb.collectAsStateWithLifecycle()
    val clip by AutoRecorder.clipMs.collectAsStateWithLifecycle()
    val savedAt by AutoRecorder.savedAt.collectAsStateWithLifecycle()
    val count by AutoRecorder.todayCount.collectAsStateWithLifecycle()
    val sens by AutoRecorder.sens.collectAsStateWithLifecycle()
    val stopIdx by AutoRecorder.stopIdx.collectAsStateWithLifecycle()
    var notice by remember { mutableStateOf(false) }
    var more by remember { mutableStateOf(false) }
    var justSaved by remember { mutableStateOf(false) }
    LaunchedEffect(savedAt) { if (savedAt > 0 && System.currentTimeMillis() - savedAt < 3000) { justSaved = true; delay(2500); justSaved = false } }

    val perm = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        AutoRecorder.setEnabled(ok)
        if (!ok) Toast.makeText(ctx, "마이크를 허용해야 ‘말하면 담기’를 쓸 수 있어요", Toast.LENGTH_SHORT).show()
    }
    fun turnOn() {
        if (granted(ctx, Manifest.permission.RECORD_AUDIO)) AutoRecorder.setEnabled(true)
        else perm.launch(Manifest.permission.RECORD_AUDIO)
    }

    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(T.bg.copy(alpha = 0.6f)).padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text("🎧 말하면 담기", fontSize = 15.sp, fontWeight = FontWeight.Bold, color = T.ink)
                Text("앱을 켜 둔 동안 말하면 저절로 녹음하고, 말을 멈추면 끝내요", fontSize = 12.sp, color = T.soft)
            }
            Spacer(Modifier.width(8.dp))
            Switch(on, { v ->
                if (!v) AutoRecorder.setEnabled(false)
                else if (!AutoRecorder.noticed()) notice = true
                else turnOn()
            }, colors = SwitchDefaults.colors(checkedTrackColor = T.blue))
        }
        if (on) {
            val capturing = phase == AutoRecorder.Phase.CAPTURING
            Text(when {
                capturing -> "담는 중 " + (clip / 1000).let { "%d:%02d".format(it / 60, it % 60) }
                justSaved -> "방금 담았어요 ✓"
                phase == AutoRecorder.Phase.LISTENING -> "듣는 중 · 말하면 바로 담아요"
                else -> "잠깐 쉬는 중이에요"
            }, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = if (capturing) T.coral else if (justSaved) T.mint else T.blue)
            LevelMeter(db, th, capturing)
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("오늘 자동으로 ${count}개 담았어요", fontSize = 12.sp, color = T.soft, modifier = Modifier.weight(1f))
                PeriodChip()
                Text(if (more) "자세히 ▴" else "자세히 ▾", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = T.blue,
                    modifier = Modifier.clip(CircleShape).clickable { more = !more }.padding(horizontal = 6.dp, vertical = 4.dp))
            }
            AnimatedVisibility(more) {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("감도", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = T.soft)
                    Segmented(AutoSens.entries.map { it.label }, sens.ordinal) { AutoRecorder.setSens(AutoSens.entries[it]) }
                    Text("말 끝나고 멈추기", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = T.soft)
                    Segmented(AUTO_STOP_DELAYS.map { it.second }, stopIdx) { AutoRecorder.setStop(it) }
                    Text("막대의 세로줄을 넘는 소리가 나면 담기 시작해요. 교실처럼 시끄러우면 ‘시끄러운 곳’으로 바꿔 주세요.",
                        fontSize = 11.sp, color = T.soft)
                }
            }
        }
    }

    if (notice) AlertDialog(
        onDismissRequest = { notice = false }, containerColor = T.card,
        title = { Text("말하면 담기") },
        text = { Text("주변 사람 목소리도 담길 수 있어요. 녹음은 선생님 폰과 연결한 컴퓨터에만 저장돼요.", textAlign = TextAlign.Start) },
        confirmButton = { TextButton({ notice = false; AutoRecorder.markNoticed(); turnOn() }) { Text("켜기") } },
        dismissButton = { TextButton({ notice = false }) { Text("취소", color = T.soft) } },
    )
}

/** 지금 소리 크기 막대 + 담기 시작하는 문턱 표시 (−70~−10 dBFS) */
@Composable
private fun LevelMeter(db: Float, threshold: Float, capturing: Boolean) {
    fun frac(v: Float) = ((v + 70f) / 60f).coerceIn(0f, 1f)
    BoxWithConstraints(Modifier.fillMaxWidth().height(10.dp)) {
        val w = maxWidth
        Box(Modifier.align(Alignment.CenterStart).fillMaxWidth().height(6.dp).clip(CircleShape).background(T.soft.copy(alpha = 0.18f)))
        Box(Modifier.align(Alignment.CenterStart).width(w * frac(db)).height(6.dp).clip(CircleShape)
            .background(if (capturing) T.coral else T.blue.copy(alpha = 0.7f)))
        Box(Modifier.align(Alignment.CenterStart).offset(x = (w * frac(threshold) - 1.dp).coerceAtLeast(0.dp)).width(2.dp).fillMaxHeight()
            .background(T.ink.copy(alpha = 0.6f)))
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
