import BackgroundTasks
import Foundation
import UIKit

/// 앱이 화면 밖에 있거나 잠겨 있어도 녹음을 컴퓨터로 보낸다.
/// - 녹음 올리기는 iOS 백그라운드 전송(URLSession background): 앱이 멈춰도 iOS가 끝까지 올리고, 끝나면 앱을 잠깐 깨워 결과를 적는다.
/// - 못 보낸 것 다시 보내기 · '컴퓨터가 받음' 확인 · 학생 기록 맞추기는 백그라운드 새로 고침(BGAppRefreshTask)으로 틈틈이.
final class BackgroundSend: NSObject, URLSessionTaskDelegate {
    static let shared = BackgroundSend()
    static let sessionId = "kr.sseudam.app.upload"
    static let refreshId = "kr.sseudam.app.refresh"

    /// iOS가 전송을 마치고 앱을 깨웠을 때 받은 '다 처리했음' 콜백 (AppDelegate가 넘겨줌)
    var eventsDone: (() -> Void)?

    private(set) lazy var session: URLSession = {
        let c = URLSessionConfiguration.background(withIdentifier: Self.sessionId)
        c.sessionSendsLaunchEvents = true
        c.isDiscretionary = false                       // 와이파이·충전 기다리지 않고 바로
        c.timeoutIntervalForResource = 7 * 24 * 3600    // 인터넷이 없으면 일주일까지 기다렸다 보냄
        return URLSession(configuration: c, delegate: self, delegateQueue: nil)
    }()

    /// 암호화한 녹음을 보낼 때까지 두는 곳 (백그라운드 전송은 파일에서만 올릴 수 있음)
    static var outbox: URL {
        let d = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0].appendingPathComponent("relay-out", isDirectory: true)
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        return d
    }

    func enqueue(_ request: URLRequest, body: Data, entry id: UUID) throws {
        let f = Self.outbox.appendingPathComponent(id.uuidString + ".bin")
        try body.write(to: f, options: .atomic)
        let t = session.uploadTask(with: request, fromFile: f)
        t.taskDescription = id.uuidString
        t.resume()
    }

    /// 지금 iOS가 올리고 있는 기록들
    func inFlight() async -> Set<UUID> {
        Set(await session.allTasks.compactMap { $0.taskDescription.flatMap(UUID.init(uuidString:)) })
    }

    // MARK: URLSessionTaskDelegate
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let s = task.taskDescription, let id = UUID(uuidString: s) else { return }
        try? FileManager.default.removeItem(at: Self.outbox.appendingPathComponent(s + ".bin"))
        let code = (task.response as? HTTPURLResponse)?.statusCode ?? 0
        let ok = error == nil && (200..<300).contains(code)
        let message = ok ? "" : (error?.localizedDescription ?? "연결 서버 오류 (\(code))")
        Task { @MainActor in Store.shared.relayFinished(id, ok: ok, error: message) }
    }

    func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        DispatchQueue.main.async {
            self.eventsDone?()
            self.eventsDone = nil
        }
    }

    // MARK: 백그라운드 새로 고침
    static func registerRefresh() {
        BGTaskScheduler.shared.register(forTaskWithIdentifier: refreshId, using: nil) { task in
            guard let task = task as? BGAppRefreshTask else { return }
            scheduleRefresh()
            let work = Task { @MainActor in
                await Store.shared.syncAll()
                await DataStore.shared.syncNow()
                task.setTaskCompleted(success: !Task.isCancelled)
            }
            task.expirationHandler = { work.cancel() }
        }
    }

    /// 15분 뒤쯤 (실제 시각은 iOS가 사용 습관·배터리를 보고 정함)
    static func scheduleRefresh() {
        let r = BGAppRefreshTaskRequest(identifier: refreshId)
        r.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)
        try? BGTaskScheduler.shared.submit(r)
    }
}

/// 백그라운드 전송이 끝나 iOS가 앱을 깨울 때와 새로 고침 등록은 앱 델리게이트에서만 받을 수 있다
final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        BackgroundSend.registerRefresh()
        _ = BackgroundSend.shared.session   // 앱이 꺼진 사이 끝난 전송 결과를 받도록 다시 연결
        return true
    }

    func application(_ application: UIApplication, handleEventsForBackgroundURLSession identifier: String,
                     completionHandler: @escaping () -> Void) {
        guard identifier == BackgroundSend.sessionId else { completionHandler(); return }
        BackgroundSend.shared.eventsDone = completionHandler
        _ = BackgroundSend.shared.session
    }
}
