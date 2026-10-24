import AVFoundation
import Foundation
import UIKit

/// sending = iOS 백그라운드 전송에 맡겨 올리는 중 (앱이 꺼져도 계속)
enum SyncState: String, Codable { case off, pending, sending, done, failed }
/// 아이폰 안 받아쓰기 상태: 대기·진행 중·끝·지원 안 함·실패
enum SttState: String, Codable { case none, working, done, unavailable, failed }

/// 기록 한 건: 녹음(audio) 또는 한 줄 메모(text). 파일 이름에 날짜·유형·메모가 들어가
/// 컴퓨터의 쓰담이 시간표·학급을 알아서 판단한다. (예: "쓰담 20261012 1030 상담 2-3.m4a")
struct Entry: Codable, Identifiable, Equatable {
    var id = UUID()
    var type: String = "audio"          // audio | text
    var fileName: String
    var createdAt: Date
    var duration: Double = 0
    var kind: String = "수업"           // 수업 | 상담
    var memo: String = ""
    var text: String = ""
    var icloud: SyncState = .off
    var google: SyncState = .off
    /// QR 연동(암호화 중계)으로 컴퓨터에 보냈는지
    var relay: SyncState = .off
    var lastError: String = ""
    /// 저장한 시각 (녹음 시작 시각과 다름) — 보내기 전 고칠 시간 계산용
    var savedAt: Date? = nil
    /// 아이폰에서 받아쓴 글 (녹음일 때)
    var transcript: String = ""
    var stt: SttState = .none
    var sttNote: String = ""
    /// 컴퓨터의 쓰담이 실제로 가져갔는지 (iCloud '처리완료' 폴더로 확인)
    var received: Bool = false
    /// 폰에서 학생별로 나눈 결과 (이름들). nil = 아직 안 나눔
    var splitNames: [String]? = nil
    /// 학생 이름을 못 찾은 앞부분 (선생님이 학생을 골라 줄 수 있게)
    var splitLeftover: String = ""
    var splitUnsure: Int = 0
    var aiRefined: Bool = false
    /// 녹음 중 누른 이름표·⭐
    var markers: [Marker] = []
    /// ⭐ 누른 순간의 문장들
    var starSnippets: [String] = []
    /// 녹음하면서 고른 반(학급 uid)·교시
    var classUid: String? = nil
    var period: Int? = nil
    /// QR 연동으로 마지막으로 보낸 때 (컴퓨터가 오래 안 받아 가면 다시 보냄)
    var relaySentAt: Date? = nil

    var isAudio: Bool { type == "audio" }
    var editableUntil: Date { (savedAt ?? createdAt).addingTimeInterval(Store.grace) }
    var title: String {
        if !isAudio { return text }
        if !memo.isEmpty { return memo }
        if !transcript.isEmpty { return transcript }
        return "녹음 \(timeString(duration))"
    }
    var sent: Bool { icloud == .done || google == .done || relay == .done }

    init(type: String, fileName: String, createdAt: Date, duration: Double = 0, kind: String = "수업", memo: String = "", text: String = "") {
        self.type = type; self.fileName = fileName; self.createdAt = createdAt
        self.duration = duration; self.kind = kind; self.memo = memo; self.text = text
    }

