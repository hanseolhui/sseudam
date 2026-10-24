"""텍스트 동기화 — 녹음 원본은 빼고 학급·학생·관찰기록·초안만 기기끼리 주고받는다.

공유 폴더(iCloud '쓰담/동기화')에 기기마다 자기 파일 하나(<기기 id>.json)만 쓴다.
각 파일에는 그 기기가 아는 전체 기록이 들어 있고, 읽는 쪽은 모든 파일을 합쳐
기록마다 가장 나중에 고친 것(updated_at)을 고른다. 지운 기록은 deleted 표시로 남긴다.
→ 같은 파일을 두 기기가 동시에 고치는 일이 없어 충돌이 나지 않는다.

학급·학생의 uid는 처음 만들 때 (학년도·학기·학년·반·과목·유형 / 학급·이름)으로 정해지므로
맥과 폰에서 같은 반을 따로 만들어도 하나로 합쳐진다.
"""
import hashlib
import json
import os
import socket
import threading
import time
import uuid

import db
import platform_util

FORMAT = "sseudam-sync"
VERSION = 1
CONTAINER = "iCloud~kr~sseudam~app"
TABLES = ("classes", "students", "notes", "drafts")
FIELDS = {
    "classes": ("year", "semester", "grade", "class_no", "subject", "kind", "label"),
    "students": ("class_uid", "number", "name", "aliases"),
    "notes": ("student_uid", "date", "kind", "area", "category", "content", "source", "use_in_draft"),
    "drafts": ("student_uid", "area", "content", "status"),
}

_lock = threading.Lock()
_status = {"state": "준비", "last": 0, "devices": [], "error": ""}


def status():
    return dict(_status, folder=sync_dir() or "")


def sync_dir():
    """iCloud의 쓰담 폴더 안 '동기화'. 아이폰 앱을 한 번이라도 쓴 Apple ID여야 폴더가 있다."""
    if db.get_settings().get("text_sync", "1") != "1":
        return None
    if os.environ.get("SETEUK_DATA") and not os.environ.get("SSEUDAM_SYNC_DIR"):
        return None   # 테스트 데이터로 띄운 서버는 진짜 iCloud 동기화 폴더를 건드리지 않음
    base = os.environ.get("SSEUDAM_SYNC_DIR") or platform_util.icloud_container_dir(CONTAINER)
    if not os.path.isdir(base):
        return None
    d = base if os.environ.get("SSEUDAM_SYNC_DIR") else os.path.join(base, "동기화")
    os.makedirs(d, exist_ok=True)
    return d


def class_uid(year, semester, grade, class_no, subject, kind):
    key = "|".join(str(x if x is not None else "") for x in (year, semester, grade, class_no, (subject or "").strip(), kind or "교과"))
    return "c-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def student_uid(cuid, name):
    return "s-" + hashlib.sha1(("%s|%s" % (cuid, (name or "").strip())).encode("utf-8")).hexdigest()[:16]


def _device(conn):
    s = db.get_settings(conn)
    did = s.get("device_id")
    if not did:
        did = "mac-" + uuid.uuid4().hex[:12]
        conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('device_id', ?)", (did,))
    return did


# ───────────────────────── DB 준비 ─────────────────────────

def migrate(conn):
    def cols(t):
        return {r[1] for r in conn.execute("PRAGMA table_info(%s)" % t)}
    for t in TABLES:
        if "uid" not in cols(t):
            conn.execute("ALTER TABLE %s ADD COLUMN uid TEXT" % t)
    if "source" not in cols("notes"):
        conn.execute("ALTER TABLE notes ADD COLUMN source TEXT DEFAULT ''")
    conn.execute("CREATE TABLE IF NOT EXISTS sync_state (tbl TEXT, uid TEXT, hash TEXT, updated_at REAL, "
                 "deleted INTEGER DEFAULT 0, PRIMARY KEY (tbl, uid))")
    for t in TABLES:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_%s_uid ON %s(uid)" % (t, t))


