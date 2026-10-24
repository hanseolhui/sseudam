package kr.sseudam.app

import android.content.Context
import android.os.Build
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.security.SecureRandom
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * QR 연동 — 컴퓨터(맥·윈도우)의 쓰담이 보여 준 QR 하나로 이어진다.
 * 녹음·학생 기록은 QR 안의 열쇠로 암호화해서 중계 서버를 거친다 (서버는 내용을 볼 수 없음).
 * 암호 방식은 컴퓨터 쓰담 app/relay.py 와 똑같다:
 *   kEnc = HMAC(열쇠,"sseudam-enc"), kMac = HMAC(열쇠,"sseudam-mac"), 토큰 = hex(HMAC(열쇠,"sseudam-relay-auth"))
 *   덩어리 = "SSD1" + nonce(16) + (평문 XOR HMAC(kEnc, nonce‖블록번호)) + HMAC(kMac, "SSD1"‖nonce‖암호문)
 *   평문 = 메타 JSON 길이(4) + 메타 JSON + 본문
 */
object Relay {
    private val MAGIC = "SSD1".toByteArray()
    private lateinit var ctx: Context
    private val prefs get() = ctx.getSharedPreferences("sseudam", Context.MODE_PRIVATE)

    fun init(c: Context) { if (!::ctx.isInitialized) ctx = c.applicationContext }

    data class Pair(val url: String, val channel: String, val key: ByteArray, val name: String)

    fun parse(text: String): Pair? {
        val uri = runCatching { android.net.Uri.parse(text.trim()) }.getOrNull() ?: return null
        if (uri.scheme != "sseudam" || uri.host != "pair" || uri.getQueryParameter("v") != "1") return null
        val u = uri.getQueryParameter("u") ?: return null
        val c = uri.getQueryParameter("c") ?: return null
        val k = uri.getQueryParameter("k") ?: return null
        if (!u.startsWith("https://") || !Regex("[0-9a-f]{32}").matches(c)) return null
        val key = runCatching { Base64.decode(k, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP) }.getOrNull() ?: return null
        if (key.size != 32) return null
        return Pair(u.trimEnd('/'), c, key, uri.getQueryParameter("n") ?: "")
    }

    fun pair(p: Pair) {
        prefs.edit().putString("relayUrl", p.url).putString("relayCh", p.channel)
            .putString("relayKey", Base64.encodeToString(p.key, Base64.NO_WRAP)).putString("relayPc", p.name)
            .remove("relayDocSig").apply()
    }

    fun unpair() { prefs.edit().remove("relayUrl").remove("relayCh").remove("relayKey").remove("relayPc").remove("relayDocSig").apply() }
    fun paired(): Boolean = ::ctx.isInitialized && (prefs.getString("relayCh", "") ?: "").isNotEmpty()
    fun pcName(): String = prefs.getString("relayPc", "") ?: ""

    private fun creds(): Triple<String, String, ByteArray>? {
        val u = prefs.getString("relayUrl", "") ?: ""; val c = prefs.getString("relayCh", "") ?: ""; val k = prefs.getString("relayKey", "") ?: ""
        if (u.isEmpty() || c.isEmpty() || k.isEmpty()) return null
        return Triple(u, c, Base64.decode(k, Base64.NO_WRAP))
    }

    // ── 암호 ──
    private fun hmac(key: ByteArray, data: ByteArray): ByteArray =
        Mac.getInstance("HmacSHA256").apply { init(SecretKeySpec(key, "HmacSHA256")) }.doFinal(data)

    private fun hex(b: ByteArray) = b.joinToString("") { "%02x".format(it) }
    private fun token(master: ByteArray) = hex(hmac(master, "sseudam-relay-auth".toByteArray()))

    private fun xorStream(kEnc: ByteArray, nonce: ByteArray, data: ByteArray): ByteArray {
        val out = ByteArray(data.size)
        val mac = Mac.getInstance("HmacSHA256").apply { init(SecretKeySpec(kEnc, "HmacSHA256")) }
        var block = 0L; var i = 0
        val ctr = ByteArray(8)
        while (i < data.size) {
            for (j in 0 until 8) ctr[j] = (block ushr (56 - 8 * j)).toByte()
            mac.update(nonce); val ks = mac.doFinal(ctr)
            var j = 0
            while (j < ks.size && i < data.size) { out[i] = (data[i].toInt() xor ks[j].toInt()).toByte(); i++; j++ }
            block++
        }
        return out
    }

    fun seal(master: ByteArray, meta: JSONObject, body: ByteArray = ByteArray(0)): ByteArray {
        val kEnc = hmac(master, "sseudam-enc".toByteArray()); val kMac = hmac(master, "sseudam-mac".toByteArray())
        val m = meta.toString().toByteArray(Charsets.UTF_8)
        val plain = ByteArrayOutputStream().apply {
            write(byteArrayOf((m.size ushr 24).toByte(), (m.size ushr 16).toByte(), (m.size ushr 8).toByte(), m.size.toByte()))
            write(m); write(body)
        }.toByteArray()
        val nonce = ByteArray(16).also { SecureRandom().nextBytes(it) }
        val ct = xorStream(kEnc, nonce, plain)
        val tag = hmac(kMac, MAGIC + nonce + ct)
        return MAGIC + nonce + ct + tag
    }

