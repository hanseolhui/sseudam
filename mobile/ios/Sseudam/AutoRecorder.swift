import AVFoundation
import Foundation
import UIKit

/// '말하면 담기' 판단만 하는 상태 기계 (소리 크기 dB만 보고 결정 — 테스트하기 쉽게 오디오와 분리)
struct AutoGate {
    enum Sensitivity: Int, CaseIterable { case quiet = 0, normal = 1, noisy = 2
        var label: String { ["조용한 곳", "보통", "시끄러운 곳"][rawValue] }
        /// (주변 소음보다 얼마나 커야 하는지, 아무리 조용해도 이보다는 커야 하는 dBFS)
        var margin: Float { [10, 14, 20][rawValue] }
        var absMin: Float { [-50, -45, -38][rawValue] }
    }
    enum Event { case none, start, stop(voiced: Double) }

    var sensitivity: Sensitivity = .normal
    var stopDelay: Double = 2.5          // 말 끝나고 이만큼 조용하면 끝
    let attack = 0.25                    // 이만큼 이어서 커야 시작 (문 닫는 소리 같은 순간 소리는 무시)
    let hysteresis: Float = 3            // 끝낼 때는 기준보다 3dB 더 작아야 조용한 걸로

    private(set) var floor: Float?       // 주변 소음 (적응)
    private(set) var capturing = false
    private var loudRun = 0.0
    private var silence = 0.0
    private(set) var voiced = 0.0
    private var warm: [Float] = []

    var threshold: Float { max((floor ?? -60) + sensitivity.margin, sensitivity.absMin) }

    /// 한 조각(dt초)의 소리 크기를 넣으면 시작/끝 여부를 돌려준다
    mutating func feed(db: Float, dt: Double) -> Event {
        if floor == nil {                      // 처음 1초는 주변 소음만 잰다
            warm.append(db)
            if Double(warm.count) * dt >= 1 { floor = warm.reduce(0, +) / Float(warm.count); warm = [] }
            return .none
        }
        let th = threshold
        if !capturing {
            if db > th { loudRun += dt } else { loudRun = 0 }
            if db < floor! { floor = floor! * 0.9 + db * 0.1 }          // 더 조용해지면 빨리 따라감
            else if db <= th { floor = floor! * 0.995 + db * 0.005 }     // 시끄러워지면 천천히 (말소리는 소음으로 안 배움)
            if loudRun >= attack {
                capturing = true; silence = 0; voiced = loudRun; loudRun = 0
                return .start
            }
            return .none
        }
        if db > th - hysteresis {
            silence = 0
            if db > th { voiced += dt }
        } else {
            silence += dt
            if silence >= stopDelay {
                capturing = false
                let v = voiced; voiced = 0; silence = 0
                return .stop(voiced: v)
            }
        }
        return .none
    }

    /// 강제로 끝낼 때 (화면 끔 · 손 녹음 시작)
    mutating func reset() -> Double? {
        let v = capturing ? voiced : nil
        capturing = false; loudRun = 0; silence = 0; voiced = 0
        return v
    }
}

/// 앱이 켜져 있는 동안만 귀 기울이다가, 말하면 녹음하고 말을 멈추면 끝낸다.
/// 배터리: 16kHz 모노 · 0.1초마다 소리 크기만 계산 · 화면이 꺼지거나 앱을 나가면 마이크를 완전히 놓는다.
@MainActor
final class AutoRecorder: ObservableObject {
    @Published var enabled = UserDefaults.standard.bool(forKey: "autoRec") { didSet { UserDefaults.standard.set(enabled, forKey: "autoRec") } }
    @Published var sensitivity = AutoGate.Sensitivity(rawValue: UserDefaults.standard.integer(forKey: "autoSens1") ) ?? .normal {
        didSet { UserDefaults.standard.set(sensitivity.rawValue, forKey: "autoSens1"); gate.sensitivity = sensitivity }
    }
    @Published var stopDelay: Double = UserDefaults.standard.object(forKey: "autoStop") as? Double ?? 2.5 {
        didSet { UserDefaults.standard.set(stopDelay, forKey: "autoStop"); gate.stopDelay = stopDelay }
    }
    @Published private(set) var listening = false
    @Published private(set) var capturing = false
    @Published private(set) var level: Float = 0          // 0...1
    @Published private(set) var thresholdLevel: Float = 0 // 0...1 (이 선을 넘으면 시작)
    @Published private(set) var captureElapsed: TimeInterval = 0
    @Published var justSaved = false
    @Published var permissionDenied = false

    /// 다 담은 조각 → (파일, 길이, 시작 시각)
    var onClip: ((URL, TimeInterval, Date) -> Void)?

    private let engine = AVAudioEngine()
    private var gate = AutoGate()
    private var preroll: [AVAudioPCMBuffer] = []
    private var prerollFrames: AVAudioFrameCount = 0
    private var file: AVAudioFile?
    private var url: URL?
    private var framesWritten: AVAudioFramePosition = 0
    private var sampleRate: Double = 16000
    private var clipStart = Date()
    private let maxClip: TimeInterval = 600

    init() {
        gate.sensitivity = sensitivity
        gate.stopDelay = stopDelay
    }

    static func dbToLevel(_ db: Float) -> Float { max(0, min(1, (db + 60) / 60)) }

