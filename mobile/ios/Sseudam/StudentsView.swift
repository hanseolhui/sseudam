import SwiftUI

/// 학생: 반 → 학생 → 학생별 기록·초안. 맥과 같은 Apple ID면 맥에서 정리한 내용도 여기 함께 보인다.
struct StudentsView: View {
    @EnvironmentObject var data: DataStore
    @EnvironmentObject var store: Store
    @State private var addingClass = false
    @State private var exportURL: URL?
    @State private var query = ""
    @State private var showPast = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if !query.isEmpty {
                        searchResults
                    } else {
                        syncCard
                        if data.activeClasses.isEmpty { empty } else {
                            ForEach(data.currentClasses) { c in
                                NavigationLink { ClassDetail(cls: c) } label: { classRow(c) }.buttonStyle(.plain)
                            }
                            if !data.pastClasses.isEmpty {
                                Button { withAnimation(.spring(response: 0.4)) { showPast.toggle() } } label: {
                                    HStack {
                                        Label("지난 학기 반 \(data.pastClasses.count)개", systemImage: "archivebox").font(Theme.font(14, .bold))
                                        Spacer()
                                        Image(systemName: "chevron.down").rotationEffect(.degrees(showPast ? 180 : 0))
                                    }
                                    .foregroundStyle(Theme.soft).padding(.horizontal, 6).padding(.top, 6)
                                }
                                if showPast {
                                    ForEach(data.pastClasses) { c in
                                        NavigationLink { ClassDetail(cls: c) } label: { classRow(c).opacity(0.8) }.buttonStyle(.plain)
                                            .transition(.move(edge: .top).combined(with: .opacity))
                                    }
                                }
                            }
                        }
                    }
                }
                .padding(18).frame(maxWidth: 640).frame(maxWidth: .infinity)
            }
            .softBackground()
            .navigationTitle("학생")
            .searchable(text: $query, prompt: "학생 이름 찾기")
            .refreshable { await data.syncNow() }
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Menu {
                        Button { addingClass = true } label: { Label("반 만들기", systemImage: "plus") }
                        Button { exportURL = data.exportCSV() } label: { Label("엑셀로 내보내기 (CSV)", systemImage: "tablecells") }
                        Toggle(isOn: Binding(get: { data.splitOnPhone }, set: { data.splitOnPhone = $0 })) {
                            Label("폰에서 학생별로 나누기", systemImage: "person.2")
                        }
                    } label: { Image(systemName: "ellipsis.circle").font(.title3) }
                }
            }
            .sheet(isPresented: $addingClass) { AddClassSheet() }
            .sheet(item: Binding(get: { exportURL.map(ShareItem.init) }, set: { if $0 == nil { exportURL = nil } })) { item in
                ShareSheet(url: item.url)
            }
        }
    }

    var searchResults: some View {
        let list = data.search(query)
        return VStack(alignment: .leading, spacing: 10) {
            if list.isEmpty {
                Text("‘\(query)’ 학생을 찾지 못했어요").font(Theme.font(15)).foregroundStyle(Theme.soft).padding(.top, 20)
            }
            ForEach(list) { s in
                NavigationLink { StudentDetail(student: s) } label: {
                    HStack(spacing: 12) {
                        StudentChip(student: s)
                        Text(data.classOf(s)?.title ?? "").font(Theme.font(13)).foregroundStyle(Theme.soft)
                        Spacer()
                        Text("기록 \(data.notes(of: s).count)").font(Theme.font(12, .bold)).foregroundStyle(Theme.soft)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading).card()
                }.buttonStyle(.plain)
            }
        }
    }

    var syncCard: some View {
        HStack(spacing: 12) {
            Image(systemName: data.otherDevices.isEmpty ? "icloud" : "arrow.triangle.2.circlepath.icloud.fill")
                .font(.system(size: 20, weight: .semibold)).foregroundStyle(Theme.blue)
                .frame(width: 42, height: 42).background(Theme.blue.opacity(0.14), in: RoundedRectangle(cornerRadius: 13))
            VStack(alignment: .leading, spacing: 3) {
                Text(data.otherDevices.isEmpty ? "이 폰에서 정리 중" : "\(data.otherDevices.joined(separator: ", "))와 맞춰 보는 중")
                    .font(Theme.font(15, .bold)).lineLimit(1)
                Text(syncSub).font(Theme.font(12)).foregroundStyle(Theme.soft).fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
            if data.syncing { ProgressView() }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    var syncSub: String {
        if !store.icloudAvailable { return "iCloud에 로그인하면 맥·아이패드와 기록이 맞춰져요 (녹음은 빼고 글만)" }
        let t = data.lastSync.map { "마지막 \($0.formatted(date: .omitted, time: .shortened))" } ?? "아직 맞추지 않음"
        return "같은 Apple ID 기기끼리 글 기록만 주고받아요 · \(t)"
    }

    var empty: some View {
        VStack(spacing: 14) {
            Dami(size: 84, mood: .calm)
            Text("학생 명단을 넣어 볼까요?").font(Theme.font(19, .bold))
            Text("반을 만들고 이름을 붙여넣으면, 말한 내용이\n학생별 기록으로 쏙쏙 나뉘어 들어가요.\n맥의 쓰담에 명단이 있으면 저절로 들어와요.")
                .font(Theme.font(14)).foregroundStyle(Theme.soft).multilineTextAlignment(.center)
            Button { addingClass = true } label: {
                Label("반 만들기", systemImage: "plus").font(Theme.font(16, .bold))
                    .padding(.horizontal, 26).padding(.vertical, 12)
                    .background(Theme.brand, in: Capsule()).foregroundStyle(.white)
            }.buttonStyle(Squishy())
        }
        .frame(maxWidth: .infinity).padding(.vertical, 20)
        .card()
    }

    func classRow(_ c: SClass) -> some View {
        let n = data.students(in: c).count
        let color = kindColor(c.kind)
        return HStack(spacing: 14) {
            Image(systemName: kindIcon(c.kind)).font(.system(size: 20, weight: .bold)).foregroundStyle(.white)
                .frame(width: 46, height: 46).background(color, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
            VStack(alignment: .leading, spacing: 4) {
                Text(c.title).font(Theme.font(17, .bold)).foregroundStyle(Theme.ink)
                Text("\(c.kind ?? "교과") · 학생 \(n)명 · 기록 \(data.noteCount(c))개").font(Theme.font(13)).foregroundStyle(Theme.soft)
            }
            Spacer()
            Image(systemName: "chevron.right").font(.system(size: 13, weight: .bold)).foregroundStyle(.tertiary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }
}

func kindIcon(_ k: String?) -> String {
    switch k ?? "교과" {
    case "담임": return "house.fill"
    case "동아리": return "star.fill"
    case "기타": return "sparkles"
    default: return "book.fill"
    }
}

/// "10월 12일 (월)" 처럼 읽기 쉬운 날짜
func friendlyDate(_ iso: String?) -> String {
    guard let iso, iso.count >= 10 else { return iso ?? "" }
    let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd"
    guard let d = f.date(from: String(iso.prefix(10))) else { return iso }
    if Calendar.current.isDateInToday(d) { return "오늘" }
    if Calendar.current.isDateInYesterday(d) { return "어제" }
    let o = DateFormatter(); o.locale = Locale(identifier: "ko_KR")
    o.dateFormat = Calendar.current.isDate(d, equalTo: Date(), toGranularity: .year) ? "M월 d일 (E)" : "yyyy년 M월 d일"
    return o.string(from: d)
}

func kindColor(_ k: String?) -> Color {
    switch k ?? "교과" {
    case "담임": return Theme.coral
    case "동아리": return Theme.mint
    case "기타": return Theme.butter
    default: return Theme.blue
    }
}

// MARK: - 반

struct ClassDetail: View {
    @EnvironmentObject var data: DataStore
    @Environment(\.dismiss) private var dismiss
    var cls: SClass
    @State private var pasting = false
    @State private var confirmDelete = false
    @State private var editing: SStudent?
    @State private var drafting = false

    var body: some View {
        List {
            let list = data.students(in: cls)
            if list.isEmpty {
                Section {
                    Button { pasting = true } label: {
                        Label("명단 붙여넣기", systemImage: "list.bullet.clipboard").font(Theme.font(16, .bold))
                    }
                    Text("NEIS나 엑셀에서 번호·이름을 복사해 붙여넣으면 돼요.").font(Theme.font(13)).foregroundStyle(Theme.soft)
                }.listRowBackground(Theme.card)
            }
            let quiet = list.filter { data.notes(of: $0).isEmpty }
            if !list.isEmpty && !quiet.isEmpty && quiet.count < list.count {
                Section {
                    HStack(alignment: .top, spacing: 10) {
                        Text("🌱").font(.title3)
                        VStack(alignment: .leading, spacing: 3) {
                            Text("아직 기록이 없는 친구 \(quiet.count)명").font(Theme.font(14, .bold))
                            Text(quiet.prefix(6).map(\.displayName).joined(separator: ", ") + (quiet.count > 6 ? " 외" : "") + " — 다음 수업에 한마디 남겨 볼까요?")
                                .font(Theme.font(12)).foregroundStyle(Theme.soft)
                        }
                    }
                }.listRowBackground(Theme.mint.opacity(0.1))
            }
            Section {
                ForEach(list) { s in
                    NavigationLink { StudentDetail(student: s) } label: {
                        HStack(spacing: 12) {
                            Text(s.number.map(String.init) ?? "–").font(Theme.font(14, .bold)).foregroundStyle(Theme.soft)
                                .frame(width: 26)
                            Text(s.displayName).font(Theme.font(16, .semibold))
                            Spacer()
                            CountBar(count: data.notes(of: s).count,
                                     maxCount: list.map { data.notes(of: $0).count }.max() ?? 1, color: kindColor(cls.kind))
                        }
                    }
                    .swipeActions {
                        Button("지우기", role: .destructive) { withAnimation { data.deleteStudent(s) } }
                        Button("고치기") { editing = s }.tint(Theme.blue)
                    }
                    .contextMenu {
                        Section("빠른 기록") {
                            ForEach(QuickTags.all, id: \.text) { t in
                                Button("\(t.emoji) \(t.text)") { data.addNote(s, content: t.text) }
                            }
                        }
                        Button { editing = s } label: { Label("이름 고치기 · 합치기", systemImage: "pencil") }
                        Button(role: .destructive) { withAnimation { data.deleteStudent(s) } } label: { Label("지우기", systemImage: "trash") }
                    }
                }
            } header: {
                if !list.isEmpty { Text("학생 \(list.count)명").font(Theme.font(13, .bold)) }
            }
            .listRowBackground(Theme.card)
        }
        .scrollContentBackground(.hidden)
        .softBackground()
        .navigationTitle(cls.title)
        .bigBackButton("학생")
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                Menu {
                    Button { drafting = true } label: { Label("반 전체 초안 (ChatGPT·Gemini)", systemImage: "wand.and.stars") }
                    Button { pasting = true } label: { Label("학생 더하기 · 명단 붙여넣기", systemImage: "person.badge.plus") }
                    Button(role: .destructive) { confirmDelete = true } label: { Label("이 반 지우기", systemImage: "trash") }
                } label: { Image(systemName: "ellipsis.circle") }
            }
        }
        .sheet(isPresented: $pasting) { RosterSheet(cls: cls) }
        .sheet(item: $editing) { s in StudentEditSheet(student: s) }
        .sheet(isPresented: $drafting) { ClassDraftSheet(cls: cls) }
        .animation(.spring(response: 0.4, dampingFraction: 0.85), value: data.students(in: cls).map(\.uid))
        .alert("이 반을 지울까요?", isPresented: $confirmDelete) {
            Button("지우기", role: .destructive) { data.deleteClass(cls); dismiss() }
            Button("취소", role: .cancel) {}
        } message: { Text("학생과 학생별 기록도 함께 지워지고, 연결된 다른 기기에서도 지워져요. 녹음 원본은 그대로 남아요.") }
    }
}

// MARK: - 학생

struct StudentDetail: View {
    @EnvironmentObject var data: DataStore
    var student: SStudent
    @State private var newNote = ""
    @State private var editing: SNote?
    @State private var editText = ""
    @State private var copied = false
    @State private var editingStudent = false
    @State private var moving: SNote?
    @State private var promptCopied = false
    @State private var pdfURL: URL?
    @FocusState private var focused: Bool
    @Environment(\.dismiss) private var dismiss

    var cls: SClass? { data.classOf(student) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header
                if !data.notes(of: student).isEmpty { summaryCard }
                addCard
                tagCard
                let drafts = data.drafts(of: student)
                if !drafts.isEmpty {
                    Text("초안").font(Theme.font(15, .bold)).foregroundStyle(Theme.soft).padding(.leading, 4)
                    ForEach(drafts) { d in draftCard(d) }
                }
                let notes = data.notes(of: student)
                if !notes.isEmpty { promptCard }
                Text(notes.isEmpty ? "아직 기록이 없어요 🌱" : "관찰 기록 \(notes.count)개").font(Theme.font(15, .bold))
                    .foregroundStyle(Theme.soft).padding(.leading, 4)
                ForEach(notes) { n in
                    noteCard(n).transition(.asymmetric(insertion: .scale(scale: 0.94).combined(with: .opacity),
                                                       removal: .move(edge: .trailing).combined(with: .opacity)))
                }
            }
            .padding(18).frame(maxWidth: 640).frame(maxWidth: .infinity)
        }
        .scrollDismissesKeyboard(.interactively)
        .softBackground()
        .animation(.spring(response: 0.42, dampingFraction: 0.82), value: data.notes(of: student).map { $0.uid + ($0.content ?? "") })
        .navigationTitle(student.displayName)
        .navigationBarTitleDisplayMode(.inline)
        .bigBackButton(cls?.title ?? "반")
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                Menu {
                    Button { editingStudent = true } label: { Label("이름·별칭 고치기", systemImage: "pencil") }
                    Button { pdfURL = StudentPDF.make(student: student, cls: cls, notes: data.notes(of: student), drafts: data.drafts(of: student)) } label: {
                        Label("PDF 한 장으로 내보내기", systemImage: "doc.richtext")
                    }
                } label: { Image(systemName: "ellipsis.circle") }.accessibilityLabel("학생 메뉴")
            }
        }
        .sheet(item: Binding(get: { pdfURL.map(ShareItem.init) }, set: { if $0 == nil { pdfURL = nil } })) { ShareSheet(url: $0.url) }
        .sheet(isPresented: $editingStudent) { StudentEditSheet(student: data.student(student.uid) ?? student) { dismiss() } }
        .sheet(item: $moving) { n in
            StudentPicker(title: "누구의 기록인가요?", suggested: data.candidates(n), current: n.student_uid) { s in
                withAnimation(.spring(response: 0.42, dampingFraction: 0.82)) { data.moveNote(n, to: s) }
            }
        }
        .sheet(item: $editing) { n in
            NavigationStack {
                VStack(alignment: .leading, spacing: 10) {
                    HStack(spacing: 8) {
                        StudentChip(student: student)
                        Text(friendlyDate(n.date)).font(Theme.font(13, .semibold)).foregroundStyle(Theme.soft)
                        Spacer()
                        Text("\(editText.count)자").font(Theme.font(12, .semibold)).foregroundStyle(Theme.soft)
                    }
                    TextEditor(text: $editText).font(Theme.font(17)).scrollContentBackground(.hidden)
                        .padding(12).frame(minHeight: 180)
                        .background(Theme.card, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                    Text("있었던 일 그대로 짧게 고쳐 주세요. 초안은 이 기록을 바탕으로 만들어져요 ✍️")
                        .font(Theme.font(12)).foregroundStyle(Theme.soft)
                    Spacer()
                }
                .padding(18).softBackground()
                .navigationTitle("기록 고치기").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("취소") { editing = nil } }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("저장") { withAnimation { data.editNote(n, content: editText) }; editing = nil }.fontWeight(.bold)
                    }
                }
            }.presentationDetents([.medium, .large])
        }
    }

    var header: some View {
        HStack(spacing: 14) {
            Text(String(student.displayName.suffix(2))).font(Theme.font(18, .heavy)).foregroundStyle(.white)
                .frame(width: 54, height: 54).background(kindColor(cls?.kind), in: Circle())
            VStack(alignment: .leading, spacing: 4) {
                Text(student.displayName).font(Theme.font(22, .bold))
                Text([cls?.title, student.number.map { "\($0)번" }].compactMap { $0 }.joined(separator: " · "))
                    .font(Theme.font(13)).foregroundStyle(Theme.soft)
            }
            Spacer()
            Button {
                UIPasteboard.general.string = allNotesText
                copied = true
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { copied = false }
            } label: {
                Label(copied ? "복사됨" : "기록 복사", systemImage: copied ? "checkmark" : "doc.on.doc")
                    .font(Theme.font(13, .bold)).padding(.horizontal, 12).padding(.vertical, 8)
                    .background(Theme.blue.opacity(0.12), in: Capsule())
            }.buttonStyle(Squishy())
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    /// 초안 만들 때 쓰도록 날짜와 함께 모은 기록
    var allNotesText: String {
        data.notes(of: student).reversed().map { "[\($0.date ?? "")] \($0.content ?? "")" }.joined(separator: "\n")
    }

    var addCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            TextField("\(student.displayName) 학생에 대해 한 줄 남기기", text: $newNote, axis: .vertical)
                .font(Theme.font(15)).lineLimit(1...5).focused($focused)
                .padding(12).background(Theme.bg, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            HStack {
                PhotoCaptureButtons { t in
                    if !t.isEmpty { newNote = newNote.isEmpty ? t : newNote + "\n" + t; focused = true }
                }
                Spacer()
                Button {
                    let t = newNote.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !t.isEmpty else { return }
                    data.addNote(student, content: t)
                    newNote = ""; focused = false
                    UINotificationFeedbackGenerator().notificationOccurred(.success)
                } label: {
                    Label("담기", systemImage: "arrow.down.circle.fill").font(Theme.font(14, .bold))
                        .padding(.horizontal, 14).padding(.vertical, 8)
                        .background(newNote.trimmingCharacters(in: .whitespaces).isEmpty ? Color.gray.opacity(0.25) : Theme.blue, in: Capsule())
                        .foregroundStyle(.white)
                }.buttonStyle(Squishy())
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    var tagCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("톡 눌러 바로 담기").font(Theme.font(13, .bold)).foregroundStyle(Theme.soft)
            QuickTagRow(student: student)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    func noteCard(_ n: SNote) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Text(friendlyDate(n.date)).font(Theme.font(12, .bold)).foregroundStyle(Theme.soft)
                if data.isUnsure(n) {
                    Button { moving = n } label: {
                        Label("동명이인 확인", systemImage: "questionmark.circle.fill").font(Theme.font(11, .bold))
                            .padding(.horizontal, 7).padding(.vertical, 2)
                            .background(Theme.butter.opacity(0.18), in: Capsule()).foregroundStyle(Theme.butter)
                    }
                }
                if let k = n.kind, !k.isEmpty {
                    Text(k).font(Theme.font(11, .bold)).padding(.horizontal, 7).padding(.vertical, 2)
                        .foregroundStyle(k == "상담" ? Theme.lavender : Theme.blue)
                        .background((k == "상담" ? Theme.lavender : Theme.blue).opacity(0.14), in: Capsule())
                }
                Text(Areas.name(n.area?.isEmpty == false ? n.area : Areas.forKind(cls?.kind).first))
                    .font(Theme.font(11, .semibold)).foregroundStyle(Theme.soft)
                Spacer()
                if (n.source ?? "").hasSuffix(".m4a") { Image(systemName: "waveform").font(.caption).foregroundStyle(.tertiary) }
                Menu {
                    Button { editText = n.content ?? ""; editing = n } label: { Label("고치기", systemImage: "pencil") }
                    Button { moving = n } label: { Label("다른 학생으로 옮기기", systemImage: "arrow.right.arrow.left") }
                    Menu {
                        ForEach(Areas.all, id: \.id) { a in
                            Button { data.setArea(n, a.id) } label: {
                                if (n.area?.isEmpty == false ? n.area : Areas.forKind(cls?.kind).first) == a.id { Label(a.name, systemImage: "checkmark") } else { Text(a.name) }
                            }
                        }
                    } label: { Label("영역 바꾸기", systemImage: "square.grid.2x2") }
                    if data.isUnsure(n) {
                        Button { data.confirmNote(n) } label: { Label("이 학생이 맞아요", systemImage: "checkmark") }
                    }
                    Button { UIPasteboard.general.string = n.content } label: { Label("복사", systemImage: "doc.on.doc") }
                    Button(role: .destructive) { data.deleteNote(n) } label: { Label("지우기", systemImage: "trash") }
                } label: { Image(systemName: "ellipsis").font(.system(size: 15, weight: .bold)).foregroundStyle(Theme.soft).padding(6) }
            }
            Text(n.content ?? "").font(Theme.font(15)).fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    /// 한눈에 보기 — 모인 기록 수·기간·최근 활동. (AI가 쓰는 요약은 쓰담 플러스에서)
    var summaryCard: some View {
        let ns = data.notes(of: student)
        let dates = ns.compactMap(\.date).sorted()
        let month = ns.filter { ($0.date ?? "") >= DataStore.isoDaysAgo(30) }.count
        let talks = ns.filter { $0.kind == "상담" }.count
        return VStack(alignment: .leading, spacing: 12) {
            Label("한눈에 보기", systemImage: "sparkle.magnifyingglass").font(Theme.font(15, .bold))
            HStack(spacing: 10) {
                stat("\(ns.count)", "모인 기록", Theme.blue)
                stat("\(month)", "최근 30일", Theme.mint)
                if Features.counseling { stat("\(talks)", "상담", Theme.lavender) }
            }
            WeekBars(dates: ns.compactMap(\.date))
            if let f = dates.first, let l = dates.last {
                Text("\(friendlyDate(f))부터 \(friendlyDate(l))까지 · 마지막 기록 \(friendlyDate(l))")
                    .font(Theme.font(12)).foregroundStyle(Theme.soft)
            }
            HStack(spacing: 8) {
                Image(systemName: "wand.and.stars").foregroundStyle(Theme.lavender)
                Text("AI가 모인 기록을 몇 줄로 정리해 주는 요약은 ‘쓰담 플러스’나 내 AI 키 연결로 준비 중이에요.")
                    .font(Theme.font(12)).foregroundStyle(Theme.soft).fixedSize(horizontal: false, vertical: true)
            }
            .padding(10).frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.lavender.opacity(0.08), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    func stat(_ v: String, _ label: String, _ color: Color) -> some View {
        VStack(spacing: 2) {
            Text(v).font(Theme.font(22, .heavy)).foregroundStyle(color).contentTransition(.numericText())
            Text(label).font(Theme.font(11, .semibold)).foregroundStyle(Theme.soft)
        }
        .frame(maxWidth: .infinity).padding(.vertical, 10)
        .background(color.opacity(0.1), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }

    /// ChatGPT·Gemini 등에 붙여넣을 초안 요청문 (학생 이름은 빼고 'OO'으로)
    var promptCard: some View {
        let area = Areas.forKind(cls?.kind).first ?? "subject"
        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label("초안 도움 받기", systemImage: "wand.and.stars").font(Theme.font(15, .bold)).foregroundStyle(Theme.lavender)
                Spacer()
                Button {
                    UIPasteboard.general.string = draftPrompt(area: area)
                    withAnimation(.spring(response: 0.3)) { promptCopied = true }
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.6) { withAnimation { promptCopied = false } }
                } label: {
                    Label(promptCopied ? "복사됨" : "요청문 복사", systemImage: promptCopied ? "checkmark" : "doc.on.doc")
                        .font(Theme.font(13, .bold)).padding(.horizontal, 12).padding(.vertical, 7)
                        .background(Theme.lavender.opacity(0.15), in: Capsule()).foregroundStyle(Theme.lavender)
                }.buttonStyle(Squishy())
            }
            Text("기록을 모은 \(Areas.name(area)) 초안 요청문을 복사해요. 이름은 ‘OO’으로 바꿔 넣으니 ChatGPT·Gemini에 붙여넣고, 나온 글은 꼭 다듬어 주세요. 생기부 내용의 책임은 선생님께 있어요.")
                .font(Theme.font(12)).foregroundStyle(Theme.soft).fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    func draftPrompt(area: String) -> String {
        let name = student.displayName
        let short = name.count >= 3 ? String(name.dropFirst()) : name
        let lines = data.notes(of: student).reversed().map { n -> String in
            let t = (n.content ?? "").replacingOccurrences(of: name, with: "OO").replacingOccurrences(of: short, with: "OO")
            return "- [\(n.date ?? "")] \(t)"
        }
        return """
        너는 학교 선생님의 학교생활기록부 작성을 돕는 보조자야. 아래 '관찰 기록'에 있는 사실만 근거로 \(Areas.name(area)) 초안을 써 줘.
        - 학생은 'OO'로만 부르고 이름을 만들지 마.
        - 기록에 없는 활동·성과·수상은 절대 지어내지 마.
        - 문장 끝은 '~함', '~임' 같은 명사형으로, 한 문단으로 써 줘.
        - NEIS 기준 \(Areas.limit(area))바이트(한글 3바이트) 이내.
        - 사교육·부모 직업·교외 수상 등 기재 금지 내용은 넣지 마.

        관찰 기록:
        \(lines.joined(separator: "\n"))
        """
    }

    func draftCard(_ d: SDraft) -> some View {
        let text = d.content ?? ""
        let limit = Areas.limit(d.area)
        let bytes = neisBytes(text)
        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(Areas.name(d.area)).font(Theme.font(14, .bold)).foregroundStyle(Theme.lavender)
                Spacer()
                Text("\(bytes) / \(limit) 바이트").font(Theme.font(12, .semibold)).foregroundStyle(bytes > limit ? Theme.coral : Theme.soft)
                Button { UIPasteboard.general.string = text } label: { Image(systemName: "doc.on.doc") }
            }
            Text(text).font(Theme.font(15)).fixedSize(horizontal: false, vertical: true)
            CheckList(text: text, limit: limit)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
        .contextMenu {
            Button { UIPasteboard.general.string = text } label: { Label("복사", systemImage: "doc.on.doc") }
            Button(role: .destructive) { withAnimation { data.deleteDraft(d) } } label: { Label("초안 지우기", systemImage: "trash") }
        }
    }
}

// MARK: - 반 만들기 · 명단

struct AddClassSheet: View {
    @EnvironmentObject var data: DataStore
    @Environment(\.dismiss) private var dismiss
    @State private var kind = "교과"
    @State private var grade = 1
    @State private var classNo = 1
    @State private var subject = ""
    @State private var names = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("어떤 반인가요?") {
                    Picker("유형", selection: $kind) {
                        ForEach(["교과", "담임", "동아리", "기타"], id: \.self) { Text($0) }
                    }.pickerStyle(.segmented)
                    if kind != "동아리" {
                        Stepper("\(grade)학년", value: $grade, in: 1...6)
                        Stepper("\(classNo)반", value: $classNo, in: 1...20)
                    }
                    if kind == "교과" || kind == "동아리" || kind == "기타" {
                        TextField(kind == "동아리" ? "동아리 이름" : "과목 (예: 국어)", text: $subject)
                    }
                }
                Section {
                    TextField("김민수\n이서연\n박지훈\n…", text: $names, axis: .vertical).lineLimit(5...14)
                } header: { Text("학생 명단 (나중에 넣어도 돼요)") } footer: {
                    Text("이름만 한 줄에 한 명씩 붙여넣어도 번호가 1번부터 차례로 붙어요. NEIS·엑셀에서 번호와 이름을 함께 복사해도 돼요.")
                }
                RosterPreview(lines: DataStore.previewRoster(names))
            }
            .navigationTitle("반 만들기").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("취소") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("만들기") {
                        let c = data.addClass(grade: kind == "동아리" ? nil : grade, classNo: kind == "동아리" ? nil : classNo,
                                              subject: kind == "담임" ? "" : subject.trimmingCharacters(in: .whitespaces), kind: kind)
                        if !names.isEmpty { data.addStudents(names, to: c) }
                        dismiss()
                    }.disabled(kind == "동아리" && subject.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
    }
}

struct RosterSheet: View {
    @EnvironmentObject var data: DataStore
    @Environment(\.dismiss) private var dismiss
    var cls: SClass
    @State private var names = ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("김민수\n이서연\n박지훈\n…", text: $names, axis: .vertical).lineLimit(6...16)
                } footer: { Text("이름만 한 줄에 한 명씩 붙여넣어도 번호가 차례로 붙어요. '3 김민수'처럼 번호를 써도 돼요. 이미 있는 이름은 건너뛰어요.") }
                RosterPreview(lines: data.parseRoster(names, for: cls))
            }
            .navigationTitle("\(cls.title) 명단").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("취소") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("넣기") { data.addStudents(names, to: cls); dismiss() }.disabled(names.isEmpty)
                }
            }
        }
    }
}

