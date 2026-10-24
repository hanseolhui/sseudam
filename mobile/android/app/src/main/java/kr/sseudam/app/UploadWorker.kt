package kr.sseudam.app

import android.content.Context
import android.os.Build
import android.util.Base64
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** 대기 중인 녹음을 선생님 본인의 구글 드라이브(쓰담 Apps Script)로 올린다. 인터넷이 될 때 자동 재시도. */
class UploadWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    companion object {
        fun enqueue(c: Context) {
            val req = OneTimeWorkRequestBuilder<UploadWorker>()
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build()
            WorkManager.getInstance(c).enqueueUniqueWork("upload", ExistingWorkPolicy.APPEND_OR_REPLACE, req)
        }

        /** 컴퓨터에서 바뀐 학생 기록을 받아 오도록 15분마다 (QR 연동일 때) */
        fun schedulePeriodic(c: Context) {
            val req = PeriodicWorkRequestBuilder<UploadWorker>(15, java.util.concurrent.TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build()
            WorkManager.getInstance(c).enqueueUniquePeriodicWork("relay-sync", ExistingPeriodicWorkPolicy.KEEP, req)
        }

        fun post(url: String, body: JSONObject): JSONObject {
            val conn = URL(url).openConnection() as HttpURLConnection
            conn.requestMethod = "POST"; conn.doOutput = true; conn.instanceFollowRedirects = true
            conn.connectTimeout = 30000; conn.readTimeout = 300000
            conn.setRequestProperty("Content-Type", "text/plain;charset=utf-8")
            conn.outputStream.use { it.write(body.toString().toByteArray()) }
            var code = conn.responseCode
            var c = conn
            // Apps Script는 302로 결과 주소를 돌려줌 → GET으로 따라감
            var hops = 0
            while (code in 301..303 && hops < 5) {
                val loc = c.getHeaderField("Location") ?: break
                c = URL(loc).openConnection() as HttpURLConnection
                c.readTimeout = 300000; code = c.responseCode; hops++
            }
            if (code != 200) throw Exception("연결 실패 ($code)")
            val text = c.inputStream.bufferedReader().readText()
            val obj = runCatching { JSONObject(text) }.getOrElse { throw Exception("응답을 이해하지 못했습니다. 컴퓨터의 구글 연결을 최신으로 다시 배포해 주세요.") }
            if (!obj.optBoolean("ok")) throw Exception(obj.optString("error", "알 수 없는 오류"))
            return obj
        }
    }

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        Store.init(applicationContext)
        if (Relay.paired()) {
            // QR 연동: 녹음·메모를 암호화해서 컴퓨터로, 학생 기록은 서로 맞추기
            var failed = false
            for (r in Store.items.value.filter { it.google == Sync.PENDING || it.google == Sync.FAILED }) {
                try {
                    Relay.uploadRecording(r, if (r.isAudio) Store.file(r).readBytes() else ByteArray(0))
                    Store.update(r.copy(google = Sync.DONE, lastError = ""))
                } catch (e: Exception) {
                    failed = true
                    Store.update(r.copy(google = Sync.FAILED, lastError = "연결: ${e.message}"))
                }
            }
            runCatching { Relay.syncDocs() }.onFailure { failed = true }
            return@withContext if (failed) Result.retry() else Result.success()
        }
        val url = Store.googleUrl(); val token = Store.googleToken()
        if (url.isEmpty() || token.isEmpty()) return@withContext Result.success()
        var failed = false
        val df = SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.KOREA)
        for (r in Store.items.value.filter { it.google == Sync.PENDING || it.google == Sync.FAILED }) {
            try {
                val bytes = Store.file(r).readBytes()
                post(url, JSONObject().put("action", "upload_recording").put("token", token).put("filename", r.fileName)
                    .put("mime", if (r.isAudio) "audio/mp4" else "text/plain").put("data", Base64.encodeToString(bytes, Base64.NO_WRAP))
                    .put("recorded_at", df.format(Date(r.createdAt))).put("kind", r.kind)
                    .put("title", r.fileName.substringBeforeLast('.')).put("memo", r.memo).put("device", Build.MODEL))
                Store.update(r.copy(google = Sync.DONE, lastError = ""))
            } catch (e: Exception) {
                failed = true
                Store.update(r.copy(google = Sync.FAILED, lastError = "구글: ${e.message}"))
            }
        }
        if (failed) Result.retry() else Result.success()
    }
}
