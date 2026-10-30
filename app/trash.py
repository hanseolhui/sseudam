# -*- coding: utf-8 -*-
"""휴지통 — 지운 학급·학생·녹음·관찰기록·초안을 30일 동안 보관했다가 되살린다.

지울 때 그 행과 함께 사라지는(CASCADE) 하위 행, 끊어지는(SET NULL) 연결을 JSON으로 담아 두고
되살릴 때 원래 id·uid 그대로 다시 넣는다. uid가 같아야 텍스트 동기화(sync_text)가
'다시 생긴 기록'으로 보고 더 새 updated_at으로 다른 기기에 퍼뜨린다.
"""
import datetime
import json
import os
import uuid

import db

KEEP_DAYS = 30
ORDER = ("classes", "students", "recordings", "notes", "drafts", "unmatched")
KIND_NAME = {"class": "학급", "student": "학생", "recording": "녹음", "note": "관찰기록", "draft": "초안"}
KIND_TABLE = {"class": "classes", "student": "students", "recording": "recordings", "note": "notes", "draft": "drafts"}
UID_PREFIX = {"classes": "c-", "students": "s-", "notes": "n-", "drafts": "d-"}
# (외래키 컬럼, 부모 테이블, 꼭 있어야 하는지)
REFS = {
    "students": [("class_id", "classes", True)],
    "recordings": [("class_id", "classes", False)],
    "notes": [("student_id", "students", True), ("recording_id", "recordings", False)],
    "drafts": [("student_id", "students", True)],
    "unmatched": [("recording_id", "recordings", True)],
}
PARENT_NAME = {"classes": "학급", "students": "학생", "recordings": "녹음"}


def _cut(text, n=60):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n] + "…"


def _ids(rows):
    return [r["id"] for r in rows]


def _in(ids):
    return ",".join(str(int(i)) for i in ids) or "NULL"


def _snapshot(conn, kind, rid, delete_notes=False):
    data = {t: [] for t in ORDER}
    links = {}
    if kind == "class":
        c = db.row(conn, "SELECT * FROM classes WHERE id=?", (rid,))
        if not c:
            return None
        data["classes"] = [c]
        data["students"] = db.rows(conn, "SELECT * FROM students WHERE class_id=?", (rid,))
        sids = _in(_ids(data["students"]))
        data["notes"] = db.rows(conn, "SELECT * FROM notes WHERE student_id IN (%s)" % sids)
        data["drafts"] = db.rows(conn, "SELECT * FROM drafts WHERE student_id IN (%s)" % sids)
        links["recordings.class_id"] = _ids(db.rows(conn, "SELECT id FROM recordings WHERE class_id=?", (rid,)))
        title = db.class_label(c)
        detail = "%s년 %s학기 · 학생 %d명 · 관찰기록 %d건" % (c.get("year") or "?", c.get("semester") or "?",
                                                    len(data["students"]), len(data["notes"]))
    elif kind == "student":
        s = db.row(conn, "SELECT * FROM students WHERE id=?", (rid,))
        if not s:
            return None
        c = db.row(conn, "SELECT * FROM classes WHERE id=?", (s["class_id"],)) or {}
        data["students"] = [s]
        data["notes"] = db.rows(conn, "SELECT * FROM notes WHERE student_id=?", (rid,))
        data["drafts"] = db.rows(conn, "SELECT * FROM drafts WHERE student_id=?", (rid,))
        title = "%s %s" % (("%s번" % s["number"]) if s.get("number") is not None else "", s["name"])
        detail = "%s · 관찰기록 %d건 · 초안 %d개" % (db.class_label(c) if c else "학급 없음",
                                              len(data["notes"]), len(data["drafts"]))
    elif kind == "recording":
        r = db.row(conn, "SELECT * FROM recordings WHERE id=?", (rid,))
        if not r:
            return None
        data["recordings"] = [r]
        data["unmatched"] = db.rows(conn, "SELECT * FROM unmatched WHERE recording_id=?", (rid,))
        notes = db.rows(conn, "SELECT * FROM notes WHERE recording_id=?", (rid,))
        if delete_notes:
            data["notes"] = notes
        else:
            links["notes.recording_id"] = _ids(notes)
        title = r.get("title") or "녹음"
        detail = "%s · %s" % ((r.get("recorded_at") or "")[:16], r.get("kind") or "수업")
    elif kind == "note":
        n = db.row(conn, "SELECT * FROM notes WHERE id=?", (rid,))
        if not n:
            return None
        s = db.row(conn, "SELECT name, number FROM students WHERE id=?", (n["student_id"],)) or {}
        data["notes"] = [n]
        title = _cut(n.get("content"))
        detail = "%s · %s" % (s.get("name") or "?", n.get("date") or "")
    elif kind == "draft":
        d = db.row(conn, "SELECT * FROM drafts WHERE id=?", (rid,))
        if not d:
            return None
        s = db.row(conn, "SELECT name FROM students WHERE id=?", (d["student_id"],)) or {}
        data["drafts"] = [d]
        title = _cut(d.get("content"))
        detail = "%s · %s · %s" % (s.get("name") or "?", db.area_name(d.get("area")), d.get("status") or "초안")
    else:
        raise ValueError("알 수 없는 종류: %s" % kind)
    return {"rows": data, "links": links}, title, detail


