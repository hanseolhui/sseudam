package kr.sseudam.app

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID

enum class Sync { OFF, PENDING, DONE, FAILED }

/** 녹음 중에 누른 표시: 학생 이름표(이제부터 이 학생 이야기) 또는 ⭐(중요한 순간). t = 녹음 시작부터 초 */
data class Marker(val t: Double, val student: String? = null, val star: Boolean = false) {
    fun toJson(): JSONObject = JSONObject().put("t", t).put("star", star).apply { student?.let { put("student", it) } }
    companion object {
        fun from(o: JSONObject) = Marker(o.optDouble("t", 0.0), o.optString("student").ifEmpty { null }, o.optBoolean("star"))
    }
}

/** 기록함 한 줄: 녹음(m4a) 또는 한 줄 메모(txt). 둘 다 선생님 구글 드라이브를 거쳐 컴퓨터로 간다. */
data class Recording(
    val id: String = UUID.randomUUID().toString(),
    val fileName: String,
    val createdAt: Long,
    val durationSec: Double,
    val kind: String,
    val memo: String,
    val google: Sync = Sync.OFF,
    val lastError: String = "",
    val type: String = "audio",          // audio | text
    val text: String = "",
    /** 폰에서 학생별로 나눈 결과 (null = 아직 나누지 않음) */
    val splitNames: List<String>? = null,
    /** 학생 이름을 못 찾은 앞부분 (선생님이 학생을 골라 줄 수 있게) */
    val splitLeftover: String = "",
    val splitUnsure: Int = 0,
    /** 녹음하면서 누른 이름표·⭐, 고른 반(학급 uid)·교시 — 컴퓨터가 이 표시대로 학생별로 나눈다 */
    val markers: List<Marker> = emptyList(),
    val classUid: String? = null,
    val period: Int? = null,
) {
    val isAudio: Boolean get() = type == "audio"

    fun toJson(): JSONObject = JSONObject().put("id", id).put("fileName", fileName).put("createdAt", createdAt)
        .put("duration", durationSec).put("kind", kind).put("memo", memo).put("google", google.name).put("lastError", lastError)
        .put("type", type).put("text", text).put("splitLeftover", splitLeftover).put("splitUnsure", splitUnsure)
        .apply { splitNames?.let { put("splitNames", JSONArray(it)) } }
        .apply { if (markers.isNotEmpty()) put("markers", JSONArray(markers.map { it.toJson() })) }
        .apply { classUid?.let { put("classUid", it) }; period?.let { put("period", it) } }

    companion object {
        fun from(o: JSONObject) = Recording(
            o.getString("id"), o.getString("fileName"), o.getLong("createdAt"), o.optDouble("duration", 0.0),
            o.optString("kind", "수업"), o.optString("memo", ""), Sync.valueOf(o.optString("google", "OFF")),
            o.optString("lastError", ""), o.optString("type", "audio"), o.optString("text", ""),
            o.optJSONArray("splitNames")?.let { a -> (0 until a.length()).map { a.getString(it) } },
            o.optString("splitLeftover", ""), o.optInt("splitUnsure", 0),
            o.optJSONArray("markers")?.let { a -> (0 until a.length()).map { Marker.from(a.getJSONObject(it)) } } ?: emptyList(),
            o.optString("classUid").ifEmpty { null }, if (o.has("period")) o.optInt("period") else null,
        )
    }
}

/** 녹음·메모 목록과 연결 정보. 녹음은 선생님이 지우기 전까지 휴대폰에 보관한다(학기말 아카이빙). */
object Store {
    private val _items = MutableStateFlow<List<Recording>>(emptyList())
    val items: StateFlow<List<Recording>> = _items
    private val _paired = MutableStateFlow(false)
    val paired: StateFlow<Boolean> = _paired
    private lateinit var ctx: Context

    fun init(c: Context) {
        if (::ctx.isInitialized) return
        ctx = c.applicationContext
        DataStore.init(ctx)
        Relay.init(ctx)
        load()
        refreshPaired()
    }

    val folder: File get() = File(ctx.filesDir, "recordings").apply { mkdirs() }
    private val index: File get() = File(folder, "index.json")
    private val prefs get() = ctx.getSharedPreferences("sseudam", Context.MODE_PRIVATE)

