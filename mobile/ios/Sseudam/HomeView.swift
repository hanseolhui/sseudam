import Combine
import SwiftUI

/// 담기 화면: 큰 녹음 버튼 하나 + 한 줄 메모. 묻지 않고 바로 저장하고, 필요하면 저장 카드에서 고친다.
struct HomeView: View {
    @EnvironmentObject var store: Store
    @EnvironmentObject var nav: Nav
    @EnvironmentObject var data: DataStore
    @AppStorage("markClass") private var markClass = ""
    @StateObject private var rec = Recorder()
    @StateObject private var auto = AutoRecorder()
    @Environment(\.scenePhase) private var scenePhase
    @State private var autoMore = false
    @State private var autoNotice = false
    @AppStorage("autoNoticeSeen") private var autoNoticeSeen = false
    @State private var memoText = ""
    @State private var memoKind = Store.shared.lastKind
    @State private var showTips = false
    @FocusState private var memoFocused: Bool

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 18) {
                    header
                    recordCard
                    if let id = store.justSaved, let e = store.items.first(where: { $0.id == id }), !rec.isRecording {
                        SavedCard(entry: e) { withAnimation { store.justSaved = nil } }
                            .transition(.move(edge: .top).combined(with: .opacity))
                    }
                    memoCard
                    howCard
                }
                .padding(.horizontal, 18).padding(.bottom, 100)
                .frame(maxWidth: 640)
                .frame(maxWidth: .infinity)
            }
            .scrollDismissesKeyboard(.interactively)
            .softBackground()
            .toolbar(.hidden, for: .navigationBar)
            .sheet(isPresented: $showTips) { TipsView() }
            .alert("마이크 권한이 필요해요", isPresented: $rec.permissionDenied) {
                Button("설정 열기") { UIApplication.shared.open(URL(string: UIApplication.openSettingsURLString)!) }
                Button("닫기", role: .cancel) {}
            } message: { Text("설정 → 쓰담 → 마이크를 켜 주세요.") }
            .alert("주변 소리도 담길 수 있어요", isPresented: $autoNotice) {
                Button("알겠어요") { autoNoticeSeen = true }
            } message: { Text("앱을 켜 둔 동안 말소리가 들리면 녹음해요. 주변 사람 목소리도 담길 수 있고, 녹음은 이 폰과 연결한 컴퓨터에만 저장돼요. 화면이 꺼지면 쉬어요.") }
            .onChange(of: nav.startRecordingRequest) { _ in checkStartRequest() }
            .onAppear { checkStartRequest(); setupAuto(); resumeAuto() }
            .onDisappear { auto.stop() }
            .onChange(of: scenePhase) { p in if p == .active { resumeAuto() } else { auto.stop() } }
            .animation(.spring(response: 0.4, dampingFraction: 0.8), value: store.justSaved)
            .animation(.spring(response: 0.4, dampingFraction: 0.85), value: rec.isRecording)
        }
    }

    // MARK: 머리말
    var header: some View {
        HStack(spacing: 14) {
            Dami(size: 58, mood: rec.isRecording ? .listening : .happy)
            VStack(alignment: .leading, spacing: 4) {
                Text(greeting).font(Theme.font(22, .bold))
                HStack(spacing: 6) {
                    if store.autoSend && store.computerSeen {
                        Pill(text: "컴퓨터로 자동 전송", icon: "checkmark.circle.fill", color: Theme.mint)
                    } else if store.autoSend {
                        Button { nav.tab = .connect } label: {
                            Pill(text: "컴퓨터 쓰담 기다리는 중", icon: "hourglass", color: Theme.butter)
                        }
                    } else {
                        Button { nav.tab = .connect } label: {
                            Pill(text: "컴퓨터와 연결하기", icon: "link", color: Theme.coral)
                        }
                    }
                    if store.todayCount > 0 {
                        Pill(text: "오늘 \(store.todayCount)개", icon: "sparkles", color: Theme.lavender)
                    }
                }
            }
            Spacer(minLength: 0)
            Button { showTips = true } label: {
                Image(systemName: "questionmark").font(.system(size: 16, weight: .bold)).foregroundStyle(Theme.blue)
                    .frame(width: 38, height: 38).background(Theme.blue.opacity(0.12), in: Circle())
            }
            .buttonStyle(Squishy())
            .accessibilityLabel("사용 방법")
        }
        .padding(.top, 6)
    }

    var greeting: String {
        if rec.isRecording { return "잘 듣고 있어요" }
        let h = Calendar.current.component(.hour, from: Date())
        if h < 12 { return "좋은 아침이에요!" }
        if h < 17 { return "오늘 수업, 한마디 남겨요" }
        return "오늘도 수고하셨어요"
    }

    // MARK: 녹음
    var recordCard: some View {
        VStack(spacing: 16) {
            ZStack {
                if rec.isRecording && !rec.isPaused {
                    PulseRings(color: Theme.coral, level: CGFloat(rec.level))
                }
                Button(action: toggle) {
                    ZStack {
                        Circle().fill(rec.isRecording ? Theme.warm : Theme.brand)
                            .frame(width: 148, height: 148)
                            .shadow(color: (rec.isRecording ? Theme.coral : Theme.blue).opacity(0.4), radius: 18, y: 8)
                        Image(systemName: rec.isRecording ? "stop.fill" : "mic.fill")
                            .font(.system(size: 52, weight: .semibold)).foregroundStyle(.white)
                    }
                }
                .buttonStyle(Squishy())
                .accessibilityLabel(rec.isRecording ? "녹음 끝내기" : "녹음 시작")
            }
            .frame(height: 200)

            Text(rec.isRecording ? timeString(rec.elapsed) : "눌러서 말하기")
                .font(Theme.font(rec.isRecording ? 40 : 20, rec.isRecording ? .light : .semibold))
                .monospacedDigit()
                .contentTransition(.numericText())

            Text(statusText).font(Theme.font(14)).foregroundStyle(Theme.soft).multilineTextAlignment(.center)

            if !rec.isRecording { autoCard }

            if rec.isRecording && !rec.liveText.isEmpty {
                LiveCaption(text: rec.liveText).transition(.opacity.combined(with: .move(edge: .bottom)))
            }
            if rec.isRecording && data.hasRoster {
                markStrip.transition(.opacity.combined(with: .move(edge: .bottom)))
            }
            if rec.isRecording {
                HStack(spacing: 10) {
                    periodMenu
                    Button { rec.togglePause() } label: {
                        Label(rec.isPaused ? "이어서" : "잠깐 멈춤", systemImage: rec.isPaused ? "play.fill" : "pause.fill")
                            .font(Theme.font(15, .semibold)).padding(.horizontal, 18).padding(.vertical, 10)
                            .background(Theme.blue.opacity(0.12), in: Capsule())
                    }
                    Button(role: .destructive) { rec.discard() } label: {
                        Label("버리기", systemImage: "xmark").font(Theme.font(15, .semibold))
                            .padding(.horizontal, 18).padding(.vertical, 10)
                            .background(Theme.coral.opacity(0.12), in: Capsule())
                    }.foregroundStyle(Theme.coral)
                }
                .buttonStyle(Squishy())
            }
        }
        .frame(maxWidth: .infinity)
        .card(padding: 22)
    }

    /// 몇 교시 수업인지 (컴퓨터 시간표로 반을 정확히 찾게 · 고르지 않으면 녹음 시각으로 찾음)
    var periodMenu: some View {
        Menu {
            Button("안 정함") { rec.period = nil }
            ForEach(1...9, id: \.self) { p in Button("\(p)교시") { rec.period = p } }
        } label: {
            Label(rec.period.map { "\($0)교시" } ?? "교시", systemImage: "clock")
                .font(Theme.font(15, .semibold)).padding(.horizontal, 14).padding(.vertical, 10)
                .background(Theme.lavender.opacity(rec.period == nil ? 0.12 : 0.25), in: Capsule())
                .foregroundStyle(Theme.lavender)
        }
        .accessibilityLabel("몇 교시 수업인지 고르기")
    }

    /// 녹음하면서 톡: 이 학생 이야기 / ⭐ 중요
    var markClassObj: SClass? {
        data.currentClasses.first { $0.uid == markClass } ?? data.currentClasses.first ?? data.activeClasses.first
    }

    var markStrip: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Text("누구 이야기인지 톡").font(Theme.font(13, .bold)).foregroundStyle(Theme.soft)
                Menu {
                    ForEach(data.activeClasses) { c in Button(c.title) { markClass = c.uid; rec.pickedClass = c.uid } }
                } label: {
                    HStack(spacing: 3) {
                        Text(markClassObj?.title ?? "반 고르기").font(Theme.font(12, .bold))
                        Image(systemName: "chevron.down").font(.system(size: 9, weight: .bold))
                    }
                    .padding(.horizontal, 9).padding(.vertical, 4)
                    .background(Theme.blue.opacity(0.12), in: Capsule()).foregroundStyle(Theme.blue)
                }
                Spacer()
                Button {
                    rec.star()
                    UIImpactFeedbackGenerator(style: .rigid).impactOccurred()
                } label: {
                    Label("\(rec.markers.filter(\.star).count)", systemImage: "star.fill").font(Theme.font(13, .bold))
                        .padding(.horizontal, 11).padding(.vertical, 6)
                        .background(Theme.butter.opacity(0.2), in: Capsule()).foregroundStyle(Theme.butter)
                        .contentTransition(.numericText())
                }
                .buttonStyle(Squishy())
                .accessibilityLabel("중요한 순간 표시")
            }
            ScrollViewReader { proxy in
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) {
                        ForEach(markClassObj.map { data.students(in: $0) } ?? []) { s in
                            let on = rec.currentStudent == s.uid
                            Button {
                                withAnimation(.spring(response: 0.3, dampingFraction: 0.6)) { rec.mark(student: s.uid) }
                                UIImpactFeedbackGenerator(style: .light).impactOccurred()
                            } label: {
                                Text(s.displayName).font(Theme.font(14, on ? .bold : .semibold))
                                    .padding(.horizontal, 12).padding(.vertical, 8)
                                    .background(on ? AnyShapeStyle(Theme.brand) : AnyShapeStyle(Theme.bg), in: Capsule())
                                    .foregroundStyle(on ? .white : Theme.ink)
                                    .scaleEffect(on ? 1.06 : 1)
                            }
                            .buttonStyle(Squishy())
                            .id(s.uid)
                        }
                    }
                }
                .onChange(of: rec.currentStudent) { id in if let id { withAnimation { proxy.scrollTo(id, anchor: .center) } } }
            }
            if let cur = rec.currentStudent, let s = data.student(cur) {
                Text("지금부터 \(s.displayName) 이야기로 담아요 ✍️").font(Theme.font(12, .semibold)).foregroundStyle(Theme.lavender)
            }
        }
        .padding(12)
        .background(Theme.bg.opacity(0.6), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    var statusText: String {
        if !rec.isRecording { return "학년·반·이름부터 말하면 학생별로 쏙쏙 담겨요 ✨\n“2학년 3반 김민수! 친구 의견 모아 멋지게 발표 🌟”" }
        return rec.isPaused ? "잠깐 멈췄어요" : "화면을 꺼도 계속 녹음돼요 · 끝나면 한 번 더 누르세요"
    }

    /// 위젯·제어센터·단축어·워치에서 온 '녹음 시작' 요청
    func checkStartRequest() {
        guard nav.startRecordingRequest > nav.handledRecordingRequest else { return }
        nav.handledRecordingRequest = nav.startRecordingRequest
        if !rec.isRecording { auto.stop(); Task { await rec.start(hints: data.rosterNames) } }
    }

    // MARK: 말하면 담기 (앱이 켜져 있는 동안만)
    func setupAuto() {
        auto.onClip = { url, d, at in
            store.addAudio(tempFile: url, duration: d, at: at, markers: [],
                           classUid: markClass.isEmpty ? nil : markClass, period: nil)
        }
    }

    func resumeAuto() {
        guard auto.enabled, !rec.isRecording, scenePhase == .active else { return }
        Task { await auto.start() }
    }

    var autoCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Toggle(isOn: Binding(get: { auto.enabled }, set: { on in
                auto.enabled = on
                if on { if !autoNoticeSeen { autoNotice = true }; resumeAuto() } else { auto.stop() }
            })) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("말하면 담기").font(Theme.font(15, .bold))
                    Text("앱을 켜 둔 동안 말하면 저절로 녹음하고, 말을 멈추면 끝내요").font(Theme.font(12)).foregroundStyle(Theme.soft)
                }
            }
            .tint(Theme.blue)
            if auto.enabled {
                HStack(spacing: 8) {
                    Circle().fill(auto.capturing ? Theme.coral : (auto.listening ? Theme.mint : Color.gray.opacity(0.4)))
                        .frame(width: 8, height: 8)
                    Text(autoStatus).font(Theme.font(13, .semibold)).foregroundStyle(auto.capturing ? Theme.coral : Theme.ink)
                        .monospacedDigit().contentTransition(.numericText())
                    Spacer()
                    Button { withAnimation { autoMore.toggle() } } label: {
                        Label("자세히", systemImage: autoMore ? "chevron.up" : "chevron.down").font(Theme.font(12, .semibold))
                    }
                }
                AutoMeter(level: CGFloat(auto.level), threshold: CGFloat(auto.thresholdLevel), active: auto.capturing)
                    .frame(height: 8)
                    .accessibilityHidden(true)
                if autoMore {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("감도 — 시끄러운 곳일수록 크게 말해야 시작해요").font(Theme.font(12, .semibold)).foregroundStyle(Theme.soft)
                        Picker("감도", selection: $auto.sensitivity) {
                            ForEach(AutoGate.Sensitivity.allCases, id: \.self) { Text($0.label).tag($0) }
                        }.pickerStyle(.segmented)
                        Text("말 끝나고 멈추기 — 이만큼 조용하면 녹음을 끝내요").font(Theme.font(12, .semibold)).foregroundStyle(Theme.soft)
                        Picker("말 끝나고 멈추기", selection: $auto.stopDelay) {
                            Text("1.5초").tag(1.5); Text("2.5초").tag(2.5); Text("4초").tag(4.0)
                        }.pickerStyle(.segmented)
                        Text("막대의 선을 넘는 소리가 0.25초 이어지면 시작해요. 1초보다 짧은 소리(기침 · 문소리)는 버리고, 말 시작 직전 1초도 같이 담아요. 화면이 꺼지거나 다른 탭으로 가면 쉬어요.")
                            .font(Theme.font(11)).foregroundStyle(Theme.soft)
                    }
                    .transition(.opacity)
                }
            }
        }
        .padding(12)
        .background(Theme.bg.opacity(0.6), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .alert("마이크 권한이 필요해요", isPresented: $auto.permissionDenied) {
            Button("설정 열기") { UIApplication.shared.open(URL(string: UIApplication.openSettingsURLString)!) }
            Button("닫기", role: .cancel) {}
        } message: { Text("설정 → 쓰담 → 마이크를 켜 주세요.") }
    }

    var autoStatus: String {
        if auto.justSaved { return "방금 담았어요 ✓" }
        if auto.capturing { return "담는 중 " + timeString(auto.captureElapsed) }
        return auto.listening ? "듣는 중 · 말하면 바로 담아요" : "잠깐 쉬는 중"
    }

    func toggle() {
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        if rec.isRecording {
            if let r = rec.stop() {
                if r.1 < 1 { try? FileManager.default.removeItem(at: r.0) }
                else {
                    store.addAudio(tempFile: r.0, duration: r.1, at: r.2, markers: r.3,
                                   classUid: rec.pickedClass, period: rec.period)
                    UINotificationFeedbackGenerator().notificationOccurred(.success)
                }
            }
            resumeAuto()
        } else {
            memoFocused = false
            auto.stop()
            Task { await rec.start(hints: data.rosterNames) }
        }
    }

    // MARK: 한 줄 메모
    var memoCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("한 줄로 남기기", systemImage: "pencil.line").font(Theme.font(17, .bold))
                Spacer()
                KindPicker(kind: $memoKind)
            }
            TextField("예) 2학년 3반 이서연, 발표 자료를 꼼꼼하게 준비해 옴 🌱", text: $memoText, axis: .vertical)
                .font(Theme.font(16))
                .lineLimit(2...5)
                .focused($memoFocused)
                .padding(12)
                .background(Theme.bg, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            HStack {
                Text("키보드의 🎤로 말해도 돼요").font(Theme.font(12)).foregroundStyle(Theme.soft)
                Spacer()
                Button {
                    if store.addText(memoText, kind: memoKind) != nil {
                        memoText = ""; memoFocused = false
                        UINotificationFeedbackGenerator().notificationOccurred(.success)
                    }
                } label: {
                    Label("담기", systemImage: "arrow.down.circle.fill").font(Theme.font(15, .bold))
                        .padding(.horizontal, 16).padding(.vertical, 9)
                        .background(memoText.trimmingCharacters(in: .whitespaces).isEmpty ? Color.gray.opacity(0.25) : Theme.blue, in: Capsule())
                        .foregroundStyle(.white)
                }
                .buttonStyle(Squishy())
                .disabled(memoText.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .card()
    }

    // MARK: 흐름 안내
    var howCard: some View {
        HStack(spacing: 0) {
            step("mic.fill", "말하기", Theme.blue)
            arrow
            step("icloud.and.arrow.up.fill", "자동 전송", Theme.lavender)
            arrow
            step("person.2.fill", "학생별 정리", Theme.mint)
            arrow
            step("doc.text.fill", "초안", Theme.coral)
        }
        .frame(maxWidth: .infinity)
        .card(padding: 14)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("말하면 컴퓨터로 자동 전송되어 학생별로 정리되고 학기말 초안이 만들어집니다")
    }

    func step(_ icon: String, _ text: String, _ color: Color) -> some View {
        VStack(spacing: 6) {
            Image(systemName: icon).font(.system(size: 18, weight: .semibold)).foregroundStyle(color)
                .frame(width: 40, height: 40).background(color.opacity(0.14), in: Circle())
            Text(text).font(Theme.font(11, .semibold)).foregroundStyle(Theme.soft).lineLimit(1).minimumScaleFactor(0.8)
        }.frame(maxWidth: .infinity)
    }

    var arrow: some View {
        Image(systemName: "chevron.right").font(.system(size: 10, weight: .bold)).foregroundStyle(.tertiary)
    }
}

/// 수업 / 상담 선택 알약
/// 지금은 혼자 녹음하는 수업 기록 위주 — 상담 유형은 나중에 켠다
enum Features {
    static let counseling = false
}

struct KindPicker: View {
    @Binding var kind: String
    var body: some View {
        if Features.counseling { picker }
    }
    var picker: some View {
        HStack(spacing: 4) {
            ForEach(["수업", "상담"], id: \.self) { k in
                Button { withAnimation(.spring(response: 0.3, dampingFraction: 0.8)) { kind = k } } label: {
                    Text(k).font(Theme.font(13, .semibold))
                        .padding(.horizontal, 12).padding(.vertical, 6)
                        .foregroundStyle(kind == k ? .white : Theme.soft)
                        .background(kind == k ? (k == "상담" ? Theme.lavender : Theme.blue) : Color.clear, in: Capsule())
                }
            }
        }
        .padding(3)
        .background(Color.gray.opacity(0.12), in: Capsule())
    }
}

/// 방금 저장한 기록 — 유형·메모를 바로 고칠 수 있는 카드
struct SavedCard: View {
    @EnvironmentObject var store: Store
    var entry: Entry
    var onClose: () -> Void
    @State private var memo = ""
    @State private var kind = "수업"
    @State private var remaining = Int(Store.grace)
    let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Image(systemName: "checkmark.circle.fill").foregroundStyle(Theme.mint).font(.title3)
                Text(entry.isAudio ? "녹음을 담았어요 · \(timeString(entry.duration))" : "메모를 담았어요")
                    .font(Theme.font(16, .bold))
                Spacer()
                Button(action: onClose) { Image(systemName: "xmark.circle.fill").foregroundStyle(.tertiary).font(.title3) }
            }
            HStack(spacing: 8) {
                KindPicker(kind: $kind)
                    .onChange(of: kind) { k in store.edit(entry, kind: k) }
                if entry.isAudio {
                    TextField("메모 (예: 2-3 국어)", text: $memo)
                        .font(Theme.font(14)).padding(.horizontal, 10).padding(.vertical, 7)
                        .background(Theme.bg, in: Capsule())
                        .onSubmit { store.edit(entry, memo: memo) }
                }
            }
            if entry.isAudio { TranscriptPreview(entry: entry) }
            if let names = current.splitNames {
                VStack(alignment: .leading, spacing: 6) {
                    if !names.isEmpty {
                        FlowChips(names: names)
                    }
                    if current.splitUnsure > 0 || !current.splitLeftover.isEmpty || names.isEmpty {
                        NavigationLink { EntryDetail(entry: current, player: Player()) } label: {
                            Label(names.isEmpty ? "누구 이야기인지 골라 주세요" :
                                    current.splitUnsure > 0 ? "이름이 같은 학생이 있어요 · 눌러서 확인" : "이름이 안 나온 부분이 있어요 · 눌러서 정리",
                                  systemImage: "hand.point.up.left.fill")
                                .font(Theme.font(13, .bold)).foregroundStyle(Theme.butter)
                        }
                    }
                }
                .transition(.scale(scale: 0.95).combined(with: .opacity))
            }
            Label(status, systemImage: statusIcon)
                .font(Theme.font(12)).foregroundStyle(current.received ? Theme.mint : Theme.soft)
        }
        .card()
        .animation(.easeInOut, value: current)
        .onAppear { memo = entry.memo; kind = entry.kind; remaining = max(0, Int(entry.editableUntil.timeIntervalSinceNow.rounded())) }
        .onReceive(timer) { _ in
            remaining = max(0, Int(entry.editableUntil.timeIntervalSinceNow.rounded()))
            if remaining == 0 && memo != entry.memo && entry.isAudio { store.edit(entry, memo: memo) }
        }
        .onDisappear { if entry.isAudio && memo != entry.memo { store.edit(entry, memo: memo) } }
    }
}

