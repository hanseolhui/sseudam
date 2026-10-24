package kr.sseudam.app

import android.content.Context
import android.os.Build
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.Locale

/**
 * 학급·학생·관찰기록·초안 (녹음 원본은 빼고 글만). 맥 app/sync_text.py 와 같은 SyncDoc 형식으로
 * 앱 저장소(files/data.json)에 보관한다. 안드로이드는 iCloud가 없어서, 맥과는
 * '기록 파일 내보내기/가져오기'(같은 형식의 .json)로 주고받는다. 합칠 때는 기록마다 updated_at이 큰 쪽.
 */
object DataStore {
    private val _db = MutableStateFlow(DB())
    val db: StateFlow<DB> = _db
    private val _splitOnPhone = MutableStateFlow(true)
    val splitOnPhone: StateFlow<Boolean> = _splitOnPhone
    private lateinit var ctx: Context

    fun init(c: Context) {
        if (::ctx.isInitialized) return
        ctx = c.applicationContext
        _splitOnPhone.value = prefs.getBoolean("splitOnPhone", true)
        load()
    }

    private val prefs get() = ctx.getSharedPreferences("sseudam", Context.MODE_PRIVATE)
    private val file: File get() = File(ctx.filesDir, "data.json")

    val deviceId: String
        get() {
            prefs.getString("deviceId", null)?.let { return it }
            val d = "android-" + java.util.UUID.randomUUID().toString().replace("-", "").take(12)
            prefs.edit().putString("deviceId", d).apply()
            return d
        }

    fun setSplitOnPhone(on: Boolean) { prefs.edit().putBoolean("splitOnPhone", on).apply(); _splitOnPhone.value = on }

    // ───────── 고치기 ─────────
    @Synchronized private fun mutate(f: (DB) -> DB) {
        _db.value = f(_db.value)
        save()
    }

    private fun <T> List<T>.upsert(item: T, id: (T) -> String): List<T> {
        val i = indexOfFirst { id(it) == id(item) }
        return if (i >= 0) toMutableList().also { it[i] = item } else this + item
    }
    private fun DB.withClass(c: SClass) = copy(classes = classes.upsert(c) { it.uid })
    private fun DB.withStudent(s: SStudent) = copy(students = students.upsert(s) { it.uid })
    private fun DB.withNote(n: SNote) = copy(notes = notes.upsert(n) { it.uid })
    private fun DB.withDraft(d: SDraft) = copy(drafts = drafts.upsert(d) { it.uid })
    // 지움 표시만 남긴다 (다른 기기에도 지워지도록)
    private fun DB.dropNote(uid: String) = if (notes.any { it.uid == uid }) withNote(SNote(uid, nowSec(), deleted = true)) else this
    private fun DB.dropStudent(uid: String) = if (students.any { it.uid == uid }) withStudent(SStudent(uid, nowSec(), deleted = true)) else this

    fun addClass(grade: Int?, classNo: Int?, subject: String, kind: String): SClass {
        val (y, sem) = currentTerm()
        val uid = Uids.classUid(y, sem, grade, classNo, subject, kind)
        val base = listOfNotNull(grade?.let { "$it-" }, classNo?.toString()).joinToString("")
        val label = when (kind) {
            "담임" -> "$base (담임)"
            "동아리" -> "동아리 $subject"
            else -> listOf(base, subject).filter { it.isNotEmpty() }.joinToString(" ")
        }
        val c = SClass(uid, nowSec(), year = y, semester = sem, grade = grade, classNo = classNo, subject = subject, kind = kind, label = label)
        mutate { it.withClass(c) }
        return c
    }

    /** 명단 붙여넣기: 줄마다 "번호 이름" 또는 "이름". 이미 있는 이름은 건너뜀. 넣은 수 반환 */
    fun addStudents(text: String, c: SClass): Int {
        var added = 0
        mutate { db0 ->
            var db = db0
            var nextNo = (db.studentsIn(c).mapNotNull { it.number }.maxOrNull() ?: 0) + 1
            for ((number, name) in Roster.parse(text)) {
                val uid = Uids.studentUid(c.uid, name)
                val cur = db.students.firstOrNull { it.uid == uid }
                if (cur != null && !cur.deleted) continue
                val no = number ?: nextNo
                nextNo = maxOf(nextNo, no + 1)
                db = db.withStudent(SStudent(uid, nowSec(), classUid = c.uid, number = no, name = name, aliases = ""))
                added++
            }
            db
        }
        return added
    }

