# -*- coding: utf-8 -*-
"""쓰담 로컬 서버. 실행: python3 app/server.py"""
import datetime
import json
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db  # noqa: E402
import gemini  # noqa: E402
import localai  # noqa: E402
import pipeline  # noqa: E402
import platform_util  # noqa: E402
import prompts  # noqa: E402
import sheets  # noqa: E402
import sync_text  # noqa: E402
import telemetry  # noqa: E402
import relay  # noqa: E402
import trash  # noqa: E402
import update  # noqa: E402
import version  # noqa: E402
import watcher  # noqa: E402
import whisper  # noqa: E402

HOST, PORT = "127.0.0.1", int(os.environ.get("SETEUK_PORT", "8765"))
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
ALLOWED_HOSTS = {"127.0.0.1:%d" % PORT, "localhost:%d" % PORT}

ROUTES = []


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return deco


class ApiError(Exception):
    def __init__(self, msg, code=400):
        Exception.__init__(self, msg)
        self.code = code


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def open_in_finder(path, reveal=False):
    platform_util.open_path(path, reveal)


# ───────────────────────── 대시보드 ─────────────────────────

def term_range(year, sem):
    """학기 날짜 범위 [시작, 끝). 1학기 3~8월, 2학기 9월~이듬해 2월."""
    if sem == 1:
        return "%04d-03-01" % year, "%04d-09-01" % year
    return "%04d-09-01" % year, "%04d-03-01" % (year + 1)


def current_term(today=None):
    d = today or datetime.date.today()
    if 3 <= d.month <= 8:
        return d.year, 1
    return (d.year, 2) if d.month >= 9 else (d.year - 1, 2)


@route("GET", "/api/dashboard")
def dashboard(h, q, body):
    year, sem = _int(q.get("year")), _int(q.get("semester"))
    if year and sem in (1, 2):
        cf = "SELECT id FROM classes WHERE year=%d AND semester=%d" % (year, sem)
        t0, t1 = term_range(year, sem)
        rf = "(r.class_id IN (%s) OR (r.class_id IS NULL AND r.recorded_at >= '%s' AND r.recorded_at < '%s'))" % (cf, t0, t1)
    else:
        cf, t0, t1 = "SELECT id FROM classes", None, None
        rf = "1=1"
    sf = "SELECT id FROM students WHERE class_id IN (%s)" % cf
    conn = db.connect()
    try:
        one = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
        t = {
            "classes": one("SELECT COUNT(*) FROM classes WHERE id IN (%s)" % cf),
            "students": one("SELECT COUNT(*) FROM students WHERE class_id IN (%s)" % cf),
            "recordings": one("SELECT COUNT(*) FROM recordings r WHERE %s" % rf),
            "notes": one("SELECT COUNT(*) FROM notes WHERE student_id IN (%s)" % sf),
            "with_notes": one("SELECT COUNT(DISTINCT student_id) FROM notes WHERE student_id IN (%s)" % sf),
            "drafted": one("SELECT COUNT(DISTINCT student_id) FROM drafts WHERE student_id IN (%s)" % sf),
            "finalized": one("SELECT COUNT(DISTINCT student_id) FROM drafts WHERE status='확정' AND student_id IN (%s)" % sf),
            "pending_review": one("SELECT COUNT(*) FROM recordings r WHERE r.status IN ('확인필요','오류','보관됨') AND %s" % rf),
            "all_classes": one("SELECT COUNT(*) FROM classes"),
        }
        classes = db.rows(conn, """
            SELECT c.*,
              (SELECT COUNT(*) FROM students s WHERE s.class_id=c.id) AS students,
              (SELECT COUNT(DISTINCT n.student_id) FROM notes n JOIN students s ON s.id=n.student_id WHERE s.class_id=c.id) AS with_notes,
              (SELECT COUNT(*) FROM notes n JOIN students s ON s.id=n.student_id WHERE s.class_id=c.id) AS notes,
              (SELECT COUNT(DISTINCT d.student_id) FROM drafts d JOIN students s ON s.id=d.student_id WHERE s.class_id=c.id) AS drafted,
              (SELECT COUNT(DISTINCT d.student_id) FROM drafts d JOIN students s ON s.id=d.student_id WHERE s.class_id=c.id AND d.status='확정') AS finalized,
              (SELECT COUNT(*) FROM recordings r WHERE r.class_id=c.id) AS recordings
            FROM classes c WHERE c.id IN (%s) ORDER BY c.year DESC, c.semester DESC, c.grade, c.class_no""" % cf)
        for c in classes:
            c["label"] = db.class_label(c)
        today = datetime.date.today()
        if t1:
            end = datetime.date.fromisoformat(t1) - datetime.timedelta(days=1)
            today = min(today, end)  # 지난 학기는 그 학기 마지막 주까지
        start = (today - datetime.timedelta(weeks=11)).isoformat()
        weekly_raw = db.rows(conn, "SELECT date, kind, COUNT(*) AS n FROM notes WHERE date >= ? AND student_id IN (%s) "
                                   "GROUP BY date, kind" % sf, (start,))
        weeks = []
        monday = today - datetime.timedelta(days=today.weekday())
        for i in range(11, -1, -1):
            ws = monday - datetime.timedelta(weeks=i)
            weeks.append({"start": ws.isoformat(), "label": "%d/%d" % (ws.month, ws.day), "수업": 0, "상담": 0})
        for r in weekly_raw:
            try:
                d = datetime.date.fromisoformat(r["date"][:10])
            except (TypeError, ValueError):
                continue
            idx = 11 - (monday - (d - datetime.timedelta(days=d.weekday()))).days // 7
            if 0 <= idx < 12:
                key = "상담" if r["kind"] == "상담" else "수업"
                weeks[idx][key] += r["n"]
        needy = db.rows(conn, """
            SELECT s.id, s.number, s.name, c.grade, c.class_no, c.subject, c.kind,
                   (SELECT COUNT(*) FROM notes n WHERE n.student_id=s.id) AS notes,
                   (SELECT MAX(date) FROM notes n WHERE n.student_id=s.id) AS last_date
            FROM students s JOIN classes c ON c.id=s.class_id WHERE c.id IN (%s)
            ORDER BY notes ASC, last_date ASC, c.grade, c.class_no, s.number LIMIT 12""" % cf)
        for n in needy:
            n["label"] = db.class_label(n)
        categories = db.rows(conn, "SELECT COALESCE(NULLIF(category,''),'기타') AS category, COUNT(*) AS n "
                                   "FROM notes WHERE student_id IN (%s) GROUP BY 1 ORDER BY n DESC" % sf)
        recent = db.rows(conn, """SELECT r.id, r.title, r.kind, r.status, r.recorded_at, c.grade, c.class_no, c.subject, c.kind AS ckind,
                   (SELECT COUNT(*) FROM notes n WHERE n.recording_id=r.id) AS notes
                   FROM recordings r LEFT JOIN classes c ON c.id=r.class_id WHERE %s
                   ORDER BY r.recorded_at DESC, r.id DESC LIMIT 8""" % rf)
        for r in recent:
            r["label"] = db.class_label(dict(r, kind=r.get("ckind"))) if (r.get("grade") or r.get("subject")) else "학급 미지정"
        return {"totals": t, "classes": classes, "weeks": weeks, "needy": needy,
                "categories": categories, "recent": recent}
    finally:
        conn.close()


@route("GET", "/api/term")
def term_now(h, q, b):
    y, s = current_term()
    return {"year": y, "semester": s}


# ───────────────────────── 검색 ─────────────────────────

def _snippet(text, term, before=40, after=70):
    text = " ".join((text or "").split())
    i = text.lower().find(term.lower())
    if i < 0:
        return text[:before + after] + ("…" if len(text) > before + after else "")
    a, z = max(0, i - before), min(len(text), i + len(term) + after)
    return ("…" if a else "") + text[a:z] + ("…" if z < len(text) else "")