extension SavedCard {
    var current: Entry { store.items.first(where: { $0.id == entry.id }) ?? entry }

    var status: String {
        let e = current
        if remaining > 0 { return "\(remaining)초 뒤에 보내요 · 그 전에 유형·메모를 고칠 수 있어요" }
        if e.stt == .working { return "글자로 바꾸고 나서 보낼게요" }
        if e.received { return "컴퓨터의 쓰담이 받았어요" }
        if e.relay == .done { return "컴퓨터로 보냈어요 · 컴퓨터 쓰담이 켜지면 가져가요" }
        if e.relay == .sending { return "컴퓨터로 보내는 중이에요 · 앱을 닫아도 계속 보내요" }
        if e.google == .done { return "구글 드라이브로 보냈어요 · 컴퓨터 쓰담이 켜지면 가져가요" }
        if e.icloud == .done { return "iCloud에 올렸어요 · 맥에서 쓰담을 켜면 가져가요" }
        if [e.icloud, e.google, e.relay].contains(.failed) { return "보내지 못했어요 · 기록함에서 다시 시도해요" }
        if !store.autoSend { return "휴대폰에 보관했어요 · ‘연결’에서 컴퓨터와 연결하면 보내져요" }
        return "보내는 중이에요"
    }

    var statusIcon: String {
        let e = current
        if e.received { return "checkmark.circle.fill" }
        if e.icloud == .done || e.google == .done || e.relay == .done { return "icloud.and.arrow.up" }
        if remaining > 0 || e.stt == .working { return "clock" }
        return "iphone"
    }
}

