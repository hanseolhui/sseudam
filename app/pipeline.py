# -*- coding: utf-8 -*-
"""AI 작업 큐와 결과 적용 로직.

모든 작업은 build_prompt(op, params) → (Gemini 호출 | 수동 붙여넣기) → apply(op, params, text)
의 3단계로 이루어진다. 수동 모드는 2단계를 사용자가 웹 채팅으로 대신한다.
"""
import datetime
import json
import os
import re
import threading
import time
import traceback

import db
import gemini
import prompts

_wake = threading.Event()
_lock = threading.Lock()


# ───────────────────────── 공용 조회 ─────────────────────────

def _class_info(conn, class_id):
    if not class_id:
        return {"label": "", "subject": ""}
    c = db.row(conn, "SELECT * FROM classes WHERE id=?", (class_id,))
    if not c:
        return {"label": "", "subject": ""}
    c["label"] = db.class_label(c)
    return c


def _students(conn, class_id):
    if not class_id:
        return []
    return db.rows(conn, "SELECT * FROM students WHERE class_id=? ORDER BY number, name", (class_id,))


def _term_students(conn):
    """이번 학기 모든 학급 학생 (없으면 전체) — 학급이 지정되지 않은 녹음, 다른 반 학생이 섞인 녹음용.
    학생마다 class_label 을 붙여 AI 명단에 학급도 보이게 한다."""
    today = datetime.date.today()
    y, m = today.year, today.month
    year, sem = (y - 1, 2) if m <= 2 else (y, 1 if m <= 8 else 2)
    sql = ("SELECT s.*, c.grade, c.class_no, c.subject, c.kind AS ckind, c.label AS clabel, c.year, c.semester "
           "FROM students s JOIN classes c ON c.id=s.class_id %s ORDER BY c.grade, c.class_no, s.number, s.name")
    rows = db.rows(conn, sql % "WHERE c.year=? AND c.semester=?", (year, sem))
    if not rows:
        rows = db.rows(conn, sql % "")
    for s in rows:
        s["class_label"] = db.class_label({"grade": s["grade"], "class_no": s["class_no"], "subject": s["subject"],
                                           "kind": s["ckind"], "label": s["clabel"], "year": s["year"], "semester": s["semester"]})
    return rows


def _term_classes(conn):
    today = datetime.date.today()
    y, m = today.year, today.month
    year, sem = (y - 1, 2) if m <= 2 else (y, 1 if m <= 8 else 2)
    return db.rows(conn, "SELECT * FROM classes WHERE year=? AND semester=?", (year, sem))


def _roster_for(conn, r):
    """AI 분리에 쓸 명단: 학급이 정해졌으면 그 반, 아니면 이번 학기 전체(학급 표시)."""
    if r.get("class_id"):
        own = _students(conn, r["class_id"])
        if own:
            return own
    return _term_students(conn)


def _recording(conn, rid):
    r = db.row(conn, "SELECT * FROM recordings WHERE id=?", (rid,))
    if not r:
        raise ValueError("녹음을 찾을 수 없습니다.")
    return r


def _set_rec(conn, rid, **kw):
    sets = ", ".join("%s=?" % k for k in kw)
    conn.execute("UPDATE recordings SET %s WHERE id=?" % sets, list(kw.values()) + [rid])
    conn.commit()


# ───────────────────────── 프롬프트 생성 ─────────────────────────

def build_prompt(op, params):
    conn = db.connect()
    try:
        settings = db.get_settings(conn)
        if op == "transcribe":
            r = _recording(conn, params["recording_id"])
            c = _class_info(conn, r["class_id"])
            return {"prompt": prompts.transcribe(r["kind"], c["label"], _students(conn, r["class_id"])),
                    "audio_path": r["audio_path"]}
        if op == "segment":
            r = _recording(conn, params["recording_id"])
            if not (r.get("transcript") or "").strip():
                raise ValueError("전사문이 없습니다. 먼저 전사하거나 붙여넣으세요.")
            c = _class_info(conn, r["class_id"])
            roster = _roster_for(conn, r)
            label = c["label"] if r["class_id"] and c["label"] else "미지정 — 아래는 이번 학기 모든 학급 명단"
            return {"prompt": prompts.segment(r["kind"], label, roster,
                                              r["transcript"], (r["recorded_at"] or "")[:10]),
                    "system": prompts.SEGMENT_SYSTEM, "json": True}
        if op == "draft":
            s = db.row(conn, "SELECT * FROM students WHERE id=?", (params["student_id"],))
            if not s:
                raise ValueError("학생을 찾을 수 없습니다.")
            c = _class_info(conn, s["class_id"])
            kind = c.get("kind") or "교과"
            area = params.get("area") or db.areas_for_kind(kind)[0]["id"]
            notes = [n for n in db.rows(conn, "SELECT * FROM notes WHERE student_id=? AND use_in_draft=1 "
                                              "ORDER BY date, id", (s["id"],))
                     if db.note_in_area(n, kind, area)]
            if not notes:
                raise ValueError("%s 학생의 '%s' 관찰기록이 없습니다." % (s["name"], db.area_name(area)))
            ctx = db.row(conn, "SELECT topic, competencies, philosophy FROM class_context WHERE class_id=? AND area=?",
                         (s["class_id"], area)) or {}
            t = db.row(conn, "SELECT bytes FROM student_targets WHERE student_id=? AND area=?", (s["id"], area))
            return {"prompt": prompts.draft(s, c, notes, settings, params.get("extra", ""), area,
                                            context=ctx, target=(t or {}).get("bytes"), deep=bool(params.get("deep"))),
                    "system": prompts.draft_system(area)}
        if op == "shorten":
            text = params.get("text", "")
            limit = db.area_limit(params.get("area") or "subject", settings)
            if params.get("student_id"):
                t = db.row(conn, "SELECT bytes FROM student_targets WHERE student_id=? AND area=?",
                           (params["student_id"], params.get("area") or "subject"))
                if t and t["bytes"]:
                    limit = t["bytes"]
            return {"prompt": prompts.shorten(text, limit, db.neis_bytes(text)),
                    "system": prompts.DRAFT_SYSTEM}
        raise ValueError("알 수 없는 작업: %s" % op)
    finally:
        conn.close()


# ───────────────────────── 결과 적용 ─────────────────────────

