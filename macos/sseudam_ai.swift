// 쓰담 맥용 기기 안 AI 도우미 (애플 Foundation Models, macOS 26+ · 애플 인텔리전스 켜진 Apple Silicon 맥).
// 파이썬 서버가 부른다. 인터넷으로 아무것도 보내지 않는다.
//   sseudam-ai status            → {"state": "ready" | "notEnabled" | "notReady" | "notEligible" | "unsupportedOS"}
//   sseudam-ai owners < 입력.json → {"owners": [학생번호…]}   (입력: {"sentences": [...], "names": [...], "known": {"문장번호": 학생번호}})
//   sseudam-ai generate < 입력.json → {"text": "..."}       (입력: {"system": "...", "prompt": "..."})
import Foundation
#if canImport(FoundationModels)
import FoundationModels
#endif

func emit(_ obj: Any) {
    let data = (try? JSONSerialization.data(withJSONObject: obj)) ?? Data("{}".utf8)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
}

func fail(_ msg: String) -> Never {
    emit(["error": msg])
    exit(1)
}

func state() -> String {
    #if canImport(FoundationModels)
    if #available(macOS 26.0, *) {
        switch SystemLanguageModel.default.availability {
        case .available: return "ready"
        case .unavailable(.appleIntelligenceNotEnabled): return "notEnabled"
        case .unavailable(.modelNotReady): return "notReady"
        default: return "notEligible"
        }
    }
    #endif
    return "unsupportedOS"
}

let instructions = """
너는 선생님이 수업 중 남긴 관찰 메모를 학생별로 나누는 도우미야.
각 문장이 아래 학생 중 누구에 대한 내용인지 학생 번호로 답해.
- "그 친구", "이 학생", "걔", "또한", "다만"처럼 이름 없이 이어지는 문장은 바로 앞 문장의 학생과 같은 학생이야.
- "오늘 수업", "반 전체", "모두", "분위기"처럼 여러 학생이나 수업 이야기면 0.
- 목록에 없는 학생은 절대 만들지 마.
예시) 학생: 1. 김민수 2. 이서연
[1] 오늘 실험을 했음. → 0
[2] (김민수 언급) 김민수는 가설을 세웠음. → 1
[3] 그 친구는 결과도 정리함. → 1
[4] (이서연 언급) 이서연은 질문을 많이 함. → 2
[5] 다만 기록이 부족했음. → 2
[6] 모두 열심히 참여함. → 0
"""

#if canImport(FoundationModels)
@available(macOS 26.0, *)
@Generable
struct SentenceOwners {
    @Guide(description: "문장마다 하나씩: 문장 번호와 그 문장의 학생 번호")
    var items: [SentenceOwner]
}

@available(macOS 26.0, *)
@Generable
struct SentenceOwner {
    @Guide(description: "문장 번호 (1부터)")
    var sentence: Int
    @Guide(description: "학생 번호 (1부터). 특정 학생이 아니거나 모르면 0")
    var student: Int
}

@available(macOS 26.0, *)
func owners(_ input: [String: Any]) async throws -> [Int] {
    let sentences = input["sentences"] as? [String] ?? []
    let names = input["names"] as? [String] ?? []
    let known = input["known"] as? [String: Int] ?? [:]
    let roster = names.enumerated().map { "\($0.offset + 1). \($0.element)" }.joined(separator: "\n")
    let lines = sentences.enumerated().map { i, s -> String in
        if let k = known[String(i + 1)], k >= 1, k <= names.count { return "[\(i + 1)] (\(names[k - 1]) 언급) \(s)" }
        return "[\(i + 1)] \(s)"
    }.joined(separator: "\n")
    let session = LanguageModelSession(instructions: instructions)
    let r = try await session.respond(to: "학생 목록:\n\(roster)\n\n문장:\n\(lines)", generating: SentenceOwners.self)
    var out = Array(repeating: 0, count: sentences.count)
    for a in r.content.items where (1...max(1, sentences.count)).contains(a.sentence) && (0...names.count).contains(a.student) {
        out[a.sentence - 1] = a.student
    }
    return out
}

@available(macOS 26.0, *)
func generate(_ input: [String: Any]) async throws -> String {
    let session = LanguageModelSession(instructions: input["system"] as? String ?? "")
    return try await session.respond(to: input["prompt"] as? String ?? "").content
}
#endif

func readInput() -> [String: Any] {
    let data = FileHandle.standardInput.readDataToEndOfFile()
    guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { fail("입력 JSON을 읽지 못했어요.") }
    return obj
}

let cmd = CommandLine.arguments.dropFirst().first ?? "status"
if cmd == "status" {
    emit(["state": state()])
    exit(0)
}
guard state() == "ready" else { fail("기기 안 AI를 쓸 수 없어요 (\(state())).") }

#if canImport(FoundationModels)
if #available(macOS 26.0, *) {
    let input = readInput()
    let done = DispatchSemaphore(value: 0)
    Task {
        do {
            switch cmd {
            case "owners": emit(["owners": try await owners(input)])
            case "generate": emit(["text": try await generate(input)])
            default: emit(["error": "알 수 없는 명령: \(cmd)"])
            }
        } catch {
            emit(["error": "\(error)"])
        }
        done.signal()
    }
    done.wait()
    exit(0)
}
#endif
fail("macOS 26 이상에서 쓸 수 있어요.")
