import AVFoundation
import Foundation
import Speech

/// 녹음 중에 누른 표시: 학생 이름표(이제부터 이 학생 이야기) 또는 ⭐(중요한 순간)
struct Marker: Codable, Equatable, Hashable {
    var t: Double              // 녹음 시작부터 초
    var student: String?       // 학생 uid
    var star: Bool = false
}

/// AVAudioEngine 녹음: 파일(AAC m4a 모노)로 쓰면서 동시에 기기 안 받아쓰기로 실시간 글자를 보여 준다.
/// 화면이 꺼져도 계속 녹음(백그라운드 오디오). 실시간 글자는 미리 보기이고, 끝난 뒤 파일 전체를 다시 받아써 정확도를 높인다.
@MainActor
final class Recorder: NSObject, ObservableObject {
    @Published var isRecording = false
    @Published var isPaused = false
    @Published var elapsed: TimeInterval = 0
    @Published var level: Float = 0           // 0...1
    @Published var permissionDenied = false
    @Published var liveText = ""              // 실시간 받아쓰기 (미리 보기)
    @Published var markers: [Marker] = []
    @Published var currentStudent: String?
    /// 이번 녹음에서 선생님이 직접 고른 반(학급 uid)·교시 — 컴퓨터가 학급을 정할 때 쓴다
    @Published var pickedClass: String?
    @Published var period: Int?
    /// 손 없이 시작한 녹음(시리 · 얼굴 가까이): 말을 멈추면 저절로 끝낸다
    @Published private(set) var handsFree = false
    /// 저절로 끝났을 때 (말 멈춤 · '녹음 끝') — 화면이 저장한다
    var onAutoStop: (() -> Void)?
    private var floorDb: Float?
    private var warmDbs: [Float] = []
    private var loudRun = 0.0
    private var spoke = false
    private var quietRun = 0.0
    private var stopDelay = 2.5
    private var liveStartFrame: AVAudioFramePosition = 0   // 지금 받아쓰기 요청이 시작된 곳 ('녹음 끝' 자를 위치 계산)
    private(set) var trimTo: Double?                         // '녹음 끝'이라고 말한 곳 — 그 앞까지만 남긴다

    private let engine = AVAudioEngine()
    private var file: AVAudioFile?
    private var tempURL: URL?
    private var framesWritten: AVAudioFramePosition = 0
    private var sampleRate: Double = 44100
    private var timer: Timer?
    private(set) var startedAt = Date()

    // 실시간 받아쓰기
    private var recognizer: SFSpeechRecognizer?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var committed = ""                // 끊겨서 다시 시작한 앞부분
    private var hints: [String] = []

    override init() {
        super.init()
        NotificationCenter.default.addObserver(self, selector: #selector(interrupted(_:)),
                                               name: AVAudioSession.interruptionNotification, object: nil)
    }

