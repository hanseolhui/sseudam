import CryptoKit
import Foundation

// 텍스트 동기화 — 맥의 app/sync_text.py 와 같은 형식.
// iCloud '쓰담/동기화' 폴더에 기기마다 자기 파일(<기기 id>.json) 하나만 쓰고,
// 읽을 때 모든 파일을 합쳐 기록마다 가장 나중에 고친 것(updated_at)을 고른다. 녹음 원본은 오가지 않는다.

struct SClass: Codable, Identifiable, Equatable {
    var uid: String
    var updated_at: Double
    var deleted: Bool? = nil
    var year: Int? = nil
    var semester: Int? = nil
    var grade: Int? = nil
    var class_no: Int? = nil
    var subject: String? = nil
    var kind: String? = nil
    var label: String? = nil
    var id: String { uid }
    var isDeleted: Bool { deleted == true }
    var title: String {
        if let l = label, !l.isEmpty { return l }
        let base = [grade.map { "\($0)학년" }, class_no.map { "\($0)반" }].compactMap { $0 }.joined(separator: " ")
        switch kind ?? "교과" {
        case "담임": return base + " (담임)"
        case "동아리": return "동아리 " + (subject ?? "")
        default: return [base, subject ?? ""].filter { !$0.isEmpty }.joined(separator: " ")
        }
    }
}

struct SStudent: Codable, Identifiable, Equatable {
    var uid: String
    var updated_at: Double
    var deleted: Bool? = nil
    var class_uid: String? = nil
    var number: Int? = nil
    var name: String? = nil
    var aliases: String? = nil
    var id: String { uid }
    var isDeleted: Bool { deleted == true }
    var displayName: String { name ?? "" }
}

struct SNote: Codable, Identifiable, Equatable {
    var uid: String
    var updated_at: Double
    var deleted: Bool? = nil
    var student_uid: String? = nil
    var date: String? = nil
    var kind: String? = nil
    var area: String? = nil
    var category: String? = nil
    var content: String? = nil
    var source: String? = nil
    var use_in_draft: Int? = nil
    var id: String { uid }
    var isDeleted: Bool { deleted == true }
}

struct SDraft: Codable, Identifiable, Equatable {
    var uid: String
    var updated_at: Double
    var deleted: Bool? = nil
    var student_uid: String? = nil
    var area: String? = nil
    var content: String? = nil
    var status: String? = nil
    var id: String { uid }
    var isDeleted: Bool { deleted == true }
}

struct SyncDoc: Codable {
    struct Device: Codable { var id: String; var name: String; var kind: String }
    var format = "sseudam-sync"
    var version = 1
    var device: Device
    var updated_at: Double
    var classes: [SClass] = []
    var students: [SStudent] = []
    var notes: [SNote] = []
    var drafts: [SDraft] = []
}

/// 생기부 영역 이름 (맥 db.AREAS 와 같음)
enum Areas {
    static let all: [(id: String, name: String, bytes: Int)] = [
        ("subject", "교과 세특", 1500), ("individual", "개인별 세특", 1500), ("behavior", "행동특성", 900),
        ("autonomy", "자율·자치", 1500), ("career", "진로활동", 2100), ("club", "동아리", 1500),
    ]
    static func forKind(_ kind: String?) -> [String] {
        switch kind ?? "교과" {
        case "담임": return ["behavior", "autonomy", "career", "individual"]
        case "동아리": return ["club"]
        case "기타": return all.map(\.id)
        default: return ["subject"]
        }
    }
    static func name(_ id: String?) -> String { all.first { $0.id == id }?.name ?? (id ?? "") }
    static func limit(_ id: String?) -> Int { all.first { $0.id == id }?.bytes ?? 1500 }
}

/// NEIS 글자 수: 한글 3바이트, 영문·숫자 1바이트, 줄바꿈 2바이트
func neisBytes(_ s: String) -> Int {
    s.unicodeScalars.reduce(0) { $0 + ($1 == "\n" ? 2 : ($1.value < 128 ? 1 : 3)) }
}

private func sha1(_ s: String) -> String {
    Insecure.SHA1.hash(data: Data(s.utf8)).map { String(format: "%02x", $0) }.joined()
}