    fun updateStudent(s: SStudent, name: String, number: Int?, aliases: String) = mutate {
        it.withStudent(s.copy(name = name.trim(), number = number, aliases = aliases.trim(), updatedAt = nowSec()))
    }

    fun deleteStudent(s: SStudent) = mutate { db0 ->
        var db = db0
        for (n in db.notesOf(s)) db = db.dropNote(n.uid)
        db.dropStudent(s.uid)
    }

    fun deleteClass(c: SClass) = mutate { db0 ->
        var db = db0
        for (s in db.studentsIn(c)) {
            for (n in db.notesOf(s)) db = db.dropNote(n.uid)
            db = db.dropStudent(s.uid)
        }
        db.withClass(SClass(c.uid, nowSec(), deleted = true))
    }

    private fun newNote(s: SStudent, content: String, dateMs: Long, kind: String, source: String) =
        SNote(Uids.newUid("n-"), nowSec(), studentUid = s.uid, date = isoDate(dateMs), kind = kind, area = "", category = "",
            content = content, source = source, useInDraft = 1)

    fun addNote(s: SStudent, content: String, dateMs: Long = System.currentTimeMillis(), kind: String = "수업", source: String = ""): SNote {
        val n = newNote(s, content, dateMs, kind, source)
        mutate { it.withNote(n) }
        return n
    }

    fun editNote(n: SNote, content: String) = mutate { it.withNote(n.copy(content = content, updatedAt = nowSec())) }
    fun deleteNote(n: SNote) = mutate { it.dropNote(n.uid) }
    fun setArea(n: SNote, area: String) = mutate { it.withNote(n.copy(area = area, updatedAt = nowSec())) }
    /** 기록을 다른 학생에게 옮긴다 (동명이인 확인도 이걸로 끝) */
    fun moveNote(n: SNote, s: SStudent) = mutate { it.withNote(n.copy(studentUid = s.uid, category = "", updatedAt = nowSec())) }
    /** 확인만 (지금 학생이 맞음) */
    fun confirmNote(n: SNote) = mutate { it.withNote(n.copy(category = "", updatedAt = nowSec())) }
    /** 두 기록을 하나로: other 내용을 into 뒤에 붙이고 other는 지운다 */
    fun mergeNotes(other: SNote, into: SNote) = mutate {
        val t = into.copy(content = listOf(into.content ?: "", other.content ?: "").filter { s -> s.isNotEmpty() }.joinToString(" "),
            updatedAt = nowSec())
        it.withNote(t).dropNote(other.uid)
    }

    /** 같은 학생이 둘로 들어간 경우: from의 기록·초안을 into로 옮기고 from 이름은 별칭으로 남긴다 */
    fun mergeStudent(from: SStudent, into: SStudent) = mutate { db0 ->
        var db = db0
        val t = nowSec()
        for (n in db.notes.filter { !it.deleted && it.studentUid == from.uid }) db = db.withNote(n.copy(studentUid = into.uid, updatedAt = t))
        for (d in db.drafts.filter { !it.deleted && it.studentUid == from.uid }) db = db.withDraft(d.copy(studentUid = into.uid, updatedAt = t))
        val al = (into.aliases ?: "").split(",").map { it.trim() }.filter { it.isNotEmpty() }.toSortedSet()
        if (from.displayName != into.displayName) al += from.displayName
        db = db.withStudent(into.copy(aliases = al.joinToString(","), updatedAt = t))
        db.dropStudent(from.uid)
    }

    fun addDraft(s: SStudent, area: String, content: String) = mutate {
        it.withDraft(SDraft(Uids.newUid("d-"), nowSec(), studentUid = s.uid, area = area, content = content, status = "초안"))
    }
    fun deleteDraft(d: SDraft) = mutate { it.withDraft(SDraft(d.uid, nowSec(), deleted = true)) }

    // ───────── 학생별로 나누기 ─────────
    data class SplitResult(val count: Int, val names: List<String>, val leftover: String, val unsure: Int)