/// 붙여넣은 명단이 몇 번 누구로 들어갈지 미리 보기
struct RosterPreview: View {
    var lines: [DataStore.RosterLine]
    var body: some View {
        if !lines.isEmpty {
            Section("이렇게 들어가요 · \(lines.filter { !$0.exists }.count)명") {
                ForEach(lines) { l in
                    HStack(spacing: 10) {
                        Text("\(l.number)").font(Theme.font(14, .bold)).foregroundStyle(Theme.blue).frame(width: 30, alignment: .trailing)
                        Text(l.name).font(Theme.font(15))
                        Spacer()
                        if l.exists { Text("이미 있음").font(Theme.font(12)).foregroundStyle(Theme.soft) }
                    }
                    .opacity(l.exists ? 0.5 : 1)
                }
            }
        }
    }
}

struct ShareItem: Identifiable { let url: URL; var id: String { url.path } }

struct ShareSheet: UIViewControllerRepresentable {
    let url: URL
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [url], applicationActivities: nil)
    }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}


/// 최근 8주 기록 막대 — 화면에 나오면 아래에서 쏙쏙 자라남
struct WeekBars: View {
    var dates: [String]
    @State private var grown = false

    var weeks: [(label: String, n: Int)] {
        let cal = Calendar(identifier: .gregorian)
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd"
        let today = Date()
        let monday = cal.date(from: cal.dateComponents([.yearForWeekOfYear, .weekOfYear], from: today)) ?? today
        return (0..<8).reversed().map { i in
            let start = cal.date(byAdding: .day, value: -7 * i, to: monday)!
            let end = cal.date(byAdding: .day, value: 7, to: start)!
            let n = dates.compactMap { f.date(from: String($0.prefix(10))) }.filter { $0 >= start && $0 < end }.count
            let lf = DateFormatter(); lf.dateFormat = "M/d"
            return (i == 0 ? "이번 주" : lf.string(from: start), n)
        }
    }

