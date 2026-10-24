import CryptoKit
import Foundation
import UIKit

/// QR 연동 — 컴퓨터(맥·윈도우)의 쓰담이 보여 준 QR 하나로 이어진다. 윈도우 PC도, iCloud가 다른 맥도.
/// 녹음·학생 기록은 QR 안의 열쇠로 암호화해서 중계 서버를 거친다 (서버는 내용을 볼 수 없음).
/// 암호 방식은 컴퓨터 쓰담 app/relay.py · 안드로이드 Relay.kt 와 똑같다:
///   kEnc = HMAC(열쇠,"sseudam-enc"), kMac = HMAC(열쇠,"sseudam-mac"), 토큰 = hex(HMAC(열쇠,"sseudam-relay-auth"))
///   덩어리 = "SSD1" + nonce(16) + (평문 XOR HMAC(kEnc, nonce‖블록번호)) + HMAC(kMac, "SSD1"‖nonce‖암호문)
///   평문 = 메타 JSON 길이(4) + 메타 JSON + 본문
enum Relay {
    struct Pairing { let url: String; let channel: String; let key: Data; let name: String }
    private static let magic = Data("SSD1".utf8)
    private static let d = UserDefaults.standard

    // MARK: 연결 정보
    static func parse(_ text: String) -> Pairing? {
        guard let c = URLComponents(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              c.scheme == "sseudam", c.host == "pair" else { return nil }
        let q = Dictionary((c.queryItems ?? []).map { ($0.name, $0.value ?? "") }, uniquingKeysWith: { a, _ in a })
        guard q["v"] == "1", let u = q["u"], u.hasPrefix("https://"), let ch = q["c"],
              ch.range(of: "^[0-9a-f]{32}$", options: .regularExpression) != nil,
              let k = q["k"], let key = b64u(k), key.count == 32 else { return nil }
        return Pairing(url: u.hasSuffix("/") ? String(u.dropLast()) : u, channel: ch, key: key, name: q["n"] ?? "")
    }

    static func pair(_ p: Pairing) {
        d.set(p.url, forKey: "relayURL"); d.set(p.channel, forKey: "relayCh"); d.set(p.name, forKey: "relayPC")
        d.removeObject(forKey: "relayDocSig")
        Keychain.set("relayKey", p.key.base64EncodedString())
    }

    static func unpair() {
        ["relayURL", "relayCh", "relayPC", "relayDocSig"].forEach { d.removeObject(forKey: $0) }
        Keychain.delete("relayKey")
    }

    static var paired: Bool { !(d.string(forKey: "relayCh") ?? "").isEmpty && Keychain.get("relayKey") != nil }
    static var pcName: String { d.string(forKey: "relayPC") ?? "" }

    private static func creds() -> (url: String, ch: String, key: Data)? {
        guard let u = d.string(forKey: "relayURL"), let c = d.string(forKey: "relayCh"), !c.isEmpty,
              let k = Keychain.get("relayKey"), let key = Data(base64Encoded: k) else { return nil }
        return (u, c, key)
    }

    private static func b64u(_ s: String) -> Data? {
        var t = s.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        while t.count % 4 != 0 { t += "=" }
        return Data(base64Encoded: t)
    }

    // MARK: 암호
    private static func hmac(_ key: Data, _ data: Data) -> Data {
        Data(HMAC<SHA256>.authenticationCode(for: data, using: SymmetricKey(data: key)))
    }
    private static func token(_ master: Data) -> String {
        hmac(master, Data("sseudam-relay-auth".utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private static func xorStream(_ kEnc: Data, _ nonce: Data, _ input: Data) -> Data {
        var out = Data(count: input.count)
        let key = SymmetricKey(data: kEnc)
        var block: UInt64 = 0
        var i = 0
        input.withUnsafeBytes { src in
            out.withUnsafeMutableBytes { dst in
                let s = src.bindMemory(to: UInt8.self), o = dst.bindMemory(to: UInt8.self)
                while i < input.count {
                    var ctr = block.bigEndian
                    let counter = Data(bytes: &ctr, count: 8)
                    let ks = Array(HMAC<SHA256>.authenticationCode(for: nonce + counter, using: key))
                    var j = 0
                    while j < ks.count && i < input.count { o[i] = s[i] ^ ks[j]; i += 1; j += 1 }
                    block += 1
                }
            }
        }
        return out
    }

    static func seal(_ master: Data, meta: [String: Any], body: Data = Data()) throws -> Data {
        let kEnc = hmac(master, Data("sseudam-enc".utf8)), kMac = hmac(master, Data("sseudam-mac".utf8))
        let m = try JSONSerialization.data(withJSONObject: meta)
        var len = UInt32(m.count).bigEndian
        let plain = Data(bytes: &len, count: 4) + m + body
        var nonceBytes = [UInt8](repeating: 0, count: 16)
        _ = SecRandomCopyBytes(kSecRandomDefault, 16, &nonceBytes)
        let nonce = Data(nonceBytes)
        let ct = xorStream(kEnc, nonce, plain)
        return magic + nonce + ct + hmac(kMac, magic + nonce + ct)
    }

    static func open(_ master: Data, _ blob: Data) throws -> (meta: [String: Any], body: Data) {
        let b = [UInt8](blob)
        guard b.count >= 52, Data(b[0..<4]) == magic else { throw RelayError.format }
        let kEnc = hmac(master, Data("sseudam-enc".utf8)), kMac = hmac(master, Data("sseudam-mac".utf8))
        let nonce = Data(b[4..<20]), ct = Data(b[20..<(b.count - 32)]), tag = Data(b[(b.count - 32)...])
        guard hmac(kMac, magic + nonce + ct) == tag else { throw RelayError.key }
        let plain = [UInt8](xorStream(kEnc, nonce, ct))
        let n = Int(plain[0]) << 24 | Int(plain[1]) << 16 | Int(plain[2]) << 8 | Int(plain[3])
        let meta = (try JSONSerialization.jsonObject(with: Data(plain[4..<(4 + n)]))) as? [String: Any] ?? [:]
        return (meta, Data(plain[(4 + n)...]))
    }

    enum RelayError: LocalizedError {
        case format, key, notPaired, server(Int), notFound
        var errorDescription: String? {
            switch self {
            case .format: return "쓰담 연동 형식이 아니에요"
            case .key: return "열쇠가 맞지 않아요 — 컴퓨터의 QR을 다시 찍어 주세요"
            case .notPaired: return "컴퓨터와 연결되어 있지 않아요"
            case .server(let c): return "연결 서버 오류 (\(c))"
            case .notFound: return "없음"
            }
        }
    }

    // MARK: 중계 서버
    private static func req(_ method: String, _ path: String, body: Data? = nil) async throws -> Data {
        guard let c = creds(), let url = URL(string: "\(c.url)/v1/\(c.ch)\(path)") else { throw RelayError.notPaired }
        var r = URLRequest(url: url, timeoutInterval: 300)
        r.httpMethod = method
        r.setValue(token(c.key), forHTTPHeaderField: "x-relay-token")
        if let body { r.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type"); r.httpBody = body }
        let (data, resp) = try await URLSession.shared.data(for: r)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        if code == 404 { throw RelayError.notFound }
        guard (200..<300).contains(code) else { throw RelayError.server(code) }
        return data
    }

    private static var deviceName: String { String(UIDevice.current.name.prefix(40)) }

    /// 녹음(또는 한 줄 메모) 하나를 컴퓨터로
    static func upload(file: URL, entry e: Entry, deviceId: String) async throws {
        guard let c = creds() else { throw RelayError.notPaired }
        let df = DateFormatter(); df.locale = Locale(identifier: "ko_KR"); df.dateFormat = "yyyy-MM-dd HH:mm"
        let ext = "." + (e.fileName.split(separator: ".").last.map(String.init) ?? "m4a")
        let meta: [String: Any] = ["type": "rec", "name": e.fileName, "ext": ext, "recorded_at": df.string(from: e.createdAt),
                                   "kind": e.kind, "title": (e.fileName as NSString).deletingPathExtension, "memo": e.memo,
                                   "transcript": e.isAudio ? e.transcript : e.text, "device": deviceId, "device_name": deviceName]
        let body = e.isAudio ? ((try? Data(contentsOf: file)) ?? Data()) : Data()
        let name = "rec-\(Int(e.createdAt.timeIntervalSince1970 * 1000))-\(e.id.uuidString.prefix(8)).bin"
        _ = try await req("PUT", "/pc/\(name)", body: try seal(c.key, meta: meta, body: body))
    }

    /// 학생 기록: 내 문서 올리기(바뀐 경우만) + 컴퓨터 문서 받아 오기
    static func syncDocs(myDoc: Data, deviceId: String) async throws -> Data? {
        guard let c = creds() else { return nil }
        let sig = SHA256.hash(data: stripUpdatedAt(myDoc)).map { String(format: "%02x", $0) }.joined()
        if d.string(forKey: "relayDocSig") != sig {
            let meta: [String: Any] = ["type": "doc", "device": deviceId, "device_name": deviceName]
            _ = try await req("PUT", "/pc/doc-\(deviceId.prefix(40)).bin", body: try seal(c.key, meta: meta, body: myDoc))
            d.set(sig, forKey: "relayDocSig")
        }
        do { return try open(c.key, try await req("GET", "/phone/doc-pc.bin")).body }
        catch RelayError.notFound { return nil }
    }

    private static func stripUpdatedAt(_ doc: Data) -> Data {
        guard var o = (try? JSONSerialization.jsonObject(with: doc)) as? [String: Any] else { return doc }
        o.removeValue(forKey: "updated_at")
        return (try? JSONSerialization.data(withJSONObject: o, options: [.sortedKeys])) ?? doc
    }

    static func disconnectRemote() async { _ = try? await req("DELETE", "") }
}