def ensure_uids(conn):
    for c in db.rows(conn, "SELECT * FROM classes WHERE uid IS NULL OR uid=''"):
        u = class_uid(c["year"], c["semester"], c["grade"], c["class_no"], c["subject"], c["kind"])
        if db.row(conn, "SELECT id FROM classes WHERE uid=?", (u,)):
            u = "c-" + uuid.uuid4().hex[:16]
        conn.execute("UPDATE classes SET uid=? WHERE id=?", (u, c["id"]))
    for s in db.rows(conn, "SELECT s.id, s.name, c.uid AS cuid FROM students s JOIN classes c ON c.id=s.class_id "
                           "WHERE s.uid IS NULL OR s.uid=''"):
        u = student_uid(s["cuid"], s["name"])
        if db.row(conn, "SELECT id FROM students WHERE uid=?", (u,)):
            u = "s-" + uuid.uuid4().hex[:16]
        conn.execute("UPDATE students SET uid=? WHERE id=?", (u, s["id"]))
    for t, p in (("notes", "n-"), ("drafts", "d-")):
        for r in db.rows(conn, "SELECT id FROM %s WHERE uid IS NULL OR uid=''" % t):
            conn.execute("UPDATE %s SET uid=? WHERE id=?" % t, (p + uuid.uuid4().hex[:16], r["id"]))


def local_records(conn):
    out = {t: {} for t in TABLES}
    for c in db.rows(conn, "SELECT * FROM classes"):
        out["classes"][c["uid"]] = {k: c[k] for k in FIELDS["classes"]}
    for s in db.rows(conn, "SELECT s.*, c.uid AS class_uid FROM students s JOIN classes c ON c.id=s.class_id"):
        out["students"][s["uid"]] = {k: s[k] for k in FIELDS["students"]}
    for n in db.rows(conn, "SELECT n.*, s.uid AS student_uid, r.original_name AS rname FROM notes n "
                           "JOIN students s ON s.id=n.student_id LEFT JOIN recordings r ON r.id=n.recording_id"):
        n["source"] = n.get("source") or n.get("rname") or ""
        out["notes"][n["uid"]] = {k: n[k] for k in FIELDS["notes"]}
    for d in db.rows(conn, "SELECT d.*, s.uid AS student_uid FROM drafts d JOIN students s ON s.id=d.student_id"):
        out["drafts"][d["uid"]] = {k: d[k] for k in FIELDS["drafts"]}
    return out