    // 1.0 형식(Recording)도 읽기
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        id = try c.decodeIfPresent(UUID.self, forKey: .id) ?? UUID()
        type = try c.decodeIfPresent(String.self, forKey: .type) ?? "audio"
        fileName = try c.decode(String.self, forKey: .fileName)
        createdAt = try c.decode(Date.self, forKey: .createdAt)
        duration = try c.decodeIfPresent(Double.self, forKey: .duration) ?? 0
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "수업"
        memo = try c.decodeIfPresent(String.self, forKey: .memo) ?? ""
        text = try c.decodeIfPresent(String.self, forKey: .text) ?? ""
        icloud = try c.decodeIfPresent(SyncState.self, forKey: .icloud) ?? .off
        google = try c.decodeIfPresent(SyncState.self, forKey: .google) ?? .off
        relay = try c.decodeIfPresent(SyncState.self, forKey: .relay) ?? .off
        lastError = try c.decodeIfPresent(String.self, forKey: .lastError) ?? ""
        savedAt = try c.decodeIfPresent(Date.self, forKey: .savedAt)
        transcript = try c.decodeIfPresent(String.self, forKey: .transcript) ?? ""
        stt = try c.decodeIfPresent(SttState.self, forKey: .stt) ?? .none
        sttNote = try c.decodeIfPresent(String.self, forKey: .sttNote) ?? ""
        received = try c.decodeIfPresent(Bool.self, forKey: .received) ?? false
        splitNames = try c.decodeIfPresent([String].self, forKey: .splitNames)
        splitLeftover = try c.decodeIfPresent(String.self, forKey: .splitLeftover) ?? ""
        splitUnsure = try c.decodeIfPresent(Int.self, forKey: .splitUnsure) ?? 0
        aiRefined = try c.decodeIfPresent(Bool.self, forKey: .aiRefined) ?? false
        markers = try c.decodeIfPresent([Marker].self, forKey: .markers) ?? []
        starSnippets = try c.decodeIfPresent([String].self, forKey: .starSnippets) ?? []
        classUid = try c.decodeIfPresent(String.self, forKey: .classUid)
        period = try c.decodeIfPresent(Int.self, forKey: .period)
        relaySentAt = try c.decodeIfPresent(Date.self, forKey: .relaySentAt)
    }
}

@MainActor
final class Store: ObservableObject {
    static let shared = Store()
    /// 저장 직후 이 시간 동안은 보내지 않고 기다린다 (수업/상담·메모를 고칠 수 있게)
    nonisolated static let grace: TimeInterval = 20

    @Published var items: [Entry] = []
    @Published var icloudAvailable = false
    @Published var syncing = false
    @Published var justSaved: UUID?

    let defaults = UserDefaults.standard
    var onboarded: Bool {
        get { defaults.bool(forKey: "onboarded") }
        set { defaults.set(newValue, forKey: "onboarded"); objectWillChange.send() }
    }
    /// 선생님 컴퓨터 종류 — 연결 화면에서 추천 방법을 고를 때 사용
    var computer: String {
        get { defaults.string(forKey: "computer") ?? "mac" }
        set { defaults.set(newValue, forKey: "computer"); objectWillChange.send() }
    }
    var useICloud: Bool {
        get { defaults.object(forKey: "useICloud") as? Bool ?? true }
        set { defaults.set(newValue, forKey: "useICloud"); objectWillChange.send(); Task { await syncAll() } }
    }
    var lastKind: String {
        get { Features.counseling ? (defaults.string(forKey: "lastKind") ?? "수업") : "수업" }
        set { defaults.set(newValue, forKey: "lastKind") }
    }
    /// 컴퓨터로 보낸 기록을 휴대폰에서 지울 시점(일). 0 = 지우지 않음(기본 — 학기말까지 보관)
    var deleteAfterDays: Int {
        get { defaults.integer(forKey: "deleteAfterDays") }
        set { defaults.set(newValue, forKey: "deleteAfterDays"); objectWillChange.send() }
    }
    var googleURL: String { defaults.string(forKey: "googleURL") ?? "" }
    var googleToken: String { Keychain.get("googleToken") ?? "" }
    var teacherName: String { defaults.string(forKey: "teacherName") ?? "" }
    var googlePaired: Bool { !googleURL.isEmpty && !googleToken.isEmpty }
    var autoSend: Bool { Relay.paired || googlePaired || (useICloud && icloudAvailable) }
    /// 컴퓨터의 쓰담이 한 번이라도 기록을 받아 갔는지 (구글 연결은 컴퓨터에서 QR을 띄워야 하므로 받은 것으로 봄)
    var computerSeen: Bool {
        get { googlePaired || defaults.bool(forKey: "computerSeen") }
        set { defaults.set(newValue, forKey: "computerSeen"); objectWillChange.send() }
    }
    /// 아이폰에서 받아쓰기 (기본 켜짐)
    var transcribeOnPhone: Bool {
        get { defaults.object(forKey: "transcribeOnPhone") as? Bool ?? true }
        set { defaults.set(newValue, forKey: "transcribeOnPhone"); objectWillChange.send() }
    }

    static let folder: URL = {
        let d = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("Recordings")
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        return d
    }()
    private var indexURL: URL { Store.folder.appendingPathComponent("index.json") }