@route("GET", "/api/search")
def search(h, q, b):
    term = (q.get("q") or "").strip()[:80]
    out = {"q": term, "classes": [], "students": [], "notes": [], "recordings": []}
    if not term:
        return out
    like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    esc = " ESCAPE '\\'"
    conn = db.connect()
    try:
        cls = db.rows(conn, "SELECT c.*, (SELECT COUNT(*) FROM students s WHERE s.class_id=c.id) AS students FROM classes c "
                            "WHERE c.subject LIKE ?" + esc + " OR (CAST(c.grade AS TEXT) || '-' || CAST(c.class_no AS TEXT)) LIKE ?" + esc +
                            " ORDER BY c.year DESC, c.semester DESC, c.grade, c.class_no LIMIT 10", (like, like))
        for c in cls:
            c["label"] = db.class_label(c)
        out["classes"] = cls
        st = db.rows(conn, """SELECT s.id, s.number, s.name, s.aliases, c.id AS class_id, c.year, c.semester, c.grade, c.class_no,
                   c.subject, c.kind, (SELECT COUNT(*) FROM notes n WHERE n.student_id=s.id) AS notes
                   FROM students s JOIN classes c ON c.id=s.class_id
                   WHERE s.name LIKE ?""" + esc + " OR s.aliases LIKE ?" + esc + """
                   ORDER BY c.year DESC, c.semester DESC, c.grade, c.class_no, s.number LIMIT 20""", (like, like))
        for s in st:
            s["label"] = db.class_label(s)
        out["students"] = st
        notes = db.rows(conn, """SELECT n.id, n.student_id, n.date, n.kind AS nkind, n.category, n.content, n.evidence,
                   s.name, s.number, c.year, c.semester, c.grade, c.class_no, c.subject, c.kind
                   FROM notes n JOIN students s ON s.id=n.student_id JOIN classes c ON c.id=s.class_id
                   WHERE n.content LIKE ?""" + esc + " OR n.evidence LIKE ?" + esc + """
                   ORDER BY n.date DESC, n.id DESC LIMIT 30""", (like, like))
        for n in notes:
            n["label"] = db.class_label(n)
            n["snippet"] = _snippet(n["content"] if term.lower() in (n["content"] or "").lower() else n["evidence"], term)
            n.pop("evidence", None)
            n.pop("content", None)
        out["notes"] = notes
        recs = db.rows(conn, """SELECT r.id, r.title, r.kind AS rkind, r.recorded_at, r.status, r.transcript,
                   c.year, c.semester, c.grade, c.class_no, c.subject, c.kind
                   FROM recordings r LEFT JOIN classes c ON c.id=r.class_id
                   WHERE r.title LIKE ?""" + esc + " OR r.transcript LIKE ?" + esc + """
                   ORDER BY r.recorded_at DESC, r.id DESC LIMIT 15""", (like, like))
        for r in recs:
            r["label"] = db.class_label(r) if (r.get("grade") or r.get("subject")) else "학급 미지정"
            r["snippet"] = "" if term.lower() in (r["title"] or "").lower() else _snippet(r["transcript"], term)
            r.pop("transcript", None)
        out["recordings"] = recs
        return out
    finally:
        conn.close()


# ───────────────────────── 휴지통 ─────────────────────────

@route("GET", "/api/trash")
def trash_list(h, q, b):
    return trash.listing()


@route("POST", "/api/trash/restore")
def trash_restore(h, q, b):
    return trash.restore(int(b["id"]))


@route("POST", "/api/trash/delete")
def trash_delete(h, q, b):
    return {"ok": True, "deleted": trash.purge(trash_id=int(b["id"]))}


@route("POST", "/api/trash/empty")
def trash_empty(h, q, b):
    return {"ok": True, "deleted": trash.purge(everything=True)}


# ───────────────────────── 학급 / 학생 ─────────────────────────

@route("GET", "/api/classes")
def classes_list(h, q, body):
    conn = db.connect()
    cs = db.rows(conn, """SELECT c.*, (SELECT COUNT(*) FROM students s WHERE s.class_id=c.id) AS students,
                          (SELECT COUNT(*) FROM notes n JOIN students s ON s.id=n.student_id WHERE s.class_id=c.id) AS notes
                          FROM classes c ORDER BY c.year DESC, c.semester DESC, c.grade, c.class_no, c.subject""")
    conn.close()
    for c in cs:
        c["label"] = db.class_label(c)
    return {"classes": cs}


@route("POST", "/api/classes/save")
def classes_save(h, q, b):
    kind = b.get("kind") if b.get("kind") in db.CLASS_KINDS else "교과"
    vals = (_int(b.get("year"), datetime.date.today().year), _int(b.get("semester"), 1),
            _int(b.get("grade")), _int(b.get("class_no")), (b.get("subject") or "").strip(), kind)
    if kind in ("교과", "담임") and (not vals[2] or not vals[3]):
        raise ApiError("학년과 반을 입력하세요.")
    if kind in ("동아리", "기타") and not vals[4]:
        raise ApiError("%s 이름을 입력하세요." % ("동아리" if kind == "동아리" else "모둠"))
    conn = db.connect()
    if b.get("id"):
        conn.execute("UPDATE classes SET year=?, semester=?, grade=?, class_no=?, subject=?, kind=? WHERE id=?",
                     vals + (int(b["id"]),))
        cid = int(b["id"])
    else:
        cid = conn.execute("INSERT INTO classes(year, semester, grade, class_no, subject, kind) VALUES (?,?,?,?,?,?)",
                           vals).lastrowid
    conn.commit()
    conn.close()
    return {"ok": True, "id": cid}


@route("POST", "/api/classes/copy")
def classes_copy(h, q, b):
    """새 학기 준비: 학급 명단(번호·이름·별칭)을 다른 학기의 새 학급으로 복사. 관찰기록·초안은 복사하지 않음."""
    year, sem = _int(b.get("year")), _int(b.get("semester"))
    if not year or sem not in (1, 2):
        raise ApiError("옮길 학기를 고르세요.")
    items = b.get("items") or []
    if not items:
        raise ApiError("복사할 학급을 고르세요.")
    copy_memo = bool(b.get("memo"))
    conn = db.connect()
    made, added, ids = 0, 0, []
    try:
        for it in items:
            src = db.row(conn, "SELECT * FROM classes WHERE id=?", (int(it["id"]),))
            if not src:
                continue
            kind = it.get("kind") if it.get("kind") in db.CLASS_KINDS else (src.get("kind") or "교과")
            grade = _int(it.get("grade"), src.get("grade")) if "grade" in it else src.get("grade")
            class_no = _int(it.get("class_no"), src.get("class_no")) if "class_no" in it else src.get("class_no")
            subject = (it.get("subject") if "subject" in it else src.get("subject") or "") or ""
            subject = subject.strip()
            ex = db.row(conn, "SELECT id FROM classes WHERE year=? AND semester=? AND IFNULL(grade,0)=IFNULL(?,0) "
                              "AND IFNULL(class_no,0)=IFNULL(?,0) AND IFNULL(subject,'')=? AND IFNULL(kind,'교과')=?",
                        (year, sem, grade, class_no, subject, kind))
            if ex:
                cid = ex["id"]
            else:
                cid = conn.execute("INSERT INTO classes(year, semester, grade, class_no, subject, kind) VALUES (?,?,?,?,?,?)",
                                   (year, sem, grade, class_no, subject, kind)).lastrowid
                made += 1
            ids.append(cid)
            if cid == src["id"]:
                continue
            have = {r["name"] for r in db.rows(conn, "SELECT name FROM students WHERE class_id=?", (cid,))}
            for st in db.rows(conn, "SELECT * FROM students WHERE class_id=? ORDER BY number, id", (src["id"],)):
                if st["name"] in have:
                    continue
                conn.execute("INSERT INTO students(class_id, number, name, aliases, memo) VALUES (?,?,?,?,?)",
                             (cid, st["number"], st["name"], st.get("aliases") or "", (st.get("memo") or "") if copy_memo else ""))
                added += 1
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "classes": made, "students": added, "ids": ids}


@route("POST", "/api/classes/delete")
def classes_delete(h, q, b):
    conn = db.connect()
    tid = trash.move(conn, "class", b["id"])
    conn.commit()
    conn.close()
    return {"ok": True, "trash_id": tid}


@route("POST", "/api/classes/context")
def class_context_save(h, q, b):
    """초안에 함께 쓰는 수업 정보: 종목·단원 / 배우는 역량 / 교사의 철학 (학급·영역별)"""
    cid = _int(b.get("class_id"))
    if not cid:
        raise ApiError("학급을 골라 주세요.")
    area = b.get("area") or "subject"
    vals = tuple((b.get(k) or "").strip()[:2000] for k in ("topic", "competencies", "philosophy"))
    conn = db.connect()
    conn.execute("INSERT OR REPLACE INTO class_context(class_id, area, topic, competencies, philosophy) VALUES (?,?,?,?,?)",
                 (cid, area) + vals)
    conn.commit()
    conn.close()
    return {"ok": True}


@route("POST", "/api/students/target")
def student_target_save(h, q, b):
    """학생별 초안 분량(NEIS 바이트). 비우면 영역 기본 한도를 씀"""
    sid = _int(b.get("student_id"))
    if not sid:
        raise ApiError("학생을 골라 주세요.")
    area = b.get("area") or "subject"
    n = _int(b.get("bytes"))
    conn = db.connect()
    if n and n > 0:
        conn.execute("INSERT OR REPLACE INTO student_targets(student_id, area, bytes) VALUES (?,?,?)", (sid, area, min(n, 6000)))
    else:
        conn.execute("DELETE FROM student_targets WHERE student_id=? AND area=?", (sid, area))
    conn.commit()
    conn.close()
    return {"ok": True, "bytes": n if n and n > 0 else None}