    fun file(r: Recording) = File(folder, r.fileName)
    /** 컴퓨터와 이어졌는지: QR 연동(새 방식) 또는 구글 드라이브(예전 방식) */
    fun refreshPaired() { _paired.value = Relay.paired() || (googleUrl().isNotEmpty() && googleToken().isNotEmpty()) }

    fun pairRelay(p: Relay.Pair) {
        Relay.pair(p)
        prefs.edit().putString("teacherName", p.name).apply()
        refreshPaired()
        save(_items.value.map { if (it.google == Sync.OFF) it.copy(google = Sync.PENDING) else it })   // 이어지기 전 녹음도 보내기
        UploadWorker.enqueue(ctx)
    }

    fun googleUrl(): String = prefs.getString("googleUrl", "") ?: ""
    fun googleToken(): String = prefs.getString("googleToken", "") ?: ""
    fun teacherName(): String = prefs.getString("teacherName", "") ?: ""

    @Synchronized private fun load() {
        val list = mutableListOf<Recording>()
        if (index.exists()) runCatching {
            val arr = JSONArray(index.readText())
            for (i in 0 until arr.length()) list += Recording.from(arr.getJSONObject(i))
        }
        _items.value = list.filter { file(it).exists() }
    }

    @Synchronized private fun save(list: List<Recording>) {
        _items.value = list
        val arr = JSONArray(); list.forEach { arr.put(it.toJson()) }
        val tmp = File(folder, "index.json.tmp"); tmp.writeText(arr.toString()); tmp.renameTo(index)
    }

    private fun baseName(at: Long, kind: String, memo: String, suffix: String = ""): String {
        var name = "쓰담 " + SimpleDateFormat("yyyyMMdd HHmm", Locale.KOREA).format(Date(at))
        if (kind == "상담") name += " 상담"
        if (suffix.isNotEmpty()) name += " $suffix"
        val clean = memo.replace(Regex("[/\\\\:*?\"<>|\\n\\r\\t]"), " ").trim().take(30)
        if (clean.isNotEmpty()) name += " $clean"
        return name
    }

    private fun uniqueFile(name: String, ext: String): String {
        var fileName = "$name.$ext"; var i = 2
        while (File(folder, fileName).exists()) { fileName = "$name ($i).$ext"; i++ }
        return fileName
    }

    fun add(temp: File, durationSec: Double, kind: String, memo: String, at: Long,
            markers: List<Marker> = emptyList(), classUid: String? = null, period: Int? = null) {
        val fileName = uniqueFile(baseName(at, kind, memo), "m4a")
        temp.copyTo(File(folder, fileName)); temp.delete()
        val r = Recording(fileName = fileName, createdAt = at, durationSec = durationSec, kind = kind, memo = memo,
            google = if (_paired.value) Sync.PENDING else Sync.OFF, markers = markers, classUid = classUid, period = period)
        save(listOf(r) + _items.value)
        UploadWorker.enqueue(ctx)
    }

    /** 다른 녹음 앱(갤럭시 음성 녹음 등)에서 '공유 → 쓰담' 으로 받은 파일 */
    fun addShared(input: java.io.InputStream, displayName: String, at: Long = System.currentTimeMillis()): Recording {
        val ext = displayName.substringAfterLast('.', "m4a").lowercase().take(5).ifEmpty { "m4a" }
        val base = displayName.substringBeforeLast('.').replace(Regex("[/\\\\:*?\"<>|\\n\\r\\t]"), " ").trim().take(40).ifEmpty { "공유받은 녹음" }
        val fileName = uniqueFile(base, ext)
        val f = File(folder, fileName)
        input.use { inp -> f.outputStream().use { inp.copyTo(it) } }
        val dur = runCatching {
            android.media.MediaMetadataRetriever().use { mr -> mr.setDataSource(f.path); (mr.extractMetadata(android.media.MediaMetadataRetriever.METADATA_KEY_DURATION)?.toDouble() ?: 0.0) / 1000 }
        }.getOrDefault(0.0)
        val r = Recording(fileName = fileName, createdAt = at, durationSec = dur, kind = "수업", memo = base,
            google = if (_paired.value) Sync.PENDING else Sync.OFF)
        save(listOf(r) + _items.value)
        UploadWorker.enqueue(ctx)
        return r
    }