    init() {
        load()
        icloudAvailable = FileManager.default.ubiquityIdentityToken != nil
        // 켜져 있는 동안 30초마다 '컴퓨터가 받았는지' 확인
        Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { _ in
            Task { @MainActor in await Store.shared.checkReceived() }
        }
        // 앱이 꺼져 끊긴 받아쓰기는 다시 시작
        for e in items where e.isAudio && e.stt == .working {
            transcribe(e)
        }
    }

    func url(_ e: Entry) -> URL { Store.folder.appendingPathComponent(e.fileName) }

    var pendingCount: Int { items.filter { $0.icloud == .pending || $0.google == .pending || $0.icloud == .failed || $0.google == .failed }.count }
    var todayCount: Int { items.filter { Calendar.current.isDateInToday($0.createdAt) }.count }

    // MARK: 저장
    func load() {
        guard let data = try? Data(contentsOf: indexURL),
              let list = try? JSONDecoder().decode([Entry].self, from: data) else { return }
        items = list.filter { FileManager.default.fileExists(atPath: url($0).path) }
    }

    func save() {
        if let data = try? JSONEncoder().encode(items) { try? data.write(to: indexURL, options: .atomic) }
    }

    private func baseName(date: Date, kind: String, memo: String, suffix: String = "") -> String {
        let f = DateFormatter(); f.locale = Locale(identifier: "ko_KR"); f.dateFormat = "yyyyMMdd HHmm"
        var name = "쓰담 " + f.string(from: date)
        if kind == "상담" { name += " 상담" }
        if !suffix.isEmpty { name += " " + suffix }
        let clean = memo.components(separatedBy: CharacterSet(charactersIn: "/\\:*?\"<>|\n\r\t")).joined(separator: " ")
            .trimmingCharacters(in: .whitespaces)
        if !clean.isEmpty { name += " " + String(clean.prefix(30)) }
        return name
    }

    private func uniqueFile(_ name: String, _ ext: String, excluding: String? = nil) -> String {
        var fileName = "\(name).\(ext)"; var i = 2
        while fileName != excluding && FileManager.default.fileExists(atPath: Store.folder.appendingPathComponent(fileName).path) {
            fileName = "\(name) (\(i)).\(ext)"; i += 1
        }
        return fileName
    }

    private func newEntry(_ e: Entry) -> Entry {
        var e = e
        e.savedAt = Date()
        e.icloud = useICloud && icloudAvailable ? .pending : .off
        e.google = googlePaired ? .pending : .off
        e.relay = Relay.paired ? .pending : .off
        items.insert(e, at: 0)
        save()
        justSaved = e.id
        scheduleSync()
        return e
    }

    /// 녹음을 바로 저장 (묻지 않음). 유형은 지난번과 같게 — 저장 후 카드에서 바꿀 수 있다.
    @discardableResult
    func addAudio(tempFile: URL, duration: Double, at date: Date, markers: [Marker] = [],
                  classUid: String? = nil, period: Int? = nil) -> Entry {
        let kind = lastKind
        let fileName = uniqueFile(baseName(date: date, kind: kind, memo: ""), "m4a")
        try? FileManager.default.moveItem(at: tempFile, to: Store.folder.appendingPathComponent(fileName))
        var e = Entry(type: "audio", fileName: fileName, createdAt: date, duration: duration, kind: kind)
        e.markers = markers
        e.classUid = classUid
        e.period = period
        if transcribeOnPhone { e.stt = .working }
        let saved = newEntry(e)
        if transcribeOnPhone { transcribe(saved) }
        return saved
    }