@route("GET", r"/api/classes/(\d+)")
def class_detail(h, q, b, cid):
    conn = db.connect()
    try:
        c = db.row(conn, "SELECT * FROM classes WHERE id=?", (int(cid),))
        if not c:
            raise ApiError("학급이 없습니다.", 404)
        c["label"] = db.class_label(c)
        kind = c.get("kind") or "교과"
        areas = db.areas_for_kind(kind)
        area = q.get("area") if q.get("area") in [a["id"] for a in areas] else areas[0]["id"]
        settings = db.get_settings(conn)
        students = db.rows(conn, """
            SELECT s.*, (SELECT MAX(date) FROM notes n WHERE n.student_id=s.id) AS last_date
            FROM students s WHERE s.class_id=? ORDER BY s.number, s.name""", (int(cid),))
        for st in students:
            notes = db.rows(conn, "SELECT area FROM notes WHERE student_id=?", (st["id"],))
            st["notes"] = len(notes)
            st["area_notes"] = sum(1 for n in notes if db.note_area(n, kind) == area)
            d = db.row(conn, "SELECT status, bytes, content FROM drafts WHERE student_id=? AND area=? "
                             "ORDER BY (status='확정') DESC, id DESC LIMIT 1", (st["id"], area))
            st["draft_status"] = d["status"] if d else None
            st["draft_bytes"] = d["bytes"] if d else None
            st["draft"] = d["content"] if d else None
            t = db.row(conn, "SELECT bytes FROM student_targets WHERE student_id=? AND area=?", (st["id"], area))
            st["byte_target"] = t["bytes"] if t else None
        ctx = db.row(conn, "SELECT topic, competencies, philosophy FROM class_context WHERE class_id=? AND area=?",
                     (int(cid), area)) or {"topic": "", "competencies": "", "philosophy": ""}
        return {"class": c, "students": students, "areas": areas, "area": area, "context": ctx,
                "byte_limit": db.area_limit(area, settings)}
    finally:
        conn.close()


def parse_roster(text):
    """'1 김민수', '1\t김민수', '1번 김민수', '김민수' 형식을 모두 허용."""
    out = []
    auto_no = 1
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        cells = [x for x in re.split(r"[\t,]+|\s{2,}", line) if x.strip()]
        if len(cells) == 1:
            cells = line.split()
        num, name = None, None
        for cell in cells:
            cell = cell.strip()
            m = re.fullmatch(r"(\d{1,5})\s*번?", cell)  # 번호 또는 학번(20315)
            if m and num is None:
                num = int(m.group(1))
            elif re.fullmatch(r"[가-힣A-Za-z·\s]{2,20}", cell) and name is None:
                name = cell.replace(" ", "")
        if not name:
            continue
        if num is None:
            num = auto_no
        auto_no = num + 1
        out.append((num, name))
    return out


@route("POST", "/api/students/bulk")
def students_bulk(h, q, b):
    cid = int(b["class_id"])
    parsed = parse_roster(b.get("text", ""))
    if not parsed:
        raise ApiError("명단을 읽지 못했습니다. 한 줄에 '번호 이름' 형식으로 붙여넣으세요.")
    conn = db.connect()
    added, updated = 0, 0
    for num, name in parsed:
        ex = db.row(conn, "SELECT id FROM students WHERE class_id=? AND number=?", (cid, num))
        if ex:
            conn.execute("UPDATE students SET name=? WHERE id=?", (name, ex["id"]))
            updated += 1
        else:
            conn.execute("INSERT INTO students(class_id, number, name) VALUES (?,?,?)", (cid, num, name))
            added += 1
    conn.commit()
    conn.close()
    return {"ok": True, "added": added, "updated": updated}


@route("POST", "/api/students/save")
def students_save(h, q, b):
    name = (b.get("name") or "").strip()
    if not name:
        raise ApiError("이름을 입력하세요.")
    conn = db.connect()
    vals = (_int(b.get("number")), name, (b.get("aliases") or "").strip(), (b.get("memo") or "").strip())
    if b.get("id"):
        conn.execute("UPDATE students SET number=?, name=?, aliases=?, memo=? WHERE id=?", vals + (int(b["id"]),))
        sid = int(b["id"])
    else:
        sid = conn.execute("INSERT INTO students(number, name, aliases, memo, class_id) VALUES (?,?,?,?,?)",
                           vals + (int(b["class_id"]),)).lastrowid
    conn.commit()
    conn.close()
    return {"ok": True, "id": sid}


@route("POST", "/api/students/delete")
def students_delete(h, q, b):
    conn = db.connect()
    tid = trash.move(conn, "student", b["id"])
    conn.commit()
    conn.close()
    return {"ok": True, "trash_id": tid}


@route("GET", r"/api/students/(\d+)")
def student_detail(h, q, b, sid):
    conn = db.connect()
    try:
        s = db.row(conn, "SELECT * FROM students WHERE id=?", (int(sid),))
        if not s:
            raise ApiError("학생이 없습니다.", 404)
        c = db.row(conn, "SELECT * FROM classes WHERE id=?", (s["class_id"],))
        c["label"] = db.class_label(c)
        notes = db.rows(conn, """SELECT n.*, r.title AS rec_title, r.audio_path IS NOT NULL AS has_audio
                                 FROM notes n LEFT JOIN recordings r ON r.id=n.recording_id
                                 WHERE n.student_id=? ORDER BY n.date DESC, n.id DESC""", (int(sid),))
        drafts = db.rows(conn, "SELECT * FROM drafts WHERE student_id=? ORDER BY id DESC", (int(sid),))
        for d in drafts:
            d["forbidden"] = prompts.check_forbidden(d["content"])
        siblings = db.rows(conn, "SELECT id, number, name FROM students WHERE class_id=? ORDER BY number, name",
                           (s["class_id"],))
        kind = c.get("kind") or "교과"
        settings = db.get_settings(conn)
        targets = {t["area"]: t["bytes"] for t in db.rows(conn, "SELECT area, bytes FROM student_targets WHERE student_id=?", (int(sid),))}
        # 학생별 목표 분량이 있으면 그 영역 한도로 씀
        areas = [dict(a, limit=targets.get(a["id"]) or db.area_limit(a["id"], settings),
                      default_limit=db.area_limit(a["id"], settings), target=targets.get(a["id"]))
                 for a in db.areas_for_kind(kind)]
        for n in notes:
            n["area_eff"] = db.note_area(n, kind)
        return {"student": s, "class": c, "notes": notes, "drafts": drafts, "siblings": siblings,
                "areas": areas, "byte_limit": areas[0]["limit"]}
    finally:
        conn.close()


# ───────────────────────── 관찰기록 ─────────────────────────

@route("POST", "/api/notes/save")
def notes_save(h, q, b):
    content = (b.get("content") or "").strip()
    if not content:
        raise ApiError("내용을 입력하세요.")
    conn = db.connect()
    if b.get("id"):
        conn.execute("UPDATE notes SET student_id=COALESCE(?, student_id), date=?, kind=?, category=?, content=?, "
                     "use_in_draft=?, area=? WHERE id=?",
                     (_int(b.get("student_id")), b.get("date") or datetime.date.today().isoformat(),
                      b.get("kind") or "수업", b.get("category") or "", content,
                      1 if b.get("use_in_draft", True) else 0, b.get("area") or "", int(b["id"])))
    else:
        conn.execute("INSERT INTO notes(student_id, date, kind, category, content, recording_id, use_in_draft, area) "
                     "VALUES (?,?,?,?,?,?,1,?)",
                     (int(b["student_id"]), b.get("date") or datetime.date.today().isoformat(),
                      b.get("kind") or "수업", b.get("category") or "", content, _int(b.get("recording_id")),
                      b.get("area") or ""))
    conn.commit()
    conn.close()
    return {"ok": True}


@route("POST", "/api/notes/delete")
def notes_delete(h, q, b):
    conn = db.connect()
    tid = trash.move(conn, "note", b["id"])
    conn.commit()
    conn.close()
    return {"ok": True, "trash_id": tid}


# ───────────────────────── 녹음 ─────────────────────────

@route("GET", "/api/recordings")
def recordings_list(h, q, b):
    conn = db.connect()
    where, args = "", []
    if q.get("class_id"):
        where, args = "WHERE r.class_id=?", [int(q["class_id"])]
    recs = db.rows(conn, """SELECT r.id, r.class_id, r.kind, r.title, r.recorded_at, r.status, r.error, r.original_name,
               r.audio_path IS NOT NULL AS has_audio, length(r.transcript) AS transcript_len,
               c.grade, c.class_no, c.subject,
               (SELECT COUNT(*) FROM notes n WHERE n.recording_id=r.id) AS notes,
               (SELECT COUNT(*) FROM unmatched u WHERE u.recording_id=r.id) AS unmatched
               FROM recordings r LEFT JOIN classes c ON c.id=r.class_id %s
               ORDER BY r.recorded_at DESC, r.id DESC LIMIT 500""" % where, args)
    conn.close()
    for r in recs:
        r["label"] = db.class_label(r) if r.get("grade") else "학급 미지정"
    return {"recordings": recs}