@MainActor
final class DataStore: ObservableObject {
    static let shared = DataStore()

    @Published private(set) var classes: [SClass] = []
    @Published private(set) var students: [SStudent] = []
    @Published private(set) var notes: [SNote] = []
    @Published private(set) var drafts: [SDraft] = []
    @Published private(set) var lastSync: Date?
    @Published private(set) var otherDevices: [String] = []
    @Published var syncing = false

    let defaults = UserDefaults.standard
    lazy var deviceId: String = {
        if let d = defaults.string(forKey: "deviceId") { return d }
        let d = "ios-" + UUID().uuidString.replacingOccurrences(of: "-", with: "").prefix(12).lowercased()
        defaults.set(d, forKey: "deviceId")
        return d
    }()
    /// 기기 안 AI로 이름 없는 문장까지 나누기 (지원 기기에서만)
    var useLocalAI: Bool {
        get { defaults.object(forKey: "useLocalAI") as? Bool ?? true }
        set { defaults.set(newValue, forKey: "useLocalAI"); objectWillChange.send() }
    }
    var localAIActive: Bool { useLocalAI && AIRouter.available(.assignSentences) }

    /// 폰에서 받아쓴 글을 학생별로 나누기 (명단이 있을 때만)
    var splitOnPhone: Bool {
        get { defaults.object(forKey: "splitOnPhone") as? Bool ?? true }
        set { defaults.set(newValue, forKey: "splitOnPhone"); objectWillChange.send() }
    }