    // MARK: 받아쓰기
    /// 녹음을 아이폰 안에서 글자로 바꾸고, 받아쓴 글을 m4a에 넣어 둔다 (보내기는 끝날 때까지 기다림)
    func transcribe(_ e: Entry, resplit: Bool = false) {
        guard var cur = items.first(where: { $0.id == e.id }), cur.isAudio else { return }
        cur.stt = .working; cur.sttNote = ""
        update(cur)
        Task {
            let bg = UIApplication.shared.beginBackgroundTask(withName: "stt")
            defer { UIApplication.shared.endBackgroundTask(bg) }
            // 명단 이름을 받아쓰기에 미리 알려 주면 이름을 훨씬 정확히 적는다
            let outcome = await Transcriber.transcribe(url(cur), hints: DataStore.shared.rosterNames)
            guard var now = items.first(where: { $0.id == e.id }) else { return }
            switch outcome {
            case .text(let t, let segs):
                now.transcript = t.trimmingCharacters(in: .whitespacesAndNewlines)
                now.stt = .done
                now.starSnippets = Store.snippets(t, segs, now.markers.filter(\.star))
                if !now.transcript.isEmpty && !now.sent { _ = await Transcriber.embed(now.transcript, into: url(now)) }
                update(now)
                if !now.transcript.isEmpty {
                    if now.markers.contains(where: { $0.student != nil }) && DataStore.shared.hasRoster {
                        // 녹음 중 이름표를 눌렀으면 그 표시대로 나눈다
                        let r = DataStore.shared.splitByMarkers(text: t, segs: segs, markers: now.markers, date: now.createdAt,
                                                                kind: now.kind, source: now.fileName, hint: now.memo)
                        now.splitNames = r.names; now.splitLeftover = r.leftover; now.splitUnsure = r.unsure
                        update(now)
                    } else {
                        splitToStudents(now, text: now.transcript, force: resplit)
                    }
                }
                now = items.first(where: { $0.id == e.id }) ?? now
            case .unavailable(let m): now.stt = .unavailable; now.sttNote = m
            case .failed(let m): now.stt = .failed; now.sttNote = m
            }
            update(now)
            scheduleSync()
        }
    }

    /// ⭐ 누른 시각이 든 문장 (앞 문장까지 함께)
    static func snippets(_ text: String, _ segs: [Transcriber.Seg], _ stars: [Marker]) -> [String] {
        guard !stars.isEmpty, !text.isEmpty else { return [] }
        let ns = text as NSString
        return stars.compactMap { m in
            // 누르기 직전 말한 내용이 보통 중요하므로 2초 앞부터
            let off = segs.last(where: { $0.t <= max(0, m.t - 2) })?.offset ?? segs.first?.offset ?? 0
            var a = off, b = off
            while a > 0, !".?!\n".contains(Character(UnicodeScalar(ns.character(at: a - 1)) ?? " ")) { a -= 1 }
            while b < ns.length, !".?!\n".contains(Character(UnicodeScalar(ns.character(at: b)) ?? " ")) { b += 1 }
            b = min(ns.length, b + 1)
            let s = ns.substring(with: NSRange(location: a, length: max(0, b - a))).trimmingCharacters(in: .whitespacesAndNewlines)
            return s.isEmpty ? nil : s
        }
    }