@route("GET", r"/api/recordings/(\d+)")
def recording_detail(h, q, b, rid):
    conn = db.connect()
    try:
        r = db.row(conn, "SELECT * FROM recordings WHERE id=?", (int(rid),))
        if not r:
            raise ApiError("녹음이 없습니다.", 404)
        r["has_audio"] = bool(r["audio_path"] and os.path.exists(r["audio_path"]))
        notes = db.rows(conn, """SELECT n.*, s.name, s.number FROM notes n JOIN students s ON s.id=n.student_id
                                 WHERE n.recording_id=? ORDER BY s.number, n.id""", (int(rid),))
        unmatched = db.rows(conn, "SELECT * FROM unmatched WHERE recording_id=? ORDER BY id", (int(rid),))
        students = db.rows(conn, "SELECT id, number, name FROM students WHERE class_id=? ORDER BY number, name",
                           (r["class_id"],)) if r["class_id"] else []
        c = db.row(conn, "SELECT kind FROM classes WHERE id=?", (r["class_id"],)) if r["class_id"] else None
        kind = (c or {}).get("kind") or "교과"
        for n in notes:
            n["area_eff"] = db.note_area(n, kind)
        return {"recording": r, "notes": notes, "unmatched": unmatched, "students": students,
                "areas": db.areas_for_kind(kind)}
    finally:
        conn.close()


@route("POST", "/api/recordings/upload")
def recordings_upload(h, q, b):
    filename = os.path.basename(q.get("filename") or "recording.m4a")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in watcher.AUDIO_EXTS | watcher.TEXT_EXTS:
        raise ApiError("지원하지 않는 파일 형식입니다: %s" % ext)
    tmpdir = tempfile.mkdtemp(prefix="seteuk-up-")
    tmp = os.path.join(tmpdir, filename)
    with open(tmp, "wb") as f:
        f.write(b)
    try:
        rid = watcher.import_file(tmp, class_id=_int(q.get("class_id")), kind=q.get("kind") or None,
                                  title=q.get("title") or None, recorded_at=q.get("recorded_at") or None,
                                  auto=(q.get("auto") == "1") or None, copy=False)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
            os.rmdir(tmpdir)
        except OSError:
            pass
    return {"ok": True, "id": rid}


@route("POST", "/api/recordings/paste")
def recordings_paste(h, q, b):
    text = (b.get("transcript") or "").strip()
    if not text:
        raise ApiError("전사문을 붙여넣으세요.")
    conn = db.connect()
    rid = conn.execute("INSERT INTO recordings(class_id, kind, title, recorded_at, transcript, status, original_name) "
                       "VALUES (?,?,?,?,?,?,?)",
                       (_int(b.get("class_id")), b.get("kind") or "수업", b.get("title") or "붙여넣은 기록",
                        b.get("recorded_at") or now_str(), text, "전사완료", "붙여넣기")).lastrowid
    conn.commit()
    conn.close()
    return {"ok": True, "id": rid}


@route("POST", "/api/recordings/update")
def recordings_update(h, q, b):
    conn = db.connect()
    fields = {}
    for k in ("kind", "title", "recorded_at", "transcript"):
        if k in b:
            fields[k] = b[k]
    if "class_id" in b:
        fields["class_id"] = _int(b["class_id"])
    if "transcript" in b:
        r = db.row(conn, "SELECT status FROM recordings WHERE id=?", (int(b["id"]),))
        if r and r["status"] in ("보관됨", "오류") and (b["transcript"] or "").strip():
            fields["status"] = "전사완료"
    if fields:
        conn.execute("UPDATE recordings SET %s WHERE id=?" % ", ".join("%s=?" % k for k in fields),
                     list(fields.values()) + [int(b["id"])])
        if "kind" in fields:
            conn.execute("UPDATE notes SET kind=? WHERE recording_id=?", (fields["kind"], int(b["id"])))
        if "recorded_at" in fields:
            conn.execute("UPDATE notes SET date=? WHERE recording_id=?", ((fields["recorded_at"] or "")[:10], int(b["id"])))
    conn.commit()
    conn.close()
    return {"ok": True}


@route("POST", "/api/recordings/mark_done")
def recordings_done(h, q, b):
    conn = db.connect()
    conn.execute("UPDATE recordings SET status='완료' WHERE id=?", (int(b["id"]),))
    conn.commit()
    conn.close()
    return {"ok": True}


@route("POST", "/api/recordings/delete")
def recordings_delete(h, q, b):
    conn = db.connect()
    # 녹음 파일은 바로 지우지 않고, 휴지통에서 영구 삭제(또는 30일 뒤)될 때 함께 지운다
    tid = trash.move(conn, "recording", b["id"], delete_notes=bool(b.get("delete_notes")),
                     delete_audio=bool(b.get("delete_audio")))
    conn.commit()
    conn.close()
    return {"ok": True, "trash_id": tid}


@route("POST", "/api/recordings/mark_general")
def recordings_mark_general(h, q, b):
    """일반 메모로 표시(이 녹음에서 나온 학생 기록은 휴지통으로) / 학생 기록으로 되돌리기."""
    rid = int(b["id"])
    conn = db.connect()
    try:
        if b.get("general", True):
            moved = 0
            for n in db.rows(conn, "SELECT id FROM notes WHERE recording_id=?", (rid,)):
                trash.move(conn, "note", n["id"])   # 30일 동안 휴지통에서 되살릴 수 있게
                moved += 1
            conn.execute("DELETE FROM unmatched WHERE recording_id=?", (rid,))
            conn.execute("UPDATE recordings SET status='일반메모', error='' WHERE id=?", (rid,))
            conn.commit()
            return {"ok": True, "moved": moved}
        conn.execute("UPDATE recordings SET status='보관됨', error='' WHERE id=?", (rid,))
        conn.commit()
    finally:
        conn.close()
    pipeline.segment_after_transcript(rid)   # 학생 기록으로 다시 나누기
    return {"ok": True}


@route("POST", "/api/recordings/rule_segment")
def recordings_rule(h, q, b):
    return pipeline.rule_segment(int(b["id"]))


@route("POST", "/api/recordings/reveal")
def recordings_reveal(h, q, b):
    conn = db.connect()
    r = db.row(conn, "SELECT audio_path FROM recordings WHERE id=?", (int(b["id"]),))
    conn.close()
    if not r or not r["audio_path"] or not os.path.exists(r["audio_path"]):
        raise ApiError("녹음 파일이 없습니다.")
    open_in_finder(r["audio_path"], reveal=True)
    return {"ok": True}


@route("POST", "/api/unmatched/assign")
def unmatched_assign(h, q, b):
    conn = db.connect()
    u = db.row(conn, "SELECT u.*, r.recorded_at, r.kind FROM unmatched u JOIN recordings r ON r.id=u.recording_id "
                     "WHERE u.id=?", (int(b["id"]),))
    if not u:
        conn.close()
        raise ApiError("항목이 없습니다.")
    conn.execute("INSERT INTO notes(student_id, recording_id, date, kind, category, content, evidence) "
                 "VALUES (?,?,?,?,?,?,?)",
                 (int(b["student_id"]), u["recording_id"], (u["recorded_at"] or "")[:10], u["kind"],
                  u["category"], u["content"], u["evidence"]))
    conn.execute("DELETE FROM unmatched WHERE id=?", (u["id"],))
    left = conn.execute("SELECT COUNT(*) FROM unmatched WHERE recording_id=?", (u["recording_id"],)).fetchone()[0]
    if not left:
        conn.execute("UPDATE recordings SET status='완료' WHERE id=? AND status='확인필요'", (u["recording_id"],))
    conn.commit()
    conn.close()
    return {"ok": True}


@route("POST", "/api/unmatched/delete")
def unmatched_delete(h, q, b):
    conn = db.connect()
    conn.execute("DELETE FROM unmatched WHERE id=?", (int(b["id"]),))
    conn.commit()
    conn.close()
    return {"ok": True}


# ───────────────────────── AI 작업 ─────────────────────────

