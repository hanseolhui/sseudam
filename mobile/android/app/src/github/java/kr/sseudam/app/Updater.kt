package kr.sseudam.app

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

/**
 * 새 버전 알림 · 업데이트.
 * 지금은 플레이 스토어 출시 전이라 GitHub 릴리스의 "Sseudam-Android.apk"를 받아 설치 화면을 띄운다.
 * 플레이 스토어로 설치된 앱(installer == com.android.vending)은 GitHub 경로를 건너뛴다.
 *
 * TODO(플레이 출시 후): PlayUpdateSource 를 구현해 Play In-App Updates
 *   (com.google.android.play:app-update-ktx 의 AppUpdateManager) 로 바꾼다. UpdateSource 만 갈아 끼우면
 *   담기 화면 카드·연결 탭 토글은 그대로 쓴다.
 */
object Updater {
    data class Release(val version: String, val url: String, val size: Long, val sha256: String?)

    interface UpdateSource {
        /** 지금보다 새 버전이 있으면 그 정보, 없으면 null */
        suspend fun latest(ctx: Context, current: String): Release?
    }

    /** 사이드로드(직접 설치)용: GitHub 최신 릴리스 */
    object GitHubSource : UpdateSource {
        private const val API = "https://api.github.com/repos/hanseolhui/sseudam/releases/latest"
        private const val ASSET = "Sseudam-Android.apk"

        override suspend fun latest(ctx: Context, current: String): Release? = withContext(Dispatchers.IO) {
            val c = URL(API).openConnection() as HttpURLConnection
            c.connectTimeout = 15000; c.readTimeout = 20000
            c.setRequestProperty("Accept", "application/vnd.github+json")
            c.setRequestProperty("User-Agent", "Sseudam-Android")
            if (c.responseCode != 200) return@withContext null
            val o = JSONObject(c.inputStream.bufferedReader().readText())
            val ver = o.optString("tag_name").trim().removePrefix("v").removePrefix("V")
            if (ver.isEmpty() || !isNewer(ver, current)) return@withContext null
            val assets = o.optJSONArray("assets") ?: return@withContext null
            for (i in 0 until assets.length()) {
                val a = assets.getJSONObject(i)
                if (a.optString("name") != ASSET) continue
                val digest = a.optString("digest", "")
                return@withContext Release(ver, a.getString("browser_download_url"), a.optLong("size", -1),
                    if (digest.startsWith("sha256:")) digest.removePrefix("sha256:").lowercase() else null)
            }
            null
        }
    }

    // TODO(플레이 출시 후): object PlayUpdateSource : UpdateSource { ... AppUpdateManager.appUpdateInfo ... }

    val available = MutableStateFlow<Release?>(null)
    /** 진행 안내 (빈 문자열이면 숨김) */
    val status = MutableStateFlow("")
    val busy = MutableStateFlow(false)

    private fun prefs(ctx: Context) = ctx.getSharedPreferences("sseudam", Context.MODE_PRIVATE)
    fun autoCheck(ctx: Context) = prefs(ctx).getBoolean("autoUpdate", true)
    fun setAutoCheck(ctx: Context, on: Boolean) { prefs(ctx).edit().putBoolean("autoUpdate", on).apply(); if (!on) available.value = null }

    fun currentVersion(ctx: Context): String =
        runCatching { ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName }.getOrNull() ?: "0"

    fun installedFromPlay(ctx: Context): Boolean = runCatching {
        val p = if (Build.VERSION.SDK_INT >= 30) ctx.packageManager.getInstallSourceInfo(ctx.packageName).installingPackageName
        else @Suppress("DEPRECATION") ctx.packageManager.getInstallerPackageName(ctx.packageName)
        p == "com.android.vending"
    }.getOrDefault(false)

    private fun source(ctx: Context): UpdateSource? = if (installedFromPlay(ctx)) null /* TODO: PlayUpdateSource */ else GitHubSource

    fun isNewer(a: String, b: String): Boolean {
        fun parts(s: String) = s.split('.', '-').map { p -> p.takeWhile { it.isDigit() }.toIntOrNull() ?: 0 }
        val x = parts(a); val y = parts(b)
        for (i in 0 until maxOf(x.size, y.size)) {
            val d = x.getOrElse(i) { 0 } - y.getOrElse(i) { 0 }
            if (d != 0) return d > 0
        }
        return false
    }

