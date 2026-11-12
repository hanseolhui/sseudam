# -*- coding: utf-8 -*-
"""내보내기·백업.

- 엑셀(.xlsx): 요약 + 학급별 세특 + 관찰기록 전체 → ~/Downloads
- 구글시트 자동 동기화: 내용이 바뀌면 5분 안에 시트에 반영 (앱 → 시트 한 방향, 시트는 '보기용 사본')
- 구글 드라이브 백업: 하루 한 번 DB 전체를 압축해 드라이브 '쓰담 백업' 폴더에 저장 (최근 30개)
  → 맥이 고장 나도 드라이브 백업으로 복원 가능
"""
import base64
import csv
import datetime
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile

import db
import gemini
import version
import xlsx

SCRIPT_MIN_VERSION = 3   # google_apps_script.gs 의 SCRIPT_VERSION 과 맞춤


# ───────────────────────── 데이터 모으기 ─────────────────────────

def class_table(conn, class_id):
    """(학급 이름, 머리글, 행). 담임반처럼 영역이 여럿이면 영역마다 초안·바이트·상태 열이 생긴다."""
    c = db.row(conn, "SELECT * FROM classes WHERE id=?", (class_id,))
    if not c:
        raise ValueError("학급을 찾을 수 없습니다.")
    kind = c.get("kind") or "교과"
    areas = db.areas_for_kind(kind)
    multi = len(areas) > 1
    header = ["번호", "이름", "관찰기록 수"]
    for a in areas:
        p = (a["name"] + " ") if multi else ""
        header += [p + ("세특 초안" if not multi else "초안"), p + "바이트", p + "상태"]
    header += ["최종 수정", "관찰기록 요약"]
    students = db.rows(conn, "SELECT * FROM students WHERE class_id=? ORDER BY number, name", (class_id,))
    out = []
    for s in students:
        notes = db.rows(conn, "SELECT date, content, area FROM notes WHERE student_id=? ORDER BY date, id", (s["id"],))
        row = [s["number"] if s["number"] is not None else "", s["name"], len(notes)]
        latest = ""
        for a in areas:
            d = db.row(conn, "SELECT * FROM drafts WHERE student_id=? AND area=? "
                             "ORDER BY (status='확정') DESC, id DESC LIMIT 1", (s["id"], a["id"]))
            row += [d["content"] if d else "", d["bytes"] if d else 0, d["status"] if d else "미작성"]
            if d and (d["created_at"] or "") > latest:
                latest = d["created_at"]
        summary = "\n".join("(%s%s) %s" % (n["date"] or "", ("·" + db.area_name(db.note_area(n, kind))) if multi else "",
                                           n["content"]) for n in notes)
        out.append(row + [latest, summary[:45000]])
    return db.class_label(c), header, out


def workbook(conn, class_id=None):
    """[(시트이름, 머리글, 행, 열너비)] — 엑셀과 구글시트가 같은 구성을 사용."""
    if class_id:
        classes = db.rows(conn, "SELECT * FROM classes WHERE id=?", (class_id,))
    else:
        classes = db.rows(conn, "SELECT * FROM classes ORDER BY year DESC, semester DESC, grade, class_no, subject")
    sheets = []
    summary = []
    for c in classes:
        label, header, rows = class_table(conn, c["id"])
        n_areas = (len(header) - 5) // 3
        drafted = sum(1 for r in rows if any(r[3 + i * 3] for i in range(n_areas)))
        final = sum(1 for r in rows if all(r[5 + i * 3] == "확정" for i in range(n_areas)))
        summary.append(["%s (%s-%s학기)" % (label, c["year"], c["semester"]), len(rows),
                        sum(r[2] for r in rows), drafted, final])
        widths = [6, 9, 9] + [60 if n_areas == 1 else 45, 8, 8] * n_areas + [17, 60]
        sheets.append((label, header, rows, widths))
    if not class_id:
        sheets.insert(0, ("요약", ["학급", "학생 수", "관찰기록", "초안 작성", "확정"], summary, [30, 9, 10, 10, 8]))
    where, args = ("WHERE s.class_id=?", (class_id,)) if class_id else ("", ())
    notes = db.rows(conn, """SELECT c.grade, c.class_no, c.subject, c.kind AS ckind, s.number, s.name, n.date,
                n.kind, n.category, n.area, n.content, n.evidence, r.title AS rec_title, n.use_in_draft
                FROM notes n JOIN students s ON s.id=n.student_id JOIN classes c ON c.id=s.class_id
                LEFT JOIN recordings r ON r.id=n.recording_id %s
                ORDER BY c.grade, c.class_no, s.number, n.date, n.id""" % where, args)
    sheets.append(("관찰기록 전체", ["학급", "번호", "이름", "날짜", "유형", "기재 영역", "분류", "내용", "원문 발췌", "출처", "초안 사용"],
                   [[db.class_label(dict(n, kind=n["ckind"])), n["number"], n["name"],
                     n["date"] or "", n["kind"] or "", db.area_name(db.note_area(n, n["ckind"])), n["category"] or "",
                     n["content"], n["evidence"] or "",
                     n["rec_title"] or "직접 입력", "O" if n["use_in_draft"] else ""] for n in notes],
                   [16, 6, 9, 11, 6, 10, 8, 60, 40, 22, 8]))
    return sheets