@route("POST", "/api/ai/run")
def ai_run(h, q, b):
    op, params = b["op"], b.get("params", {})
    settings = db.get_settings()
    if op == "transcribe" and not b.get("manual") and pipeline.use_whisper(settings):
        if not whisper.available():
            raise ApiError("NEED_WHISPER_MODEL")
        jid = pipeline.enqueue(op, params, "내 맥에서 받아쓰기 %s" % b.get("label", ""))
        return {"ok": True, "job_id": jid}
    if b.get("manual"):
        p = pipeline.build_prompt(op, params)
        return {"manual": True, "prompt": p["prompt"], "has_audio": bool(p.get("audio_path"))}
    # 내 맥 AI (기기 안 AI · Ollama · LM Studio) — 키 없이, 기록이 맥 밖으로 나가지 않음
    if op == "segment" and pipeline.seg_engine(settings) in ("apple", "local"):
        eng = pipeline.seg_engine(settings)
        pipeline.build_prompt(op, params)  # 전사문 확인
        jid = pipeline.enqueue("segment_local", dict(params, engine=eng),
                               "%s 학생별 분리 %s" % ("기기 안 AI" if eng == "apple" else "내 맥 AI", b.get("label", "")))
        return {"ok": True, "job_id": jid}
    if op in ("draft", "shorten") and pipeline.draft_engine(settings) == "local":
        pipeline.build_prompt(op, params)
        labels = {"draft": "세특 초안", "shorten": "초안 줄이기"}
        jid = pipeline.enqueue(op, params, "내 맥 AI %s %s" % (labels[op], b.get("label", "")))
        return {"ok": True, "job_id": jid}
    if settings.get("mode") == "manual" or not settings.get("gemini_api_key"):
        # 쓸 AI가 없으면 오류 대신: 프롬프트를 복사해서 ChatGPT·Gemini 앱에 붙여넣기
        p = pipeline.build_prompt(op, params)
        return {"manual": True, "prompt": p["prompt"], "has_audio": bool(p.get("audio_path"))}
    pipeline.build_prompt(op, params)  # 사전 검증(관찰기록 없음 등)
    labels = {"transcribe": "전사", "segment": "학생별 분리", "draft": "세특 초안", "shorten": "초안 줄이기"}
    jid = pipeline.enqueue(op, params, "%s %s" % (labels.get(op, op), b.get("label", "")))
    return {"ok": True, "job_id": jid}


@route("POST", "/api/ai/apply")
def ai_apply(h, q, b):
    return pipeline.apply(b["op"], b.get("params", {}), b.get("text", ""))


def _batch_targets(conn, class_id, area_in, only_missing):
    c = db.row(conn, "SELECT * FROM classes WHERE id=?", (int(class_id),))
    kind = c.get("kind") or "교과"
    area = area_in or db.areas_for_kind(kind)[0]["id"]
    out = []
    for st in db.rows(conn, "SELECT * FROM students WHERE class_id=? ORDER BY number", (c["id"],)):
        notes = [n for n in db.rows(conn, "SELECT * FROM notes WHERE student_id=? AND use_in_draft=1 ORDER BY date, id", (st["id"],))
                 if db.note_area(n, kind) == area]
        if not notes:
            continue
        if only_missing and db.row(conn, "SELECT id FROM drafts WHERE student_id=? AND area=?", (st["id"], area)):
            continue
        t = db.row(conn, "SELECT bytes FROM student_targets WHERE student_id=? AND area=?", (st["id"], area))
        out.append((st, notes, (t or {}).get("bytes")))
    return c, area, out


@route("POST", "/api/drafts/batch_prompt")
def drafts_batch_prompt(h, q, b):
    """AI 없이: 반 전체 초안 요청문 하나 (ChatGPT·Gemini 앱에 붙여넣기)."""
    conn = db.connect()
    try:
        c, area, items = _batch_targets(conn, b["class_id"], b.get("area"), b.get("only_missing"))
        if not items:
            raise ApiError("초안을 만들 학생이 없어요 (관찰기록이 있는 학생이 없거나 모두 초안이 있어요).")
        ci = dict(c)
        ci["label"] = db.class_label(c)
        ctx = db.row(conn, "SELECT topic, competencies, philosophy FROM class_context WHERE class_id=? AND area=?", (c["id"], area)) or {}
        return {"prompt": prompts.draft_batch(ci, items, db.get_settings(), area, context=ctx), "count": len(items)}
    finally:
        conn.close()


@route("POST", "/api/drafts/batch_apply")
def drafts_batch_apply(h, q, b):
    """AI 답을 붙여넣으면 '[3번] …' 줄마다 그 학생 초안으로 저장."""
    conn = db.connect()
    try:
        c = db.row(conn, "SELECT * FROM classes WHERE id=?", (int(b["class_id"]),))
        students = db.rows(conn, "SELECT * FROM students WHERE class_id=?", (c["id"],))
    finally:
        conn.close()
    area = b.get("area") or "subject"
    text = (b.get("text") or "").replace("**", "")
    parts = re.split(r"(?m)^\s*(?:#+\s*)?\[?\s*(\d{1,5})\s*번\s*\]?\s*[:：.)-]?\s*", text)
    saved, missing = 0, []
    for i in range(1, len(parts) - 1, 2):
        num, body = int(parts[i]), parts[i + 1].strip()
        st = next((s for s in students if s["number"] == num), None)
        if not st or not body:
            missing.append(num)
            continue
        pipeline.apply_draft(st["id"], body.split("\n\n")[0], area)
        saved += 1
    if not saved:
        raise ApiError("답에서 '[1번] …' 같은 줄을 찾지 못했어요. AI 답을 그대로 전부 붙여넣어 주세요.")
    return {"ok": True, "saved": saved, "missing": missing}


@route("POST", "/api/drafts/batch")
def drafts_batch(h, q, b):
    settings = db.get_settings()
    if pipeline.draft_engine(settings) not in ("gemini", "local"):
        raise ApiError("AI가 연결돼 있지 않아요. '반 전체 프롬프트 복사'로 ChatGPT·Gemini 앱에서 만들 수 있어요.")
    conn = db.connect()
    c = db.row(conn, "SELECT * FROM classes WHERE id=?", (int(b["class_id"]),))
    kind = c.get("kind") or "교과"
    area = b.get("area") or db.areas_for_kind(kind)[0]["id"]
    students = db.rows(conn, "SELECT id, name, number FROM students WHERE class_id=? ORDER BY number", (c["id"],))
    targets = []
    for st in students:
        notes = db.rows(conn, "SELECT area FROM notes WHERE student_id=? AND use_in_draft=1", (st["id"],))
        if not any(db.note_area(n, kind) == area for n in notes):
            continue
        if b.get("only_missing") and db.row(conn, "SELECT id FROM drafts WHERE student_id=? AND area=?", (st["id"], area)):
            continue
        targets.append(st)
    conn.close()
    for st in targets:
        pipeline.enqueue("draft", {"student_id": st["id"], "area": area},
                         "%s 초안 %s번 %s" % (db.area_name(area), st["number"], st["name"]))
    return {"ok": True, "count": len(targets)}


@route("GET", "/api/jobs")
def jobs_list(h, q, b):
    conn = db.connect()
    jobs = db.rows(conn, "SELECT * FROM jobs ORDER BY id DESC LIMIT 40")
    active = conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('대기','진행중')").fetchone()[0]
    conn.close()
    return {"jobs": jobs, "active": active}


@route("POST", "/api/jobs/clear")
def jobs_clear(h, q, b):
    conn = db.connect()
    conn.execute("DELETE FROM jobs WHERE status IN ('완료','실패')")
    conn.commit()
    conn.close()
    return {"ok": True}


@route("POST", "/api/jobs/cancel")
def jobs_cancel(h, q, b):
    conn = db.connect()
    conn.execute("UPDATE jobs SET status='실패', message='사용자가 취소' WHERE status='대기'")
    conn.execute("UPDATE recordings SET status='보관됨' WHERE status='대기중'")
    conn.commit()
    conn.close()
    return {"ok": True}


# ───────────────────────── 초안 ─────────────────────────

@route("POST", "/api/drafts/save")
def drafts_save(h, q, b):
    content = (b.get("content") or "").strip()
    if not content:
        raise ApiError("내용이 비어 있습니다.")
    conn = db.connect()
    status = b.get("status") or "초안"
    area = b.get("area") or "subject"
    if status == "확정":
        conn.execute("UPDATE drafts SET status='초안' WHERE student_id=? AND area=? AND status='확정'",
                     (int(b["student_id"]), area))
    if b.get("id") and not b.get("as_new"):
        conn.execute("UPDATE drafts SET content=?, bytes=?, status=? WHERE id=?",
                     (content, db.neis_bytes(content), status, int(b["id"])))
    else:
        conn.execute("INSERT INTO drafts(student_id, content, bytes, status, area) VALUES (?,?,?,?,?)",
                     (int(b["student_id"]), content, db.neis_bytes(content), status, area))
    conn.commit()
    conn.close()
    return {"ok": True}


@route("POST", "/api/drafts/delete")
def drafts_delete(h, q, b):
    conn = db.connect()
    tid = trash.move(conn, "draft", b["id"])
    conn.commit()
    conn.close()
    return {"ok": True, "trash_id": tid}


# ───────────────────────── 설정 ─────────────────────────