/// 녹음 중 실시간 글자 (마지막 몇 줄만)
struct LiveCaption: View {
    var text: String
    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                Text(text).font(Theme.font(15)).foregroundStyle(Theme.ink)
                    .frame(maxWidth: .infinity, alignment: .leading).id("end")
            }
            .frame(maxHeight: 76)
            .onChange(of: text) { _ in proxy.scrollTo("end", anchor: .bottom) }
        }
        .padding(12)
        .background(Theme.bg, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(alignment: .topTrailing) {
            Text("실시간").font(Theme.font(10, .bold)).padding(.horizontal, 6).padding(.vertical, 2)
                .background(Theme.coral.opacity(0.15), in: Capsule()).foregroundStyle(Theme.coral).padding(6)
        }
        .animation(.easeOut(duration: 0.2), value: text)
    }
}

/// "담은 학생" 칩 줄 — 하나씩 톡톡 나타남
struct FlowChips: View {
    var names: [String]
    @State private var shown = 0
    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                Image(systemName: "person.2.fill").font(.system(size: 12, weight: .bold)).foregroundStyle(Theme.lavender)
                ForEach(Array(names.enumerated()), id: \.offset) { i, n in
                    if i < shown {
                        Text(n).font(Theme.font(13, .bold)).foregroundStyle(Theme.lavender)
                            .padding(.horizontal, 10).padding(.vertical, 4)
                            .background(Theme.lavender.opacity(0.14), in: Capsule())
                            .transition(.scale(scale: 0.6).combined(with: .opacity))
                    }
                }
                Text("에게 담았어요").font(Theme.font(12)).foregroundStyle(Theme.soft).opacity(shown >= names.count ? 1 : 0)
            }
        }
        .onAppear {
            for i in 0..<names.count {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.12 * Double(i + 1)) {
                    withAnimation(.spring(response: 0.35, dampingFraction: 0.6)) { shown = i + 1 }
                }
            }
        }
    }
}