# ───────────────────────── 엑셀 / CSV / TSV ─────────────────────────

def export_xlsx(class_id=None):
    conn = db.connect()
    try:
        books = workbook(conn, class_id)
        name = db.class_label(db.row(conn, "SELECT * FROM classes WHERE id=?", (class_id,))) if class_id else "전체"
    finally:
        conn.close()
    import platform_util
    path = os.path.join(platform_util.downloads_dir(), "쓰담_%s_%s.xlsx" % (name.replace("/", "-"),
                                                       datetime.datetime.now().strftime("%Y%m%d-%H%M")))
    xlsx.write(path, books)
    return path


def to_csv(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return "﻿" + buf.getvalue()  # 엑셀 한글 깨짐 방지 BOM


def to_tsv(header, rows):
    def cell(v):
        v = str(v)
        if any(ch in v for ch in "\t\n\""):
            v = '"' + v.replace('"', '""') + '"'
        return v
    return "\n".join("\t".join(cell(v) for v in r) for r in [header] + rows)


# ───────────────────────── 구글 Apps Script 호출 ─────────────────────────

def _call(action, payload, timeout=120):
    s = db.get_settings()
    url = (s.get("sheets_url") or "").strip()
    if not url:
        raise ValueError("설정에서 구글시트 웹앱 주소를 먼저 입력하세요.")
    body = dict(payload)
    body.update(action=action, token=s.get("sheets_token") or "", client=version.VERSION)
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "text/plain;charset=utf-8"}, method="POST")
    try:
        # Apps Script는 302로 결과 주소를 돌려주며, urllib가 GET으로 따라간다
        resp = urllib.request.urlopen(req, timeout=timeout, context=gemini._CTX)
        text = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise ValueError("구글 연결 실패 (HTTP %s). 웹앱 배포 설정(액세스: 모든 사용자)을 확인하세요." % e.code)
    except urllib.error.URLError as e:
        raise ValueError("구글에 연결하지 못했습니다: %s" % e.reason)
    try:
        res = json.loads(text)
    except ValueError:
        raise ValueError("구글 응답을 이해하지 못했습니다. 웹앱 주소가 '/exec'로 끝나는지 확인하세요.")
    if not res.get("ok"):
        raise ValueError("구글 오류: %s" % res.get("error", "알 수 없음"))
    if int(res.get("version") or 1) < SCRIPT_MIN_VERSION:
        raise ValueError("구글 Apps Script가 예전 버전입니다. 설정의 '스크립트 복사'로 새로 붙여넣고 '배포 관리 → 새 버전'으로 다시 배포하세요.")
    return res


def ping():
    return _call("ping", {}, timeout=30)