    func start() async {
        guard enabled, !listening else { return }
        let granted = await withCheckedContinuation { c in
            AVAudioSession.sharedInstance().requestRecordPermission { c.resume(returning: $0) }
        }
        guard granted else { permissionDenied = true; enabled = false; return }
        guard enabled, !listening else { return }
        do {
            let s = AVAudioSession.sharedInstance()
            try s.setCategory(.playAndRecord, mode: .spokenAudio, options: [.defaultToSpeaker, .allowBluetooth, .mixWithOthers])
            try? s.setPreferredSampleRate(16000)
            try? s.setPreferredIOBufferDuration(0.1)
            try s.setActive(true)
            let input = engine.inputNode
            let fmt = input.outputFormat(forBus: 0)
            sampleRate = fmt.sampleRate
            guard let mono = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: fmt.sampleRate, channels: 1, interleaved: false) else { return }
            gate = AutoGate(); gate.sensitivity = sensitivity; gate.stopDelay = stopDelay
            preroll = []; prerollFrames = 0
            input.removeTap(onBus: 0)
            input.installTap(onBus: 0, bufferSize: AVAudioFrameCount(fmt.sampleRate * 0.1), format: fmt) { [weak self] buf, _ in
                guard let self else { return }
                let m = AutoRecorder.copyMono(buf, mono)
                let db = AutoRecorder.dbfs(m)
                Task { @MainActor in self.consume(m, db: db) }
            }
            engine.prepare()
            try engine.start()
            listening = true
        } catch {
            print("자동 녹음 시작 실패", error)
        }
    }

    /// 마이크를 놓는다. 담던 조각이 있으면 저장 (화면 끔 · 앱 나감 · 손 녹음 시작)
    func stop() {
        guard listening else { return }
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        listening = false; level = 0
        if let v = gate.reset() { finish(voiced: v) }
        preroll = []; prerollFrames = 0
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    nonisolated private static func copyMono(_ buf: AVAudioPCMBuffer, _ mono: AVAudioFormat) -> AVAudioPCMBuffer {
        guard let out = AVAudioPCMBuffer(pcmFormat: mono, frameCapacity: buf.frameLength),
              let src = buf.floatChannelData, let dst = out.floatChannelData else { return buf }
        out.frameLength = buf.frameLength
        dst[0].update(from: src[0], count: Int(buf.frameLength))   // 탭 버퍼는 재사용되므로 복사해 둔다
        return out
    }

    nonisolated private static func dbfs(_ buf: AVAudioPCMBuffer) -> Float {
        guard let d = buf.floatChannelData else { return -100 }
        let n = Int(buf.frameLength)
        var sum: Float = 0
        for i in stride(from: 0, to: n, by: 2) { sum += d[0][i] * d[0][i] }
        let rms = sqrt(sum / Float(max(1, n / 2)))
        return 20 * log10(max(rms, 0.000_01))
    }

    private func consume(_ buf: AVAudioPCMBuffer, db: Float) {
        guard listening else { return }
        let dt = Double(buf.frameLength) / sampleRate
        level = AutoRecorder.dbToLevel(db)
        thresholdLevel = AutoRecorder.dbToLevel(gate.threshold)
        switch gate.feed(db: db, dt: dt) {
        case .start:
            begin()
        case .stop(let voiced):
            write(buf)
            finish(voiced: voiced)
            return
        case .none:
            break
        }
        if capturing {
            write(buf)
            captureElapsed = Double(framesWritten) / sampleRate
            if captureElapsed >= maxClip {          // 너무 길면 끊어서 저장하고 계속 듣기
                let v = gate.reset() ?? captureElapsed
                finish(voiced: v)
            }
        } else {
            preroll.append(buf); prerollFrames += buf.frameLength
            while prerollFrames > AVAudioFrameCount(sampleRate * 1.0), let first = preroll.first {   // 말 시작 직전 1초를 남겨 둔다
                prerollFrames -= first.frameLength; preroll.removeFirst()
            }
        }
    }

    private func begin() {
        let u = FileManager.default.temporaryDirectory.appendingPathComponent("auto-" + UUID().uuidString + ".m4a")
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: sampleRate, AVNumberOfChannelsKey: 1,
            AVEncoderBitRateKey: 32000, AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue,
        ]
        do {
            file = try AVAudioFile(forWriting: u, settings: settings, commonFormat: .pcmFormatFloat32, interleaved: false)
        } catch { print("자동 녹음 파일 실패", error); return }
        url = u; framesWritten = 0
        clipStart = Date().addingTimeInterval(-Double(prerollFrames) / sampleRate)
        for b in preroll { write(b) }
        preroll = []; prerollFrames = 0
        capturing = true; captureElapsed = 0
        UIImpactFeedbackGenerator(style: .soft).impactOccurred()
    }

    private func write(_ buf: AVAudioPCMBuffer) {
        guard let file else { return }
        do { try file.write(from: buf); framesWritten += AVAudioFramePosition(buf.frameLength) } catch {}
    }

    private func finish(voiced: Double) {
        guard capturing, let u = url else { capturing = false; return }
        let d = Double(framesWritten) / sampleRate
        file = nil; url = nil; capturing = false; captureElapsed = 0   // 닫혀야 m4a가 마무리됨
        if voiced < 1.0 {                          // 기침 · 문소리처럼 짧은 소리는 버림
            try? FileManager.default.removeItem(at: u)
            return
        }
        onClip?(u, d, clipStart)
        justSaved = true
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        Task { try? await Task.sleep(nanoseconds: 2_000_000_000); justSaved = false }
    }
}