def _hash(rec):
    return hashlib.sha1(json.dumps(rec, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def stamp(conn, local, now=None):
    """바뀐 기록에 updated_at을 찍고, 사라진 기록은 지움 표시. {tbl: {uid: (rec, updated_at, deleted)}} 반환."""
    now = now or time.time()
    state = {t: {} for t in TABLES}
    for r in db.rows(conn, "SELECT * FROM sync_state"):
        state.setdefault(r["tbl"], {})[r["uid"]] = r
    out = {t: {} for t in TABLES}
    for t in TABLES:
        for u, rec in local[t].items():
            h = _hash(rec)
            st = state[t].get(u)
            if not st or st["hash"] != h or st["deleted"]:
                conn.execute("INSERT OR REPLACE INTO sync_state(tbl, uid, hash, updated_at, deleted) VALUES (?,?,?,?,0)",
                             (t, u, h, now))
                out[t][u] = (rec, now, 0)
            else:
                out[t][u] = (rec, st["updated_at"], 0)
        for u, st in state[t].items():
            if u in local[t]:
                continue
            if not st["deleted"]:
                conn.execute("UPDATE sync_state SET deleted=1, updated_at=? WHERE tbl=? AND uid=?", (now, t, u))
                out[t][u] = (None, now, 1)
            else:
                out[t][u] = (None, st["updated_at"], 1)
    return out


# ───────────────────────── 다른 기기 기록 반영 ─────────────────────────

def read_remote(folder, own):
    docs = []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if name.startswith(".") and name.endswith(".icloud"):
            os.system("brctl download '%s' >/dev/null 2>&1" % path.replace("'", "'\\''"))
            continue
        if not name.endswith(".json") or name == own + ".json":
            continue
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("format") == FORMAT:
                docs.append(d)
        except (OSError, ValueError):
            pass  # 쓰는 중이면 다음 차례에
    return docs


def merge_remote(docs):
    best = {t: {} for t in TABLES}
    for d in docs:
        for t in TABLES:
            for r in d.get(t, []):
                u = r.get("uid")
                if u and (u not in best[t] or (r.get("updated_at") or 0) > (best[t][u].get("updated_at") or 0)):
                    best[t][u] = r
    return best


def apply_remote(conn, mine, remote):
    changed = 0
    for t in TABLES:
        for u, r in remote[t].items():
            ts = r.get("updated_at") or 0
            cur = mine[t].get(u)
            if cur and cur[1] >= ts:
                continue
            if r.get("deleted"):
                if cur and not cur[2]:
                    conn.execute("DELETE FROM %s WHERE uid=?" % t, (u,))
                    changed += 1
                conn.execute("INSERT OR REPLACE INTO sync_state(tbl, uid, hash, updated_at, deleted) VALUES (?,?,?,?,1)",
                             (t, u, "", ts))
                continue
            rec = {k: r.get(k) for k in FIELDS[t]}
            if _upsert(conn, t, u, rec):
                conn.execute("INSERT OR REPLACE INTO sync_state(tbl, uid, hash, updated_at, deleted) VALUES (?,?,?,?,0)",
                             (t, u, _hash(_normalized(conn, t, u, rec)), ts))
                changed += 1
    return changed


def _normalized(conn, t, u, rec):
    """DB에 넣은 뒤 local_records가 읽어 낼 모양 (해시가 같아야 다시 찍히지 않음)."""
    loc = local_records_one(conn, t, u)
    return loc if loc is not None else rec


def local_records_one(conn, t, u):
    q = {
        "classes": "SELECT * FROM classes WHERE uid=?",
        "students": "SELECT s.*, c.uid AS class_uid FROM students s JOIN classes c ON c.id=s.class_id WHERE s.uid=?",
        "notes": "SELECT n.*, s.uid AS student_uid, r.original_name AS rname FROM notes n JOIN students s ON s.id=n.student_id "
                 "LEFT JOIN recordings r ON r.id=n.recording_id WHERE n.uid=?",
        "drafts": "SELECT d.*, s.uid AS student_uid FROM drafts d JOIN students s ON s.id=d.student_id WHERE d.uid=?",
    }[t]
    r = db.row(conn, q, (u,))
    if not r:
        return None
    if t == "notes":
        r["source"] = r.get("source") or r.get("rname") or ""
    return {k: r[k] for k in FIELDS[t]}


def _upsert(conn, t, u, rec):
    row = db.row(conn, "SELECT id FROM %s WHERE uid=?" % t, (u,))
    if t == "classes":
        vals = (rec["year"], rec["semester"], rec["grade"], rec["class_no"], rec["subject"] or "",
                rec["label"] or "", rec["kind"] or "교과")
        if row:
            conn.execute("UPDATE classes SET year=?, semester=?, grade=?, class_no=?, subject=?, label=?, kind=? WHERE id=?",
                         vals + (row["id"],))
        else:
            conn.execute("INSERT INTO classes(year, semester, grade, class_no, subject, label, kind, uid) VALUES (?,?,?,?,?,?,?,?)",
                         vals + (u,))
        return True
    if t == "students":
        c = db.row(conn, "SELECT id FROM classes WHERE uid=?", (rec["class_uid"],))
        if not c:
            return False
        vals = (c["id"], rec["number"], rec["name"] or "", rec["aliases"] or "")
        if row:
            conn.execute("UPDATE students SET class_id=?, number=?, name=?, aliases=? WHERE id=?", vals + (row["id"],))
        else:
            conn.execute("INSERT INTO students(class_id, number, name, aliases, uid) VALUES (?,?,?,?,?)", vals + (u,))
        return True
    s = db.row(conn, "SELECT id FROM students WHERE uid=?", (rec["student_uid"],))
    if not s:
        return False
    if t == "notes":
        rid = None
        if rec.get("source"):
            r = db.row(conn, "SELECT id FROM recordings WHERE original_name=? ORDER BY id DESC LIMIT 1", (rec["source"],))
            rid = r["id"] if r else None
        vals = (s["id"], rec["date"] or "", rec["kind"] or "수업", rec["area"] or "", rec["category"] or "",
                rec["content"] or "", rec["source"] or "", 1 if rec.get("use_in_draft") in (None, 1, True, "1") else 0)
        if row:
            conn.execute("UPDATE notes SET student_id=?, date=?, kind=?, area=?, category=?, content=?, source=?, use_in_draft=? "
                         "WHERE id=?", vals + (row["id"],))
        else:
            conn.execute("INSERT INTO notes(student_id, date, kind, area, category, content, source, use_in_draft, recording_id, uid) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?)", vals + (rid, u))
        return True
    if t == "drafts":
        content = rec["content"] or ""
        vals = (s["id"], rec["area"] or "subject", content, db.neis_bytes(content) if hasattr(db, "neis_bytes") else len(content.encode("utf-8")),
                rec["status"] or "초안")
        if row:
            conn.execute("UPDATE drafts SET student_id=?, area=?, content=?, bytes=?, status=? WHERE id=?", vals + (row["id"],))
        else:
            conn.execute("INSERT INTO drafts(student_id, area, content, bytes, status, uid) VALUES (?,?,?,?,?,?)", vals + (u,))
        return True
    return False


# ───────────────────────── 내 파일 쓰기 ─────────────────────────

def build_doc(device_id, state):
    doc = {"format": FORMAT, "version": VERSION,
           "device": {"id": device_id, "name": socket.gethostname().replace(".local", ""), "kind": "windows" if platform_util.IS_WIN else "mac"},
           "updated_at": time.time()}
    for t in TABLES:
        items = []
        for u, (rec, ts, deleted) in sorted(state[t].items()):
            item = {"uid": u, "updated_at": ts}
            if deleted:
                item["deleted"] = True
            else:
                item.update(rec)
            items.append(item)
        doc[t] = items
    return doc


def write_doc(folder, device_id, doc):
    path = os.path.join(folder, device_id + ".json")
    body = {k: v for k, v in doc.items() if k != "updated_at"}
    sig = _hash(body)
    if _status.get("sig") == sig and os.path.exists(path):
        return False
    tmp = os.path.join(folder, ".%s.tmp" % device_id)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, default=str)
    os.replace(tmp, path)
    _status["sig"] = sig
    return True


def sync_once():
    import relay
    folder = sync_dir()
    rfolder = relay.inbox_dir() if db.get_settings().get("text_sync", "1") == "1" else None   # QR 연동한 폰이 보낸 기록
    if not folder and not rfolder:
        _status.update(state="꺼짐" if db.get_settings().get("text_sync", "1") != "1" else "iCloud 쓰담 폴더 없음")
        return {"ok": False, "message": _status["state"]}
    with _lock:
        conn = db.connect()
        try:
            migrate(conn)
            did = _device(conn)
            ensure_uids(conn)
            mine = stamp(conn, local_records(conn))
            docs = (read_remote(folder, did) if folder else []) + (read_remote(rfolder, did) if rfolder else [])
            changed = apply_remote(conn, mine, merge_remote(docs))
            mine = stamp(conn, local_records(conn))  # 받은 기록 반영 후 (지워져 따라 사라진 것 포함)
            conn.commit()
            doc = build_doc(did, mine)
            if folder:
                write_doc(folder, did, doc)
            if rfolder:
                try:
                    relay.push_doc(doc)     # QR 연동한 폰에도 (암호화해서)
                    relay.push_peer(doc)    # 같은 채널의 다른 컴퓨터에도 (쓰담 플러스)
                except Exception as e:  # noqa
                    print("[QR 연동] 기록 올리기 실패:", e)
            _status.update(state="정상", last=time.time(), error="",
                           devices=[(d.get("device") or {}).get("name", "") for d in docs])
            return {"ok": True, "received": changed}
        except Exception as e:  # noqa
            conn.rollback()
            _status.update(state="오류", error=str(e))
            return {"ok": False, "message": str(e)}
        finally:
            conn.close()


def linked_notes(conn, original_name):
    """다른 기기(폰)에서 이미 학생별로 나눠 보낸 녹음이면 그 기록 수."""
    if not original_name:
        return 0
    r = db.row(conn, "SELECT COUNT(*) AS n FROM notes WHERE source=?", (original_name,))
    return r["n"] if r else 0


def _loop():
    while True:
        try:
            sync_once()
        except Exception as e:  # noqa
            print("텍스트 동기화 실패:", e)
        time.sleep(20)


def start():
    threading.Thread(target=_loop, daemon=True, name="text-sync").start()
