import AVFoundation
import SwiftUI

/// 기록함: 날짜별로 모아 보기 · 밀어서 보내기(AirDrop)·지우기 · 여러 개 골라 한꺼번에 보내기
struct RecordsView: View {
    @EnvironmentObject var store: Store
    @StateObject private var player = Player()
    @State private var selecting = false
    @State private var selected = Set<UUID>()
    @State private var confirmDelete: Entry?

    var body: some View {
        NavigationStack {
            Group {
                if store.items.isEmpty { empty } else { list }
            }
            .softBackground()
            .navigationTitle("기록함")
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    if !store.items.isEmpty {
                        Button(selecting ? "완료" : "골라서 보내기") { selecting.toggle(); selected.removeAll() }
                            .font(Theme.font(15, .semibold))
                    }
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    if store.syncing { ProgressView() }
                    else if !selecting {
                        Button { Task { await store.syncAll(force: true) } } label: { Image(systemName: "arrow.clockwise") }
                            .accessibilityLabel("지금 보내기")
                    }
                }
            }
            .safeAreaInset(edge: .bottom) {
                if selecting && !selected.isEmpty {
                    ShareLink(items: store.items.filter { selected.contains($0.id) }.map { store.url($0) }) {
                        Label("\(selected.count)개 보내기 (AirDrop 등)", systemImage: "square.and.arrow.up")
                            .font(Theme.font(17, .bold)).frame(maxWidth: .infinity).padding(.vertical, 14)
                            .background(Theme.brand, in: Capsule()).foregroundStyle(.white)
                    }
                    .padding(.horizontal, 20).padding(.bottom, 8)
                }
            }
            .alert("이 기록을 지울까요?", isPresented: Binding(get: { confirmDelete != nil }, set: { if !$0 { confirmDelete = nil } })) {
                Button("지우기", role: .destructive) { if let e = confirmDelete { store.delete(e) }; confirmDelete = nil }
                Button("취소", role: .cancel) { confirmDelete = nil }
            } message: {
                Text(confirmDelete.map { $0.icloud == .done || $0.google == .done } == true
                     ? "컴퓨터에는 이미 보내져 보관되어 있어요." : "아직 컴퓨터로 보내지 않았어요. 지우면 되돌릴 수 없어요.")
            }
        }
    }

    var empty: some View {
        VStack(spacing: 14) {
            Spacer()
            Dami(size: 90, mood: .calm)
            Text("아직 담은 기록이 없어요").font(Theme.font(20, .bold))
            Text("‘담기’에서 녹음하거나 한 줄 메모를 남기면\n여기에 날짜별로 차곡차곡 쌓여요.")
                .font(Theme.font(15)).foregroundStyle(Theme.soft).multilineTextAlignment(.center)
            Spacer()
        }.frame(maxWidth: .infinity)
    }

    var groups: [(String, [Entry])] {
        let cal = Calendar.current
        let f = DateFormatter(); f.locale = Locale(identifier: "ko_KR"); f.dateFormat = "M월 d일 EEEE"
        var out: [(String, [Entry])] = []
        for e in store.items {
            let key = cal.isDateInToday(e.createdAt) ? "오늘" : cal.isDateInYesterday(e.createdAt) ? "어제" : f.string(from: e.createdAt)
            if let i = out.firstIndex(where: { $0.0 == key }) { out[i].1.append(e) } else { out.append((key, [e])) }
        }
        return out
    }

    var list: some View {
        List {
            if !store.autoSend {
                Section {
                    Button { Nav.shared.tab = .connect } label: {
                        HStack {
                            Label("아직 컴퓨터와 연결되지 않았어요", systemImage: "link").font(Theme.font(14, .semibold))
                            Spacer()
                            Text("연결하기").font(Theme.font(13, .bold))
                        }.foregroundStyle(Theme.coral)
                    }
                    Text("기록은 휴대폰에 안전하게 보관돼요. 연결하면 쌓인 기록이 한꺼번에 보내지고, 지금은 밀어서 AirDrop으로도 보낼 수 있어요.")
                        .font(Theme.font(12)).foregroundStyle(Theme.soft)
                }.listRowBackground(Theme.coral.opacity(0.08))
            }
            ForEach(groups, id: \.0) { title, entries in
                Section {
                    ForEach(entries) { e in
                        row(e)
                            .listRowBackground(Theme.card)
                            .swipeActions(edge: .trailing) {
                                Button(role: .destructive) { confirmDelete = e } label: { Label("지우기", systemImage: "trash") }
                                ShareLink(item: store.url(e)) { Label("보내기", systemImage: "square.and.arrow.up") }.tint(Theme.blue)
                            }
                    }
                } header: {
                    Text(title).font(Theme.font(14, .bold)).foregroundStyle(Theme.soft)
                }
            }
        }
        .scrollContentBackground(.hidden)
        .refreshable { await store.syncAll(force: true) }
    }

    @ViewBuilder func row(_ e: Entry) -> some View {
        let content = HStack(spacing: 12) {
            if selecting {
                Image(systemName: selected.contains(e.id) ? "checkmark.circle.fill" : "circle")
                    .font(.title2).foregroundStyle(selected.contains(e.id) ? Theme.blue : Color.secondary)
            }
            ZStack {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill((e.isAudio ? Theme.blue : Theme.butter).opacity(0.16)).frame(width: 44, height: 44)
                Image(systemName: e.isAudio ? (player.playing == e.id ? "stop.fill" : "waveform") : "text.quote")
                    .font(.system(size: 18, weight: .semibold)).foregroundStyle(e.isAudio ? Theme.blue : Color.orange)
            }
            VStack(alignment: .leading, spacing: 4) {
                Text(e.title).font(Theme.font(16, .semibold)).lineLimit(2).foregroundStyle(Theme.ink)
                HStack(spacing: 6) {
                    Text(e.createdAt.formatted(date: .omitted, time: .shortened)).font(Theme.font(12)).foregroundStyle(Theme.soft)
                    Text(e.kind).font(Theme.font(11, .bold)).padding(.horizontal, 7).padding(.vertical, 2)
                        .foregroundStyle(e.kind == "상담" ? Theme.lavender : Theme.blue)
                        .background((e.kind == "상담" ? Theme.lavender : Theme.blue).opacity(0.14), in: Capsule())
                    syncBadge(e)
                }
                if let names = e.splitNames, !names.isEmpty {
                    HStack(spacing: 4) {
                        Image(systemName: "person.2.fill").font(.system(size: 10, weight: .bold))
                        Text(names.prefix(3).joined(separator: " · ") + (names.count > 3 ? " 외 \(names.count - 3)명" : ""))
                            .font(Theme.font(12, .semibold)).lineLimit(1)
                        if e.splitUnsure > 0 || !e.splitLeftover.isEmpty {
                            Image(systemName: "questionmark.circle.fill").foregroundStyle(Theme.butter)
                        }
                    }
                    .foregroundStyle(Theme.lavender)
                }
                if !e.lastError.isEmpty && (e.icloud == .failed || e.google == .failed) {
                    Text(e.lastError).font(Theme.font(11)).foregroundStyle(Theme.coral).lineLimit(2)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 4)
        .contentShape(Rectangle())

        if selecting {
            Button { if selected.contains(e.id) { selected.remove(e.id) } else { selected.insert(e.id) } } label: { content }
                .buttonStyle(.plain)
        } else {
            NavigationLink { EntryDetail(entry: e, player: player) } label: { content }
        }
    }

    @ViewBuilder func syncBadge(_ e: Entry) -> some View {
        let states = [e.icloud, e.google, e.relay].filter { $0 != .off }
        if e.stt == .working { mini("text.bubble", "받아쓰는 중", Theme.soft) }
        else if states.contains(.failed) { mini("exclamationmark.triangle.fill", "다시 시도", Theme.coral) }
        else if e.received { mini("checkmark.circle.fill", "컴퓨터가 받음", Theme.mint) }
        else if e.relay == .done && e.relaySentAt != nil { mini("paperplane.fill", "보냄 · 컴퓨터 대기", Theme.blue) }
        else if e.google == .done { mini("checkmark.circle.fill", "보냄", Theme.mint) }
        else if e.icloud == .done { mini("icloud.fill", "iCloud에 올림", Theme.blue) }
        else if states.contains(.sending) { mini("arrow.up.circle", "보내는 중", Theme.blue) }
        else if states.contains(.pending) { mini("clock", "보낼 예정", Theme.soft) }
        else if states.contains(.done) { mini("checkmark.circle.fill", "보냄", Theme.mint) }
        else { mini("iphone", "휴대폰에만 있음", Theme.soft) }
    }

    func mini(_ icon: String, _ text: String, _ color: Color) -> some View {
        HStack(spacing: 3) {
            Image(systemName: icon).font(.system(size: 10, weight: .semibold))
            Text(text).font(Theme.font(11, .semibold))
        }.foregroundStyle(color)
    }
}

/// 기록 자세히 보기: 듣기 · 고치기 · 보내기
struct EntryDetail: View {
    @EnvironmentObject var store: Store
    @Environment(\.dismiss) private var dismiss
    var entry: Entry
    @ObservedObject var player: Player
    @State private var kind = "수업"
    @State private var memo = ""
    @State private var text = ""
    @State private var transcript = ""

    var current: Entry { store.items.first(where: { $0.id == entry.id }) ?? entry }
    var sent: Bool { current.icloud == .done || current.google == .done }

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                VStack(spacing: 14) {
                    if current.isAudio {
                        Button { player.toggle(current.id, store.url(current)) } label: {
                            ZStack {
                                Circle().fill(Theme.brand).frame(width: 96, height: 96)
                                Image(systemName: player.playing == current.id ? "stop.fill" : "play.fill")
                                    .font(.system(size: 36, weight: .bold)).foregroundStyle(.white)
                            }
                        }.buttonStyle(Squishy())
                        Text(timeString(current.duration)).font(Theme.font(22, .light)).monospacedDigit()
                    } else {
                        TextField("메모", text: $text, axis: .vertical).font(Theme.font(17)).lineLimit(3...12)
                            .disabled(sent)
                    }
                    Text(current.createdAt.formatted(date: .long, time: .shortened)).font(Theme.font(13)).foregroundStyle(Theme.soft)
                }
                .frame(maxWidth: .infinity).card(padding: 22)

                if current.isAudio { transcriptCard }
                if !current.isAudio || current.stt == .done || !current.transcript.isEmpty {
                    RecordingSplitSection(entry: current)
                }

                VStack(alignment: .leading, spacing: 12) {
                    if Features.counseling {
                        HStack { Text("유형").font(Theme.font(15, .semibold)); Spacer(); KindPicker(kind: $kind).disabled(sent) }
                    }
                    if current.isAudio {
                        TextField("메모 (예: 2-3 국어 토론)", text: $memo).font(Theme.font(15))
                            .padding(10).background(Theme.bg, in: RoundedRectangle(cornerRadius: 12)).disabled(sent)
                    }
                    Text(sent ? "이미 컴퓨터로 보냈어요. 바꿀 내용은 컴퓨터의 쓰담에서 고쳐 주세요." : "보내기 전이라 고칠 수 있어요.")
                        .font(Theme.font(12)).foregroundStyle(Theme.soft)
                }.card()

                VStack(alignment: .leading, spacing: 10) {
                    if current.relay != .off { status("컴퓨터 (QR 연결)", current.relay, received: current.received) }
                    status("iCloud (맥)", current.icloud, received: current.received)
                    status("구글 드라이브", current.google)
                    if !current.lastError.isEmpty { Text(current.lastError).font(Theme.font(12)).foregroundStyle(Theme.coral) }
                    if !current.received && (current.relaySentAt != nil || current.icloud == .done) {
                        HStack {
                            Text("컴퓨터가 아직 안 받았어요. 컴퓨터 쓰담이 켜지면 가져가요.").font(Theme.font(12)).foregroundStyle(Theme.soft)
                            Spacer()
                            Button("다시 보내기") { store.resend(current) }.font(Theme.font(13, .bold))
                        }
                    }
                }.card()

                ShareLink(item: store.url(current)) {
                    Label("AirDrop · 다른 앱으로 보내기", systemImage: "square.and.arrow.up")
                        .font(Theme.font(16, .bold)).frame(maxWidth: .infinity).padding(.vertical, 14)
                        .background(Theme.blue.opacity(0.12), in: Capsule()).foregroundStyle(Theme.blue)
                }
                Text("맥으로 AirDrop하면 쓰담이 ‘다운로드’ 폴더에서 자동으로 가져가요.")
                    .font(Theme.font(12)).foregroundStyle(Theme.soft)
            }
            .padding(18).frame(maxWidth: 640).frame(maxWidth: .infinity)
        }
        .softBackground()
        .navigationTitle(current.isAudio ? "녹음" : "메모")
        .bigBackButton("기록함")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { kind = current.kind; memo = current.memo; text = current.text; transcript = current.transcript }
        .onChange(of: current.transcript) { t in if transcript.isEmpty { transcript = t } }
        .onDisappear {
            player.stop()
            let tChanged = current.isAudio && transcript != current.transcript
            if !sent && (kind != current.kind || memo != current.memo || (!current.isAudio && text != current.text) || tChanged) {
                store.edit(current, kind: kind, memo: memo, text: current.isAudio ? nil : text,
                           transcript: tChanged ? transcript : nil)
            }
        }
    }

    /// 아이폰에서 받아쓴 글 — 보내기 전에는 고칠 수 있다
    @ViewBuilder var transcriptCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label("받아쓴 글", systemImage: "text.bubble.fill").font(Theme.font(15, .semibold))
                Spacer()
                if current.stt != .working {
                    // 받아쓰기 엔진이 좋아졌을 때 예전 녹음도 다시 받아쓸 수 있게 (학생별 조각도 다시 나눔)
                    Button("다시 받아쓰기") { transcript = ""; store.transcribe(current, resplit: true) }.font(Theme.font(13, .semibold))
                }
            }
            switch current.stt {
            case .working:
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("아이폰에서 글자로 바꾸는 중…").font(Theme.font(14)).foregroundStyle(Theme.soft)
                }
            case .done where !current.transcript.isEmpty:
                if !current.starSnippets.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(current.starSnippets, id: \.self) { s in
                            Label(s, systemImage: "star.fill").font(Theme.font(14, .semibold))
                                .foregroundStyle(Theme.ink).labelStyle(StarLabel())
                        }
                    }
                    .padding(10).frame(maxWidth: .infinity, alignment: .leading)
                    .background(Theme.butter.opacity(0.12), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
                TextField("받아쓴 글", text: $transcript, axis: .vertical).font(Theme.font(16)).lineLimit(3...20)
                    .disabled(sent)
                Text(sent ? "컴퓨터로 함께 보냈어요." : "잘못 들린 이름이나 낱말은 여기서 고쳐요. 보낼 때 함께 가요.")
                    .font(Theme.font(12)).foregroundStyle(Theme.soft)
            case .done:
                Text("말소리를 찾지 못했어요.").font(Theme.font(14)).foregroundStyle(Theme.soft)
            case .unavailable, .failed, .none:
                Text(current.sttNote.isEmpty ? "컴퓨터의 쓰담이 글자로 바꿔요." : current.sttNote)
                    .font(Theme.font(14)).foregroundStyle(Theme.soft)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    func status(_ name: String, _ s: SyncState, received: Bool = false) -> some View {
        HStack {
            Text(name).font(Theme.font(14))
            Spacer()
            switch s {
            case .off: Text("사용 안 함").font(Theme.font(13)).foregroundStyle(.tertiary)
            case .pending: Pill(text: "보낼 예정", icon: "clock", color: .gray)
            case .sending: Pill(text: "보내는 중", icon: "arrow.up.circle", color: Theme.blue)
            case .done where received: Pill(text: "컴퓨터가 받음", icon: "checkmark", color: Theme.mint)
            case .done where name.hasPrefix("iCloud"): Pill(text: "iCloud에 올림 · 맥 대기", icon: "icloud", color: Theme.blue)
            case .done where name.hasPrefix("컴퓨터") && current.relaySentAt != nil: Pill(text: "보냄 · 컴퓨터 대기", icon: "paperplane", color: Theme.blue)
            case .done: Pill(text: "보냄", icon: "checkmark", color: Theme.mint)
            case .failed: Pill(text: "다시 시도", icon: "exclamationmark.triangle", color: Theme.coral)
            }
        }
    }
}

struct StarLabel: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(alignment: .top, spacing: 6) {
            configuration.icon.foregroundStyle(Theme.butter).font(.system(size: 12))
            configuration.title
        }
    }
}

@MainActor
final class Player: NSObject, ObservableObject, AVAudioPlayerDelegate {
    @Published var playing: UUID?
    private var p: AVAudioPlayer?
    func stop() { p?.stop(); p = nil; playing = nil }

    func toggle(_ id: UUID, _ url: URL) {
        if playing == id { p?.stop(); playing = nil; return }
        try? AVAudioSession.sharedInstance().setCategory(.playback)
        try? AVAudioSession.sharedInstance().setActive(true)
        p = try? AVAudioPlayer(contentsOf: url)
        p?.delegate = self
        p?.play()
        playing = id
    }
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in self.playing = nil }
    }
}