    /** 앱을 열 때: 하루에 한 번까지만 (force면 바로) */
    suspend fun check(ctx: Context, force: Boolean = false): Release? {
        if (!force && !autoCheck(ctx)) return null
        val p = prefs(ctx)
        val now = System.currentTimeMillis()
        if (!force && now - p.getLong("updateCheckedAt", 0) < 24 * 3600_000L) {
            // 오늘 이미 확인했으면 기억해 둔 결과만 다시 보여 줌
            val v = p.getString("updateVer", null)
            if (v != null && isNewer(v, currentVersion(ctx))) {
                available.value = Release(v, p.getString("updateUrl", "") ?: "", p.getLong("updateSize", -1), p.getString("updateSha", null))
            }
            return available.value
        }
        val src = source(ctx) ?: return null
        val r = runCatching { src.latest(ctx, currentVersion(ctx)) }.getOrNull()
        p.edit().putLong("updateCheckedAt", now).apply {
            if (r != null) putString("updateVer", r.version).putString("updateUrl", r.url).putLong("updateSize", r.size).putString("updateSha", r.sha256)
            else remove("updateVer")
        }.apply()
        available.value = r
        return r
    }

    /** 받기 → 크기·sha256 확인 → 설치 화면 */
    suspend fun downloadAndInstall(ctx: Context, r: Release) {
        if (busy.value) return
        busy.value = true
        try {
            status.value = "새 버전을 받는 중…"
            val f = downloaded(ctx, r) ?: withContext(Dispatchers.IO) { download(ctx, r) }
            status.value = ""
            install(ctx, f)
        } catch (e: Exception) {
            status.value = "받지 못했어요: ${e.message ?: "알 수 없는 오류"} · 잠시 뒤 다시 눌러 주세요"
        } finally { busy.value = false }
    }

    private fun download(ctx: Context, r: Release): File {
        val dir = File(ctx.cacheDir, "updates").apply { mkdirs() }
        dir.listFiles()?.forEach { it.delete() }
        val f = File(dir, "Sseudam-${r.version}.apk")
        var c = URL(r.url).openConnection() as HttpURLConnection
        c.instanceFollowRedirects = true; c.connectTimeout = 20000; c.readTimeout = 60000
        c.setRequestProperty("User-Agent", "Sseudam-Android")
        var hops = 0
        while (c.responseCode in 301..308 && hops < 5) {
            val loc = c.getHeaderField("Location") ?: break
            c = URL(URL(r.url), loc).openConnection() as HttpURLConnection
            c.connectTimeout = 20000; c.readTimeout = 60000; hops++
        }
        if (c.responseCode != 200) throw Exception("서버 응답 ${c.responseCode}")
        val md = MessageDigest.getInstance("SHA-256")
        var total = 0L
        val len = c.contentLengthLong
        c.inputStream.use { inp ->
            f.outputStream().use { out ->
                val buf = ByteArray(64 * 1024)
                var lastPct = -1
                while (true) {
                    val n = inp.read(buf); if (n < 0) break
                    out.write(buf, 0, n); md.update(buf, 0, n); total += n
                    val size = if (r.size > 0) r.size else len
                    if (size > 0) {
                        val pct = (total * 100 / size).toInt()
                        if (pct != lastPct) { lastPct = pct; status.value = "새 버전을 받는 중… $pct%" }
                    }
                }
            }
        }
        if (r.size > 0 && total != r.size) { f.delete(); throw Exception("파일 크기가 맞지 않아요") }
        if (r.sha256 != null) {
            val got = md.digest().joinToString("") { "%02x".format(it) }
            if (got != r.sha256) { f.delete(); throw Exception("파일 확인(sha256)에 실패했어요") }
        }
        return f
    }

    /** '알 수 없는 앱 설치'를 허용해야 하면 설정 화면부터 */
    fun canInstall(ctx: Context): Boolean = Build.VERSION.SDK_INT < 26 || ctx.packageManager.canRequestPackageInstalls()

    fun openInstallPermission(ctx: Context) {
        if (Build.VERSION.SDK_INT >= 26) runCatching {
            ctx.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + ctx.packageName))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
    }

    fun install(ctx: Context, f: File) {
        if (!canInstall(ctx)) {
            status.value = "설정에서 ‘이 출처 허용’을 켠 뒤 돌아와서 ‘업데이트’를 한 번 더 눌러 주세요."
            openInstallPermission(ctx)
            return
        }
        val uri = FileProvider.getUriForFile(ctx, ctx.packageName + ".files", f)
        ctx.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    /** 받아 둔 파일이 있으면 다시 받지 않고 설치 */
    fun downloaded(ctx: Context, r: Release): File? = File(ctx.cacheDir, "updates/Sseudam-${r.version}.apk").takeIf { it.exists() && (r.size <= 0 || it.length() == r.size) }
}