def remember_exclusion(conn, rid, payload):
    conn.execute("INSERT OR IGNORE INTO excluded_recordings(original_id,payload) VALUES (?,?)",
                 (rid, json.dumps(payload, ensure_ascii=False)))
    # 제외 이력은 휴지통을 비워도 유지. 직접 파일 올리기는 이 이력을 조회하지 않는다.
    import watcher
    for item in db.rows(conn, "SELECT source, ext_id FROM imported WHERE recording_id=?", (rid,)):
        conn.execute("INSERT OR IGNORE INTO auto_import_exclusions(source,ext_id) VALUES (?,?)", (item["source"], item["ext_id"]))
    ap = payload["rows"]["recordings"][0].get("audio_path")
    if ap and os.path.isfile(ap):
        conn.execute("INSERT OR IGNORE INTO auto_import_exclusions(source,ext_id) VALUES ('file',?)", (watcher.file_identity(ap),))


def move(conn, kind, rid, delete_notes=False, delete_audio=False):
    """kind 행을 휴지통으로 옮기고 지운다. 커밋은 호출한 쪽에서. 휴지통 id 반환(없으면 None)."""
    rid = int(rid)
    snap = _snapshot(conn, kind, rid, delete_notes)
    if not snap:
        return None
    payload, title, detail = snap
    if kind == "recording":
        remember_exclusion(conn, rid, payload)
        conn.execute("UPDATE excluded_recordings SET payload=?, restored_id=NULL, excluded_at=datetime('now','localtime') WHERE original_id=?",
                     (json.dumps(payload, ensure_ascii=False), rid))
    if kind == "recording" and delete_audio:
        ap = payload["rows"]["recordings"][0].get("audio_path")
        if ap:
            payload["delete_audio"] = [ap]
    tid = conn.execute("INSERT INTO trash(kind, title, detail, payload, deleted_at) VALUES (?,?,?,?,?)",
                       (kind, title, detail, json.dumps(payload, ensure_ascii=False, default=str),
                        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))).lastrowid
    if kind == "recording" and delete_notes:
        conn.execute("DELETE FROM notes WHERE recording_id=?", (rid,))
    conn.execute("DELETE FROM %s WHERE id=?" % KIND_TABLE[kind], (rid,))
    return tid


def _cols(conn, table):
    return [r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)]