    fun open(master: ByteArray, blob: ByteArray): kotlin.Pair<JSONObject, ByteArray> {
        require(blob.size >= 52 && blob.copyOfRange(0, 4).contentEquals(MAGIC)) { "쓰담 연동 형식이 아니에요" }
        val kEnc = hmac(master, "sseudam-enc".toByteArray()); val kMac = hmac(master, "sseudam-mac".toByteArray())
        val nonce = blob.copyOfRange(4, 20); val ct = blob.copyOfRange(20, blob.size - 32); val tag = blob.copyOfRange(blob.size - 32, blob.size)
        require(MessageDigest.isEqual(tag, hmac(kMac, MAGIC + nonce + ct))) { "열쇠가 맞지 않아요" }
        val plain = xorStream(kEnc, nonce, ct)
        val n = ((plain[0].toInt() and 0xff) shl 24) or ((plain[1].toInt() and 0xff) shl 16) or ((plain[2].toInt() and 0xff) shl 8) or (plain[3].toInt() and 0xff)
        return JSONObject(String(plain, 4, n, Charsets.UTF_8)) to plain.copyOfRange(4 + n, plain.size)
    }

    // ── 중계 서버 ──
    private fun req(method: String, path: String, body: ByteArray? = null): ByteArray {
        val (url, ch, master) = creds() ?: throw IllegalStateException("컴퓨터와 연결되어 있지 않아요")
        val conn = URL("$url/v1/$ch$path").openConnection() as HttpURLConnection
        conn.requestMethod = method; conn.connectTimeout = 30000; conn.readTimeout = 300000
        conn.setRequestProperty("x-relay-token", token(master))
        if (body != null) {
            conn.doOutput = true; conn.setFixedLengthStreamingMode(body.size)
            conn.setRequestProperty("Content-Type", "application/octet-stream")
            conn.outputStream.use { it.write(body) }
        }
        val code = conn.responseCode
        if (code == 404) throw NoSuchElementException()
        if (code !in 200..299) throw Exception("연결 서버 오류 ($code)")
        return conn.inputStream.use { it.readBytes() }
    }

    private fun deviceName() = (Build.MODEL ?: "Android").take(40)

    /** 녹음(또는 한 줄 메모) 하나를 컴퓨터로 */
    fun uploadRecording(r: Recording, bytes: ByteArray) {
        val (_, _, master) = creds() ?: return
        val df = SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.KOREA)
        val meta = JSONObject().put("type", "rec").put("name", r.fileName).put("ext", "." + r.fileName.substringAfterLast('.', "m4a"))
            .put("recorded_at", df.format(Date(r.createdAt))).put("kind", r.kind).put("title", r.fileName.substringBeforeLast('.'))
            .put("memo", r.memo).put("transcript", if (r.isAudio) "" else r.text)
            .put("device", DataStore.deviceId).put("device_name", deviceName()).put("duration", r.durationSec)
        // 녹음하면서 누른 학생 이름표·⭐, 고른 반·교시 — 컴퓨터가 이 표시대로 학생별로 나눈다
        val db = DataStore.db.value
        if (r.markers.isNotEmpty()) meta.put("markers", JSONArray(r.markers.map { m ->
            JSONObject().put("t", m.t).put("star", m.star).apply {
                m.student?.let { uid -> put("student_uid", uid).put("name", db.students.firstOrNull { it.uid == uid }?.displayName ?: "") }
            }
        }))
        r.classUid?.let { c -> meta.put("class_uid", c).put("class_title", db.classes.firstOrNull { it.uid == c }?.title ?: "") }
        r.period?.let { meta.put("period", it) }
        req("PUT", "/pc/${uploadName(r)}", seal(master, meta, if (r.isAudio) bytes else ByteArray(0)))
    }

    /** 중계 상자에 올리는 이름 — 컴퓨터가 '받음' 목록에 이 이름을 적어 돌려준다 */
    fun uploadName(r: Recording) = "rec-" + r.createdAt + "-" + r.id.take(8) + ".bin"

    /** 컴퓨터가 받아 간 녹음 이름들 (컴퓨터 쓰담이 phone/ack-<기기>.bin 에 올려 둠) */
    fun receivedNames(): Set<String> {
        val (_, _, master) = creds() ?: return emptySet()
        val dev = DataStore.deviceId.filter { it.code < 128 && (it.isLetterOrDigit() || it == '-' || it == '_') }.take(40).ifEmpty { "phone" }
        return try {
            val (_, body) = open(master, req("GET", "/phone/ack-$dev.bin"))
            val a = JSONObject(String(body, Charsets.UTF_8)).optJSONArray("received") ?: return emptySet()
            (0 until a.length()).map { a.getString(it) }.toSet()
        } catch (e: NoSuchElementException) { emptySet() }
    }

    /** 학생 기록 맞추기: 내 기록 올리기(바뀐 경우만) + 컴퓨터 기록 받아 합치기. 받아서 바뀐 수 반환 */
    fun syncDocs(): Int {
        val (_, _, master) = creds() ?: return 0
        val doc = DataStore.makeDocJson()
        val sig = hex(MessageDigest.getInstance("SHA-256").digest(JSONObject(doc.toString()).apply { remove("updated_at") }.toString().toByteArray()))
        if (prefs.getString("relayDocSig", "") != sig) {
            val meta = JSONObject().put("type", "doc").put("device", DataStore.deviceId).put("device_name", deviceName())
            req("PUT", "/pc/doc-${DataStore.deviceId.take(40)}.bin", seal(master, meta, doc.toString().toByteArray(Charsets.UTF_8)))
            prefs.edit().putString("relayDocSig", sig).apply()
        }
        return try {
            val (_, body) = open(master, req("GET", "/phone/doc-pc.bin"))
            DataStore.importDoc(String(body, Charsets.UTF_8))
        } catch (e: NoSuchElementException) { 0 }
    }

    fun disconnectRemote() { runCatching { req("DELETE", "") } }
}