def _mask(k):
    return (k[:4] + "•" * 8 + k[-4:]) if len(k) > 10 else ("•" * len(k))


@route("GET", "/api/settings")
def settings_get(h, q, b):
    s = db.get_settings()
    s["active_seg"] = pipeline.seg_engine(s)
    s["active_draft"] = pipeline.draft_engine(s) or "manual"
    s["gemini_api_key_masked"] = _mask(s.get("gemini_api_key", ""))
    s["has_key"] = bool(s.get("gemini_api_key"))
    s.pop("gemini_api_key", None)
    s["inbox_exists"] = os.path.isdir(os.path.expanduser(s.get("inbox_dir") or ""))
    s["areas"] = [dict(a, limit=db.area_limit(a["id"], s)) for a in db.AREAS]
    s["class_kinds"] = db.CLASS_KINDS
    s["platform"] = "mac" if platform_util.IS_MAC else ("win" if platform_util.IS_WIN else "other")
    s["data_dir"] = db.DATA_DIR
    return s


@route("POST", "/api/settings")
def settings_save(h, q, b):
    vals = dict(b)
    if "gemini_api_key" in vals and ("•" in vals["gemini_api_key"] or not vals["gemini_api_key"].strip()):
        if not vals.get("clear_key"):
            vals.pop("gemini_api_key")
    if vals.get("clear_key"):
        vals["gemini_api_key"] = ""
    if "gemini_api_key" in vals:
        vals["gemini_api_key"] = vals["gemini_api_key"].strip()
    if (vals.get("local_ai_url") or "").strip() and not localai.is_local_url(vals["local_ai_url"]):
        raise ApiError("내 맥 AI 주소는 이 맥(127.0.0.1 또는 localhost)만 넣을 수 있어요. 학생 기록이 밖으로 나가지 않게요.")
    db.set_settings(vals)
    if any(k in vals for k in ("share_info", "contact_email", "school_name", "telemetry")):
        telemetry.send_async(force=True)   # 선생님이 정보를 바꾸면 바로 반영
    return {"ok": True}


@route("GET", "/api/relay")
def relay_get(h, q, b):
    out = relay.status()
    if out["paired"]:
        out.update(relay.pair_info())
    return out


@route("POST", "/api/relay/pair")
def relay_pair(h, q, b):
    """QR 만들기 (new=true 면 새 열쇠로 — 예전에 연결한 폰은 끊김)."""
    return dict(relay.status(), **relay.pair_info(new=bool(b.get("new"))), paired=True)


@route("POST", "/api/relay/unpair")
def relay_unpair(h, q, b):
    relay.unpair()
    return {"ok": True}


@route("POST", "/api/relay/poll")
def relay_poll(h, q, b):
    try:
        r = relay.poll_once()
        sync_text.sync_once()
        return r
    except Exception as e:  # noqa
        raise ApiError("연결 서버에 닿지 못했어요: %s" % e)


@route("GET", "/api/telemetry/preview")
def telemetry_preview(h, q, b):
    """설정 화면: 실제로 무엇을 보내는지 그대로 보여 주기."""
    return telemetry.payload()


@route("GET", "/api/localai/status")
def localai_status(h, q, b):
    s = db.get_settings()
    out = localai.status(s)
    out["seg_engine"] = pipeline.seg_engine(s)
    out["draft_engine"] = pipeline.draft_engine(s)
    return out


def _ai_choice(s):
    """지금 고른 AI: builtin(쓰담 AI 모델) | apple | gemini | external(Ollama·LM Studio) | manual(AI 없이)."""
    c = s.get("ai_choice") or ""
    if c:
        return c
    eng = s.get("seg_engine") or "auto"
    if eng == "auto":
        eng = pipeline.seg_engine(s)
    if eng == "local":
        return "builtin" if s.get("local_ai_url") == localai.BUILTIN else "external"
    if eng in ("gemini", "apple"):
        return eng
    return "manual"


def _ai_state():
    s = db.get_settings()
    choice = _ai_choice(s)
    return {"choice": choice, "active_seg": pipeline.seg_engine(s), "draft": pipeline.draft_engine(s) or "manual",
            "has_key": bool(s.get("gemini_api_key")), "gemini_model": s.get("gemini_model") or "",
            "apple": {"state": localai.apple_state(), "text": localai.APPLE_TEXT.get(localai.apple_state(), "")},
            "builtin": localai.llm_status(), "local_ai_url": s.get("local_ai_url") or "",
            "local_ai_model": s.get("local_ai_model") or "", "draft_local": s.get("draft_local", "1"),
            "draft_light_ok": s.get("draft_light_ok", "0"), "light": sorted(localai.LIGHT_MODELS)}


@route("GET", "/api/ai/state")
def ai_state(h, q, b):
    return _ai_state()


@route("POST", "/api/ai/choose")
def ai_choose(h, q, b):
    """AI 하나 고르면 학생 분리·세특 초안 설정을 한 번에 맞춘다 (바로 저장)."""
    c = b.get("choice")
    s = db.get_settings()
    vals = {"ai_choice": c, "mode": "api"}
    started = None
    if c == "builtin":
        st = localai.llm_status()
        installed = [m["id"] for m in st["models"] if m["installed"]]
        mid = st["recommended"] if st["recommended"] in installed else (installed[0] if installed else st["recommended"])
        if not mid:
            raise ApiError(st["machine"]["why"])
        vals.update(seg_engine="local", local_ai_url=localai.BUILTIN, local_ai_model=mid)
        if mid not in installed:
            if not st["engine"]:
                raise ApiError("쓰담을 최신 버전으로 업데이트하면 쓸 수 있어요.")
            localai.llm_download(mid)   # 이 컴퓨터에 맞는 모델을 바로 받기 시작
            started = mid
    elif c == "apple":
        vals["seg_engine"] = "apple"
    elif c == "gemini":
        vals["seg_engine"] = "gemini"
    elif c == "external":
        url = (b.get("url") or "").strip()
        if not localai.is_local_url(url) or url == localai.BUILTIN:
            raise ApiError("내 맥 AI 주소는 127.0.0.1 또는 localhost만 쓸 수 있어요.")
        vals.update(seg_engine="local", local_ai_url=url, local_ai_model=(b.get("model") or "").strip())
    elif c == "manual":
        vals.update(seg_engine="rules", mode="manual")
    else:
        raise ApiError("알 수 없는 선택")
    db.set_settings(vals)
    out = _ai_state()
    out["started"] = started
    return out


@route("GET", "/api/localai/models")
def localai_models(h, q, b):
    return localai.llm_status()


@route("POST", "/api/localai/models/download")
def localai_models_download(h, q, b):
    if not localai.llama_bin():
        raise ApiError("쓰담 내장 AI 엔진이 없어요. 쓰담을 최신 버전으로 업데이트해 주세요.")
    localai.llm_download(b["id"])
    return {"ok": True}


@route("POST", "/api/localai/models/cancel")
def localai_models_cancel(h, q, b):
    localai.llm_cancel(b["id"])
    return {"ok": True}


@route("POST", "/api/localai/models/delete")
def localai_models_delete(h, q, b):
    localai.llm_delete(b["id"])
    return {"ok": True}


@route("POST", "/api/localai/models/use")
def localai_models_use(h, q, b):
    if not localai.llm_installed(b["id"]):
        raise ApiError("먼저 받아 주세요.")
    vals = {"local_ai_url": localai.BUILTIN, "local_ai_model": b["id"]}
    if db.get_settings().get("seg_engine") in ("rules",):
        vals["seg_engine"] = "auto"
    db.set_settings(vals)
    return {"ok": True}


@route("POST", "/api/localai/test")
def localai_test(h, q, b):
    """짧은 예시로 학생 고르기를 시험해 본다 (엔진: apple | local)."""
    s = dict(db.get_settings())
    for k in ("local_ai_url", "local_ai_model"):
        if b.get(k):
            s[k] = b[k]
    eng = b.get("engine") or "apple"
    if eng == "local" and not localai.is_local_url(s.get("local_ai_url")):
        raise ApiError("내 맥 AI 주소는 127.0.0.1 또는 localhost만 쓸 수 있어요.")
    import time as _t
    t0 = _t.time()
    sents = ["오늘 체육 시간이었어요.", "김민수는 줄넘기를 끝까지 해냈어요.", "그 친구는 친구들 줄도 세어 줬어요.",
             "이서연은 질문을 많이 했어요.", "다만 마무리가 조금 아쉬웠어요.", "모두 열심히 참여했어요."]
    try:
        got = localai.owners(eng, s, sents, ["김민수", "이서연"], {1: 1, 3: 2})
    except Exception as e:  # noqa
        raise ApiError("시험 실패: %s" % e)
    want = [0, 1, 1, 2, 2, 0]
    return {"ok": True, "correct": sum(1 for a, b2 in zip(got, want) if a == b2), "total": len(want),
            "seconds": round(_t.time() - t0, 1)}


