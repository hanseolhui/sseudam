import SwiftUI
import WidgetKit
import AppIntents

private enum Brand {
    static let blue = Color(red: 0.18, green: 0.23, blue: 0.55)      // #2E3A8C
    static let lavender = Color(red: 0.29, green: 0.35, blue: 0.71)  // #4B58B5
    static let recordURL = URL(string: "sseudam://record")!
}

@main
struct SseudamWidgetBundle: WidgetBundle {
    var body: some Widget {
        QuickRecordWidget()
        if #available(iOS 18.0, *) {
            RecordControl()
        }
    }
}

// MARK: - 잠금 화면 위젯 (원형 · 사각형)

struct QuickRecordEntry: TimelineEntry {
    let date: Date
}

struct QuickRecordProvider: TimelineProvider {
    func placeholder(in context: Context) -> QuickRecordEntry { QuickRecordEntry(date: .now) }
    func getSnapshot(in context: Context, completion: @escaping (QuickRecordEntry) -> Void) {
        completion(QuickRecordEntry(date: .now))
    }
    func getTimeline(in context: Context, completion: @escaping (Timeline<QuickRecordEntry>) -> Void) {
        completion(Timeline(entries: [QuickRecordEntry(date: .now)], policy: .never))
    }
}

struct QuickRecordWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "kr.sseudam.app.widgets.quickrecord", provider: QuickRecordProvider()) { _ in
            QuickRecordView()
        }
        .configurationDisplayName("쓰담 녹음")
        .description("잠금 화면에서 눌러 바로 녹음해요.")
        .supportedFamilies([.accessoryCircular, .accessoryRectangular])
    }
}

struct QuickRecordView: View {
    @Environment(\.widgetFamily) private var family

    var body: some View {
        content
            .widgetURL(Brand.recordURL)
            .containerBackground(for: .widget) {
                if family == .accessoryCircular { AccessoryWidgetBackground() } else { Color.clear }
            }
    }

    @ViewBuilder var content: some View {
        switch family {
        case .accessoryRectangular:
            HStack(spacing: 8) {
                Image(systemName: "mic.fill")
                    .font(.system(size: 22, weight: .semibold, design: .rounded))
                    .widgetAccentable()
                VStack(alignment: .leading, spacing: 1) {
                    Text("쓰담")
                        .font(.system(.headline, design: .rounded))
                        .widgetAccentable()
                    Text("눌러서 말하기")
                        .font(.system(.caption, design: .rounded))
                }
                Spacer(minLength: 0)
            }
        default:
            Image(systemName: "mic.fill")
                .font(.system(size: 24, weight: .semibold, design: .rounded))
                .widgetAccentable()
        }
    }
}

// MARK: - 제어 센터 · 동작 버튼 컨트롤 (iOS 18+)

@available(iOS 18.0, *)
struct RecordControl: ControlWidget {
    var body: some ControlWidgetConfiguration {
        StaticControlConfiguration(kind: "kr.sseudam.app.widgets.recordcontrol") {
            ControlWidgetButton(action: OpenRecordIntent()) {
                Label("쓰담 녹음", systemImage: "mic.fill")
            }
            .tint(Brand.blue)
        }
        .displayName("쓰담 녹음")
        .description("눌러서 바로 녹음을 시작해요.")
    }
}

#if DEBUG
@available(iOS 17.0, *)
#Preview("원형", as: .accessoryCircular) {
    QuickRecordWidget()
} timeline: {
    QuickRecordEntry(date: .now)
}

@available(iOS 17.0, *)
#Preview("사각형", as: .accessoryRectangular) {
    QuickRecordWidget()
} timeline: {
    QuickRecordEntry(date: .now)
}
#endif