    /** 받아쓴 글·메모를 학생별 기록으로 (명단이 있을 때만). force면 이 출처의 조각을 지우고 처음부터 */
    fun split(text: String, dateMs: Long, kind: String, source: String, hint: String = "", force: Boolean = false): SplitResult {
        val empty = SplitResult(0, emptyList(), text, 0)
        val cur = _db.value
        if (!cur.hasRoster || text.isBlank() || !(force || (_splitOnPhone.value && cur.notesForSource(source).isEmpty()))) return empty
        var result = empty
        mutate { db0 ->
            var db = db0
            if (force) for (n in db.notesForSource(source)) db = db.dropNote(n.uid)
            val r = Splitter.splitWithLeftover(text, hint, db.activeClasses, { db.studentsIn(it) }, if (kind == "상담") "담임" else "교과")
            val names = mutableListOf<String>()
            var unsure = 0
            for (b in r.blocks) {
                val s = db.student(b.studentUid) ?: continue
                var n = newNote(s, b.content, dateMs, kind, source)
                if (b.ambiguous) { n = n.copy(category = DB.UNSURE_TAG + ":" + b.candidates.joinToString(",")); unsure++ }
                db = db.withNote(n)
                if (s.displayName !in names) names += s.displayName
            }
            result = SplitResult(r.blocks.size, names, r.leftover, unsure)
            db
        }
        return result
    }

    // ───────── 저장 · 내보내기 · 가져오기 ─────────
    private fun load() {
        if (!file.exists()) return
        runCatching { parseDoc(JSONObject(file.readText())) }.getOrNull()?.let { _db.value = it }
    }

    @Synchronized private fun save() {
        val tmp = File(ctx.filesDir, "data.json.tmp")
        tmp.writeText(makeDoc().toString())
        tmp.renameTo(file)
    }

    fun makeDocJson(): JSONObject = makeDoc()

    fun makeDoc(): JSONObject {
        val db = _db.value
        return JSONObject()
            .put("format", "sseudam-sync").put("version", 1)
            .put("device", JSONObject().put("id", deviceId).put("name", Build.MODEL ?: "Android").put("kind", "android"))
            .put("updated_at", nowSec())
            .put("classes", JSONArray().apply { db.classes.forEach { put(SyncJson.cls(it)) } })
            .put("students", JSONArray().apply { db.students.forEach { put(SyncJson.student(it)) } })
            .put("notes", JSONArray().apply { db.notes.forEach { put(SyncJson.note(it)) } })
            .put("drafts", JSONArray().apply { db.drafts.forEach { put(SyncJson.draft(it)) } })
    }

    private fun parseDoc(o: JSONObject): DB {
        if (o.optString("format") != "sseudam-sync") throw IllegalArgumentException("쓰담 기록 파일이 아니에요.")
        fun <T> arr(k: String, f: (JSONObject) -> T): List<T> {
            val a = o.optJSONArray(k) ?: return emptyList()
            return (0 until a.length()).mapNotNull { a.optJSONObject(it)?.let { j -> runCatching { f(j) }.getOrNull() } }
        }
        return DB(arr("classes", SyncJson::readCls), arr("students", SyncJson::readStudent),
            arr("notes", SyncJson::readNote), arr("drafts", SyncJson::readDraft))
    }

    /** 다른 기기(맥·아이폰·다른 폰)의 기록 파일 합치기. 바뀐 기록 수 반환 */
    fun importDoc(text: String): Int {
        val inc = parseDoc(JSONObject(text))
        var changed = 0
        fun <T> merge(list: List<T>, incoming: List<T>, id: (T) -> String, ts: (T) -> Double): List<T> {
            val out = list.toMutableList()
            val idx = HashMap<String, Int>()
            out.forEachIndexed { i, x -> idx[id(x)] = i }
            for (r in incoming) {
                val i = idx[id(r)]
                if (i == null) { out += r; idx[id(r)] = out.size - 1; changed++ }
                else if (ts(r) > ts(out[i])) { out[i] = r; changed++ }
            }
            return out
        }
        mutate { db ->
            DB(merge(db.classes, inc.classes, { it.uid }, { it.updatedAt }),
                merge(db.students, inc.students, { it.uid }, { it.updatedAt }),
                merge(db.notes, inc.notes, { it.uid }, { it.updatedAt }),
                merge(db.drafts, inc.drafts, { it.uid }, { it.updatedAt }))
        }
        return changed
    }