@route("POST", "/api/settings/test")
def settings_test(h, q, b):
    key = (b.get("key") or "").strip()
    if not key or "•" in key:
        key = db.get_settings().get("gemini_api_key", "")
    if not key:
        raise ApiError("API 키를 입력하세요.")
    try:
        models = gemini.list_models(key)
    except gemini.GeminiError as e:
        raise ApiError(str(e))
    return {"ok": True, "models": models}


@route("POST", "/api/inbox/scan")
def inbox_scan(h, q, b):
    return watcher.scan_once()


@route("POST", "/api/inbox/create")
def inbox_create(h, q, b):
    folder = os.path.expanduser(db.get_settings().get("inbox_dir") or "")
    if not folder:
        raise ApiError("수신 폴더 경로를 입력하세요.")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as e:
        raise ApiError("폴더를 만들 수 없습니다: %s" % e)
    open_in_finder(folder)
    return {"ok": True}


@route("POST", "/api/open_data")
def open_data(h, q, b):
    open_in_finder(db.DATA_DIR)
    return {"ok": True}


@route("POST", "/api/backup")
def backup_now(h, q, b):
    path = os.path.join(db.BACKUP_DIR, "seteuk-manual-%s.db" % datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    db.backup_to(path)
    open_in_finder(path, reveal=True)
    return {"ok": True, "path": path}


# ───────────────────────── 내보내기 ─────────────────────────

@route("GET", "/api/export/table")
def export_table(h, q, b):
    conn = db.connect()
    label, header, rows = sheets.class_table(conn, int(q["class_id"]))
    conn.close()
    keep = [i for i, h in enumerate(header) if h != "관찰기록 요약"]
    return {"label": label, "header": header, "rows": rows,
            "tsv": sheets.to_tsv([header[i] for i in keep], [[r[i] for i in keep] for r in rows])}


@route("POST", "/api/export/xlsx")
def export_xlsx(h, q, b):
    path = sheets.export_xlsx(_int(b.get("class_id")))
    open_in_finder(path, reveal=True)
    return {"ok": True, "path": path, "name": os.path.basename(path)}


@route("POST", "/api/export/csv")
def export_csv(h, q, b):
    conn = db.connect()
    label, header, rows = sheets.class_table(conn, int(b["class_id"]))
    conn.close()
    path = os.path.join(platform_util.downloads_dir(), "세특_%s_%s.csv" % (label, datetime.date.today().isoformat()))
    with open(path, "w", encoding="utf-8") as f:
        f.write(sheets.to_csv(header, rows))
    open_in_finder(path, reveal=True)
    return {"ok": True, "path": path, "name": os.path.basename(path)}


# ───────────────────────── 구글시트·드라이브 / 백업·복원 ─────────────────────────

def ensure_token():
    s = db.get_settings()
    if not s.get("sheets_token"):
        import secrets
        db.set_settings({"sheets_token": secrets.token_urlsafe(18)})
        s = db.get_settings()
    return s["sheets_token"]


def ensure_upload_token():
    s = db.get_settings()
    if not s.get("upload_token"):
        import secrets
        db.set_settings({"upload_token": "u" + secrets.token_urlsafe(16)})
        s = db.get_settings()
    return s["upload_token"]


@route("GET", "/api/phone/pairing")
def phone_pairing(h, q, b):
    """휴대폰 앱이 QR로 읽어 갈 연결 정보 (업로드 전용 토큰만 포함)."""
    s = db.get_settings()
    if not s.get("sheets_url"):
        return {"ready": False}
    payload = "sseudam://pair?" + urllib.parse.urlencode({"u": s["sheets_url"], "t": ensure_upload_token(),
                                                         "n": s.get("teacher_name") or ""})
    return {"ready": True, "payload": payload}


@route("POST", "/api/phone/scan")
def phone_scan(h, q, b):
    return {"ok": True, "imported": sheets.drive_inbox_scan()}


@route("POST", "/api/export/sheets")
def export_sheets(h, q, b):
    return sheets.sync_now(force=True)


@route("POST", "/api/sheets/test")
def sheets_test(h, q, b):
    res = sheets.ping()
    return {"ok": True, "url": res.get("url"), "version": res.get("version")}


@route("POST", "/api/drive/backup")
def drive_backup_now(h, q, b):
    return sheets.drive_backup()


@route("GET", "/api/backups")
def backups_list(h, q, b):
    out = {"local": sheets.local_backups(), "drive": [], "drive_error": ""}
    if db.get_settings().get("sheets_url"):
        try:
            out["drive"] = sheets.drive_list()
        except Exception as e:  # noqa
            out["drive_error"] = str(e)
    return out


@route("POST", "/api/restore")
def restore(h, q, b):
    if b.get("kind") == "local":
        name = os.path.basename(b.get("name") or "")
        p = os.path.join(db.BACKUP_DIR, name)
        if not name or not os.path.exists(p):
            raise ApiError("백업 파일이 없습니다.")
        with open(p, "rb") as f:
            data = f.read()
    elif b.get("kind") == "drive":
        data = sheets.drive_get(b["id"])
    else:
        raise ApiError("복원할 백업을 고르세요.")
    return sheets.restore_from_bytes(data)


@route("POST", "/api/restore/upload")
def restore_upload(h, q, b):
    if not b:
        raise ApiError("파일이 비어 있습니다.")
    return sheets.restore_from_bytes(b)


# ───────────────────────── 프롬프트 안내 ─────────────────────────

@route("GET", "/api/prompts")
def prompts_guide(h, q, b):
    return {"templates": prompts.guide(db.get_settings())}


@route("GET", r"/api/students/(\d+)/notes_text")
def student_notes_text(h, q, b, sid):
    conn = db.connect()
    s = db.row(conn, "SELECT * FROM students WHERE id=?", (int(sid),))
    c = db.row(conn, "SELECT kind FROM classes WHERE id=?", (s["class_id"],))
    notes = db.rows(conn, "SELECT * FROM notes WHERE student_id=? AND use_in_draft=1 ORDER BY date, id", (int(sid),))
    conn.close()
    if q.get("area"):
        notes = [n for n in notes if db.note_area(n, c["kind"] or "교과") == q["area"]]
    lines = ["- [%s/%s%s] %s" % (n["date"] or "", n["kind"] or "", ("/" + n["category"]) if n["category"] else "", n["content"])
             for n in notes]
    return {"text": "\n".join(lines), "count": len(notes)}


# ───────────────────────── Whisper (내 맥에서 받아쓰기) ─────────────────────────

@route("GET", "/api/whisper")
def whisper_status(h, q, b):
    st = whisper.status()
    s = db.get_settings()
    st.update(engine=s.get("stt_engine") or "auto", selected=s.get("whisper_model") or "",
              active=pipeline.use_whisper(s) and whisper.available())
    return st


@route("POST", "/api/whisper/download")
def whisper_download(h, q, b):
    if not whisper.supported():
        raise ApiError("Whisper는 Apple Silicon(M1 이상) 맥에서만 쓸 수 있습니다.")
    whisper.download(b["id"])
    return {"ok": True}


@route("POST", "/api/whisper/cancel")
def whisper_cancel(h, q, b):
    whisper.cancel(b["id"])
    return {"ok": True}


@route("POST", "/api/whisper/delete")
def whisper_delete(h, q, b):
    whisper.delete(b["id"])
    return {"ok": True}


# ───────────────────────── 가져오기 경로 ─────────────────────────

@route("GET", "/api/sources")
def sources_status(h, q, b):
    s = db.get_settings()
    vm_state, vm_dir = watcher.voicememo_access()
    conn = db.connect()
    counts = {r["source"]: r["n"] for r in db.rows(conn, "SELECT source, COUNT(*) AS n FROM imported "
                                                          "WHERE sig != 'skip' GROUP BY source")}
    conn.close()
    return {
        "inbox": {"dir": s["inbox_dir"], "exists": os.path.isdir(os.path.expanduser(s["inbox_dir"] or ""))},
        "voicememo": {"enabled": s["voicememo_enabled"] == "1", "access": vm_state, "dir": vm_dir,
                      "since": s["voicememo_since"], "keyword": s["voicememo_keyword"],
                      "count": counts.get("voicememo", 0)},
        "notes": {"enabled": s["notes_enabled"] == "1", "folder": s["notes_folder"], "count": counts.get("notes", 0)},
        "downloads": {"enabled": s["downloads_import"] == "1", "count": counts.get("downloads", 0)},
        "status": watcher.status(),
        "app_name": "쓰담" if os.environ.get("SETEUK_APP") else "터미널",
    }


@route("POST", "/api/sources/voicememo")
def sources_voicememo(h, q, b):
    vals = {"voicememo_enabled": "1" if b.get("enabled") else "0"}
    if "keyword" in b:
        vals["voicememo_keyword"] = (b.get("keyword") or "").strip()
    if b.get("enabled") and (b.get("reset_since") or not db.get_settings().get("voicememo_since")):
        # 켜는 날 0시 이후 녹음부터 가져옴 (예전 개인 녹음은 가져오지 않음)
        vals["voicememo_since"] = datetime.date.today().strftime("%Y-%m-%d 00:00")
    if b.get("since"):
        vals["voicememo_since"] = b["since"].replace("T", " ")[:16]
    db.set_settings(vals)
    return {"ok": True, "access": watcher.voicememo_access()[0]}


@route("POST", "/api/sources/notes")
def sources_notes(h, q, b):
    db.set_settings({"notes_enabled": "1" if b.get("enabled") else "0",
                     "notes_folder": (b.get("folder") or "세특").strip()})
    if not b.get("enabled"):
        return {"ok": True}
    try:
        notes = watcher.read_notes((b.get("folder") or "세특").strip())  # 처음이면 권한 요청 창이 뜸
    except PermissionError as e:
        raise ApiError(str(e))
    except Exception as e:  # noqa
        raise ApiError("메모 앱을 읽지 못했습니다: %s" % e)
    return {"ok": True, "found": len(notes)}


@route("POST", "/api/open_privacy")
def open_privacy(h, q, b):
    panes = {"fda": "Privacy_AllFiles", "automation": "Privacy_Automation"}
    pane = panes.get(b.get("pane"), "Privacy_AllFiles")
    if not platform_util.IS_MAC:
        return {"ok": False}
    subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?" + pane])
    return {"ok": True}


# ───────────────────────── 업데이트 ─────────────────────────

@route("GET", "/api/sync/text")
def sync_text_status(h, q, b):
    return sync_text.status()


@route("POST", "/api/sync/text")
def sync_text_set(h, q, b):
    if "enabled" in b:
        db.set_settings({"text_sync": "1" if b["enabled"] else "0"})
    return sync_text.sync_once()


@route("GET", "/api/version")
def version_info(h, q, b):
    out = {"version": version.VERSION, "repo": version.UPDATE_REPO, "code_dir": db.APP_DIR,
           "shell": update.shell_version(), "shell_outdated": update.shell_outdated(),
           "auto": update.auto_status()}
    if q.get("notice") == "1":
        out["just_updated"] = update.just_updated(consume=True)
    return out


@route("POST", "/api/update/install_app")
def update_install_app(h, q, b):
    db.backup_to(os.path.join(db.BACKUP_DIR, "seteuk-before-app-update-%s.db" % datetime.datetime.now().strftime("%Y%m%d-%H%M%S")))
    update.mark_updating(version.VERSION, "app")
    try:
        return update.install_app()
    except Exception:
        update.mark_updating("", "")
        raise


@route("GET", "/api/update/check")
def update_check(h, q, b):
    if db.get_settings().get("update_check") != "1" and not q.get("force"):
        return {"enabled": False, "current": version.VERSION}
    return update.check(force=bool(q.get("force")))


@route("POST", "/api/update/apply")
def update_apply(h, q, b):
    conn = db.connect()
    busy = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='진행중'").fetchone()[0]
    conn.close()
    if busy:
        raise ApiError("AI 작업이 진행 중입니다. 끝난 뒤 업데이트하세요.")
    db.backup_to(os.path.join(db.BACKUP_DIR, "seteuk-before-update-%s.db" % datetime.datetime.now().strftime("%Y%m%d-%H%M%S")))
    info = update.check()
    update.mark_updating(version.VERSION, info.get("latest") or "", info.get("notes") or "")
    try:
        return update.apply()
    except Exception:
        update.mark_updating("", "")
        raise


@route("POST", "/api/shutdown")
def shutdown(h, q, b):
    localai.stop_builtin()
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return {"ok": True}


# ───────────────────────── HTTP 처리 ─────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "Seteuk/1.0"

    def log_message(self, fmt, *args):
        if "/api/jobs" in (args[0] if args else ""):
            return
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    def _send(self, code, payload, ctype="application/json; charset=utf-8", extra=None):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _host_ok(self):
        return self.headers.get("Host", "") in ALLOWED_HOSTS

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden host"})
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        q = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        if method == "GET" and not path.startswith("/api/"):
            if path.startswith("/audio/"):
                return self._serve_audio(path)
            if path.startswith("/export/csv"):
                return self._serve_csv(q)
            return self._serve_static(path)
        if method == "POST" and self.headers.get("X-Seteuk") != "1":
            return self._send(403, {"error": "missing header"})
        if method == "POST":
            update.LAST_POST[0] = time.time()  # 자동 업데이트는 조작이 없을 때만
        for m, rx, fn in ROUTES:
            if m != method:
                continue
            match = rx.match(path)
            if not match:
                continue
            try:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                if method == "POST" and not path.endswith("/upload"):
                    body = json.loads(raw.decode("utf-8") or "{}")
                else:
                    body = raw
                res = fn(self, q, body, *match.groups())
                return self._send(200, res)
            except ApiError as e:
                return self._send(e.code, {"error": str(e)})
            except (ValueError, KeyError, gemini.GeminiError) as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:  # noqa
                traceback.print_exc()
                return self._send(500, {"error": "서버 오류: %s" % e})
        self._send(404, {"error": "not found"})

    def _serve_static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        if path == "/google_apps_script.gs":
            with open(os.path.join(db.APP_DIR, "google_apps_script.gs"), encoding="utf-8") as f:
                text = f.read().replace("var TOKEN = '';", "var TOKEN = '%s';" % ensure_token()) \
                    .replace("var UPLOAD_TOKEN = '';", "var UPLOAD_TOKEN = '%s';" % ensure_upload_token())
            return self._send(200, text.encode("utf-8"), "text/plain; charset=utf-8")
        full = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            full = os.path.join(STATIC_DIR, "index.html")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)

    def _serve_csv(self, q):
        conn = db.connect()
        try:
            label, header, rows = sheets.class_table(conn, int(q.get("class_id", 0)))
        except Exception as e:  # noqa
            conn.close()
            return self._send(400, {"error": str(e)})
        conn.close()
        data = sheets.to_csv(header, rows).encode("utf-8")
        fname = urllib.parse.quote("세특_%s_%s.csv" % (label, datetime.date.today().isoformat()))
        self._send(200, data, "text/csv; charset=utf-8",
                   {"Content-Disposition": "attachment; filename*=UTF-8''%s" % fname})

    def _serve_audio(self, path):
        rid = _int(path.rsplit("/", 1)[-1])
        conn = db.connect()
        r = db.row(conn, "SELECT audio_path FROM recordings WHERE id=?", (rid,))
        conn.close()
        if not r or not r["audio_path"] or not os.path.exists(r["audio_path"]):
            return self._send(404, {"error": "no audio"})
        fp = r["audio_path"]
        size = os.path.getsize(fp)
        ctype = mimetypes.guess_type(fp)[0] or "audio/mp4"
        if fp.lower().endswith(".m4a"):
            ctype = "audio/mp4"
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        code = 200
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                    if m.group(2):
                        end = min(int(m.group(2)), size - 1)
                elif m.group(2):
                    start = max(0, size - int(m.group(2)))
                code = 206
        length = end - start + 1
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if code == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.end_headers()
        with open(fp, "rb") as f:
            f.seek(start)
            left = length
            try:
                while left > 0:
                    chunk = f.read(min(65536, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass


def main():
    platform_util.migrate_support()  # 예전 이름 폴더 → 쓰담 (서버 시작 때만)
    db.init()
    httpd = None
    for _ in range(12):
        try:
            httpd = ThreadingHTTPServer((HOST, PORT), Handler)
            break
        except OSError:
            if os.environ.get("SETEUK_APP") and _ < 11:
                import time as _t
                _t.sleep(0.5)  # 업데이트 재시작 중이면 이전 서버가 포트를 놓을 때까지 대기
                continue
            break
    if httpd is None:
        print("이미 실행 중입니다.")
        if os.environ.get("SETEUK_NO_BROWSER") != "1":
            webbrowser.open("http://%s:%d" % (HOST, PORT))
        return
    httpd.daemon_threads = True
    import signal
    signal.signal(signal.SIGTERM, lambda *_: (localai.stop_builtin(), os._exit(0)))  # 앱 종료 시 내장 AI도 함께 끄기
    ensure_token()
    ensure_upload_token()
    pipeline.start_worker()
    watcher.start()
    sheets.start()
    sync_text.start()
    telemetry.start()
    relay.start()
    if update.start_auto():
        print("자동 업데이트 확인 켜짐")
    url = "http://%s:%d" % (HOST, PORT)
    print("쓰담 %s 실행 중: %s  (코드: %s, 데이터: %s)" % (version.VERSION, url, db.APP_DIR, db.DATA_DIR))
    if os.environ.get("SETEUK_NO_BROWSER") != "1":
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