def apply(op, params, text):
    if op == "transcribe":
        return apply_transcript(params["recording_id"], text, params.get("chain"))
    if op == "segment":
        return apply_segment(params["recording_id"], text)
    if op in ("draft", "shorten"):
        return apply_draft(params["student_id"], text, params.get("area") or "subject",
                           op=op, engine=params.get("_engine") or "manual", t0=params.get("_t0"))
    raise ValueError("알 수 없는 작업: %s" % op)


def apply_transcript(rid, text, chain=False):
    text = (text or "").strip()
    if not text:
        raise ValueError("전사문이 비어 있습니다.")
    conn = db.connect()
    _set_rec(conn, rid, transcript=text, status="전사완료", error="")
    conn.close()
    if chain:
        segment_after_transcript(rid)
    return {"ok": True}


def apply_segment(rid, text):
    data = gemini.extract_json(text) if isinstance(text, str) else text
    if isinstance(data, list):
        data = {"items": data}
    conn = db.connect()
    try:
        r = _recording(conn, rid)
        class_id = r["class_id"]
        if not class_id and data.get("class_hint"):
            class_id = guess_class(conn, data["class_hint"])
            if class_id:
                conn.execute("UPDATE recordings SET class_id=? WHERE id=?", (class_id, rid))
        students = _students(conn, class_id)
        everyone = _term_students(conn)   # 반이 없거나 다른 반 학생일 때 찾아볼 명단
        prefer = _preferrer(r["kind"], (r["title"] or "") + " " + (r["transcript"] or "")[:300])
        date = (r["recorded_at"] or "")[:10] or datetime.date.today().isoformat()
        # 재분리 시 이전 결과 교체
        conn.execute("DELETE FROM notes WHERE recording_id=?", (rid,))
        conn.execute("DELETE FROM unmatched WHERE recording_id=?", (rid,))
        matched, unmatched = 0, 0
        found_classes = set()
        for it in data.get("items", []) or []:
            content = strip_class_words((it.get("observation") or it.get("content") or "").strip())
            if not content:
                continue
            st = match_student(students, it.get("number"), it.get("name"), prefer) if students else None
            if not st:
                # 학급 미지정이거나 명단에 없는 경우: 이번 학기 전체 명단에서 이름으로 (번호는 반마다 겹치므로 쓰지 않음)
                cands = everyone
                if students:
                    cands = [s for s in everyone if s["class_id"] != class_id]
                st = match_student(cands, None, it.get("name"), prefer)
                if st and not class_id:
                    found_classes.add(st["class_id"])
            if st:
                conn.execute("INSERT INTO notes(student_id, recording_id, date, kind, category, content, evidence) "
                             "VALUES (?,?,?,?,?,?,?)",
                             (st["id"], rid, date, r["kind"], it.get("category", ""), content,
                              (it.get("evidence") or "")[:400]))
                matched += 1
            else:
                conn.execute("INSERT INTO unmatched(recording_id, name_heard, content, evidence, category) "
                             "VALUES (?,?,?,?,?)",
                             (rid, "%s %s" % (it.get("number") or "", it.get("name") or ""), content,
                              (it.get("evidence") or "")[:400], it.get("category", "")))
                unmatched += 1
        for it in data.get("unmatched", []) or []:
            content = (it.get("observation") or it.get("content") or "").strip()
            if content:
                conn.execute("INSERT INTO unmatched(recording_id, name_heard, content, evidence, category) "
                             "VALUES (?,?,?,?,?)",
                             (rid, it.get("name_heard", ""), content, (it.get("evidence") or "")[:400],
                              it.get("category", "")))
                unmatched += 1
        status = "확인필요" if unmatched else "완료"
        if data.get("general") or (not matched and not unmatched):
            status = "일반메모"   # AI가 학생 관찰이 아니라고 본 녹음
        if not class_id and len(found_classes) == 1:   # 모두 한 반 학생이면 녹음에 그 반을 지정
            conn.execute("UPDATE recordings SET class_id=? WHERE id=?", (found_classes.pop(), rid))
        conn.execute("UPDATE recordings SET status=?, error='' WHERE id=?", (status, rid))
        conn.commit()
        return {"ok": True, "matched": matched, "unmatched": unmatched, "general": status == "일반메모"}
    finally:
        conn.close()


def apply_draft(student_id, text, area="subject", op="draft", engine="manual", t0=None):
    import quality
    conn = db.connect()
    st = db.row(conn, "SELECT * FROM students WHERE id=?", (student_id,))
    text = prompts.clean_draft(text, st)   # 날짜·'학생은'·학생 이름 같은 군더더기 걸러내기
    if not text:
        conn.close()
        raise ValueError("초안이 비어 있습니다.")
    if op == "shorten":
        event = "shorten"
    else:   # 이 학생 · 영역에 AI 초안이 이미 있으면 '다시 뽑기'
        event = "regen" if db.row(conn, "SELECT id FROM drafts WHERE student_id=? AND area=? AND ai_text<>''",
                                  (student_id, area)) else "draft"
    conn.execute("INSERT INTO drafts(student_id, content, bytes, area, ai_text, origin) VALUES (?,?,?,?,?,?)",
                 (student_id, text, db.neis_bytes(text), area, text, engine))
    quality.record(conn, event, engine, area, ms=(time.time() - t0) * 1000 if t0 else None)
    conn.commit()
    conn.close()
    return {"ok": True, "bytes": db.neis_bytes(text)}


# ───────────────────────── 이름 매칭 ─────────────────────────

def _lev(a, b):
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _aliases(s):
    return [a.strip() for a in re.split(r"[,，/]", s.get("aliases") or "") if a.strip()]


def _room(s):
    """같은 학년·반이면 담임/교과 명단이 달라도 같은 학생으로 본다."""
    if s.get("grade") is not None and s.get("class_no") is not None:
        return "%s-%s" % (s["grade"], s["class_no"])
    return "c%s" % s.get("class_id")


def _one(cands, prefer=None):
    """후보가 모두 같은 반(담임·교과 명단 중복)이면 한 명으로 — prefer 순서로 고름. 여러 반이면 None."""
    if not cands:
        return None
    if len({_room(s) for s in cands}) > 1:
        return None
    return sorted(cands, key=prefer)[0] if prefer else cands[0]


