import SwiftUI

@main
struct SseudamWatchApp: App {
    init() { Phone.shared.activate() }

    var body: some Scene {
        WindowGroup { RecordScreen() }
    }
}

private enum Brand {
    static let blue = Color(red: 0.40, green: 0.46, blue: 0.85)      // #6574D8 (검은 화면 위 남색)
    static let lavender = Color(red: 0.56, green: 0.61, blue: 0.92)  // #8F9BEA
    static let coral = Color(red: 1.00, green: 0.55, blue: 0.48)     // #FF8C7A
    static let mint = Color(red: 0.37, green: 0.82, blue: 0.65)      // #5FD1A5
    static let gradient = LinearGradient(colors: [blue, lavender], startPoint: .topLeading, endPoint: .bottomTrailing)
    static let warm = LinearGradient(colors: [coral, Color(red: 1, green: 0.66, blue: 0.5)],
                                     startPoint: .topLeading, endPoint: .bottomTrailing)
}

struct RecordScreen: View {
    @ObservedObject private var rec = WatchRecorder.shared
    @Environment(\.scenePhase) private var scenePhase
    @State private var pulse = false

    var body: some View {
        VStack(spacing: 8) {
            Text(title)
                .font(.system(.headline, design: .rounded))
                .foregroundStyle(rec.phase == .sent ? Brand.mint : .primary)
                .contentTransition(.opacity)
                .animation(.easeInOut, value: rec.phase)

            Button { rec.toggle() } label: { recordButton }
                .buttonStyle(.plain)
                .accessibilityLabel(rec.phase == .recording ? "녹음 멈추기" : "녹음 시작")

            Text(subtitle)
                .font(.system(.footnote, design: .rounded))
                .foregroundStyle(.secondary)
                .monospacedDigit()
        }
        .onAppear { rec.refreshPending() }
        .onChange(of: scenePhase) { _, p in if p == .active { rec.refreshPending() } }
    }

    private var recordButton: some View {
        ZStack {
            Circle()
                .fill(rec.phase == .recording ? Brand.warm : Brand.gradient)
                .shadow(color: Brand.blue.opacity(0.4), radius: 8, y: 3)
            if rec.phase == .recording {
                Circle()
                    .stroke(Brand.coral.opacity(0.6), lineWidth: 4)
                    .scaleEffect(pulse ? 1.15 : 1.0)
                    .opacity(pulse ? 0 : 1)
                    .animation(.easeOut(duration: 1.2).repeatForever(autoreverses: false), value: pulse)
                    .onAppear { pulse = true }
                    .onDisappear { pulse = false }
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(.white)
                    .frame(width: 30, height: 30)
            } else if rec.phase == .sent {
                Image(systemName: "checkmark")
                    .font(.system(size: 38, weight: .bold, design: .rounded))
                    .foregroundStyle(.white)
            } else {
                Image(systemName: "mic.fill")
                    .font(.system(size: 40, weight: .semibold, design: .rounded))
                    .foregroundStyle(.white)
            }
        }
        .frame(width: 100, height: 100)
        .animation(.spring(response: 0.35, dampingFraction: 0.7), value: rec.phase)
    }

    private var title: String {
        switch rec.phase {
        case .idle: return "쓰담"
        case .recording: return "듣고 있어요"
        case .sent: return "보냈어요 ✓"
        case .denied: return "마이크가 꺼져 있어요"
        case .failed: return "앗, 다시 눌러 주세요"
        }
    }

    private var subtitle: String {
        switch rec.phase {
        case .recording: return timeString(rec.elapsed)
        case .sent: return "아이폰 기록함에 담겨요"
        case .denied: return "설정에서 마이크를 켜 주세요"
        default:
            return rec.pendingCount > 0 ? "보내는 중 \(rec.pendingCount)개" : "눌러서 말하기"
        }
    }

    private func timeString(_ t: TimeInterval) -> String {
        let s = Int(t)
        return String(format: "%d:%02d", s / 60, s % 60)
    }
}

#Preview { RecordScreen() }