    /** 한 줄 메모 저장 → 텍스트 파일로 컴퓨터에 전달 + 명단이 있으면 폰에서 바로 학생별로 나눔 */
    fun addText(text: String, kind: String = "수업", at: Long = System.currentTimeMillis()): Recording? {
        val t = text.trim()
        if (t.isEmpty()) return null
        val fileName = uniqueFile(baseName(at, kind, "", "메모"), "txt")
        File(folder, fileName).writeText(t)
        val r = Recording(fileName = fileName, createdAt = at, durationSec = 0.0, kind = kind, memo = "", type = "text", text = t,
            google = if (_paired.value) Sync.PENDING else Sync.OFF)
        save(listOf(r) + _items.value)
        UploadWorker.enqueue(ctx)
        splitToStudents(r, force = false)
        return _items.value.firstOrNull { it.id == r.id }
    }

    fun get(id: String): Recording? = _items.value.firstOrNull { it.id == id }

    /** 글(메모)을 학생별 기록으로. 맥은 같은 파일을 받으면 자기 쪽에서 다시 나눈다 (폰 기록은 '기록 파일'로 따로 옮김) */
    fun splitToStudents(e: Recording, force: Boolean) {
        val cur = get(e.id) ?: return
        val text = cur.text
        if (text.isBlank()) return
        if (!(force || DataStore.splitOnPhone.value) || !DataStore.db.value.hasRoster) return
        val r = DataStore.split(text, cur.createdAt, cur.kind, cur.fileName, cur.memo, force)
        update(cur.copy(splitNames = r.names, splitLeftover = r.leftover, splitUnsure = r.unsure))
    }

    /** 이름 없는 부분이 학생 이야기가 아니면 치우기 (원본 글은 그대로) */
    fun dropLeftover(e: Recording) { get(e.id)?.let { update(it.copy(splitLeftover = "")) } }

    /** 학생을 못 찾은 부분을 선생님이 고른 학생에게 담기 */
    fun assignLeftover(e: Recording, s: SStudent) {
        val cur = get(e.id) ?: return
        if (cur.splitLeftover.isEmpty()) return
        DataStore.addNote(s, cur.splitLeftover, cur.createdAt, cur.kind, cur.fileName)
        val names = (cur.splitNames ?: emptyList()).toMutableList()
        if (s.displayName !in names) names.add(0, s.displayName)
        update(cur.copy(splitLeftover = "", splitNames = names))
    }

    /** 나눈 게 없을 때 글 전체를 한 학생에게 */
    fun assignWhole(e: Recording, s: SStudent) {
        val cur = get(e.id) ?: return
        DataStore.addNote(s, cur.text, cur.createdAt, cur.kind, cur.fileName)
        val names = (cur.splitNames ?: emptyList()).toMutableList()
        if (s.displayName !in names) names.add(0, s.displayName)
        update(cur.copy(splitLeftover = "", splitNames = names))
    }

    fun update(r: Recording) = save(_items.value.map { if (it.id == r.id) r else it })

    fun delete(r: Recording) { file(r).delete(); save(_items.value.filter { it.id != r.id }) }

    fun pair(url: String, token: String, name: String) {
        prefs.edit().putString("googleUrl", url).putString("googleToken", token).putString("teacherName", name).apply()
        _paired.value = true
        save(_items.value.map { if (it.google == Sync.OFF) it.copy(google = Sync.PENDING) else it })
        UploadWorker.enqueue(ctx)
    }

    fun unpair() {
        if (Relay.paired()) Thread { Relay.disconnectRemote(); Relay.unpair() }.start() else Relay.unpair()
        prefs.edit().remove("googleUrl").remove("googleToken").apply()
        _paired.value = false
        save(_items.value.map { if (it.google != Sync.DONE) it.copy(google = Sync.OFF) else it })
    }

    /** sseudam://pair?u=...&t=...&n=...  (예전 seteuk:// 도 허용) */
    fun parsePairing(text: String): Triple<String, String, String>? {
        val uri = runCatching { android.net.Uri.parse(text.trim()) }.getOrNull() ?: return null
        if (uri.scheme !in listOf("sseudam", "seteuk") || uri.host != "pair") return null
        val u = uri.getQueryParameter("u") ?: return null
        val t = uri.getQueryParameter("t") ?: return null
        if (!u.startsWith("https://") || t.isEmpty()) return null
        return Triple(u, t, uri.getQueryParameter("n") ?: "")
    }
}