def _preferrer(kind, hint=""):
    """수업 녹음은 교과(말한 과목 우선), 상담은 담임 명단을 고른다."""
    want = "담임" if kind == "상담" else "교과"

    def key(s):
        r = 0
        if (s.get("ckind") or s.get("kind")) == want:
            r -= 2
        sub = s.get("subject") or ""
        if sub and sub in (hint or ""):
            r -= 3
        return r
    return key


def match_student(students, number, name, prefer=None):
    name = re.sub(r"\s+", "", str(name or ""))
    # AI가 '3번 김민수', '김민수 학생', '2-3 김민수', '김민수(3번)'처럼 돌려줘도 이름만 남김
    name = re.sub(r"^\d+\s*-\s*\d+", "", name)
    name = re.sub(r"^\d+번?", "", name)
    name = re.sub(r"\(.*?\)|학생$|군$|양$", "", name)
    try:
        number = int(str(number).replace("번", "").strip()) if number not in (None, "") else None
    except ValueError:
        number = None
    if not students:
        return None
    if name:
        exact = [s for s in students if s["name"] == name]
        if exact and number is not None:
            for s in exact:
                if s["number"] == number:
                    return s
        if _one(exact, prefer):
            return _one(exact, prefer)
        al = [s for s in students if name in _aliases(s)]
        if _one(al, prefer):
            return _one(al, prefer)
        # 성 빼고 부른 이름 ("민수", "민수가", "서연이")
        for g in (name, re.sub(r"(이가|이는|이도|이랑|이를|이|가|는|도|랑|를|야|아)$", "", name)):
            given = [s for s in students if len(s["name"]) >= 3 and s["name"][1:] == g]
            if _one(given, prefer):
                return _one(given, prefer)
    if number is not None:
        by_num = [s for s in students if s["number"] == number]
        if by_num and (not name or _lev(by_num[0]["name"], name) <= 1):
            return by_num[0]
    if name:
        # 받아쓰기가 한 글자 틀린 이름 ("박지운" → 박지훈) — 성이 같을 때만
        near = [s for s in students if _lev(s["name"], name) <= 1 and s["name"][:1] == name[:1]]
        if _one(near, prefer):
            return _one(near, prefer)
    return None


# ───────────────────────── 반·번호 말 정리 ─────────────────────────
_KNUM = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}


def _knum(w):
    """'육' → 6, '십이' → 12, '12' → 12."""
    if w.isdigit():
        return int(w)
    val, cur = 0, 0
    for ch in w:
        if ch == "십":
            val += (cur or 1) * 10
            cur = 0
        elif ch in _KNUM:
            cur = _KNUM[ch]
    return val + cur


_KN = r"(?:십?[일이삼사오육칠팔구]|십|\d{1,2})"


def normalize_class_words(text):
    """받아쓰기가 글자로 적은 반·번호를 숫자로: '이학년 육반' → '2학년 6반', '육반' → '6반', '삼번' → '3번'."""
    t = text or ""
    t = re.sub(r"(?<![가-힣])([일이삼사오육]|\d)\s*학년\s*(%s)\s*반" % _KN,
               lambda m: "%d학년 %d반" % (_knum(m.group(1)), _knum(m.group(2))), t)
    t = re.sub(r"(?<![가-힣\d])(%s)\s*반(?![가-힣])" % _KN, lambda m: "%d반" % _knum(m.group(1)), t)
    t = re.sub(r"(?<![가-힣\d])(%s)\s*번(?=[\s,.]|$)" % _KN, lambda m: "%d번" % _knum(m.group(1)), t)
    return t