def sync_now(force=False):
    """모든 학급을 구글시트에 반영. 바뀐 게 없으면 건너뜀."""
    conn = db.connect()
    try:
        books = workbook(conn)
    finally:
        conn.close()
    payload = [{"name": n, "header": h, "rows": [[("" if v is None else v) for v in r] for r in rows], "widths": w}
               for n, h, rows, w in books]
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    s = db.get_settings()
    if not force and digest == s.get("sheets_last_hash"):
        return {"ok": True, "skipped": True}
    try:
        res = _call("sync", {"sheets": payload})
    except Exception as e:
        db.set_settings({"sheets_last_error": "%s · %s" % (datetime.datetime.now().strftime("%m-%d %H:%M"), e)})
        raise
    db.set_settings({"sheets_last_hash": digest, "sheets_last_error": "",
                     "sheets_last_sync": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")})
    return {"ok": True, "sheets": len(payload), "url": res.get("url")}


def _db_zip_bytes():
    tmp = tempfile.mkdtemp(prefix="seteuk-bk-")
    try:
        dbfile = os.path.join(tmp, "seteuk.db")
        db.backup_to(dbfile)
        import backupsafe
        backupsafe.scrub(dbfile)   # AI 키 · 플러스 로그인 · 휴대폰 연결 열쇠는 밖으로 나가는 백업에 넣지 않는다
        zpath = os.path.join(tmp, "b.zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(dbfile, "seteuk.db")
            z.writestr("info.json", json.dumps({"app": "쓰담", "version": version.VERSION,
                                                "created": datetime.datetime.now().isoformat(),
                                                "connections_included": False}))
        with open(zpath, "rb") as f:
            return f.read()
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def drive_backup():
    data = _db_zip_bytes()
    name = "쓰담-백업-%s.zip" % datetime.datetime.now().strftime("%Y%m%d-%H%M")
    res = _call("backup", {"filename": name, "data": base64.b64encode(data).decode("ascii"), "keep": 30}, timeout=300)
    db.set_settings({"drive_last_backup": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")})
    return {"ok": True, "name": name, "size": len(data), "url": res.get("url")}


def drive_list():
    return _call("list_backups", {}).get("files", [])


def drive_get(file_id):
    res = _call("get_backup", {"id": file_id}, timeout=300)
    return base64.b64decode(res["data"])


# ───────────────────────── 휴대폰 녹음함 (구글 드라이브) ─────────────────────────

def drive_inbox_scan():
    """휴대폰 앱이 드라이브 '쓰담 녹음함'에 올린 녹음을 가져와 녹음함에 넣는다."""
    import watcher
    files = _call("list_inbox", {}).get("files", [])
    imported = 0
    for f in files:
        tmp = tempfile.mkdtemp(prefix="seteuk-in-")
        try:
            data = base64.b64decode(_call("get_inbox_file", {"id": f["id"]}, timeout=300)["data"])
            name = os.path.basename(f.get("name") or "녹음.m4a")
            path = os.path.join(tmp, name)
            with open(path, "wb") as fh:
                fh.write(data)
            meta = f.get("meta") or {}
            rec_at = (meta.get("recorded_at") or "").replace("T", " ")[:16] or None
            watcher.import_file(path, kind=meta.get("kind") or None, title=meta.get("title") or None,
                                recorded_at=rec_at, copy=False)
            _call("done_inbox", {"id": f["id"]})
            imported += 1
        except Exception as e:  # noqa
            print("드라이브 녹음함 가져오기 실패:", f.get("name"), e)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
    return imported


def _inbox_loop():
    time.sleep(30)
    while True:
        try:
            s = db.get_settings()
            if s.get("sheets_url") and s.get("drive_inbox") == "1":
                drive_inbox_scan()
        except Exception as e:  # noqa
            print("드라이브 녹음함 확인 실패:", e)
        time.sleep(60)


# ───────────────────────── 복원 ─────────────────────────

def restore_from_bytes(data):
    """백업(zip 또는 .db)으로 현재 기록을 바꾼다. 바꾸기 전 현재 상태를 자동 백업."""
    tmp = tempfile.mkdtemp(prefix="seteuk-rs-")
    try:
        src = os.path.join(tmp, "in.db")
        if data[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if "seteuk.db" not in z.namelist():
                    raise ValueError("쓰담 백업 파일이 아닙니다.")
                with open(src, "wb") as f:
                    f.write(z.read("seteuk.db"))
        elif data[:16] == b"SQLite format 3\x00":
            with open(src, "wb") as f:
                f.write(data)
        else:
            raise ValueError("백업 파일 형식을 알 수 없습니다 (.zip 또는 .db).")
        chk = sqlite3.connect(src)
        try:
            tables = {r[0] for r in chk.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"classes", "students", "notes"} <= tables:
                raise ValueError("쓰담 백업 파일이 아닙니다.")
            counts = {t: chk.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in ("classes", "students", "notes")}
        finally:
            chk.close()
        before = os.path.join(db.BACKUP_DIR, "seteuk-before-restore-%s.db" % datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
        db.backup_to(before)
        import backupsafe
        cur = db.connect()
        keep = backupsafe.remember(cur)   # 이 컴퓨터의 로그인 · 휴대폰 연결 · AI 키는 복원해도 그대로
        cur.close()
        s = sqlite3.connect(src)
        d = db.connect()
        with d:
            s.backup(d)
        s.close()
        with d:
            backupsafe.put_back(d, keep)
        d.close()
        db.init()  # 새 컬럼·설정 보충
        return {"ok": True, "counts": counts, "before": before,
                "warning": "로그인 · 휴대폰 연결 · AI 키는 이 컴퓨터의 것을 그대로 두었습니다."}
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def local_backups():
    out = []
    if os.path.isdir(db.BACKUP_DIR):
        for f in sorted(os.listdir(db.BACKUP_DIR), reverse=True):
            if f.endswith(".db"):
                p = os.path.join(db.BACKUP_DIR, f)
                out.append({"name": f, "size": os.path.getsize(p),
                            "time": datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")})
    return out


# ───────────────────────── 자동 동기화 루프 ─────────────────────────

def _loop():
    time.sleep(60)
    while True:
        try:
            s = db.get_settings()
            if s.get("sheets_url"):
                if s.get("sheets_auto") == "1":
                    try:
                        sync_now()
                    except Exception as e:  # noqa
                        print("구글시트 동기화 실패:", e)
                if s.get("drive_backup") == "1" and (s.get("drive_last_backup") or "")[:10] != datetime.date.today().isoformat():
                    try:
                        drive_backup()
                    except Exception as e:  # noqa
                        print("드라이브 백업 실패:", e)
        except Exception as e:  # noqa
            print("동기화 루프 오류:", e)
        time.sleep(300)


def start():
    threading.Thread(target=_loop, daemon=True, name="sheets-sync").start()
    threading.Thread(target=_inbox_loop, daemon=True, name="drive-inbox").start()
