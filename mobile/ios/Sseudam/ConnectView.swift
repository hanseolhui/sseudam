import AVFoundation
import SwiftUI

/// 연결: "내 컴퓨터는?"을 고르면 그에 맞는 방법만 보여 준다.
struct ConnectView: View {
    @EnvironmentObject var store: Store
    @State private var scanning = false
    @State private var showManual = false
    @State private var manual = ""
    @State private var testResult = ""

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    qrCard
                    offlineHelpCard
                    computerPicker
                    if store.autoSend && !store.computerSeen && !Relay.paired { waitingCard }
                    if store.computer == "mac" { macCards } else { windowsCards }
                    PlusCard()
                    sttCard
                    aiCard
                    lockCard
                    keepCard
                    linksCard
                }
                .padding(18).frame(maxWidth: 640).frame(maxWidth: .infinity)
            }
            .softBackground()
            .navigationTitle("연결")
            .sheet(isPresented: $scanning) {
                QRScanner { code in scanning = false; handle(code) }.ignoresSafeArea()
            }
            .alert("연결 코드", isPresented: $showManual) {
                TextField("sseudam://pair?…", text: $manual)
                Button("연결") { handle(manual); manual = "" }
                Button("취소", role: .cancel) {}
            } message: { Text("컴퓨터 쓰담의 QR 아래 ‘코드 복사’로 받은 내용을 붙여넣으세요.") }
        }
    }

    var offlineHelpCard: some View {
        DisclosureGroup {
            VStack(alignment: .leading, spacing: 14) {
                offlineHelpItem("연결 없이도 남길 수 있어요", "녹음과 한 줄 메모를 기기에 저장하고, 이미 저장된 학생 기록과 초안을 보고 고칠 수 있어요. 기본 녹음·기록에는 쓰담 계정 로그인이 필요하지 않아요.")
                offlineHelpItem("받아쓰기는 기기 준비 상태에 따라 달라요", "한국어 기기 내 받아쓰기를 지원하고 필요한 모델이 준비된 아이폰·아이패드에서는 오프라인으로 글자로 바꿔요. 모델을 처음 내려받을 때는 인터넷이 필요할 수 있어요. 지원하지 않거나 준비되지 않았다면 음성을 보관한 뒤 연결된 컴퓨터에서 처리하세요.")
                offlineHelpItem("기기 안 AI는 지원 기기에서", "이름이 없는 문장을 학생별로 나누는 보정은 iOS·iPadOS 26 이상, Apple Intelligence 지원 기기에서 해당 기능과 모델이 준비돼야 해요. 사용할 수 없을 때도 이름 기준으로 나눌 수 있어요.")
                offlineHelpItem("인터넷이 필요한 작업", "QR 중계 연결, iCloud·구글 드라이브 전송과 다른 기기 기록 맞추기, 계정 로그인, 구독 결제·구매 복원, 업데이트에는 인터넷이 필요해요. QR 연결도 인터넷을 거쳐요. 컴퓨터가 기록을 받으려면 그 컴퓨터의 쓰담이 켜져 있고 연결되어 있어야 해요.")
                offlineHelpItem("플러스 이용권과 기록 연결은 별개예요", "현재 쓰담 플러스 AI 정리·초안은 컴퓨터 쓰담에서 온라인으로 사용해요. 같은 쓰담 계정으로 로그인하면 이용권이 연결되지만, 기록은 QR이나 iCloud 연결을 통해 따로 맞춰요. 기기에서 쓰담의 iCloud 사용이 허용되면 같은 Apple 계정의 학생 기록을 맞출 수 있으며, 녹음 iCloud 전송 스위치와는 별개예요. 휴대폰의 ‘요청문 복사’는 기기에서 만들고, ChatGPT·Gemini에 보내 답을 받는 과정에는 인터넷이 필요해요.")
                offlineHelpItem("기기에 저장됨과 백업 완료는 달라요", "연결이 없을 때 남긴 기록은 기기에 보관돼요. 다시 연결한 뒤 전송 상태와 ‘컴퓨터가 받음’을 확인해 주세요. 클라우드 폴더에 저장됐다는 표시만으로 원격 업로드까지 끝난 것은 아니며, 해당 클라우드의 동기화 상태도 확인해야 해요. 앱을 지우기 전에는 사본을 따로 보관하세요.")
                Link(destination: URL(string: "https://apps.seoriarts.com/sseudam-guide#offline-online")!) {
                    Label("기기별·인터넷 연결 상세 안내 (온라인)", systemImage: "arrow.up.right.square")
                        .font(Theme.font(13, .semibold))
                }
            }
            .padding(.top, 10)
        } label: {
            Label("인터넷 없이 쓸 때", systemImage: "wifi.slash").font(Theme.font(16, .bold))
        }
        .tint(Theme.blue)
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    func offlineHelpItem(_ title: String, _ text: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title).font(Theme.font(14, .semibold)).foregroundStyle(Theme.ink)
            Text(text).font(Theme.font(13)).foregroundStyle(Theme.soft)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    /// QR 한 번으로 컴퓨터(맥·윈도우)와 연결 — 녹음·학생 기록이 암호화돼서 오감
    var qrCard: some View {
        methodCard(icon: "qrcode.viewfinder", color: Theme.blue, title: "컴퓨터와 QR로 연결", badge: "추천 · 맥·윈도우 모두",
                   text: "컴퓨터 쓰담 → 설정 → 📱 휴대폰에 나오는 QR을 찍으면 끝이에요. 녹음·한 줄 메모·학생 기록이 저절로 오가요. 이 아이폰과 그 컴퓨터만 아는 열쇠로 암호화돼서, 중간 서버는 내용을 볼 수 없어요.") {
            if Relay.paired {
                HStack {
                    Pill(text: Relay.pcName.isEmpty ? "연결됨 🔒" : "\(Relay.pcName) 연결됨 🔒", icon: "checkmark", color: Theme.mint)
                    Spacer()
                    Button("지금 맞추기") { Task { await store.syncAll(force: true); await DataStore.shared.syncNow(); testResult = "✓ 컴퓨터와 맞췄어요" } }
                        .font(Theme.font(14, .semibold))
                    Button("끊기", role: .destructive) { store.unpairRelay(); testResult = "" }.font(Theme.font(14, .semibold))
                }
            } else {
                Button { scanning = true } label: {
                    Label("QR 찍어서 연결", systemImage: "qrcode.viewfinder").font(Theme.font(16, .bold))
                        .frame(maxWidth: .infinity).padding(.vertical, 12)
                        .background(Theme.brand, in: Capsule()).foregroundStyle(.white)
                }.buttonStyle(Squishy())
                Button("QR이 안 찍히면 코드 붙여넣기") { showManual = true }.font(Theme.font(13))
            }
            Text("🎙 음성 메모 앱으로 녹음했다면: 음성 메모에서 녹음 → 공유(⋯) → ‘쓰담’을 고르면 쓰담에 담기고 컴퓨터로 가요.")
                .font(Theme.font(12)).foregroundStyle(Theme.ink).fixedSize(horizontal: false, vertical: true)
            if !testResult.isEmpty && Relay.paired {
                Text(testResult).font(Theme.font(13)).foregroundStyle(testResult.hasPrefix("✓") ? Theme.mint : Theme.coral)
            }
        }
    }

    var computerPicker: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("기록을 정리할 컴퓨터는?").font(Theme.font(17, .bold))
            HStack(spacing: 10) {
                choice("mac", "맥", "laptopcomputer")
                choice("windows", "윈도우", "desktopcomputer")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    /// 아직 컴퓨터가 한 번도 받아 가지 않았을 때
    var waitingCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("컴퓨터의 쓰담을 기다리고 있어요", systemImage: "hourglass").font(Theme.font(16, .bold))
                .foregroundStyle(Theme.ink)
            Text("기록은 \(store.useICloud && store.icloudAvailable ? "iCloud" : "휴대폰")에 안전하게 쌓여 있어요. \(store.computer == "mac" ? "맥" : "컴퓨터")에 쓰담을 설치하고 켜면 쌓인 기록을 한꺼번에 가져가고, 기록함에 ‘컴퓨터가 받음’이 표시돼요.")
                .font(Theme.font(14)).foregroundStyle(Theme.soft).fixedSize(horizontal: false, vertical: true)
            Link(destination: URL(string: "https://apps.seoriarts.com/sseudam")!) {
                Label("컴퓨터용 쓰담 받기", systemImage: "arrow.down.circle.fill").font(Theme.font(15, .bold))
                    .frame(maxWidth: .infinity).padding(.vertical, 11)
                    .background(Theme.butter, in: Capsule()).foregroundStyle(.white)
            }.buttonStyle(Squishy())
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    /// 기기 안 AI
    var aiCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Toggle(isOn: Binding(get: { DataStore.shared.useLocalAI }, set: { DataStore.shared.useLocalAI = $0; store.objectWillChange.send() })) {
                Label("기기 안 AI로 더 똑똑하게 나누기", systemImage: "sparkles").font(Theme.font(16, .bold))
            }
            .tint(Theme.mint).disabled(!LocalAI.isReady)
            Text("“그 친구는…”처럼 이름 없이 말한 문장도 누구 이야기인지 짐작해 담아요. 아이폰 안에서만 처리하고 밖으로 보내지 않아요. 짐작한 조각엔 ✨ 표시가 붙어요.")
                .font(Theme.font(12)).foregroundStyle(Theme.soft).fixedSize(horizontal: false, vertical: true)
            Text(LocalAI.stateText).font(Theme.font(12, .semibold))
                .foregroundStyle(LocalAI.isReady ? Theme.mint : Theme.soft)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    /// 앱 잠금
    var lockCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Toggle(isOn: Binding(get: { AppLock.shared.enabled }, set: { v in Task { await AppLock.shared.setEnabled(v); store.objectWillChange.send() } })) {
                Label("\(AppLock.shared.biometryName)로 잠그기", systemImage: "lock.fill").font(Theme.font(16, .bold))
            }.tint(Theme.mint)
            Text("휴대폰을 잠깐 빌려줘도 학생 기록은 안 보이게 지켜요. 앱을 나갔다 1분 넘게 지나면 다시 잠기고, 앱 전환 화면에서도 내용을 가려요.")
                .font(Theme.font(12)).foregroundStyle(Theme.soft).fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    /// 아이폰 안 받아쓰기 켜고 끄기
    var sttCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Toggle(isOn: Binding(get: { store.transcribeOnPhone }, set: { store.transcribeOnPhone = $0 })) {
                Label("아이폰에서 바로 받아쓰기", systemImage: "text.bubble.fill").font(Theme.font(16, .bold))
            }.tint(Theme.mint)
            Text(Transcriber.supported
                 ? "녹음이 끝나면 아이폰 안에서 글자로 바꿔 기록함에 함께 남겨요. 인터넷으로 나가지 않고, 받아쓴 글은 녹음과 함께 컴퓨터로 가요."
                 : "이 아이폰은 기기 안 받아쓰기를 지원하지 않아요. 컴퓨터의 쓰담이 글자로 바꿔요.")
                .font(Theme.font(12)).foregroundStyle(Theme.soft).fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    func choice(_ id: String, _ title: String, _ icon: String) -> some View {
        Button { withAnimation(.spring(response: 0.3)) { store.computer = id } } label: {
            VStack(spacing: 6) {
                Image(systemName: icon).font(.system(size: 26, weight: .semibold))
                Text(title).font(Theme.font(15, .bold))
            }
            .frame(maxWidth: .infinity).padding(.vertical, 14)
            .foregroundStyle(store.computer == id ? .white : Theme.ink)
            .background(store.computer == id ? AnyShapeStyle(Theme.brand) : AnyShapeStyle(Theme.bg),
                        in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }.buttonStyle(Squishy())
    }

    // MARK: 맥
    @ViewBuilder var macCards: some View {
        methodCard(icon: "icloud.fill", color: Theme.blue, title: "iCloud로도 보내기", badge: "같은 Apple ID면 덤으로",
                   text: "위 QR 연결과 함께 켜 둬도 괜찮아요. 아이폰과 맥이 같은 Apple ID면 담은 녹음이 iCloud로도 맥의 쓰담에 넘어가요.") {
            Toggle(isOn: Binding(get: { store.useICloud }, set: { store.useICloud = $0 })) {
                Text("iCloud로 보내기").font(Theme.font(15, .semibold))
            }.tint(Theme.mint)
            if !store.icloudAvailable {
                Label("이 아이폰이 iCloud에 로그인되어 있지 않아요 (설정 → 맨 위 이름)", systemImage: "exclamationmark.circle")
                    .font(Theme.font(12)).foregroundStyle(Theme.coral)
            }
        }
        methodCard(icon: "wave.3.right", color: Theme.lavender, title: "AirDrop으로 보내기", badge: "가까이 있을 때",
                   text: "기록함에서 왼쪽으로 밀기 → 보내기 → 내 맥 선택. 맥의 쓰담이 ‘다운로드’ 폴더에서 자동으로 가져가요.") { EmptyView() }
        if store.googlePaired || !Relay.paired { googleCard }
    }

    // MARK: 윈도우
    @ViewBuilder var windowsCards: some View {
        if store.googlePaired || !Relay.paired { googleCard }
        methodCard(icon: "icloud.fill", color: Theme.blue, title: "iCloud for Windows", badge: "선택",
                   text: "윈도우 PC에 'iCloud for Windows'가 설치되어 있다면 iCloud로도 보낼 수 있어요.") {
            Toggle(isOn: Binding(get: { store.useICloud }, set: { store.useICloud = $0 })) {
                Text("iCloud로도 보내기").font(Theme.font(15, .semibold))
            }.tint(Theme.mint)
        }
    }

    /// 다른 방법: 학교 인터넷이 QR 연결을 막을 때만 (QR로 이어졌으면 숨김)
    var googleCard: some View {
        methodCard(icon: "externaldrive.fill", color: Theme.mint, title: "구글 드라이브를 거쳐 보내기",
                   badge: "QR 연결이 안 될 때만",
                   text: "위 QR 연결이 학교 인터넷에서 막힐 때 쓰는 방법이에요. 컴퓨터 쓰담 → 설정 → 📱 휴대폰 → ‘다른 방법: 구글 드라이브’를 펼쳐 나오는 QR을 찍으면, 녹음이 선생님 구글 드라이브를 거쳐 컴퓨터로 가요.") {
            if store.googlePaired {
                HStack {
                    Pill(text: store.teacherName.isEmpty ? "연결됨" : "\(store.teacherName) 선생님 연결됨", icon: "checkmark", color: Theme.mint)
                    Spacer()
                    Button("확인") { Task { await test() } }.font(Theme.font(14, .semibold))
                    Button("끊기", role: .destructive) { store.unpair(); testResult = "" }.font(Theme.font(14, .semibold))
                }
            } else {
                Button { scanning = true } label: {
                    Label("QR 찍어서 연결", systemImage: "qrcode.viewfinder").font(Theme.font(16, .bold))
                        .frame(maxWidth: .infinity).padding(.vertical, 12)
                        .background(Theme.mint, in: Capsule()).foregroundStyle(.white)
                }.buttonStyle(Squishy())
                Button("QR이 안 찍히면 코드 붙여넣기") { showManual = true }.font(Theme.font(13))
            }
            if !testResult.isEmpty {
                Text(testResult).font(Theme.font(13)).foregroundStyle(testResult.hasPrefix("✓") ? Theme.mint : Theme.coral)
            }
        }
    }

    func methodCard<Content: View>(icon: String, color: Color, title: String, badge: String, text: String,
                                   @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                Image(systemName: icon).font(.system(size: 20, weight: .semibold)).foregroundStyle(color)
                    .frame(width: 44, height: 44).background(color.opacity(0.15), in: RoundedRectangle(cornerRadius: 14))
                VStack(alignment: .leading, spacing: 3) {
                    Text(title).font(Theme.font(17, .bold))
                    Text(badge).font(Theme.font(12, .semibold)).foregroundStyle(color)
                }
            }
            Text(text).font(Theme.font(14)).foregroundStyle(Theme.soft).fixedSize(horizontal: false, vertical: true)
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    var keepCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label("기록 보관", systemImage: "archivebox.fill").font(Theme.font(16, .bold))
                Spacer()
                Picker("휴대폰에 보관", selection: Binding(get: { store.deleteAfterDays }, set: { store.deleteAfterDays = $0 })) {
                    Text("계속 보관 (추천)").tag(0)
                    Text("보낸 뒤 180일 후 지우기").tag(180)
                    Text("보낸 뒤 90일 후 지우기").tag(90)
                }
                .pickerStyle(.menu).labelsHidden()
            }
            Text("학기말 생기부를 쓸 때까지 자동으로 지우지 않아요. 컴퓨터의 쓰담에도 원본이 그대로 보관돼요.")
                .font(Theme.font(12)).foregroundStyle(Theme.soft).fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    var linksCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Link(destination: URL(string: "https://apps.seoriarts.com/sseudam")!) {
                Label("컴퓨터용 쓰담 받기·사용법", systemImage: "desktopcomputer")
            }
            Link(destination: URL(string: "https://apps.seoriarts.com/sseudam-privacy")!) {
                Label("개인정보 처리방침", systemImage: "hand.raised.fill")
            }
            Button { store.onboarded = false } label: { Label("처음 안내 다시 보기", systemImage: "sparkles") }
            Text("쓰담 \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "")")
                .font(Theme.font(12)).foregroundStyle(.tertiary)
        }
        .font(Theme.font(15, .semibold))
        .labelStyle(AlignedLabel())
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    func handle(_ code: String) {
        if let p = Relay.parse(code) {   // 새 QR 연동 (암호화)
            store.pairRelay(p)
            testResult = "✓ 연결됐어요! 녹음과 학생 기록이 컴퓨터와 오가요"
            return
        }
        if let p = Sync.parsePairing(code) {
            store.pair(url: p.url, token: p.token, name: p.name)
            Task { await test() }
        } else {
            testResult = "쓰담 연결 QR이 아니에요."
        }
    }

    func test() async {
        testResult = "확인 중…"
        do { try await Sync.ping(url: store.googleURL, token: store.googleToken); testResult = "✓ 연결됐어요!" }
        catch { testResult = error.localizedDescription }
    }
}