    fun exportFile(): File {
        val dir = File(ctx.cacheDir, "share").apply { mkdirs() }
        val f = File(dir, "쓰담기록_$deviceId.json")
        f.writeText(makeDoc().toString())
        return f
    }

    /** 엑셀에서 바로 열리는 CSV (학생별 관찰 기록) */
    fun exportCSV(): File {
        val db = _db.value
        fun q(s: String) = "\"" + s.replace("\"", "\"\"") + "\""
        val rows = mutableListOf("학급,번호,이름,날짜,유형,영역,내용")
        for (c in db.activeClasses) for (s in db.studentsIn(c)) for (n in db.notesOf(s).reversed()) {
            rows += listOf(q(c.title), s.number?.toString() ?: "", q(s.displayName), n.date ?: "", n.kind ?: "",
                q(Areas.name(if (!n.area.isNullOrEmpty()) n.area else Areas.forKind(c.kind).firstOrNull())), q(n.content ?: "")).joinToString(",")
        }
        val dir = File(ctx.cacheDir, "share").apply { mkdirs() }
        val f = File(dir, "쓰담_학생기록_" + java.text.SimpleDateFormat("yyyyMMdd", Locale.US).format(java.util.Date()) + ".csv")
        f.writeText("\uFEFF" + rows.joinToString("\r\n"))
        return f
    }
}

/** SyncDoc 한 줄씩 (맥과 같은 키 이름 · 없는 값은 빼고 씀) */
object SyncJson {
    private fun JSONObject.opt(k: String, v: Any?): JSONObject = if (v == null) this else put(k, v)
    private fun base(uid: String, ts: Double, deleted: Boolean) =
        JSONObject().put("uid", uid).put("updated_at", ts).apply { if (deleted) put("deleted", true) }

    fun cls(c: SClass) = base(c.uid, c.updatedAt, c.deleted).opt("year", c.year).opt("semester", c.semester).opt("grade", c.grade)
        .opt("class_no", c.classNo).opt("subject", c.subject).opt("kind", c.kind).opt("label", c.label)
    fun student(s: SStudent) = base(s.uid, s.updatedAt, s.deleted).opt("class_uid", s.classUid).opt("number", s.number)
        .opt("name", s.name).opt("aliases", s.aliases)
    fun note(n: SNote) = base(n.uid, n.updatedAt, n.deleted).opt("student_uid", n.studentUid).opt("date", n.date).opt("kind", n.kind)
        .opt("area", n.area).opt("category", n.category).opt("content", n.content).opt("source", n.source).opt("use_in_draft", n.useInDraft)
    fun draft(d: SDraft) = base(d.uid, d.updatedAt, d.deleted).opt("student_uid", d.studentUid).opt("area", d.area)
        .opt("content", d.content).opt("status", d.status)

    private fun JSONObject.str(k: String): String? = if (!has(k) || isNull(k)) null else optString(k)
    private fun JSONObject.int(k: String): Int? = if (!has(k) || isNull(k)) null else when (val v = opt(k)) {
        is Number -> v.toInt(); is Boolean -> if (v) 1 else 0; is String -> v.toIntOrNull(); else -> null
    }
    private fun JSONObject.ts() = optDouble("updated_at", 0.0).let { if (it.isNaN()) 0.0 else it }
    private fun JSONObject.del() = optBoolean("deleted", false)

    fun readCls(o: JSONObject) = SClass(o.getString("uid"), o.ts(), o.del(), o.int("year"), o.int("semester"), o.int("grade"),
        o.int("class_no"), o.str("subject"), o.str("kind"), o.str("label"))
    fun readStudent(o: JSONObject) = SStudent(o.getString("uid"), o.ts(), o.del(), o.str("class_uid"), o.int("number"),
        o.str("name"), o.str("aliases"))
    fun readNote(o: JSONObject) = SNote(o.getString("uid"), o.ts(), o.del(), o.str("student_uid"), o.str("date"), o.str("kind"),
        o.str("area"), o.str("category"), o.str("content"), o.str("source"), o.int("use_in_draft"))
    fun readDraft(o: JSONObject) = SDraft(o.getString("uid"), o.ts(), o.del(), o.str("student_uid"), o.str("area"),
        o.str("content"), o.str("status"))
}