/// 받아쓴 글 미리 보기 (진행 중이면 표시)
struct TranscriptPreview: View {
    @EnvironmentObject var store: Store
    var entry: Entry
    var e: Entry { store.items.first(where: { $0.id == entry.id }) ?? entry }
    @State private var text = ""
    @FocusState private var focused: Bool

    var body: some View {
        switch e.stt {
        case .working:
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text("아이폰에서 글자로 바꾸는 중…").font(Theme.font(13)).foregroundStyle(Theme.soft)
            }
        case .done where !e.transcript.isEmpty:
            // 잘못 들린 이름은 바로 눌러서 고침 — 다 고치면 학생별로 다시 나눔
            VStack(alignment: .leading, spacing: 4) {
                TextField("받아쓴 글", text: $text, axis: .vertical).font(Theme.font(14)).lineLimit(2...8)
                    .focused($focused)
                    .padding(12)
                    .background(Theme.bg, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                Text(focused ? "다 고치면 키보드를 내려 주세요 · 학생별로 다시 나눠요" : "잘못 들린 이름은 눌러서 고칠 수 있어요")
                    .font(Theme.font(11)).foregroundStyle(Theme.soft)
                ResplitAsk(entry: e)
            }
            .onAppear { text = e.transcript }
            .onChange(of: e.transcript) { t in if !focused { text = t } }
            .onChange(of: focused) { f in if !f && !text.isEmpty && text != e.transcript { store.edit(e, transcript: text) } }
            .onDisappear { if text != e.transcript && !text.isEmpty { store.edit(e, transcript: text) } }
        case .done:
            Text("말소리를 찾지 못했어요").font(Theme.font(12)).foregroundStyle(Theme.soft)
        case .unavailable, .failed:
            Text(e.sttNote.isEmpty ? "컴퓨터에서 글자로 바꿔요" : e.sttNote).font(Theme.font(12)).foregroundStyle(Theme.soft)
        case .none:
            EmptyView()
        }
    }
}