/// 카메라로 QR 읽기
struct QRScanner: UIViewControllerRepresentable {
    var onCode: (String) -> Void
    func makeUIViewController(context: Context) -> ScannerVC { let v = ScannerVC(); v.onCode = onCode; return v }
    func updateUIViewController(_ vc: ScannerVC, context: Context) {}
}

final class ScannerVC: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    var onCode: ((String) -> Void)?
    private let session = AVCaptureSession()
    private var done = false

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        guard let dev = AVCaptureDevice.default(for: .video), let input = try? AVCaptureDeviceInput(device: dev),
              session.canAddInput(input) else {
            let l = UILabel(); l.text = "카메라를 쓸 수 없어요. ‘코드 붙여넣기’를 이용해 주세요."
            l.textColor = .white; l.numberOfLines = 0; l.textAlignment = .center
            l.frame = view.bounds.insetBy(dx: 24, dy: 0); view.addSubview(l); return
        }
        session.addInput(input)
        let out = AVCaptureMetadataOutput()
        if session.canAddOutput(out) {
            session.addOutput(out)
            out.setMetadataObjectsDelegate(self, queue: .main)
            out.metadataObjectTypes = [.qr]
        }
        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.frame = view.bounds; layer.videoGravity = .resizeAspectFill
        view.layer.addSublayer(layer)
        let hint = UILabel(); hint.text = "컴퓨터 화면의 QR을 비춰 주세요"
        hint.textColor = .white; hint.textAlignment = .center; hint.font = .systemFont(ofSize: 17, weight: .bold)
        hint.frame = CGRect(x: 0, y: view.bounds.height - 140, width: view.bounds.width, height: 40)
        view.addSubview(hint)
        DispatchQueue.global(qos: .userInitiated).async { self.session.startRunning() }
    }

    override func viewWillDisappear(_ animated: Bool) { super.viewWillDisappear(animated); session.stopRunning() }

    func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput objs: [AVMetadataObject], from connection: AVCaptureConnection) {
        guard !done, let s = (objs.first as? AVMetadataMachineReadableCodeObject)?.stringValue,
              s.hasPrefix("sseudam://") || s.hasPrefix("seteuk://") else { return }
        done = true
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        onCode?(s)
    }
}

/// 아이콘 폭을 맞춰 글자가 한 줄로 가지런히 서게 하는 라벨
struct AlignedLabel: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 12) {
            configuration.icon.frame(width: 26)
            configuration.title
        }
    }
}