def restore(trash_id):
    conn = db.connect()
    try:
        t = db.row(conn, "SELECT * FROM trash WHERE id=?", (int(trash_id),))
        if not t:
            raise ValueError("휴지통에 없는 항목이에요.")
        payload = json.loads(t["payload"] or "{}")
        data = payload.get("rows") or {}
        idmap = {tbl: {} for tbl in ORDER}

        def resolve(tbl, old):
            if old is None:
                return None
            if old in idmap[tbl]:
                return idmap[tbl][old]
            if db.row(conn, "SELECT id FROM %s WHERE id=?" % tbl, (old,)):
                return old
            return None

        restored = 0
        for tbl in ORDER:
            cols = _cols(conn, tbl)
            for r in data.get(tbl) or []:
                r = {k: v for k, v in r.items() if k in cols}
                old_id = r.get("id")
                for col, parent, required in REFS.get(tbl, []):
                    if col not in r:
                        continue
                    new = resolve(parent, r[col])
                    if new is None and r[col] is not None and required:
                        raise ValueError("%s이 지워진 상태라 되살릴 수 없어요. 휴지통에서 %s부터 되살려 주세요."
                                         % (PARENT_NAME[parent], PARENT_NAME[parent]))
                    r[col] = new
                if r.get("uid") and db.row(conn, "SELECT id FROM %s WHERE uid=?" % tbl, (r["uid"],)):
                    r["uid"] = UID_PREFIX.get(tbl, "x-") + uuid.uuid4().hex[:16]  # 같은 기록이 이미 있으면 새 기록으로
                if old_id is not None and db.row(conn, "SELECT id FROM %s WHERE id=?" % tbl, (old_id,)):
                    r.pop("id")
                keys = list(r.keys())
                new_id = conn.execute("INSERT INTO %s(%s) VALUES (%s)" % (tbl, ",".join(keys), ",".join("?" * len(keys))),
                                      [r[k] for k in keys]).lastrowid
                if old_id is not None:
                    idmap[tbl][old_id] = new_id
                restored += 1
        links = payload.get("links") or {}
        cid = next(iter(idmap["classes"].values()), None)
        if cid:
            for rid in links.get("recordings.class_id") or []:
                conn.execute("UPDATE recordings SET class_id=? WHERE id=? AND class_id IS NULL", (cid, rid))
        rec = next(iter(idmap["recordings"].values()), None)
        if rec:
            for nid in links.get("notes.recording_id") or []:
                conn.execute("UPDATE notes SET recording_id=? WHERE id=? AND recording_id IS NULL", (rec, nid))
        if rec:
            for original in data.get("recordings") or []:
                conn.execute("UPDATE excluded_recordings SET restored_id=? WHERE original_id=?", (rec, original["id"]))
        conn.execute("DELETE FROM trash WHERE id=?", (t["id"],))
        conn.commit()
        target = KIND_TABLE.get(t["kind"])
        first = next(iter(idmap.get(target, {}).values()), None) if target else None
        return {"ok": True, "kind": t["kind"], "id": first, "restored": restored}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _drop_files(conn, payload):
    for p in payload.get("delete_audio") or []:
        try:
            # 휴지통 payload가 오래됐거나 변조돼도 외부 원본·심볼릭 링크 대상은 지우지 않는다.
            if not p or os.path.commonpath([os.path.realpath(p), os.path.realpath(db.AUDIO_DIR)]) != os.path.realpath(db.AUDIO_DIR):
                continue
            if os.path.isfile(p) and not db.row(conn, "SELECT id FROM recordings WHERE audio_path=?", (p,)):
                os.remove(p)
        except OSError:
            pass


def purge(trash_id=None, everything=False, days=KEEP_DAYS):
    """영구 삭제. trash_id 하나, 전부(everything), 또는 days일 지난 것."""
    conn = db.connect()
    try:
        if trash_id is not None:
            items = db.rows(conn, "SELECT * FROM trash WHERE id=?", (int(trash_id),))
        elif everything:
            items = db.rows(conn, "SELECT * FROM trash")
        else:
            cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            items = db.rows(conn, "SELECT * FROM trash WHERE deleted_at < ?", (cutoff,))
        for t in items:
            conn.execute("DELETE FROM trash WHERE id=?", (t["id"],))
        conn.commit()
        for t in items:
            try:
                _drop_files(conn, json.loads(t["payload"] or "{}"))
            except ValueError:
                pass
        return len(items)
    finally:
        conn.close()


def listing():
    conn = db.connect()
    try:
        items = db.rows(conn, "SELECT id, kind, title, detail, deleted_at FROM trash ORDER BY deleted_at DESC, id DESC")
    finally:
        conn.close()
    now = datetime.datetime.now()
    for t in items:
        try:
            dt = datetime.datetime.strptime(t["deleted_at"][:19], "%Y-%m-%d %H:%M:%S")
            t["days_left"] = max(0, KEEP_DAYS - (now - dt).days)
        except (TypeError, ValueError):
            t["days_left"] = KEEP_DAYS
        t["kind_name"] = KIND_NAME.get(t["kind"], t["kind"])
    return {"items": items, "keep_days": KEEP_DAYS}
