package kr.sseudam.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMuxer
import android.media.MediaRecorder
import android.os.Build
import android.os.IBinder
import android.os.SystemClock
import kotlinx.coroutines.flow.MutableStateFlow
import java.io.File
import java.nio.ByteBuffer

/** 화면이 꺼져도 계속 녹음하는 포그라운드 서비스. AAC(m4a) 모노 16kHz 32kbps ≈ 1시간 14MB. */
class RecordService : Service() {
    companion object {
        val recording = MutableStateFlow(false)
        val paused = MutableStateFlow(false)
        val level = MutableStateFlow(0f)
        var startedAt = 0L; private set
        private var base = 0L          // 일시정지 고려한 경과 기준
        private var pausedAt = 0L
        var lastFile: File? = null; private set
        /** 녹음하면서 누른 이름표·⭐, 고른 반·교시 (녹음을 시작할 때 비움) */
        val markers = MutableStateFlow<List<Marker>>(emptyList())
        val currentStudent = MutableStateFlow<String?>(null)
        val pickedClass = MutableStateFlow<String?>(null)
        val period = MutableStateFlow<Int?>(null)
        /** 손 없이 시작한 녹음(어시스턴트·바로가기·얼굴 가까이) · 근접 센서로 시작했는지 · 말을 멈추면 저절로 끝내는지 */
        val handsFree = MutableStateFlow(false)
        val byProximity = MutableStateFlow(false)
        val autoEnds = MutableStateFlow(false)
        /** 손 없이 녹음을 확인 창 없이 담았을 때 (홈에서 '담았어요' 카드를 띄움) */
        val lastSavedId = MutableStateFlow<String?>(null)
        fun mark(student: String) {
            if (!recording.value) return
            currentStudent.value = student
            markers.value = markers.value + Marker(elapsedMs() / 1000.0, student)
        }
        fun star() { if (recording.value) markers.value = markers.value + Marker(elapsedMs() / 1000.0, star = true) }
        fun elapsedMs(): Long = if (!recording.value) 0 else if (paused.value) pausedAt - base else SystemClock.elapsedRealtime() - base

        fun start(c: Context) = c.startForegroundService(Intent(c, RecordService::class.java).setAction("start"))
        /** 손 없이 녹음 시작 (stopDelayMs = 0 이면 저절로 끝내지 않음) */
        fun startHandsFree(c: Context, proximity: Boolean, stopDelayMs: Long) = c.startForegroundService(
            Intent(c, RecordService::class.java).setAction("start").putExtra("handsFree", true)
                .putExtra("proximity", proximity).putExtra("stopDelay", stopDelayMs))
        /** 손 없이 녹음 끝내고 확인 창 없이 바로 담기 */
        fun finishHandsFree(c: Context) = c.startService(Intent(c, RecordService::class.java).setAction("finish"))
        fun stop(c: Context) = c.startService(Intent(c, RecordService::class.java).setAction("stop"))
        fun togglePause(c: Context) = c.startService(Intent(c, RecordService::class.java).setAction("pause"))
    }

    private var recorder: MediaRecorder? = null
    private var detector: EndDetector? = null
    private val meter = object : Runnable {
        override fun run() {
            recorder?.let {
                if (!paused.value) {
                    val amp = it.maxAmplitude
                    level.value = (amp / 20000f).coerceIn(0f, 1f)
                    // 손 없이 녹음: 0.1초마다 소리 크기를 보고 말이 멈추면 끝내고 담는다
                    val d = detector
                    if (d?.feed(EndDetector.dbfs(amp)) == true) {
                        detector = null
                        // 말이 없었으면 버리고, 있었으면 끝의 조용한 구간을 0.5초만 남기고 자른다
                        if (d.spoke) endAndSave(cutMs = (d.stopDelayMs - 500).coerceAtLeast(0)) else { lastFile?.let { f -> end(); f.delete() } }
                        return
                    }
                }
            }
            if (recording.value) android.os.Handler(mainLooper).postDelayed(this, 100)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            "start" -> begin(intent)
            "stop" -> end()
            "finish" -> if (recording.value && handsFree.value) endAndSave()
            "pause" -> pauseResume()
        }
        return START_NOT_STICKY
    }