    func start(hints: [String] = [], handsFree: Bool = false, stopDelay: Double = 2.5) async {
        let granted = await withCheckedContinuation { c in
            AVAudioSession.sharedInstance().requestRecordPermission { c.resume(returning: $0) }
        }
        guard granted else { permissionDenied = true; return }
        do {
            let s = AVAudioSession.sharedInstance()
            try s.setCategory(.playAndRecord, mode: .spokenAudio, options: [.defaultToSpeaker, .allowBluetooth])
            try s.setActive(true)
            let input = engine.inputNode
            let fmt = input.outputFormat(forBus: 0)
            sampleRate = fmt.sampleRate
            let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".m4a")
            let settings: [String: Any] = [
                AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: fmt.sampleRate, AVNumberOfChannelsKey: 1,
                AVEncoderBitRateKey: 40000, AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue,
            ]
            // 입력이 여러 채널이면 첫 채널만 쓰도록 모노 형식으로 받는다
            guard let mono = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: fmt.sampleRate, channels: 1, interleaved: false) else { return }
            file = try AVAudioFile(forWriting: url, settings: settings, commonFormat: .pcmFormatFloat32, interleaved: false)
            tempURL = url; framesWritten = 0
            self.hints = hints
            startLiveRecognition()
            input.removeTap(onBus: 0)
            input.installTap(onBus: 0, bufferSize: 4096, format: fmt) { [weak self] buf, _ in
                guard let self else { return }
                let m = Recorder.toMono(buf, mono)
                Task { @MainActor in self.consume(m) }
            }
            engine.prepare()
            try engine.start()
            startedAt = Date()
            isRecording = true; isPaused = false; elapsed = 0; liveText = ""; committed = ""; markers = []; currentStudent = nil; pickedClass = nil; period = nil
            self.handsFree = handsFree; self.stopDelay = stopDelay
            floorDb = nil; warmDbs = []; loudRun = 0; spoke = false; quietRun = 0; trimTo = nil
            timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
                Task { @MainActor in self?.tick() }
            }
        } catch {
            print("녹음 시작 실패", error)
        }
    }

    nonisolated private static func toMono(_ buf: AVAudioPCMBuffer, _ mono: AVAudioFormat) -> AVAudioPCMBuffer {
        if buf.format.channelCount == 1 && buf.format.commonFormat == .pcmFormatFloat32 { return buf }
        guard let out = AVAudioPCMBuffer(pcmFormat: mono, frameCapacity: buf.frameLength),
              let src = buf.floatChannelData, let dst = out.floatChannelData else { return buf }
        out.frameLength = buf.frameLength
        dst[0].update(from: src[0], count: Int(buf.frameLength))
        return out
    }

    private func consume(_ buf: AVAudioPCMBuffer) {
        guard isRecording, !isPaused else { return }
        do { try file?.write(from: buf); framesWritten += AVAudioFramePosition(buf.frameLength) } catch {}
        request?.append(buf)
        if let d = buf.floatChannelData {
            let n = Int(buf.frameLength)
            var sum: Float = 0
            for i in stride(from: 0, to: n, by: 8) { sum += d[0][i] * d[0][i] }
            let rms = sqrt(sum / Float(max(1, n / 8)))
            let db = 20 * log10(max(rms, 0.000_01))
            level = max(0, min(1, (db + 50) / 50))
            if handsFree { watchSilence(db: db, dt: Double(n) / sampleRate) }
        }
    }

    /// 손 없이 시작한 녹음: 주변 소음보다 큰 말소리가 나온 뒤, 정한 시간만큼 조용하면 끝낸다.
    /// 처음 8초 동안 아무 말도 없으면 그냥 끝낸다 (짧아서 버려짐).
    private func watchSilence(db: Float, dt: Double) {
        guard let floor = floorDb else {
            warmDbs.append(db)
            if Double(warmDbs.count) * dt >= 0.5 { floorDb = warmDbs.min() ?? db }   // 말을 바로 시작해도 되게 가장 조용한 값
            return
        }
        let th = max(floor + 12, -48)
        if db > th { loudRun += dt; quietRun = 0; if loudRun >= 0.3 { spoke = true } }
        else {
            loudRun = 0
            if db < floor { floorDb = floor * 0.9 + db * 0.1 }
            if db < th - 3 { quietRun += dt }
        }
        if spoke && quietRun >= stopDelay { onAutoStop?() }
        else if !spoke && elapsed > 8 { onAutoStop?() }
    }

    private func tick() { elapsed = Double(framesWritten) / sampleRate }

    // MARK: 실시간 받아쓰기 (기기 안에서만 · 끊기면 이어서 다시)
    private func startLiveRecognition() {
        guard SFSpeechRecognizer.authorizationStatus() == .authorized || SFSpeechRecognizer.authorizationStatus() == .notDetermined else { return }
        let r = SFSpeechRecognizer(locale: Locale(identifier: "ko-KR"))
        guard let r, r.supportsOnDeviceRecognition else { return }
        if SFSpeechRecognizer.authorizationStatus() == .notDetermined {
            SFSpeechRecognizer.requestAuthorization { _ in }
            return
        }
        recognizer = r
        let req = SFSpeechAudioBufferRecognitionRequest()
        req.requiresOnDeviceRecognition = true
        req.shouldReportPartialResults = true
        req.addsPunctuation = true
        if !hints.isEmpty { req.contextualStrings = Array(hints.prefix(100)) }
        request = req
        liveStartFrame = framesWritten
        task = r.recognitionTask(with: req) { [weak self] result, error in
            Task { @MainActor in
                guard let self else { return }
                if let result {
                    self.liveText = [self.committed, result.bestTranscription.formattedString].filter { !$0.isEmpty }.joined(separator: " ")
                    if self.checkStopWord(result.bestTranscription) { return }
                    if result.isFinal { self.restartLive() }
                } else if error != nil {
                    self.restartLive()
                }
            }
        }
    }

    /// '녹음 끝' · '녹음 그만'이라고 말하면 끝 — 그 말 앞까지만 남긴다
    private func checkStopWord(_ t: SFTranscription) -> Bool {
        guard isRecording, trimTo == nil else { return false }
        let segs = t.segments
        guard segs.count >= 1 else { return false }
        let words = segs.map { $0.substring.replacingOccurrences(of: " ", with: "").trimmingCharacters(in: .punctuationCharacters) }
        for i in words.indices.reversed().prefix(4) {
            let w = words[i], next = i + 1 < words.count ? words[i + 1] : ""
            let joined = w + next
            if joined.hasPrefix("녹음끝") || joined.hasPrefix("녹음그만") || w == "녹음끝" || w == "녹음그만" {
                trimTo = max(0, Double(liveStartFrame) / sampleRate + segs[i].timestamp - 0.2)
                onAutoStop?()
                return true
            }
        }
        return false
    }

    private func restartLive() {
        guard isRecording else { return }
        committed = liveText
        task?.cancel(); task = nil; request = nil
        startLiveRecognition()
    }

    private func stopLive() {
        request?.endAudio(); task?.cancel(); task = nil; request = nil
    }

    // MARK: 표시
    /// 학생 이름표: 지금부터 이 학생 이야기
    func mark(student uid: String) {
        guard isRecording else { return }
        currentStudent = uid
        markers.append(Marker(t: elapsed, student: uid))
    }
    func star() {
        guard isRecording else { return }
        markers.append(Marker(t: elapsed, student: nil, star: true))
    }

    func togglePause() {
        guard isRecording else { return }
        if isPaused { try? engine.start(); isPaused = false } else { engine.pause(); isPaused = true; level = 0 }
    }

    /// 녹음 끝 → (임시 파일, 길이, 시작 시각, 표시들)
    func stop() -> (URL, TimeInterval, Date, [Marker])? {
        guard isRecording, let url = tempURL else { return nil }
        let d = Double(framesWritten) / sampleRate
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        stopLive()
        file = nil   // 닫혀야 m4a가 마무리됨
        timer?.invalidate(); timer = nil
        isRecording = false; isPaused = false; level = 0; handsFree = false
        let m = markers
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        return (url, d, startedAt, m)
    }

    func discard() {
        if let r = stop() { try? FileManager.default.removeItem(at: r.0) }
        liveText = ""; markers = []
    }

    @objc nonisolated private func interrupted(_ n: Notification) {
        guard let raw = n.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
              let type = AVAudioSession.InterruptionType(rawValue: raw) else { return }
        Task { @MainActor in
            // 전화가 오면 일시정지 → 끝나면 사용자가 다시 누르도록
            if type == .began, self.isRecording, !self.isPaused { self.engine.pause(); self.isPaused = true }
        }
    }
}

/// '녹음 끝' 앞까지만 남긴 새 파일 (잘라 내지 못하면 원래 파일)
func trimAudio(_ url: URL, to seconds: Double) async -> URL {
    let asset = AVURLAsset(url: url)
    guard seconds > 0.5, let ex = AVAssetExportSession(asset: asset, presetName: AVAssetExportPresetPassthrough) else { return url }
    let out = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".m4a")
    ex.outputURL = out
    ex.outputFileType = .m4a
    ex.timeRange = CMTimeRange(start: .zero, duration: CMTime(seconds: seconds, preferredTimescale: 600))
    await ex.export()
    guard ex.status == .completed else { return url }
    try? FileManager.default.removeItem(at: url)
    return out
}