    private var fileURL: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("data.json")
    }

    init() {
        load()
        Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { _ in
            Task { @MainActor in await DataStore.shared.syncNow() }
        }
    }

    // MARK: 보기용
    var activeClasses: [SClass] {
        classes.filter { !$0.isDeleted }.sorted {
            ($0.year ?? 0, $0.semester ?? 0) != ($1.year ?? 0, $1.semester ?? 0)
                ? ($0.year ?? 0, $0.semester ?? 0) > ($1.year ?? 0, $1.semester ?? 0)
                : $0.title < $1.title
        }
    }
    func students(in c: SClass) -> [SStudent] {
        students.filter { !$0.isDeleted && $0.class_uid == c.uid }
            .sorted { ($0.number ?? 999, $0.displayName) < ($1.number ?? 999, $1.displayName) }
    }
    func notes(of s: SStudent) -> [SNote] {
        notes.filter { !$0.isDeleted && $0.student_uid == s.uid }
            .sorted { ($0.date ?? "", $0.updated_at) > ($1.date ?? "", $1.updated_at) }
    }
    func drafts(of s: SStudent) -> [SDraft] {
        drafts.filter { !$0.isDeleted && $0.student_uid == s.uid }.sorted { $0.updated_at > $1.updated_at }
    }
    func classOf(_ s: SStudent) -> SClass? { classes.first { $0.uid == s.class_uid } }
    func noteCount(_ c: SClass) -> Int {
        let ids = Set(students(in: c).map(\.uid))
        return notes.filter { !$0.isDeleted && ids.contains($0.student_uid ?? "") }.count
    }
    func notes(forSource source: String) -> [SNote] { notes.filter { !$0.isDeleted && $0.source == source } }
    func student(_ uid: String?) -> SStudent? { students.first { $0.uid == uid } }
    var hasRoster: Bool { students.contains { !$0.isDeleted } }
    /// 받아쓰기 힌트용 이름 (이름 + 별칭), 최근 학기 반부터
    var rosterNames: [String] {
        var out: [String] = []
        for c in activeClasses {
            for s in students(in: c) {
                let names = [s.displayName] + (s.aliases ?? "").split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
                for n in names where n.count >= 2 && !out.contains(n) { out.append(n) }
            }
        }
        return Array(out.prefix(100))
    }

    // MARK: 고치기
    static func isoDaysAgo(_ n: Int) -> String {
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd"
        return f.string(from: Date().addingTimeInterval(-Double(n) * 86400))
    }

    static func currentTerm(_ d: Date = Date()) -> (year: Int, semester: Int) {
        let c = Calendar.current.dateComponents([.year, .month], from: d)
        let y = c.year ?? 2026, m = c.month ?? 3
        if m <= 2 { return (y - 1, 2) }
        return (y, m <= 8 ? 1 : 2)
    }

    static func classUID(year: Int?, semester: Int?, grade: Int?, classNo: Int?, subject: String, kind: String) -> String {
        let key = [year.map(String.init) ?? "", semester.map(String.init) ?? "", grade.map(String.init) ?? "",
                   classNo.map(String.init) ?? "", subject.trimmingCharacters(in: .whitespaces), kind.isEmpty ? "교과" : kind]
            .joined(separator: "|")
        return "c-" + sha1(key).prefix(16)
    }
    static func studentUID(_ classUID: String, _ name: String) -> String {
        "s-" + sha1("\(classUID)|\(name.trimmingCharacters(in: .whitespaces))").prefix(16)
    }
    private static func newUID(_ p: String) -> String { p + UUID().uuidString.replacingOccurrences(of: "-", with: "").prefix(16).lowercased() }
    private var now: Double { Date().timeIntervalSince1970 }

    @discardableResult
    func addClass(grade: Int?, classNo: Int?, subject: String, kind: String) -> SClass {
        let t = DataStore.currentTerm()
        let uid = DataStore.classUID(year: t.year, semester: t.semester, grade: grade, classNo: classNo, subject: subject, kind: kind)
        let label: String = {
            let base = [grade.map { "\($0)-" }, classNo.map(String.init)].compactMap { $0 }.joined()
            switch kind {
            case "담임": return "\(base) (담임)"
            case "동아리": return "동아리 \(subject)"
            default: return [base, subject].filter { !$0.isEmpty }.joined(separator: " ")
            }
        }()
        let c = SClass(uid: uid, updated_at: now, year: t.year, semester: t.semester, grade: grade, class_no: classNo,
                       subject: subject, kind: kind, label: label)
        upsert(&classes, c)
        changed()
        return c
    }

    /// 명단 붙여넣기: 줄마다 "번호 이름" 또는 "이름". 쉼표·탭으로 이어도 됨.
    @discardableResult
    func addStudents(_ text: String, to c: SClass) -> Int {
        var added = 0
        var nextNo = (students(in: c).compactMap(\.number).max() ?? 0) + 1
        let parts = text.components(separatedBy: CharacterSet(charactersIn: "\n,;\t"))
        for raw in parts {
            var line = raw.trimmingCharacters(in: .whitespaces)
            guard !line.isEmpty else { continue }
            var number: Int?
            if let m = line.range(of: #"^\d{1,3}(번|\.|\))?\s*"#, options: .regularExpression) {
                number = Int(line[m].filter(\.isNumber))
                line = String(line[m.upperBound...]).trimmingCharacters(in: .whitespaces)
            }
            let name = line.components(separatedBy: " ").first ?? line
            guard name.count >= 2, name.count <= 10 else { continue }
            let uid = DataStore.studentUID(c.uid, name)
            if let cur = students.first(where: { $0.uid == uid }), !cur.isDeleted { continue }
            let no = number ?? nextNo
            nextNo = max(nextNo, no + 1)
            upsert(&students, SStudent(uid: uid, updated_at: now, class_uid: c.uid, number: no, name: name, aliases: ""))
            added += 1
        }
        changed()
        return added
    }

    func renameStudent(_ s: SStudent, name: String, number: Int?) {
        var s = s; s.name = name; s.number = number; s.updated_at = now
        upsert(&students, s); changed()
    }

    func deleteStudent(_ s: SStudent) {
        for n in notes(of: s) { tombstone(&notes, n.uid) }
        tombstone(&students, s.uid); changed()
    }

    func deleteClass(_ c: SClass) {
        for s in students(in: c) {
            for n in notes(of: s) { tombstone(&notes, n.uid) }
            tombstone(&students, s.uid)
        }
        tombstone(&classes, c.uid); changed()
    }

    @discardableResult
    func addNote(_ s: SStudent, content: String, date: Date = Date(), kind: String = "수업", source: String = "") -> SNote {
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd"
        let n = SNote(uid: DataStore.newUID("n-"), updated_at: now, student_uid: s.uid, date: f.string(from: date), kind: kind,
                      area: "", category: "", content: content, source: source, use_in_draft: 1)
        upsert(&notes, n); changed()
        return n
    }

    func editNote(_ n: SNote, content: String) {
        var n = n; n.content = content; n.updated_at = now
        upsert(&notes, n); changed()
    }

    func deleteNote(_ n: SNote) { tombstone(&notes, n.uid); changed() }

    func insertDraft(_ d: SDraft) { upsert(&drafts, d); changed() }
    func deleteDraft(_ d: SDraft) { tombstone(&drafts, d.uid); changed() }

    func setArea(_ n: SNote, _ area: String) {
        var n = n; n.area = area; n.updated_at = now
        upsert(&notes, n); changed()
    }

    /// 이번 학기 반 / 지난 학기 반
    var currentClasses: [SClass] {
        let t = DataStore.currentTerm()
        return activeClasses.filter { ($0.year ?? t.year, $0.semester ?? t.semester) >= (t.year, t.semester) }
    }
    var pastClasses: [SClass] {
        let cur = Set(currentClasses.map(\.uid))
        return activeClasses.filter { !cur.contains($0.uid) }
    }

    /// 이름·별칭으로 학생 찾기
    func search(_ q: String) -> [SStudent] {
        let q = q.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return [] }
        return students.filter { !$0.isDeleted && ($0.displayName.contains(q) || ($0.aliases ?? "").contains(q)) && classOf($0).map { !$0.isDeleted } == true }
            .sorted { $0.displayName < $1.displayName }
    }

    private func upsert<T: Codable & Identifiable>(_ list: inout [T], _ item: T) where T.ID == String {
        if let i = list.firstIndex(where: { $0.id == item.id }) { list[i] = item } else { list.append(item) }
    }

    private func tombstone<T>(_ list: inout [T], _ uid: String) where T: Codable & Identifiable, T.ID == String {
        guard let i = list.firstIndex(where: { $0.id == uid }) else { return }
        // 지움 표시만 남긴다 (다른 기기에도 지워지도록)
        if var c = list[i] as? SClass { c = SClass(uid: c.uid, updated_at: now, deleted: true); list[i] = c as! T }
        else if let s = list[i] as? SStudent { list[i] = SStudent(uid: s.uid, updated_at: now, deleted: true) as! T }
        else if let n = list[i] as? SNote { list[i] = SNote(uid: n.uid, updated_at: now, deleted: true) as! T }
        else if let d = list[i] as? SDraft { list[i] = SDraft(uid: d.uid, updated_at: now, deleted: true) as! T }
    }

    // MARK: 학생별로 나누기 (맥 pipeline.rule_segment 와 같은 방식 + "N학년 N반" 인식)
    struct SplitResult { var count: Int; var names: [String]; var leftover: String; var unsure: Int }
    /// 동명이인이라 선생님 확인이 필요한 기록 표시 (category). 후보는 "후보:uid,uid"
    static let unsureTag = "동명이인"

    @discardableResult
    func split(text: String, date: Date, kind: String, source: String, hint: String = "", force: Bool = false) -> SplitResult {
        let empty = SplitResult(count: 0, names: [], leftover: text, unsure: 0)
        guard hasRoster, !text.isEmpty, force || (splitOnPhone && notes(forSource: source).isEmpty) else { return empty }
        if force { for n in notes(forSource: source) { tombstone(&notes, n.uid) } }
        let r = Splitter.splitWithLeftover(text: text, hint: hint, classes: activeClasses, studentsIn: { self.students(in: $0) },
                                           preferKind: kind == "상담" ? "담임" : "교과")
        var names: [String] = []
        var unsure = 0
        for b in r.blocks {
            guard let s = student(b.studentUID) else { continue }
            var n = addNote(s, content: b.content, date: date, kind: kind, source: source)
            if b.ambiguous {
                n.category = DataStore.unsureTag + ":" + b.candidates.joined(separator: ",")
                upsert(&notes, n); unsure += 1
            }
            if !names.contains(s.displayName) { names.append(s.displayName) }
        }
        changed()
        return SplitResult(count: r.blocks.count, names: names, leftover: r.leftover, unsure: unsure)
    }

    /// 기기 안 AI로 다시 나누기: 이름이 나온 문장은 규칙대로, 이름 없는 문장만 AI가
    /// 그 녹음에 나온 학생 중에서 고르거나 '학생 이야기 아님'으로 둔다. 바뀐 게 없으면 nil.
    func refineWithAI(text: String, date: Date, kind: String, source: String, hint: String) async -> SplitResult? {
        guard localAIActive, hasRoster else { return nil }
        let classes = activeClasses
        let rule = Splitter.splitWithLeftover(text: text, hint: hint, classes: classes, studentsIn: { self.students(in: $0) },
                                              preferKind: kind == "상담" ? "담임" : "교과")
        // 등장한 학생 (순서대로, 중복 없이)
        var mentioned: [SStudent] = []
        for b in rule.blocks { if let s = student(b.studentUID), !mentioned.contains(where: { $0.uid == s.uid }) { mentioned.append(s) } }
        guard !mentioned.isEmpty else { return nil }
        let sentences = Splitter.sentences(Splitter.normalize(text))
        guard sentences.count >= 2 else { return nil }
        // 문장마다 규칙이 정한 주인: 그 문장에 학생 이름(또는 별칭·성 뺀 이름)이 직접 나오면 확정
        func keys(_ s: SStudent) -> [String] {
            var k = [s.displayName] + (s.aliases ?? "").split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
            if s.displayName.count >= 3 { k.append(String(s.displayName.dropFirst())) }
            return k.filter { $0.count >= 2 }
        }
        var known: [Int: Int] = [:]
        for (i, sen) in sentences.enumerated() {
            if let j = mentioned.firstIndex(where: { st in keys(st).contains { sen.contains($0) } }) { known[i] = j + 1 }
        }
        guard known.count < sentences.count else { return nil }   // 모든 문장에 이름이 있으면 AI 필요 없음
        guard let engine = AIRouter.engine(for: .assignSentences),
              let owners = try? await engine.assign(sentences: sentences, names: mentioned.map(\.displayName), known: known) else { return nil }
        // 이름이 나온 문장은 규칙을 믿고, 나머지만 AI 답을 쓴다
        var final: [(Int, Bool)] = sentences.indices.map { i in known[i].map { ($0, false) } ?? (owners[i], owners[i] != 0) }
        // 규칙 결과와 같으면 손대지 않음
        let ruleBlocks = rule.blocks
        // 이어지는 같은 학생 문장을 묶기
        struct Piece { var owner: Int; var guessed: Bool; var text: String }
        var pieces: [Piece] = []
        var leftover: [String] = []
        for (i, sen) in sentences.enumerated() {
            let (o, g) = final[i]
            if o == 0 { leftover.append(sen); continue }
            if let last = pieces.last, last.owner == o, !(last.guessed != g && g) {
                pieces[pieces.count - 1].text += " " + sen
                pieces[pieces.count - 1].guessed = last.guessed || g
            } else {
                pieces.append(Piece(owner: o, guessed: g, text: sen))
            }
        }
        final.removeAll()
        let same = pieces.count == ruleBlocks.count && zip(pieces, ruleBlocks).allSatisfy { p, b in
            mentioned[p.owner - 1].uid == b.studentUID && p.text.count == b.content.count
        }
        if same { return nil }
        // 바꾸기: 이 녹음의 조각을 새로 담는다 (동명이인 표시는 규칙 결과에서 이어받음)
        for n in notes(forSource: source) { tombstone(&notes, n.uid) }
        var names: [String] = []
        var unsure = 0
        for p in pieces {
            let s = mentioned[p.owner - 1]
            var n = addNote(s, content: String(p.text.prefix(1200)), date: date, kind: kind, source: source)
            if let rb = ruleBlocks.first(where: { $0.studentUID == s.uid && $0.ambiguous }) {
                n.category = DataStore.unsureTag + ":" + rb.candidates.joined(separator: ","); unsure += 1
            } else if p.guessed {
                n.category = DataStore.guessTag + ":" + mentioned.map(\.uid).joined(separator: ","); unsure += 1
            }
            upsert(&notes, n)
            if !names.contains(s.displayName) { names.append(s.displayName) }
        }
        changed()
        let left = leftover.joined(separator: " ")
        return SplitResult(count: pieces.count, names: names, leftover: left.count >= 6 ? left : "", unsure: unsure)
    }

    /// 녹음 중 누른 이름표대로 나누기: 이름표를 누른 뒤 말한 내용은 그 학생 몫.
    /// 첫 이름표 앞부분은 평소처럼 이름으로 나눈다.
    func splitByMarkers(text: String, segs: [Transcriber.Seg], markers: [Marker], date: Date, kind: String,
                        source: String, hint: String) -> SplitResult {
        for n in notes(forSource: source) { tombstone(&notes, n.uid) }
        let ns = text as NSString
        let marks = markers.filter { $0.student != nil }.sorted { $0.t < $1.t }
        func offset(_ t: Double) -> Int {
            segs.first(where: { $0.t >= t - 0.3 })?.offset ?? ns.length
        }
        func squash(_ s: String) -> String { s.components(separatedBy: .whitespacesAndNewlines).filter { !$0.isEmpty }.joined(separator: " ") }
        var names: [String] = []
        var count = 0
        var unsure = 0
        // 1) 첫 이름표 앞: 이름 기준
        let first = marks.first.map { offset($0.t) } ?? ns.length
        var leftover = ""
        if first > 0 {
            let head = ns.substring(to: min(first, ns.length))
            let r = Splitter.splitWithLeftover(text: head, hint: hint, classes: activeClasses, studentsIn: { self.students(in: $0) },
                                               preferKind: kind == "상담" ? "담임" : "교과")
            for b in r.blocks {
                guard let s = student(b.studentUID) else { continue }
                var n = addNote(s, content: b.content, date: date, kind: kind, source: source)
                if b.ambiguous { n.category = DataStore.unsureTag + ":" + b.candidates.joined(separator: ","); upsert(&notes, n); unsure += 1 }
                if !names.contains(s.displayName) { names.append(s.displayName) }
                count += 1
            }
            leftover = r.leftover
        }
        // 2) 이름표 구간 (같은 학생이 이어지면 합침)
        var i = 0
        while i < marks.count {
            let uid = marks[i].student!
            var j = i + 1
            while j < marks.count && marks[j].student == uid { j += 1 }
            let a = min(offset(marks[i].t), ns.length)
            let b = j < marks.count ? min(offset(marks[j].t), ns.length) : ns.length
            let chunk = squash(ns.substring(with: NSRange(location: a, length: max(0, b - a))))
            if chunk.count >= 2, let s = student(uid) {
                addNote(s, content: String(chunk.prefix(1200)), date: date, kind: kind, source: source)
                if !names.contains(s.displayName) { names.append(s.displayName) }
                count += 1
            }
            i = j
        }
        changed()
        return SplitResult(count: count, names: names, leftover: leftover, unsure: unsure)
    }

    // MARK: 바로잡기 — 다른 학생으로 옮기기 · 합치기 · 이름 고치기
    /// 기기 안 AI가 이름 없는 문장의 주인을 짐작한 기록
    static let guessTag = "AI추정"
    func isUnsure(_ n: SNote) -> Bool { (n.category ?? "").hasPrefix(DataStore.unsureTag) || isGuess(n) }
    func isGuess(_ n: SNote) -> Bool { (n.category ?? "").hasPrefix(DataStore.guessTag) }
    func candidates(_ n: SNote) -> [SStudent] {
        guard isUnsure(n), let list = n.category?.split(separator: ":").last else { return [] }
        return list.split(separator: ",").compactMap { student(String($0)) }
    }

    /// 기록을 다른 학생에게 옮긴다 (동명이인 확인도 이걸로 끝)
    func moveNote(_ n: SNote, to s: SStudent) {
        var n = n; n.student_uid = s.uid; n.category = ""; n.updated_at = now
        upsert(&notes, n); changed()
    }

    /// 확인만 (지금 학생이 맞음)
    func confirmNote(_ n: SNote) {
        var n = n; n.category = ""; n.updated_at = now
        upsert(&notes, n); changed()
    }

    /// 두 기록을 하나로: `other`의 내용을 `into` 뒤에 붙이고 `other`는 지운다
    func mergeNotes(_ other: SNote, into: SNote) {
        var t = into
        t.content = [into.content ?? "", other.content ?? ""].filter { !$0.isEmpty }.joined(separator: " ")
        t.updated_at = now
        upsert(&notes, t); tombstone(&notes, other.uid); changed()
    }

    func updateStudent(_ s: SStudent, name: String, number: Int?, aliases: String) {
        var s = s
        s.name = name.trimmingCharacters(in: .whitespaces); s.number = number
        s.aliases = aliases.trimmingCharacters(in: .whitespaces); s.updated_at = now
        upsert(&students, s); changed()
    }

    /// 같은 학생이 둘로 들어간 경우: `from`의 기록·초안을 `into`로 옮기고, `from`의 이름은 별칭으로 남긴다
    func mergeStudent(_ from: SStudent, into: SStudent) {
        for var n in notes.filter({ !$0.isDeleted && $0.student_uid == from.uid }) {
            n.student_uid = into.uid; n.updated_at = now; upsert(&notes, n)
        }
        for var d in drafts.filter({ !$0.isDeleted && $0.student_uid == from.uid }) {
            d.student_uid = into.uid; d.updated_at = now; upsert(&drafts, d)
        }
        var t = into
        var al = Set((t.aliases ?? "").split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty })
        if from.displayName != into.displayName { al.insert(from.displayName) }
        t.aliases = al.sorted().joined(separator: ","); t.updated_at = now
        upsert(&students, t)
        tombstone(&students, from.uid)
        changed()
    }

    /// 같은 이름을 가진 다른 반 학생 (동명이인 표시용)
    /// (같은 학년·반의 교과/담임 명단은 같은 학생이므로 빼고, 다른 반만)
    func sameName(_ s: SStudent) -> [SStudent] {
        func room(_ x: SStudent) -> String {
            guard let c = classOf(x), let g = c.grade else { return x.class_uid ?? "" }
            return "\(g)-\(c.class_no ?? 0)"
        }
        let mine = room(s)
        return students.filter { !$0.isDeleted && $0.uid != s.uid && $0.displayName == s.displayName && room($0) != mine }
    }

    // MARK: 저장 · 동기화
    private func load() {
        guard let d = try? Data(contentsOf: fileURL), let doc = try? JSONDecoder().decode(SyncDoc.self, from: d) else { return }
        classes = doc.classes; students = doc.students; notes = doc.notes; drafts = doc.drafts
    }

    private func makeDoc() -> SyncDoc {
        SyncDoc(device: .init(id: deviceId, name: UIDeviceName.current, kind: "ios"), updated_at: now,
                classes: classes, students: students, notes: notes, drafts: drafts)
    }

    private func saveLocal() {
        if let d = try? JSONEncoder().encode(makeDoc()) { try? d.write(to: fileURL, options: .atomic) }
    }

    private var pushTask: Task<Void, Never>?
    private func changed() {
        saveLocal()
        pushTask?.cancel()
        pushTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 1_500_000_000)
            await self?.syncNow()
        }
    }

    nonisolated static var syncFolder: URL? {
        FileManager.default.url(forUbiquityContainerIdentifier: Sync.container)?
            .appendingPathComponent("Documents/동기화", isDirectory: true)
    }

    /// 다른 기기 파일을 읽어 합치고, 내 파일을 쓴다.
    func syncNow() async {
        guard !syncing else { return }
        syncing = true
        defer { syncing = false }
        let own = deviceId
        let docs: [SyncDoc] = await Task.detached(priority: .utility) { DataStore.readRemote(own: own) }.value
        if mergeIn(docs) { saveLocal() }
        otherDevices = docs.map(\.device.name)
        let doc = makeDoc()
        let ok = await Task.detached(priority: .utility) { DataStore.writeOwn(doc) }.value
        if ok { lastSync = Date() }
        // QR 연동: 컴퓨터(맥·윈도우)와 암호화해서 주고받기
        if Relay.paired, let mine = try? JSONEncoder().encode(doc) {
            if let theirs = try? await Relay.syncDocs(myDoc: mine, deviceId: own),
               let pc = try? JSONDecoder().decode(SyncDoc.self, from: theirs), pc.format == "sseudam-sync" {
                if mergeIn([pc]) { saveLocal() }
                if !otherDevices.contains(pc.device.name) { otherDevices.append(pc.device.name) }
                lastSync = Date()
            }
        }
    }

    /// 기록마다 updated_at이 더 큰 쪽을 남긴다. 바뀐 게 있으면 true.
    private func mergeIn(_ docs: [SyncDoc]) -> Bool {
        var changed = false
        func merge<T: Codable & Identifiable & Equatable>(_ list: inout [T], _ incoming: [T], _ ts: (T) -> Double) where T.ID == String {
            var idx = Dictionary(uniqueKeysWithValues: list.enumerated().map { ($1.id, $0) })
            for r in incoming {
                if let i = idx[r.id] {
                    if ts(r) > ts(list[i]) { list[i] = r; changed = true }
                } else {
                    list.append(r); idx[r.id] = list.count - 1; changed = true
                }
            }
        }
        for d in docs {
            merge(&classes, d.classes, \.updated_at)
            merge(&students, d.students, \.updated_at)
            merge(&notes, d.notes, \.updated_at)
            merge(&drafts, d.drafts, \.updated_at)
        }
        return changed
    }

    nonisolated static func readRemote(own: String) -> [SyncDoc] {
        guard let folder = syncFolder else { return [] }
        let fm = FileManager.default
        try? fm.createDirectory(at: folder, withIntermediateDirectories: true)
        var out: [SyncDoc] = []
        for name in (try? fm.contentsOfDirectory(atPath: folder.path)) ?? [] {
            if name.hasPrefix(".") && name.hasSuffix(".icloud") {
                // 아직 내려받지 않은 파일 → 내려받기 요청, 다음 차례에 읽음
                let real = folder.appendingPathComponent(String(name.dropFirst().dropLast(7)))
                try? fm.startDownloadingUbiquitousItem(at: real)
                continue
            }
            guard name.hasSuffix(".json"), name != own + ".json" else { continue }
            let url = folder.appendingPathComponent(name)
            var data: Data?
            var err: NSError?
            NSFileCoordinator().coordinate(readingItemAt: url, options: [], error: &err) { data = try? Data(contentsOf: $0) }
            if let data, let doc = try? JSONDecoder().decode(SyncDoc.self, from: data), doc.format == "sseudam-sync" {
                out.append(doc)
            }
        }
        return out
    }

    nonisolated static func writeOwn(_ doc: SyncDoc) -> Bool {
        guard let folder = syncFolder, let data = try? JSONEncoder().encode(doc) else { return false }
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let url = folder.appendingPathComponent(doc.device.id + ".json")
        var ok = false
        var err: NSError?
        NSFileCoordinator().coordinate(writingItemAt: url, options: .forReplacing, error: &err) { u in
            ok = (try? data.write(to: u, options: .atomic)) != nil
        }
        return ok
    }

    // MARK: 내보내기
    /// 엑셀에서 바로 열리는 CSV (학생별 관찰 기록)
    func exportCSV() -> URL? {
        func q(_ s: String) -> String { "\"" + s.replacingOccurrences(of: "\"", with: "\"\"") + "\"" }
        var rows = ["학급,번호,이름,날짜,유형,영역,내용"]
        for c in activeClasses {
            for s in students(in: c) {
                for n in notes(of: s).reversed() {
                    rows.append([q(c.title), s.number.map(String.init) ?? "", q(s.displayName), n.date ?? "", n.kind ?? "",
                                 q(Areas.name(n.area?.isEmpty == false ? n.area : Areas.forKind(c.kind).first)),
                                 q(n.content ?? "")].joined(separator: ","))
                }
            }
        }
        let f = DateFormatter(); f.dateFormat = "yyyyMMdd"
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("쓰담_학생기록_\(f.string(from: Date())).csv")
        let body = "\u{FEFF}" + rows.joined(separator: "\r\n")
        return (try? body.data(using: .utf8)?.write(to: url)) != nil ? url : nil
    }
}

import UIKit
enum UIDeviceName {
    @MainActor static var current: String { UIDevice.current.name }
}
