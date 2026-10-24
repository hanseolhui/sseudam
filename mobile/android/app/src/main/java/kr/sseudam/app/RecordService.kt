package kr.sseudam.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.MediaRecorder
import android.os.Build
import android.os.IBinder
import android.os.SystemClock
import kotlinx.coroutines.flow.MutableStateFlow
import java.io.File

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
        fun mark(student: String) {
            if (!recording.value) return
            currentStudent.value = student
            markers.value = markers.value + Marker(elapsedMs() / 1000.0, student)
        }
        fun star() { if (recording.value) markers.value = markers.value + Marker(elapsedMs() / 1000.0, star = true) }
        fun elapsedMs(): Long = if (!recording.value) 0 else if (paused.value) pausedAt - base else SystemClock.elapsedRealtime() - base

        fun start(c: Context) = c.startForegroundService(Intent(c, RecordService::class.java).setAction("start"))
        fun stop(c: Context) = c.startService(Intent(c, RecordService::class.java).setAction("stop"))
        fun togglePause(c: Context) = c.startService(Intent(c, RecordService::class.java).setAction("pause"))
    }

    private var recorder: MediaRecorder? = null
    private val meter = object : Runnable {
        override fun run() {
            recorder?.let { if (!paused.value) level.value = (it.maxAmplitude / 20000f).coerceIn(0f, 1f) }
            if (recording.value) android.os.Handler(mainLooper).postDelayed(this, 120)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            "start" -> begin()
            "stop" -> end()
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

    private fun begin() {
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
        recording.value = true; paused.value = false
        android.os.Handler(mainLooper).post(meter)
    }

    private fun pauseResume() {
        val r = recorder ?: return
        if (paused.value) { r.resume(); base += SystemClock.elapsedRealtime() - pausedAt; paused.value = false }
        else { r.pause(); pausedAt = SystemClock.elapsedRealtime(); paused.value = true; level.value = 0f }
    }

    private fun end() {
        runCatching { recorder?.stop() }
        recorder?.release(); recorder = null
        recording.value = false; paused.value = false; level.value = 0f
        stopForeground(STOP_FOREGROUND_REMOVE); stopSelf()
    }
}
