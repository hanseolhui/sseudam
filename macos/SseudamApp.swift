// 쓰담 macOS 앱 셸: 자체 창(WKWebView)으로 로컬 서버 화면을 띄우고, 서버 프로세스를 관리한다.
// 빌드: macos/build_app.sh (swiftc, 외부 의존성 없음)
import Cocoa
import WebKit
import ServiceManagement

let kPort = Int(ProcessInfo.processInfo.environment["SETEUK_PORT"] ?? "") ?? 8765
let kBase = URL(string: "http://127.0.0.1:\(kPort)/")!
let kBundleVersion = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"

func versionTuple(_ v: String) -> [Int] {
    let nums = v.split(whereSeparator: { !$0.isNumber }).compactMap { Int($0) }
    return Array((nums + [0, 0, 0]).prefix(3))
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKUIDelegate, WKNavigationDelegate, NSWindowDelegate, NSMenuItemValidation {
    var window: NSWindow!
    var webView: WKWebView!
    var server: Process?
    var quitting = false
    var restarts = 0

    // MARK: 시작
    func applicationDidFinishLaunching(_ note: Notification) {
        if MoveToApplications.offerIfNeeded() { return }
        buildMenu()
        buildWindow()
        showLoading("시작하는 중…")
        serverVersion { ver in
            guard let ver = ver else { self.startServer(); return }
            // 예전 버전 서버가 떠 있으면(앱을 새로 설치한 경우) 끄고 새로 시작
            if versionTuple(ver).lexicographicallyPrecedes(versionTuple(kBundleVersion)) {
                self.showLoading("새 버전으로 바꾸는 중…")
                self.shutdownExisting { self.startServer() }
            } else {
                self.loadApp()
            }
        }
    }

    func serverVersion(_ done: @escaping (String?) -> Void) {
        var req = URLRequest(url: kBase.appendingPathComponent("api/version"))
        req.timeoutInterval = 1
        URLSession.shared.dataTask(with: req) { data, resp, _ in
            var v: String? = nil
            if (resp as? HTTPURLResponse)?.statusCode == 200, let data = data,
               let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                v = obj["version"] as? String ?? "0"
            }
            DispatchQueue.main.async { done(v) }
        }.resume()
    }

    func shutdownExisting(_ then: @escaping () -> Void) {
        var req = URLRequest(url: kBase.appendingPathComponent("api/shutdown"))
        req.httpMethod = "POST"
        req.setValue("1", forHTTPHeaderField: "X-Seteuk")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = "{}".data(using: .utf8)
        URLSession.shared.dataTask(with: req) { _, _, _ in
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { then() }
        }.resume()
    }

    func buildWindow() {
        let config = WKWebViewConfiguration()
        config.preferences.javaScriptCanOpenWindowsAutomatically = true
        config.applicationNameForUserAgent = "SeteukApp/1"
        webView = WKWebView(frame: .zero, configuration: config)
        webView.uiDelegate = self
        webView.navigationDelegate = self
        webView.allowsMagnification = true
        webView.setValue(false, forKey: "drawsBackground")
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 840),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "쓰담"
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.minSize = NSSize(width: 900, height: 600)
        window.contentView = webView
        window.delegate = self
        window.center()
        window.setFrameAutosaveName("SeteukMainWindow")
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func showLoading(_ msg: String) {
        let html = """
        <html><body style="font:15px -apple-system;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;color:#6b7384;background:transparent">
        <div style="text-align:center"><div style="font-size:24px;font-weight:800;color:#2f6fde;margin-bottom:6px">쓰담</div><div style="font-size:12px;margin-bottom:14px">말로 담고, 글로 씁니다</div>\(msg)</div></body></html>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }

    func loadApp() {
        webView.load(URLRequest(url: kBase))
    }

    // MARK: 서버 프로세스
    func startServer() {
        guard let script = Bundle.main.path(forResource: "start_server", ofType: "sh") else {
            fatal("실행 파일이 손상되었습니다. 다시 설치해 주세요."); return
        }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/bash")
        p.arguments = [script]
        var env = ProcessInfo.processInfo.environment
        env["SETEUK_APP"] = "1"
        env["SETEUK_NO_BROWSER"] = "1"
        env["SETEUK_BIN"] = (Bundle.main.resourcePath ?? "") + "/bin"
        env["SETEUK_PORT"] = String(kPort)
        env["SETEUK_SHELL"] = "5"
        env["SETEUK_APP_PATH"] = Bundle.main.bundlePath
        p.environment = env
        p.terminationHandler = { [weak self] proc in
            DispatchQueue.main.async { self?.serverEnded(proc.terminationStatus) }
        }
        do { try p.run() } catch { fatal("서버를 시작하지 못했습니다: \(error.localizedDescription)"); return }
        server = p
        waitForServer(tries: 60)
    }

    func waitForServer(tries: Int) {
        ping { alive in
            if alive { self.restarts = 0; self.loadApp(); return }
            if tries <= 0 {
                self.fatal("서버가 응답하지 않습니다. 로그: ~/Library/Application Support/쓰담/server.log"); return
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.waitForServer(tries: tries - 1) }
        }
    }

    func serverEnded(_ status: Int32) {
        server = nil
        if quitting { return }
        if status == 3 {  // python 없음 → 명령어 라인 도구 설치 안내
            let a = NSAlert()
            a.messageText = "처음 한 번만 설치가 필요합니다"
            a.informativeText = "애플의 '명령어 라인 도구'가 필요합니다. [설치]를 누르면 설치 창이 뜹니다. 설치가 끝나면 쓰담을 다시 실행하세요."
            a.addButton(withTitle: "설치")
            a.addButton(withTitle: "종료")
            if a.runModal() == .alertFirstButtonReturn {
                let x = Process(); x.executableURL = URL(fileURLWithPath: "/usr/bin/xcode-select"); x.arguments = ["--install"]
                try? x.run()
            }
            NSApp.terminate(nil); return
        }
        if status == 0 {  // 사용자가 화면에서 '프로그램 종료'
            NSApp.terminate(nil); return
        }
        // 비정상 종료 → 다시 시작 (최대 3회)
        restarts += 1
        if restarts > 3 { fatal("서버가 반복해서 멈췄습니다. 로그를 확인해 주세요: ~/Library/Application Support/쓰담/server.log"); return }
        showLoading("다시 시작하는 중…")
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.startServer() }
    }

    func ping(_ done: @escaping (Bool) -> Void) {
        var req = URLRequest(url: kBase.appendingPathComponent("api/version"))
        req.timeoutInterval = 1
        URLSession.shared.dataTask(with: req) { _, resp, _ in
            let ok = (resp as? HTTPURLResponse)?.statusCode == 200
            DispatchQueue.main.async { done(ok) }
        }.resume()
    }

    func fatal(_ msg: String) {
        let a = NSAlert(); a.messageText = "쓰담"; a.informativeText = msg; a.runModal()
    }

    // MARK: 창 닫기 = 숨기기 (뒤에서 아이폰 기록 계속 받아옴)
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        window.orderOut(nil); return false
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window.makeKeyAndOrderFront(nil); return true
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        quitting = true
        if let p = server, p.isRunning {
            p.terminate()
            p.waitUntilExit()
        }
        return .terminateNow
    }

    // MARK: 웹뷰 — 자바스크립트 대화상자
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let a = NSAlert(); a.messageText = message; a.addButton(withTitle: "확인")
        a.beginSheetModal(for: window) { _ in completionHandler() }
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = NSAlert(); a.messageText = message
        a.addButton(withTitle: "확인"); a.addButton(withTitle: "취소")
        a.beginSheetModal(for: window) { r in completionHandler(r == .alertFirstButtonReturn) }
    }

    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        let a = NSAlert(); a.messageText = prompt
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 24)); field.stringValue = defaultText ?? ""
        a.accessoryView = field
        a.addButton(withTitle: "확인"); a.addButton(withTitle: "취소")
        a.beginSheetModal(for: window) { r in completionHandler(r == .alertFirstButtonReturn ? field.stringValue : nil) }
    }

    // 파일 선택 (<input type=file>)
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = false
        panel.beginSheetModal(for: window) { r in completionHandler(r == .OK ? panel.urls : nil) }
    }

    // 새 창 요청(target=_blank) → 기본 브라우저로
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = navigationAction.request.url { NSWorkspace.shared.open(url) }
        return nil
    }

    // 앱 밖 주소는 기본 브라우저로
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let url = navigationAction.request.url, let host = url.host,
           !(host == "127.0.0.1" || host == "localhost"), url.scheme == "http" || url.scheme == "https" {
            NSWorkspace.shared.open(url); decisionHandler(.cancel); return
        }
        if navigationAction.request.url?.isFileURL == true { decisionHandler(.cancel); return }  // 파일을 창에 떨어뜨렸을 때
        decisionHandler(.allow)
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { loadApp() }

    // MARK: 메뉴
    func buildMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem(); main.addItem(appItem)
        let app = NSMenu()
        app.addItem(withTitle: "쓰담에 관하여", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        app.addItem(.separator())
        let login = NSMenuItem(title: "로그인 시 자동 실행", action: #selector(toggleLogin(_:)), keyEquivalent: "")
        login.target = self; app.addItem(login)
        app.addItem(withTitle: "데이터 폴더 열기", action: #selector(openData), keyEquivalent: "").target = self
        app.addItem(.separator())
        app.addItem(withTitle: "쓰담 가리기", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        app.addItem(.separator())
        app.addItem(withTitle: "쓰담 종료", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = app

        let editItem = NSMenuItem(); main.addItem(editItem)
        let edit = NSMenu(title: "편집")
        edit.addItem(withTitle: "실행 취소", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "실행 복귀", action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "오려두기", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "복사하기", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "붙여넣기", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "전체 선택", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit

        let viewItem = NSMenuItem(); main.addItem(viewItem)
        let view = NSMenu(title: "보기")
        view.addItem(withTitle: "새로고침", action: #selector(reload), keyEquivalent: "r").target = self
        view.addItem(withTitle: "크게", action: #selector(zoomIn), keyEquivalent: "+").target = self
        view.addItem(withTitle: "작게", action: #selector(zoomOut), keyEquivalent: "-").target = self
        view.addItem(withTitle: "실제 크기", action: #selector(zoomReset), keyEquivalent: "0").target = self
        viewItem.submenu = view

        let winItem = NSMenuItem(); main.addItem(winItem)
        let win = NSMenu(title: "윈도우")
        win.addItem(withTitle: "최소화", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        win.addItem(withTitle: "닫기", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        winItem.submenu = win
        NSApp.windowsMenu = win
        NSApp.mainMenu = main
    }

    @objc func reload() { if webView.url?.host == nil { loadApp() } else { webView.reload() } }
    @objc func zoomIn() { webView.pageZoom = min(webView.pageZoom + 0.1, 2.0) }
    @objc func zoomOut() { webView.pageZoom = max(webView.pageZoom - 0.1, 0.6) }
    @objc func zoomReset() { webView.pageZoom = 1.0 }
    @objc func openData() {
        let p = NSHomeDirectory() + "/Library/Application Support/쓰담"
        NSWorkspace.shared.open(URL(fileURLWithPath: p))
    }

    @objc func toggleLogin(_ sender: NSMenuItem) {
        if #available(macOS 13.0, *) {
            do {
                if SMAppService.mainApp.status == .enabled { try SMAppService.mainApp.unregister() }
                else { try SMAppService.mainApp.register() }
            } catch { fatal("설정하지 못했습니다: \(error.localizedDescription)") }
        } else {
            fatal("시스템 환경설정 → 사용자 및 그룹 → 로그인 항목에서 쓰담을 추가하세요.")
        }
    }

    func validateMenuItem(_ item: NSMenuItem) -> Bool {
        if item.action == #selector(toggleLogin(_:)), #available(macOS 13.0, *) {
            item.state = SMAppService.mainApp.status == .enabled ? .on : .off
        }
        return true
    }
}

/// 다운로드 폴더나 DMG에서 바로 실행하면 macOS가 읽기 전용 임시 위치(App Translocation)에서 실행해서
/// 자동 업데이트·전체 디스크 접근 권한 추가가 꼬인다 → 처음에 응용 프로그램 폴더로 옮기기를 권함 (톡톡과 같은 방식)
enum MoveToApplications {
    private static let declinedKey = "moveToApplicationsDeclined"

    static var needsMove: Bool {
        let path = Bundle.main.bundlePath
        let downloads = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first?.path ?? "~/Downloads"
        return path.contains("/AppTranslocation/") || path.hasPrefix(downloads + "/") || path.hasPrefix("/Volumes/")
            || path.hasPrefix(NSHomeDirectory() + "/Desktop/")
    }

    /// 옮기기로 해서 곧 다시 실행되면 true (이번 실행은 여기서 끝)
    @discardableResult
    static func offerIfNeeded() -> Bool {
        guard needsMove, !UserDefaults.standard.bool(forKey: declinedKey) else { return false }
        NSApp.activate(ignoringOtherApps: true)
        let a = NSAlert()
        a.messageText = "쓰담을 응용 프로그램 폴더로 옮길까요?"
        a.informativeText = "지금 위치(다운로드·설치 디스크)에서 바로 실행하면 자동 업데이트와 권한 설정이 제대로 되지 않아요. 옮긴 뒤 바로 다시 켜지고, 학생 기록은 그대로예요."
        a.addButton(withTitle: "옮기기")
        a.addButton(withTitle: "그대로 쓰기")
        guard a.runModal() == .alertFirstButtonReturn else {
            UserDefaults.standard.set(true, forKey: declinedKey)
            return false
        }
        let apps = "/Applications"
        let dest = apps + "/쓰담.app"
        guard FileManager.default.isWritableFile(atPath: apps) else {
            let e = NSAlert()
            e.messageText = "응용 프로그램 폴더에 쓸 권한이 없어요"
            e.informativeText = "Finder에서 쓰담을 응용 프로그램 폴더로 직접 끌어다 놓아 주세요."
            e.runModal()
            NSWorkspace.shared.open(URL(fileURLWithPath: apps))
            return false
        }
        let src = Bundle.main.bundlePath
        // 다운로드 폴더에 원본이 보이면 옮긴 뒤 휴지통으로 (DMG·임시 위치는 그대로 둠)
        let original = (src.contains("/AppTranslocation/") || src.hasPrefix("/Volumes/")) ? "" : src
        let script = """
        while kill -0 \(ProcessInfo.processInfo.processIdentifier) 2>/dev/null; do sleep 0.2; done
        rm -rf "$2.new"
        if /usr/bin/ditto "$1" "$2.new"; then
          rm -rf "$2.old"; [ -d "$2" ] && mv "$2" "$2.old"
          if mv "$2.new" "$2"; then rm -rf "$2.old"; [ -n "$3" ] && mv "$3" ~/.Trash/ 2>/dev/null
          else [ -d "$2.old" ] && mv "$2.old" "$2"; fi
          [ -d /Applications/세특도우미.app ] && mv /Applications/세특도우미.app ~/.Trash/ 2>/dev/null
        fi
        /usr/bin/xattr -dr com.apple.quarantine "$2" 2>/dev/null
        /usr/bin/open "$2"
        """
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/sh")
        p.arguments = ["-c", script, "sseudam-move", src, dest, original]
        do { try p.run() } catch { return false }
        NSApp.terminate(nil)
        return true
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
