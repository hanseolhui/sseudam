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

    func start(hints: [String] = []) async {
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
        }
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
        task = r.recognitionTask(with: req) { [weak self] result, error in
            Task { @MainActor in
                guard let self else { return }
                if let result {
                    self.liveText = [self.committed, result.bestTranscription.formattedString].filter { !$0.isEmpty }.joined(separator: " ")
                    if result.isFinal { self.restartLive() }
                } else if error != nil {
                    self.restartLive()
                }
            }
        }
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
        isRecording = false; isPaused = false; level = 0
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