    /// 한 줄 메모 저장 → 텍스트 파일로 컴퓨터에 전달
    @discardableResult
    func addText(_ text: String, kind: String, at date: Date = Date()) -> Entry? {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return nil }
        lastKind = kind
        let fileName = uniqueFile(baseName(date: date, kind: kind, memo: "", suffix: "메모"), "txt")
        try? t.data(using: .utf8)?.write(to: Store.folder.appendingPathComponent(fileName))
        let e = newEntry(Entry(type: "text", fileName: fileName, createdAt: date, kind: kind, text: t))
        splitToStudents(e, text: t)
        return items.first { $0.id == e.id }
    }

    /// 명단이 있으면 폰에서 바로 학생별 기록으로 나눈다 (맥이 같은 녹음을 받으면 다시 나누지 않고 연결만 함)
    func splitToStudents(_ e: Entry, text: String, force: Bool = false) {
        let data = DataStore.shared
        guard force || data.splitOnPhone, data.hasRoster, var cur = items.first(where: { $0.id == e.id }) else { return }
        let r = data.split(text: text, date: cur.createdAt, kind: cur.kind, source: cur.fileName, hint: cur.memo, force: force)
        cur.splitNames = r.names
        cur.splitLeftover = r.leftover
        cur.splitUnsure = r.unsure
        update(cur)
        // 지원 기기면 기기 안 AI로 이름 없는 문장까지 정리 (밖으로 나가는 것 없음)
        if data.localAIActive && !r.names.isEmpty {
            let id = cur.id, date = cur.createdAt, kind = cur.kind, source = cur.fileName, hint = cur.memo
            Task {
                guard let ai = await data.refineWithAI(text: text, date: date, kind: kind, source: source, hint: hint),
                      var now = items.first(where: { $0.id == id }) else { return }
                now.splitNames = ai.names; now.splitLeftover = ai.leftover; now.splitUnsure = ai.unsure
                now.aiRefined = true
                update(now)
            }
        }
    }

    /// 이름 없는 부분이 학생 이야기가 아니면 치우기 (원본 글은 그대로 남음)
    func dropLeftover(_ e: Entry) {
        guard var cur = items.first(where: { $0.id == e.id }) else { return }
        cur.splitLeftover = ""
        update(cur)
    }

    /// 학생을 못 찾은 부분을 선생님이 고른 학생에게 담기
    func assignLeftover(_ e: Entry, to s: SStudent) {
        guard var cur = items.first(where: { $0.id == e.id }), !cur.splitLeftover.isEmpty else { return }
        DataStore.shared.addNote(s, content: cur.splitLeftover, date: cur.createdAt, kind: cur.kind, source: cur.fileName)
        cur.splitLeftover = ""
        var names = cur.splitNames ?? []
        if !names.contains(s.displayName) { names.insert(s.displayName, at: 0) }
        cur.splitNames = names
        update(cur)
    }

    /// 유형·메모 바꾸기. 아직 보내기 전이면 파일 이름도 바꿔 컴퓨터가 올바로 알아듣게 한다.
    func edit(_ e: Entry, kind: String? = nil, memo: String? = nil, text: String? = nil, transcript: String? = nil) {
        guard var cur = items.first(where: { $0.id == e.id }) else { return }
        if let t = transcript, cur.isAudio, t != cur.transcript, !cur.sent {
            cur.transcript = t
            update(cur)
            let file = url(cur)
            Task { _ = await Transcriber.embed(t, into: file) }
        }
        if let k = kind { cur.kind = k; lastKind = k }
        if let m = memo { cur.memo = m }
        var resplit = false
        if let t = text, !cur.isAudio, t != cur.text { cur.text = t; try? t.data(using: .utf8)?.write(to: url(cur)); resplit = true }
        defer { if resplit, let now = items.first(where: { $0.id == e.id }) { splitToStudents(now, text: now.text, force: true) } }
        let notSent = cur.icloud != .done && cur.google != .done
        if notSent {
            let ext = cur.isAudio ? "m4a" : "txt"
            let name = baseName(date: cur.createdAt, kind: cur.kind, memo: cur.memo, suffix: cur.isAudio ? "" : "메모")
            let newName = uniqueFile(name, ext, excluding: cur.fileName)
            if newName != cur.fileName {
                try? FileManager.default.moveItem(at: url(cur), to: Store.folder.appendingPathComponent(newName))
                cur.fileName = newName
            }
        }
        update(cur)
    }

    func delete(_ e: Entry) {
        try? FileManager.default.removeItem(at: url(e))
        items.removeAll { $0.id == e.id }
        save()
    }

    func update(_ e: Entry) {
        if let i = items.firstIndex(where: { $0.id == e.id }) { items[i] = e; save() }
    }

    // MARK: 보내기
    private var syncTask: Task<Void, Never>?

    func scheduleSync() {
        syncTask?.cancel()
        // 녹음을 끝내자마자 화면을 꺼도 고칠 시간(20초)이 지나면 보내기를 맡길 수 있게 잠깐 깨어 있음
        let bg = UIApplication.shared.beginBackgroundTask(withName: "send-after-grace")
        syncTask = Task { [weak self] in
            defer { UIApplication.shared.endBackgroundTask(bg) }
            do { try await Task.sleep(nanoseconds: UInt64((Store.grace + 1) * 1_000_000_000)) } catch { return }
            await self?.syncAll()
        }
        BackgroundSend.scheduleRefresh()
    }

    /// 대기·실패한 기록을 모두 보낸다. 앱이 켜질 때·돌아올 때·저장 후 잠시 뒤 호출.
    func syncAll(force: Bool = false) async {
        guard !syncing else { return }
        syncing = true
        defer { syncing = false }
        icloudAvailable = FileManager.default.ubiquityIdentityToken != nil
        // 올리는 중으로 남아 있는데 iOS 전송 목록에 없으면(앱 재설치·전송 취소 등) 다시 보낼 차례로
        let flying = await BackgroundSend.shared.inFlight()
        for i in items.indices where items[i].relay == .sending && !flying.contains(items[i].id) { items[i].relay = .pending }
        let now = Date()
        for e in items {
            if !force && now < e.editableUntil { continue }  // 고칠 시간
            // 받아쓰는 중이면 끝날 때까지 기다림 (10분 넘게 걸리면 소리만 먼저 보냄)
            if e.stt == .working && now.timeIntervalSince(e.savedAt ?? e.createdAt) < 600 { continue }
            var cur = e
            if useICloud && icloudAvailable && [.pending, .failed, .off].contains(cur.icloud) {
                do { try await Sync.copyToICloud(url(cur)); cur.icloud = .done }
                catch { cur.icloud = .failed; cur.lastError = "iCloud: \(error.localizedDescription)" }
                update(cur)
            }
            if Relay.paired && [.pending, .failed, .off].contains(cur.relay) {
                // iOS 백그라운드 전송에 맡김 — 앱을 닫거나 화면이 꺼져도 끝까지 올라감 (끝나면 relayFinished)
                do {
                    let (req, body) = try await Relay.prepareUpload(file: url(cur), entry: cur, deviceId: DataStore.shared.deviceId)
                    try BackgroundSend.shared.enqueue(req, body: body, entry: cur.id)
                    cur.relay = .sending; cur.lastError = ""
                } catch {
                    cur.relay = .failed; cur.lastError = "연결: \(error.localizedDescription)"
                }
                update(cur)
            }
            if googlePaired && [.pending, .failed, .off].contains(cur.google) {
                let bg = UIApplication.shared.beginBackgroundTask(withName: "upload")
                do {
                    try await Sync.uploadToGoogle(file: url(cur), entry: cur, url: googleURL, token: googleToken)
                    cur.google = .done; cur.lastError = ""
                } catch {
                    cur.google = .failed; cur.lastError = "구글: \(error.localizedDescription)"
                }
                UIApplication.shared.endBackgroundTask(bg)
                update(cur)
            }
        }
        await checkReceived()
        cleanupOld()
    }

    /// 컴퓨터가 받았는지 확인해 '컴퓨터가 받음'으로 표시.
    /// QR 연동: 컴퓨터 쓰담이 받은 녹음 이름 목록을 올려 둠 · iCloud: 맥의 쓰담이 '쓰담/처리완료' 폴더로 옮김
    func checkReceived() async {
        var changed = false
        if Relay.paired, items.contains(where: { $0.relay == .done && !$0.received }),
           let got = try? await Relay.receivedNames(deviceId: DataStore.shared.deviceId), !got.isEmpty {
            for i in items.indices where !items[i].received && got.contains(Relay.uploadName(items[i])) {
                items[i].received = true; changed = true
            }
        }
        let waiting = items.filter { $0.icloud == .done && !$0.received }.map(\.fileName)
        if !waiting.isEmpty {
            let got = await Sync.receivedNames(Set(waiting))
            for i in items.indices where got.contains(items[i].fileName) { items[i].received = true; changed = true }
        }
        if changed { save(); computerSeen = true }
        resendStale()
    }

    /// 보낸 지 오래됐는데 컴퓨터가 안 받아 간 녹음은 다시 보낸다 (중계 서버는 14일 뒤 지움)
    nonisolated static let resendAfter: TimeInterval = 10 * 24 * 3600
    private func resendStale() {
        guard Relay.paired else { return }
        var any = false
        // 받음 확인이 없던 예전 버전에서 보낸 것(relaySentAt 없음)은 다시 보내지 않음 — 컴퓨터에 두 번 담기지 않게
        for i in items.indices where items[i].relay == .done && !items[i].received
            && items[i].relaySentAt.map({ Date().timeIntervalSince($0) > Store.resendAfter }) == true {
            items[i].relay = .pending; any = true
        }
        if any { save(); scheduleSync() }
    }

    /// 백그라운드 전송이 끝났을 때 (앱이 꺼져 있었으면 iOS가 잠깐 깨워서 부름)
    func relayFinished(_ id: UUID, ok: Bool, error: String) {
        guard var cur = items.first(where: { $0.id == id }) else { return }
        if ok { cur.relay = .done; cur.relaySentAt = Date(); cur.lastError = "" }
        else { cur.relay = .failed; cur.lastError = "연결: \(error)" }
        update(cur)
        if !ok { BackgroundSend.scheduleRefresh() }   // 인터넷이 돌아오면 다시
    }

    /// 기록함의 '다시 보내기' — 컴퓨터가 못 받았을 때
    func resend(_ e: Entry) {
        guard var cur = items.first(where: { $0.id == e.id }) else { return }
        if Relay.paired && cur.relay != .sending { cur.relay = .pending }
        if googlePaired && cur.google != .off { cur.google = .pending }
        if useICloud && icloudAvailable && cur.icloud != .off { cur.icloud = .pending }
        cur.received = false; cur.lastError = ""
        update(cur)
        Task { await syncAll(force: true) }
    }

    /// 선생님이 고른 경우에만, 컴퓨터로 전송이 끝난 기록을 휴대폰에서 지운다. 기본은 지우지 않음.
    func cleanupOld() {
        guard deleteAfterDays > 0 else { return }
        let limit = Date().addingTimeInterval(-Double(deleteAfterDays) * 24 * 3600)
        let old = items.filter { $0.createdAt < limit && ![.pending, .failed].contains($0.icloud)
            && ![.pending, .failed].contains($0.google) && ($0.icloud == .done || $0.google == .done) }
        old.forEach(delete)
    }

    func pair(url: String, token: String, name: String) {
        defaults.set(url, forKey: "googleURL")
        defaults.set(name, forKey: "teacherName")
        Keychain.set("googleToken", token)
        for i in items.indices where items[i].google == .off { items[i].google = .pending }
        save()
        objectWillChange.send()
        Task { await syncAll(force: true) }
    }

    /// QR 연동 (컴퓨터 쓰담의 새 QR) — 맥·윈도우 어떤 컴퓨터든
    func pairRelay(_ p: Relay.Pairing) {
        Relay.pair(p)
        if !p.name.isEmpty { defaults.set(p.name, forKey: "teacherName") }
        for i in items.indices where items[i].relay == .off { items[i].relay = .pending }
        save()
        objectWillChange.send()
        Task { await syncAll(force: true); await DataStore.shared.syncNow() }
    }

    func unpairRelay() {
        Task { await Relay.disconnectRemote(); Relay.unpair() }
        for i in items.indices where items[i].relay != .done { items[i].relay = .off }
        save()
        objectWillChange.send()
    }

    /// 다른 앱(음성 메모 등)에서 '공유 → 쓰담'으로 받은 녹음
    @discardableResult
    func addShared(_ src: URL) -> Entry? {
        let access = src.startAccessingSecurityScopedResource()
        defer { if access { src.stopAccessingSecurityScopedResource() } }
        let ext = src.pathExtension.isEmpty ? "m4a" : src.pathExtension.lowercased()
        let base = (src.lastPathComponent as NSString).deletingPathExtension
        let fileName = uniqueFile(String(base.prefix(40)).isEmpty ? "공유받은 녹음" : String(base.prefix(40)), ext)
        let dest = Store.folder.appendingPathComponent(fileName)
        do { try FileManager.default.copyItem(at: src, to: dest) } catch { return nil }
        let dur = (try? AVAudioPlayer(contentsOf: dest).duration) ?? 0
        var e = Entry(type: "audio", fileName: fileName, createdAt: Date(), duration: dur, kind: lastKind, memo: String(base.prefix(40)))
        if transcribeOnPhone { e.stt = .working }
        let saved = newEntry(e)
        if transcribeOnPhone { transcribe(saved) }
        return saved
    }

    func unpair() {
        defaults.removeObject(forKey: "googleURL")
        Keychain.delete("googleToken")
        for i in items.indices where items[i].google != .done { items[i].google = .off }
        save()
        objectWillChange.send()
    }
}

func timeString(_ t: TimeInterval) -> String {
    let s = Int(t)
    return s >= 3600 ? String(format: "%d:%02d:%02d", s / 3600, s / 60 % 60, s % 60) : String(format: "%d:%02d", s / 60, s % 60)
}