def strip_class_words(text):
    """관찰기록·초안에 들어간 '2학년 6반', '6반', '3번' 같은 말을 뺀다 (기록 내용만 남기기)."""
    t = normalize_class_words(text)
    t = re.sub(r"(\d\s*학년\s*)?\d{1,2}\s*반\s*(\d{1,2}\s*번\s*)?", "", t)
    t = re.sub(r"(^|(?<=[\s.,]))\d{1,2}\s*번\s+", "", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def guess_class(conn, hint):
    hint = normalize_class_words(hint)
    m = re.search(r"(\d)\s*학년\s*(\d{1,2})\s*반", hint or "") or re.search(r"(?<!\d)(\d)\s*-\s*(\d{1,2})(?!\d)", hint or "")
    if not m:
        # '6반'만 말했을 때: 이번 학기에 6반이 하나뿐이면 그 반
        only = re.search(r"(?<![\d학년\s])\s?(\d{1,2})반", hint or "") or re.search(r"(?:^|\s)(\d{1,2})반", hint or "")
        if only:
            rows = [c for c in _term_classes(conn) if c.get("class_no") == int(only.group(1))]
            if len({c["grade"] for c in rows}) == 1:
                return sorted(rows, key=lambda c: c.get("kind") != "교과")[0]["id"]
        return None
    g, c = int(m.group(1)), int(m.group(2))
    r = db.row(conn, "SELECT id FROM classes WHERE grade=? AND class_no=? ORDER BY year DESC, semester DESC, id DESC",
               (g, c))
    return r["id"] if r else None


def guess_class_by_time(conn, recorded_at, settings=None):
    """시간표(요일·교시 → 학급)로 녹음 시각의 학급을 찾는다. 수업 끝나고 15분까지는 그 수업으로 본다."""
    settings = settings or db.get_settings(conn)
    try:
        table = json.loads(settings.get("timetable") or "{}")
        dt = datetime.datetime.strptime((recorded_at or "")[:16], "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return None
    if not table:
        return None
    minute = dt.hour * 60 + dt.minute
    for i, line in enumerate((settings.get("period_times") or "").splitlines(), 1):
        m = re.match(r"\s*(\d{1,2}):(\d{2})\s*[-~]\s*(\d{1,2}):(\d{2})", line)
        if not m:
            continue
        start = int(m.group(1)) * 60 + int(m.group(2))
        end = int(m.group(3)) * 60 + int(m.group(4))
        if start - 5 <= minute <= end + 15:
            cid = table.get("%d-%d" % (dt.isoweekday(), i))
            if cid and db.row(conn, "SELECT id FROM classes WHERE id=?", (int(cid),)):
                return int(cid)
    return None


def class_by_period(conn, recorded_at, period, settings=None):
    """휴대폰에서 고른 교시 + 녹음한 요일 → 시간표의 학급."""
    settings = settings or db.get_settings(conn)
    try:
        table = json.loads(settings.get("timetable") or "{}")
        dt = datetime.datetime.strptime((recorded_at or "")[:16], "%Y-%m-%d %H:%M")
        cid = table.get("%d-%d" % (dt.isoweekday(), int(period)))
    except (ValueError, TypeError):
        return None
    if cid and db.row(conn, "SELECT id FROM classes WHERE id=?", (int(cid),)):
        return int(cid)
    return None


def auto_process(rid, force=False):
    """새로 들어온 기록을 설정에 맞게 자동 처리. API 키가 없으면 AI 없이 이름 기준으로 나눈다."""
    conn = db.connect()
    r = db.row(conn, "SELECT id, class_id, transcript, audio_path FROM recordings WHERE id=?", (rid,))
    settings = db.get_settings(conn)
    conn.close()
    if not r or (not force and settings.get("auto_process") != "1"):
        return
    has_text = bool((r["transcript"] or "").strip())
    if not has_text and r["audio_path"]:
        if use_whisper(settings):
            import whisper
            if whisper.available():
                enqueue("transcribe", {"recording_id": rid, "chain": True}, "내 맥에서 받아쓰기 #%d" % rid)
            else:
                conn = db.connect()
                _set_rec(conn, rid, status="보관됨", error="받아쓰기 모델을 내려받으면 자동으로 글자로 바뀝니다 (설정 → 받아쓰기 엔진)")
                conn.close()
        elif settings.get("mode") == "api" and settings.get("gemini_api_key"):   # 녹음 받아쓰기는 Gemini만
            enqueue("transcribe", {"recording_id": rid, "chain": True}, "전사 #%d" % rid)
    elif has_text:
        # 휴대폰 쓰담이 받아쓴 글이 실려 온 녹음: 내 맥 Whisper가 있으면 더 정확하게 다시 받아쓴다
        # (폰에서 나눈 학생별 기록은 그대로 두고 연결만 함 — segment_after_transcript)
        conn = db.connect()
        rec = db.row(conn, "SELECT original_name FROM recordings WHERE id=?", (rid,))
        conn.close()
        from_phone = bool(rec and (rec.get("original_name") or "").startswith("쓰담 ") and r["audio_path"])
        if from_phone and settings.get("rewhisper_phone", "1") == "1" and use_whisper(settings):
            import whisper
            if whisper.available():
                enqueue("transcribe", {"recording_id": rid, "chain": True}, "내 맥에서 다시 받아쓰기 #%d" % rid)
                return
        segment_after_transcript(rid, settings)


def process_pending():
    """받아쓰기 모델 설치 직후: 글자로 안 바뀐 채 기다리던 녹음을 모두 처리."""
    conn = db.connect()
    ids = [r["id"] for r in db.rows(conn, "SELECT id FROM recordings WHERE audio_path IS NOT NULL "
                                          "AND (transcript IS NULL OR transcript='') AND status IN ('보관됨','오류')")]
    conn.close()
    for rid in ids:
        auto_process(rid, force=True)
    return len(ids)


def ai_ready(settings):
    """외부 AI API(Gemini · ChatGPT · Claude 중 고른 것)의 키가 있는지."""
    import cloudai
    return settings.get("mode") == "api" and bool(cloudai.key_of(settings))


def use_whisper(settings):
    """받아쓰기 엔진: 기본은 내 맥(Whisper). 설정에서 Gemini를 고른 경우와 Intel 맥만 Gemini."""
    import whisper
    engine = settings.get("stt_engine") or "whisper"
    if engine == "gemini" or not whisper.supported():  # Intel 맥은 Whisper 불가 → Gemini
        return False
    return True  # 기본: 녹음이 맥 밖으로 나가지 않는 내 맥 받아쓰기


def segment_after_transcript(rid, settings=None):
    """전사문이 생긴 뒤: Gemini 키가 있으면 AI 분리, 없으면 이름 기준 규칙 분리."""
    settings = settings or db.get_settings()
    # 폰에서 이미 학생별로 나눠 보낸 녹음이면 그 기록에 연결만 한다 (같은 내용이 두 번 생기지 않게)
    conn = db.connect()
    try:
        r = db.row(conn, "SELECT original_name FROM recordings WHERE id=?", (rid,))
        import sync_text
        if r and sync_text.linked_notes(conn, r.get("original_name")):
            conn.execute("UPDATE notes SET recording_id=? WHERE source=? AND recording_id IS NULL", (rid, r["original_name"]))
            conn.execute("UPDATE recordings SET status='확인필요', error='' WHERE id=?", (rid,))
            conn.commit()
            return
    finally:
        conn.close()
    # 녹음 중 휴대폰에서 학생 이름표를 눌렀으면 그 시점대로 나눈다 (선생님이 직접 고른 것이 가장 정확)
    try:
        if marker_segment(rid):
            return
    except Exception as e:  # noqa — 실패하면 평소처럼 이름 기준으로
        print("[marker_segment] 실패, 평소대로 나눔:", e)
    eng = seg_engine(settings)
    if eng == "gemini":
        enqueue("segment", {"recording_id": rid}, "학생별 분리 #%d" % rid)
    elif eng in ("apple", "local"):
        enqueue("segment_local", {"recording_id": rid, "engine": eng},
                "%s 학생별 분리 #%d" % ("기기 안 AI" if eng == "apple" else "내 맥 AI", rid))
    else:
        try:
            rule_segment(rid)
        except ValueError:
            pass  # 학급 미지정 등 → 녹음함에서 사용자가 처리


# ───────────────────────── 휴대폰 이름표 기준 분리 ─────────────────────────

MARK_SLACK = 1.5   # 이름표는 말을 꺼내면서 누르므로, 누르기 조금 전에 시작한 문장부터 그 학생 몫


def _timed_pieces(transcript, duration=0):
    """전사문 → [(초, 문장)]. Whisper 글은 줄마다 [분:초]가 있고, 없으면(폰 받아쓰기) 글자 위치로 시각을 어림한다."""
    out = []
    for m in re.finditer(r"^\[(\d{1,3}):(\d{2})(?::(\d{2}))?\]\s*(.*)$", transcript or "", re.M):
        a, b, c = int(m.group(1)), int(m.group(2)), m.group(3)
        t = a * 3600 + b * 60 + int(c) if c else a * 60 + b
        if m.group(4).strip():
            out.append((t, m.group(4).strip()))
    if out:
        return out
    text = re.sub(r"\s+", " ", transcript or "").strip()
    if not text or not duration:
        return []
    return [(duration * a / len(text), text[a:b].strip()) for a, b in _sentences(text) if text[a:b].strip()]


def marker_segment(rid):
    """녹음하면서 휴대폰에서 누른 학생 이름표대로 나눈다: 이름표를 누른 때부터 다음 이름표까지가 그 학생 이야기.
    이름표가 없으면 False (평소처럼 이름 기준으로 나눔)."""
    conn = db.connect()
    try:
        r = db.row(conn, "SELECT * FROM recordings WHERE id=?", (rid,))
        try:
            meta = json.loads((r or {}).get("phone_meta") or "{}")
        except ValueError:
            return False
        studs = {}
        for m in meta.get("markers") or []:
            uid = m.get("student_uid")
            if uid and uid not in studs:
                s = db.row(conn, "SELECT * FROM students WHERE uid=?", (uid,))
                if s:
                    studs[uid] = s
        marks = sorted((m for m in meta.get("markers") or [] if m.get("student_uid") in studs), key=lambda m: m["t"])
        pieces = _timed_pieces(r["transcript"], meta.get("duration") or 0) if marks else []
        if not pieces:
            return False
        if not r["class_id"]:
            conn.execute("UPDATE recordings SET class_id=? WHERE id=?", (studs[marks[0]["student_uid"]]["class_id"], rid))
        long_rec = sum(len(p[1]) for p in pieces) > LONG_RECORDING_CHARS
        lead, blocks = [], []   # blocks: [학생 uid, [문장], 시작 초]
        for t, sent in pieces:
            k = -1
            for i, m in enumerate(marks):
                if t >= m["t"] - MARK_SLACK:
                    k = i
                else:
                    break
            if k < 0:
                lead.append(sent)
                continue
            uid = marks[k]["student_uid"]
            if blocks and blocks[-1][0] == uid:
                blocks[-1][1].append(sent)
            else:
                blocks.append([uid, [sent], marks[k]["t"]])
        stars = [m["t"] for m in meta.get("markers") or [] if m.get("star")]
        date = (r["recorded_at"] or "")[:10] or datetime.date.today().isoformat()
        conn.execute("DELETE FROM notes WHERE recording_id=?", (rid,))
        conn.execute("DELETE FROM unmatched WHERE recording_id=?", (rid,))
        count = 0
        for i, (uid, sents, start) in enumerate(blocks):
            if long_rec:   # 한 교시 녹음: 이름표 뒤에 이어지는 짧은 지도 말("앉아요")은 빼고
                sents = [s for s in sents if not (len(s) < 30 and _is_talk(s))]
            chunk = strip_class_words(re.sub(r"\s+", " ", " ".join(sents)).strip())
            if len(chunk) < 4:
                continue
            end = blocks[i + 1][2] if i + 1 < len(blocks) else float("inf")
            starred = any(start - MARK_SLACK <= st < end for st in stars)
            conn.execute("INSERT INTO notes(student_id, recording_id, date, kind, category, content, evidence) "
                         "VALUES (?,?,?,?,?,?,?)",
                         (studs[uid]["id"], rid, date, r["kind"], "기타", chunk[:1500],
                          "⭐ 녹음하면서 중요 표시한 부분" if starred else ""))
            count += 1
        rest = re.sub(r"\s+", " ", " ".join(lead)).strip()
        unmatched = 0
        if len(rest) >= 10 and not long_rec:
            conn.execute("INSERT INTO unmatched(recording_id, name_heard, content, evidence, category) VALUES (?,?,?,?,?)",
                         (rid, "이름표 누르기 전", rest[:1200], "", "기타"))
            unmatched = 1
        conn.execute("UPDATE recordings SET status='확인필요', error='' WHERE id=?", (rid,))
        conn.commit()
        return {"ok": True, "matched": count, "unmatched": unmatched, "by": "markers"}
    finally:
        conn.close()


# ───────────────────────── 규칙 기반 분리 (AI 없이) ─────────────────────────

def _name_hits(conn, rid):
    """전사문에서 학생 이름(성 뺀 이름·별칭·한 글자 틀린 이름·N번)이 나온 자리를 찾는다.
    돌려주는 값: (녹음, 정리된 글, [(시작, 끝, 학생)…] 위치순)"""
    r = _recording(conn, rid)
    if not r["class_id"]:
        cid = guess_class(conn, (r["title"] or "") + " " + (r["transcript"] or "")[:300])
        if cid:
            conn.execute("UPDATE recordings SET class_id=? WHERE id=?", (cid, rid))
            r["class_id"] = cid
    students = _students(conn, r["class_id"]) or _term_students(conn)
    if not students:
        raise ValueError("학생 명단이 있어야 분리할 수 있습니다. 학급을 만들고 명단을 넣어 주세요.")
    text = re.sub(r"\[\d{1,2}:\d{2}(?::\d{2})?\]", " ", normalize_class_words(r["transcript"] or ""))
    text = re.sub(r"(교사|선생님|학생)\s*:", " ", text)
    # 학생별 검색어 (긴 것 우선)
    keys = []
    for s in students:
        names = {s["name"]} | set(_aliases(s))
        if len(s["name"]) >= 3:
            names.add(s["name"][1:])
        for n in names:
            if len(n) >= 2:
                keys.append((n, s))
    # 같은 반의 담임·교과 명단에 같은 학생이 두 번 있으면 녹음 종류(수업→교과, 상담→담임)에 맞는 쪽 하나만
    prefer = _preferrer(r["kind"], (r["title"] or "") + " " + text[:300])
    by_key = {}
    for n, s in keys:
        by_key.setdefault(n, []).append(s)
    keys = []
    for n, cands in by_key.items():
        pick = _one(cands, prefer)
        if pick:
            keys.append((n, pick))
        else:  # 다른 반에 같은 이름 → 말투상 가장 맞는 반으로 담되 어느 반인지는 선생님이 확인
            keys.append((n, sorted(cands, key=prefer)[0]))
    keys.sort(key=lambda x: -len(x[0]))
    hits = []
    for n, s in keys:
        # 세 글자 이상 이름은 받아쓰기가 글자 사이에 넣은 띄어쓰기도 허용 ("샘플 준이" → 샘플준)
        pat = r"\s?".join(re.escape(ch) for ch in n) if len(n) >= 3 else re.escape(n)
        for m in re.finditer(pat, text):
            if any(h[0] <= m.start() < h[1] for h in hits):
                continue
            hits.append((m.start(), m.end(), s))
    # 받아쓰기가 이름을 한 글자 틀리게 적은 경우 ("박지운" → 박지훈): 성이 같은 3글자 이름 하나에만 가까우면
    full = {}
    for n, s in keys:
        if len(n) == 3 and n == s["name"]:
            full[n] = s
    for m in re.finditer(r"[가-힣]{3,6}", text):
        if any(h[0] <= m.start() < h[1] for h in hits):
            continue
        core = m.group(0)[:3]
        if core in full:
            continue
        near = [s for n, s in full.items() if n[0] == core[0] and _lev(n, core) == 1]
        if len(near) == 1:
            hits.append((m.start(), m.start() + 3, near[0]))
    for m in re.finditer(r"(?:^|[\s.,])(\d{1,2})\s*번(?=[\s,.]|$)", text):
        num = int(m.group(1))
        st = [s for s in students if s["number"] == num]
        pos = m.start(1)
        if st and not any(h[0] <= pos < h[1] for h in hits):
            hits.append((pos, m.end(), st[0]))
    hits.sort(key=lambda h: h[0])
    return r, text, hits


def rule_segment(rid):
    """전사문에서 학생 이름이 언급된 지점을 기준으로 내용을 나눈다."""
    conn = db.connect()
    try:
        r, text, hits = _name_hits(conn, rid)
        if not hits:   # 학생 이름이 하나도 없음 → 회의·개인 메모 같은 일반 녹음: 학생 기록에 넣지 않음
            conn.execute("DELETE FROM notes WHERE recording_id=?", (rid,))
            conn.execute("DELETE FROM unmatched WHERE recording_id=?", (rid,))
            conn.execute("UPDATE recordings SET status='일반메모', error='' WHERE id=?", (rid,))
            conn.commit()
            return {"ok": True, "matched": 0, "unmatched": 0, "general": True}
        # 각 언급이 포함된 문장의 시작점부터 다음 언급 문장 직전까지를 그 학생 몫으로 본다
        starts = []
        for start, _end, _s in hits:
            st = _sentence_start(text, start)
            if starts and st <= starts[-1]:
                st = start  # 같은 문장에 두 학생이 나오면 이름 위치에서 자름
            starts.append(st)
        # 한 교시를 통째로 녹음한 긴 녹음: 이름 사이에 수업 설명이 길게 끼므로
        # 이름이 나온 문장 + 뒤로 몇 문장만 그 학생 몫으로 (수업 설명이 학생 기록에 붙지 않게)
        long_rec = len(text) > LONG_RECORDING_CHARS
        blocks = []  # [학생, 시작, 끝]
        for i, (_start, _end, s) in enumerate(hits):
            stop = starts[i + 1] if i + 1 < len(hits) else len(text)
            if long_rec:
                stop = min(stop, _follow_end(text, starts[i]))
            if blocks and blocks[-1][0]["id"] == s["id"]:
                blocks[-1][2] = stop  # 연속된 같은 학생 언급은 합치기
            else:
                blocks.append([s, starts[i], stop])
        date = (r["recorded_at"] or "")[:10] or datetime.date.today().isoformat()
        conn.execute("DELETE FROM notes WHERE recording_id=?", (rid,))
        conn.execute("DELETE FROM unmatched WHERE recording_id=?", (rid,))
        count = 0
        for s, a, b in blocks:
            chunk = strip_class_words(re.sub(r"\s+", " ", text[a:b]).strip())
            if len(chunk) < 6:
                continue
            if long_rec and len(chunk) < 30 and _is_talk(chunk):
                continue        # 긴 수업 녹음 속 "OO 앉아요" 같은 지도 말은 기록으로 남기지 않음
            conn.execute("INSERT INTO notes(student_id, recording_id, date, kind, category, content, evidence) "
                         "VALUES (?,?,?,?,?,?,?)",
                         (s["id"], rid, date, r["kind"], "기타", chunk[:1200], ""))
            count += 1
        conn.execute("UPDATE recordings SET status='확인필요', error='' WHERE id=?", (rid,))
        conn.commit()
        return {"ok": True, "matched": count, "unmatched": 0}
    finally:
        conn.close()


LONG_RECORDING_CHARS = 2500   # 대략 10분 넘게 말한 녹음
FOLLOW_SENTENCES, FOLLOW_CHARS = 3, 300
# 학생들에게 하는 말(수업 설명 · 지도)은 대개 해요체로 끝나고, 관찰 메모는 '~함 · ~임 · ~음'으로 끝남
TALK_END = re.compile(r"(요|죠|까|세요|자|니다|니까|래|게)[.?!~…\s]*$")


def _is_talk(sentence):
    return bool(TALK_END.search(sentence.strip()))


def _follow_end(text, start):
    """start 문장(이름이 나온 문장)과 그 뒤 FOLLOW_SENTENCES 문장까지의 끝 — 단, 이름 문장 뒤로 FOLLOW_CHARS 넘지 않게."""
    spans = [(a, b) for a, b in _sentences(text[start:])]
    if not spans:
        return len(text)
    first_end = start + spans[0][1]
    end = first_end
    for a, b in spans[1:1 + FOLLOW_SENTENCES]:
        if start + b - first_end > FOLLOW_CHARS or _is_talk(text[start + a:start + b]):
            break       # 학생들에게 하는 말(수업 설명)이 나오면 거기서 끊음
        end = start + b
    return end


def _sentences(text):
    """(시작, 끝) 문장 구간들 — 마침표·물음표·느낌표·줄바꿈 기준."""
    out, a = [], 0
    for m in re.finditer(r"[.?!。\n]+", text):
        if text[a:m.end()].strip():
            out.append((a, m.end()))
        a = m.end()
    if text[a:].strip():
        out.append((a, len(text)))
    return out


def local_segment(rid, engine, settings=None):
    """내 맥 AI(기기 안 AI · Ollama · LM Studio)로 학생별 분리.
    이름이 나온 문장은 규칙으로 정하고, 이름 없이 이어지는 문장만 AI가 '이 녹음에 이름이 나온 학생' 중에서 고른다."""
    import localai
    settings = settings or db.get_settings()
    conn = db.connect()
    try:
        _set_rec(conn, rid, status="분리중", error="")
        r, text, hits = _name_hits(conn, rid)
        if not hits:
            conn.close()
            return rule_segment(rid)
        spans = _sentences(text)
        people, idx = [], {}
        for _a, _b, st in hits:
            if st["id"] not in idx:
                idx[st["id"]] = len(people) + 1
                people.append(st)
        in_sent = []   # 문장마다 이름이 나온 학생 번호들
        for a, b in spans:
            in_sent.append(sorted({idx[st["id"]] for h0, _h1, st in hits if a <= h0 < b}))
        known = {i: ks[0] for i, ks in enumerate(in_sent) if len(ks) == 1}
        sentences = [re.sub(r"\s+", " ", text[a:b]).strip() for a, b in spans]
        try:
            owner = localai.owners(engine, settings, sentences, [p["name"] for p in people], known)
        except Exception as e:  # noqa — AI가 안 되면 이름 기준으로
            print("[local_segment] AI 실패, 이름 기준으로 나눔:", e)
            conn.close()
            return rule_segment(rid)
        final = []
        for i, ks in enumerate(in_sent):
            if len(ks) == 1:
                final.append(ks[0])                                  # 이름이 하나 나온 문장은 그 학생
            elif ks:
                final.append(owner[i] if owner[i] in ks else ks[0])  # 여러 명이면 AI가 고른 쪽(그중에서)
            else:
                final.append(owner[i])                               # 이름 없는 문장은 AI (0 = 반 전체·모름)
        date = (r["recorded_at"] or "")[:10] or datetime.date.today().isoformat()
        conn.execute("DELETE FROM notes WHERE recording_id=?", (rid,))
        conn.execute("DELETE FROM unmatched WHERE recording_id=?", (rid,))
        groups, leftover = [], []
        for i, who in enumerate(final):
            if who <= 0:
                leftover.append(sentences[i])
                continue
            if groups and groups[-1][0] == who:
                groups[-1][1].append(sentences[i])
            else:
                groups.append([who, [sentences[i]]])
        count = 0
        for who, sents in groups:
            chunk = strip_class_words(" ".join(sents).strip())
            if len(chunk) < 6:
                continue
            conn.execute("INSERT INTO notes(student_id, recording_id, date, kind, category, content, evidence) "
                         "VALUES (?,?,?,?,?,?,?)",
                         (people[who - 1]["id"], rid, date, r["kind"], "기타", chunk[:1200], ""))
            count += 1
        rest = " ".join(leftover).strip()
        unmatched = 0
        if len(rest) >= 10:
            conn.execute("INSERT INTO unmatched(recording_id, name_heard, content, evidence, category) VALUES (?,?,?,?,?)",
                         (rid, "반 전체·이름 없음", rest[:1200], "", "기타"))
            unmatched = 1
        conn.execute("UPDATE recordings SET status='확인필요', error='' WHERE id=?", (rid,))
        conn.commit()
        return {"ok": True, "matched": count, "unmatched": unmatched}
    finally:
        try:
            conn.close()
        except Exception:  # noqa
            pass


def seg_engine(settings):
    """학생별 분리 엔진: gemini | local(Ollama·LM Studio) | apple(기기 안 AI) | rules(이름 기준).
    자동이면 Gemini 키 → 내 맥 AI 앱 → 기기 안 AI → 이름 기준 순."""
    import localai
    choice = settings.get("seg_engine") or "auto"
    if choice == "gemini":
        return "gemini" if ai_ready(settings) else "rules"
    if choice == "local":
        return "local" if localai.local_configured(settings) else "rules"
    if choice == "apple":
        return "apple" if localai.apple_ready() else "rules"
    if choice == "rules":
        return "rules"
    if ai_ready(settings):
        return "gemini"
    if localai.local_configured(settings):
        return "local"
    if localai.apple_ready():
        return "apple"
    return "rules"


def draft_engine(settings):
    """세특 초안 엔진: Gemini 키가 있으면 Gemini, 없으면 내 맥 AI 앱(설정한 경우). 기기 안 AI는 초안엔 작아서 안 씀."""
    import localai
    if settings.get("ai_choice") == "manual":
        return None              # 'AI 없이'를 골랐으면 늘 프롬프트 복사
    local = settings.get("draft_local", "1") == "1" and localai.local_configured(settings)
    if local and settings.get("local_ai_url") == "builtin" and settings.get("local_ai_model") in localai.LIGHT_MODELS \
            and settings.get("draft_light_ok") != "1":
        local = False            # 가벼운 모델은 초안에서 말을 지어내기 쉬워서 기본은 프롬프트 복사
    if local and settings.get("ai_choice") in ("builtin", "external"):
        return "local"           # 쓰담 AI 모델을 골랐으면 키가 있어도 맥 안에서
    if ai_ready(settings):
        return "gemini"
    if local:
        return "local"
    return None


def _sentence_start(text, pos):
    i = pos
    while i > 0 and text[i - 1] not in ".?!\n。":
        i -= 1
        if pos - i > 40:  # 너무 멀리 거슬러 가지 않음
            return pos
    return i


# ───────────────────────── 작업 큐 ─────────────────────────

def enqueue(op, params, label=""):
    conn = db.connect()
    cur = conn.execute("INSERT INTO jobs(op, params, label) VALUES (?,?,?)",
                       (op, json.dumps(params, ensure_ascii=False), label))
    jid = cur.lastrowid
    if op == "transcribe":
        conn.execute("UPDATE recordings SET status='대기중', error='' WHERE id=?", (params["recording_id"],))
    conn.commit()
    conn.close()
    _wake.set()
    return jid


def _set_job_msg(job_id, msg):
    if not job_id:
        return
    conn = db.connect()
    conn.execute("UPDATE jobs SET message=? WHERE id=?", (msg, job_id))
    conn.commit()
    conn.close()


def _run_whisper(params, job_id=None):
    import whisper
    rid = params["recording_id"]
    conn = db.connect()
    r = _recording(conn, rid)
    students = _students(conn, r["class_id"])
    _set_rec(conn, rid, status="전사중", error="")
    conn.close()
    if not r["audio_path"] or not os.path.exists(r["audio_path"]):
        raise ValueError("녹음 파일이 없습니다.")
    last = [-1]

    def progress(p):
        if p >= last[0] + 5:
            last[0] = p
            _set_job_msg(job_id, "내 맥에서 받아쓰는 중 %d%%" % p)
    text = whisper.transcribe(r["audio_path"], students, r["kind"], on_progress=progress)
    return apply_transcript(rid, text, params.get("chain"))


def _run_api(op, params, job_id=None):
    settings = db.get_settings()
    if op in ("draft", "shorten"):   # 초안 통계: 어느 엔진 · 걸린 시간 (숫자만)
        import quality
        params = dict(params, _engine=quality.engine_of(settings, params), _t0=time.time())
    if op == "transcribe" and use_whisper(settings):
        return _run_whisper(params, job_id)
    if op == "segment_local":
        return local_segment(params["recording_id"], params.get("engine") or "apple", settings)
    if op in ("draft", "shorten") and draft_engine(settings) == "local":
        import localai
        p = build_prompt(op, params)
        text = localai.generate("local", settings, p.get("system"), p["prompt"])
        if op == "draft":
            text = _expand_if_short(text, params, settings, lambda pr: localai.generate("local", settings, p.get("system"), pr))
        return apply(op, params, text)
    import cloudai
    p = build_prompt(op, params)
    if op == "transcribe":   # 녹음 파일 받아쓰기는 Gemini만 (고른 외부 AI와 상관없이 Gemini 키 필요)
        key = (settings.get("gemini_api_key") or "").strip()
        if not key:
            raise ValueError("Gemini API 키가 없습니다. 받아쓰기는 내 맥(Whisper)을 쓰거나 Gemini 키를 넣어 주세요.")
        model = settings.get("gemini_model") or "gemini-2.5-flash"

        def on_change(new_model):
            db.set_settings({"gemini_model": new_model})
        rid = params["recording_id"]
        conn = db.connect()
        _set_rec(conn, rid, status="전사중", error="")
        conn.close()
        path = p["audio_path"]
        if not path or not os.path.exists(path):
            raise ValueError("녹음 파일이 없습니다.")
        conv, mime, is_tmp = gemini.prepare_audio(path)
        name = None
        try:
            uri, mime2, name = gemini.upload_file(key, conv, mime, "rec-%d" % rid)
            text = gemini.generate(key, model, p["prompt"], file_uri=uri, file_mime=mime2,
                                   temperature=0.1, on_model_change=on_change)
        finally:
            if name:
                gemini.delete_file(key, name)
            if is_tmp:
                try:
                    os.remove(conv)
                    os.rmdir(os.path.dirname(conv))
                except OSError:
                    pass
        return apply(op, params, text)
    if op == "segment":
        conn = db.connect()
        _set_rec(conn, params["recording_id"], status="분리중", error="")
        conn.close()
    prov = cloudai.provider(settings)

    def on_model(new_model):
        db.set_settings({cloudai.PROVIDERS[prov]["model"]: new_model})

    try:
        # 쓰담 플러스: 정성 초안만 깊게 쓰는 AI, 나머지(분리 · 기본 초안 · 줄이기)는 가벼운 AI. 초안은 다시 뽑기 대비 캐시
        deep = op == "draft" and bool(params.get("deep"))
        text = cloudai.generate(settings, p["prompt"], system=p.get("system"), json_mode=p.get("json", False),
                                temperature=0.2 if op == "segment" else 0.6, on_model_change=on_model,
                                deep=deep, cache=op == "draft")
        if op == "draft":
            text = _expand_if_short(text, params, settings, lambda pr: cloudai.generate(
                settings, pr, system=p.get("system"), temperature=0.6, on_model_change=on_model, deep=deep))
    except cloudai.CloudError as e:
        raise ValueError(str(e))
    return apply(op, params, text)


def _expand_if_short(text, params, settings, gen):
    """초안이 목표 분량의 절반도 안 되면 한 번 더 — 사실은 그대로, 의미를 풀어 자세히."""
    if (params.get("area") or "subject") in prompts.OTHER_GUIDE:   # 문자 · 리포트는 짧아도 괜찮음
        return text
    conn = db.connect()
    try:
        area = params.get("area") or "subject"
        limit = db.area_limit(area, settings)
        t = db.row(conn, "SELECT bytes FROM student_targets WHERE student_id=? AND area=?", (params["student_id"], area))
        if t and t["bytes"]:
            limit = int(t["bytes"])
        st = db.row(conn, "SELECT * FROM students WHERE id=?", (params["student_id"],))
        notes = db.rows(conn, "SELECT content FROM notes WHERE student_id=? AND use_in_draft=1", (params["student_id"],))
    finally:
        conn.close()
    cur = db.neis_bytes(prompts.clean_draft(text, st))
    if cur >= limit * 0.55 or len(notes) < 3:   # 기록이 적으면 짧은 게 맞음 (늘리면 지어내게 됨)
        return text
    notes_text = "\n".join("- " + prompts.strip_names(strip_class_words(n["content"]), st) for n in notes[:20])
    try:
        longer = gen(prompts.expand(prompts.clean_draft(text, st), limit, cur, notes_text))
        return longer if db.neis_bytes(prompts.clean_draft(longer, st)) > cur else text
    except Exception:  # noqa
        return text


def _worker():
    while True:
        _wake.wait(5)
        _wake.clear()
        while True:
            conn = db.connect()
            job = db.row(conn, "SELECT * FROM jobs WHERE status='대기' ORDER BY id LIMIT 1")
            if not job:
                conn.close()
                break
            conn.execute("UPDATE jobs SET status='진행중' WHERE id=?", (job["id"],))
            conn.commit()
            conn.close()
            params = json.loads(job["params"] or "{}")
            status, msg = "완료", ""
            try:
                res = _run_api(job["op"], params, job["id"])
                if isinstance(res, dict) and res.get("general"):
                    msg = "학생 이야기가 없어 일반 메모로 표시"
                elif isinstance(res, dict) and "matched" in res:
                    msg = "배정 %d건, 미배정 %d건" % (res["matched"], res["unmatched"])
            except Exception as e:  # noqa
                status, msg = "실패", str(e)
                traceback.print_exc()
                if "recording_id" in params:
                    conn = db.connect()
                    _set_rec(conn, params["recording_id"], status="오류", error=msg[:500])
                    conn.close()
            conn = db.connect()
            conn.execute("UPDATE jobs SET status=?, message=?, finished_at=datetime('now','localtime') WHERE id=?",
                         (status, msg[:500], job["id"]))
            conn.commit()
            conn.close()


def start_worker():
    t = threading.Thread(target=_worker, daemon=True, name="ai-worker")
    t.start()