    var body: some View {
        let w = weeks
        let maxN = max(1, w.map(\.n).max() ?? 1)
        VStack(alignment: .leading, spacing: 6) {
            Text("최근 8주").font(Theme.font(12, .bold)).foregroundStyle(Theme.soft)
            HStack(alignment: .bottom, spacing: 6) {
                ForEach(Array(w.enumerated()), id: \.offset) { i, item in
                    VStack(spacing: 4) {
                        if item.n > 0 && i == w.count - 1 {
                            Text("\(item.n)").font(Theme.font(11, .heavy)).foregroundStyle(Theme.blue)
                        }
                        RoundedRectangle(cornerRadius: 6, style: .continuous)
                            .fill(item.n == 0 ? AnyShapeStyle(Color.gray.opacity(0.15))
                                  : (i == w.count - 1 ? AnyShapeStyle(Theme.brand) : AnyShapeStyle(Theme.blue.opacity(0.55))))
                            .frame(height: grown ? max(6, 64 * CGFloat(item.n) / CGFloat(maxN)) : 4)
                            .animation(.spring(response: 0.55, dampingFraction: 0.6).delay(Double(i) * 0.05), value: grown)
                        Text(item.label).font(Theme.font(9, i == w.count - 1 ? .bold : .regular))
                            .foregroundStyle(i == w.count - 1 ? Theme.blue : Theme.soft).lineLimit(1).minimumScaleFactor(0.7)
                    }
                    .frame(maxWidth: .infinity)
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel("\(item.label) 기록 \(item.n)개")
                }
            }
            .frame(height: 96, alignment: .bottom)
        }
        .onAppear { grown = true }
    }
}