    private fun notification(): Notification {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel("rec", "녹음", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, "rec").setContentTitle("쓰담 녹음 중").setContentText("눌러서 돌아가기")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now).setOngoing(true).setContentIntent(open).build()
    }

    private fun begin(intent: Intent) {
        if (recording.value) return
        if (Build.VERSION.SDK_INT >= 30) startForeground(1, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        else startForeground(1, notification())
        val f = File(cacheDir, "rec-${System.currentTimeMillis()}.m4a")
        val r = if (Build.VERSION.SDK_INT >= 31) MediaRecorder(this) else @Suppress("DEPRECATION") MediaRecorder()
        r.setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
        r.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
        r.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
        r.setAudioChannels(1); r.setAudioSamplingRate(16000); r.setAudioEncodingBitRate(32000)
        r.setOutputFile(f.absolutePath)
        r.prepare(); r.start()
        recorder = r; lastFile = f
        startedAt = System.currentTimeMillis(); base = SystemClock.elapsedRealtime()
        markers.value = emptyList(); currentStudent.value = null; pickedClass.value = null; period.value = null
        val hf = intent.getBooleanExtra("handsFree", false)
        val delay = intent.getLongExtra("stopDelay", 0)
        handsFree.value = hf; byProximity.value = hf && intent.getBooleanExtra("proximity", false)
        detector = if (hf && delay > 0) EndDetector(delay) else null
        autoEnds.value = detector != null
        recording.value = true; paused.value = false
        android.os.Handler(mainLooper).post(meter)
    }

    private fun pauseResume() {
        val r = recorder ?: return
        if (paused.value) { r.resume(); base += SystemClock.elapsedRealtime() - pausedAt; paused.value = false }
        else { r.pause(); pausedAt = SystemClock.elapsedRealtime(); paused.value = true; level.value = 0f }
    }

    /** 손 없이 녹음 끝: 버튼 녹음과 같은 Store.add 로 바로 담는다 (1초 미만은 버림) · cutMs = 끝에서 잘라 낼 길이 */
    private fun endAndSave(cutMs: Long = 0) {
        val dur = elapsedMs() - cutMs; val at = startedAt; val f = lastFile
        val marks = markers.value; val cls = pickedClass.value; val p = period.value
        end()
        if (f == null) return
        if (dur < 1000) { f.delete(); return }
        if (cutMs > 0) trimM4a(f, dur)
        Store.init(this)
        runCatching { Store.add(f, dur / 1000.0, "수업", "", at, marks.filter { it.t * 1000 <= dur }, cls, p) }
            .onSuccess { lastSavedId.value = Store.items.value.firstOrNull()?.id }
    }

    private fun end() {
        detector = null
        handsFree.value = false; byProximity.value = false; autoEnds.value = false
        runCatching { recorder?.stop() }
        recorder?.release(); recorder = null
        recording.value = false; paused.value = false; level.value = 0f
        stopForeground(STOP_FOREGROUND_REMOVE); stopSelf()
    }

    /** m4a 를 앞에서 keepMs 까지만 남긴다 (다시 인코딩 없이 그대로 옮겨 담기). 실패하면 원본 그대로 */
    private fun trimM4a(f: File, keepMs: Long) {
        val out = File(f.parentFile, f.nameWithoutExtension + "-cut.m4a")
        val ok = runCatching {
            val ex = MediaExtractor(); ex.setDataSource(f.absolutePath)
            val fmt = ex.getTrackFormat(0); ex.selectTrack(0)
            val mux = MediaMuxer(out.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
            val track = mux.addTrack(fmt); mux.start()
            val size = if (fmt.containsKey(MediaFormat.KEY_MAX_INPUT_SIZE)) fmt.getInteger(MediaFormat.KEY_MAX_INPUT_SIZE) else 64 * 1024
            val buf = ByteBuffer.allocate(size); val info = MediaCodec.BufferInfo()
            while (true) {
                val n = ex.readSampleData(buf, 0)
                if (n < 0 || ex.sampleTime > keepMs * 1000) break
                info.set(0, n, ex.sampleTime, if (ex.sampleFlags and MediaExtractor.SAMPLE_FLAG_SYNC != 0) MediaCodec.BUFFER_FLAG_KEY_FRAME else 0)
                mux.writeSampleData(track, buf, info); ex.advance()
            }
            mux.stop(); mux.release(); ex.release()
        }.isSuccess
        if (ok && out.length() > 0 && f.delete()) out.renameTo(f) else out.delete()
    }
}