/// 받아쓴 글을 고쳤는데, 나눈 뒤 손본 학생 기록이 있을 때: 다시 나눌지 묻기
struct ResplitAsk: View {
    @EnvironmentObject var store: Store
    var entry: Entry
    var body: some View {
        if entry.resplitPending {
            VStack(alignment: .leading, spacing: 8) {
                Text("고친 글로 학생별로 다시 나눌까요? 나눈 뒤 옮기거나 고친 기록은 새로 나눈 것으로 바뀌어요.")
                    .font(Theme.font(12)).foregroundStyle(Theme.ink)
                HStack(spacing: 8) {
                    Button("다시 나누기") { store.resplitAudio(entry.id) }.font(Theme.font(13, .bold))
                        .padding(.horizontal, 12).padding(.vertical, 6).background(Theme.blue, in: Capsule()).foregroundStyle(.white)
                    Button("그대로 두기") { store.change(entry.id) { $0.resplitPending = false } }.font(Theme.font(13, .semibold))
                        .padding(.horizontal, 12).padding(.vertical, 6).background(Theme.bg, in: Capsule())
                }
            }
            .padding(10)
            .background(Theme.butter.opacity(0.15), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
    }
}

/// 녹음 중 퍼지는 동그라미
struct PulseRings: View {
    var color: Color
    var level: CGFloat
    @State private var animate = false
    var body: some View {
        ZStack {
            ForEach(0..<3) { i in
                Circle().stroke(color.opacity(0.35), lineWidth: 3)
                    .frame(width: 150, height: 150)
                    .scaleEffect(animate ? 1.35 + level * 0.25 : 1)
                    .opacity(animate ? 0 : 0.9)
                    .animation(.easeOut(duration: 1.6).repeatForever(autoreverses: false).delay(Double(i) * 0.5), value: animate)
            }
            Circle().fill(color.opacity(0.15)).frame(width: 150 + level * 46, height: 150 + level * 46)
                .animation(.linear(duration: 0.1), value: level)
        }
        .onAppear { animate = true }
    }
}

/// 자동 녹음 소리 막대: 지금 소리 크기와 '이 선을 넘으면 시작' 선
struct AutoMeter: View {
    var level: CGFloat
    var threshold: CGFloat
    var active: Bool
    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.gray.opacity(0.15))
                Capsule().fill(active ? Theme.coral : (level >= threshold ? Theme.blue : Theme.mint))
                    .frame(width: max(4, g.size.width * level))
                    .animation(.linear(duration: 0.1), value: level)
                Rectangle().fill(Theme.ink.opacity(0.55)).frame(width: 2)
                    .offset(x: g.size.width * threshold - 1)
            }
        }
    }
}
