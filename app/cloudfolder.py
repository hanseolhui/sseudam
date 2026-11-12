# -*- coding: utf-8 -*-
"""내 클라우드 폴더 백업 — 선생님이 고른 폴더(OneDrive · iCloud Drive · 구글 드라이브 폴더 · USB 등)에
날마다 사본 두 개를 둔다. 무료 · 플러스 모두 쓸 수 있다.

  쓰담-백업-<컴퓨터>-<기기ID>-YYYYMMDD.zip   복원용. 구글 드라이브 백업과 같은 형식이고 연결 정보(AI 키 · 로그인 · 휴대폰 열쇠)는 빠진다
  쓰담-기록-<컴퓨터>-<기기ID>-YYYYMMDD.xlsx  쓰담이 없어도 엑셀로 열어 볼 수 있는 기록
                                   (전체 엑셀로 저장의 시트 + 초안 전체 버전 + 녹음 받아쓴 글)

쓰담 서버로는 아무것도 보내지 않는다. 폴더를 클라우드에 올리는 일은 그 클라우드 프로그램이 한다.
원본 음성은 따로 켰을 때만 cloudaudio가 기기별 폴더에 증분 보관한다 (자동 삭제 없음).
이름이 같은 컴퓨터도 기기ID로 구분한다. 예전 이름만 있는 백업은 소유 기기를 확정할 수 없어 그대로 보존한다.
"""
import datetime
import glob
import hashlib
import json
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
import unicodedata
import uuid
from functools import lru_cache

import db
import platform_util

KEEP = 30
SUBFOLDER = "쓰담 백업"
CHECK_SECONDS = 3600
KINDS = (("쓰담-백업-", ".zip"), ("쓰담-기록-", ".xlsx"))
_lock = threading.Lock()
_identity_lock = threading.Lock()
_audio_busy = threading.Event()


def _nfc(s):
    return unicodedata.normalize("NFC", s)


def device_name():
    """파일 이름에 넣을 컴퓨터 이름 (글자 · 숫자 · - _ 만)."""
    host = _nfc(socket.gethostname().replace(".local", ""))
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "-" for ch in host).strip("-")
    return safe[:30] or "PC"


@lru_cache(maxsize=1)
def _machine_fingerprint():
    """로컬에서만 쓰는 OS 기기 식별값의 해시. 원문이나 해시는 서버로 보내지 않는다."""
    raw = ""
    try:
        if platform_util.IS_WIN:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                raw = str(winreg.QueryValueEx(key, "MachineGuid")[0])
        elif platform_util.IS_MAC:
            result = subprocess.run(["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                                    capture_output=True, text=True, timeout=3)
            match = re.search(r'"IOPlatformUUID"\s*=\s*"([0-9A-Fa-f-]+)"', result.stdout)
            raw = match.group(1) if match else ""
    except (OSError, subprocess.SubprocessError):
        pass
    # OS 식별값을 못 읽어도 네트워크에 접속하지 않는다. 실제 MAC이 있으면 보조 식별값으로 쓴다.
    if not raw:
        node = uuid.getnode()
        if not (node & (1 << 40)):  # uuid.getnode가 만든 임의값은 실행마다 바뀔 수 있어 쓰지 않는다
            raw = "node:%012x" % node
    return hashlib.sha256(raw.lower().encode("utf-8")).hexdigest() if raw else ""


def _device_id():
    """DB/백업에 넣지 않는 설치 ID. DB 복원·설정 복사로 다른 컴퓨터의 ID를 물려받지 않는다.
    데이터 폴더 전체를 복사한 경우도 OS 기기값과 로컬 경로를 섞어 새 기기와 구분한다.
    OS/MAC 식별값이 모두 없으면 로컬 무작위 ID를 유지한다(완전한 디스크 복제까지 식별하지는 못함).
    """
    path = os.path.join(db.DATA_DIR, ".cloud-backup-id")
    with _identity_lock:
        try:
            with open(path, encoding="ascii") as f:
                seed = f.read(128).strip()
        except FileNotFoundError:
            seed = uuid.uuid4().hex
            created = False
            try:
                with open(path, "x", encoding="ascii") as f:
                    created = True
                    f.write(seed)
                    f.flush()
                    os.fsync(f.fileno())
            except FileExistsError:  # 다른 쓰담 프로세스가 먼저 만들었으면 그 ID를 쓴다
                with open(path, encoding="ascii") as f:
                    seed = f.read(128).strip()
            except OSError:
                if created:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                raise
        if not re.fullmatch(r"[0-9a-f]{32}", seed):
            raise OSError("이 컴퓨터의 백업 기기 번호를 읽지 못했어요.")
    material = "\0".join((seed, _machine_fingerprint(), os.path.realpath(db.DATA_DIR)))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


# ───────────────────────── 이 컴퓨터에서 찾은 클라우드 폴더 ─────────────────────────

def candidates():
    """이 컴퓨터에 있는 클라우드 폴더들. [{id, name, path}] — path 는 그 안의 '쓰담 백업' 폴더."""
    home = os.path.expanduser("~")
    found = []

    def add(cid, name, root):
        if root and os.path.isdir(root) and not any(os.path.normcase(c["root"]) == os.path.normcase(root) for c in found):
            found.append({"id": cid, "name": name, "root": root, "path": os.path.join(root, SUBFOLDER)})

    if platform_util.IS_WIN:
        for i, var in enumerate(("OneDrive", "OneDriveConsumer", "OneDriveCommercial")):
            add("onedrive%d" % i, "OneDrive", os.environ.get(var) or "")
        add("onedrive", "OneDrive", os.path.join(home, "OneDrive"))
        for sub in ("내 드라이브", "My Drive"):
            add("gdrive", "구글 드라이브", os.path.join("G:\\", sub))
    else:
        cloud = os.path.join(home, "Library", "CloudStorage")
        for d in sorted(glob.glob(os.path.join(cloud, "OneDrive*"))):
            add("onedrive:" + os.path.basename(d), _nfc(os.path.basename(d)).replace("-", " ", 1), d)
        for d in sorted(glob.glob(os.path.join(cloud, "GoogleDrive*"))):
            for sub in ("내 드라이브", "My Drive"):
                add("gdrive:" + os.path.basename(d), "구글 드라이브", os.path.join(d, sub))
        add("dropbox-cs", "Dropbox", os.path.join(cloud, "Dropbox"))
    add("icloud", "iCloud Drive", platform_util.icloud_drive_dir())
    add("dropbox", "Dropbox", os.path.join(home, "Dropbox"))
    return [{"id": c["id"], "name": c["name"], "path": c["path"]} for c in found]


# ───────────────────────── 상태 · 켜기 · 끄기 ─────────────────────────

def folder():
    return (db.get_settings().get("backup_folder") or "").strip()


def status():
    s = db.get_settings()
    f = (s.get("backup_folder") or "").strip()
    try:
        summary = json.loads(s.get("backup_audio_summary") or "{}")
    except (ValueError, TypeError):
        summary = {}
    return {"folder": f, "exists": bool(f) and os.path.isdir(f), "last": s.get("backup_folder_last") or "",
            "error": s.get("backup_folder_error") or "", "device": device_name(),
            "audio_enabled": bool(f) and s.get("backup_audio") == "1", "audio_busy": _audio_busy.is_set(),
            "audio_last": s.get("backup_audio_last") or "", "audio_error": s.get("backup_audio_error") or "",
            "audio_summary": summary,
            "candidates": [] if f else candidates()}


def set_audio_enabled(enabled):
    """음성은 별도 선택. 켜면 즉시 복사하고 다음 자동 확인에도 새 음성을 보관한다."""
    if type(enabled) is not bool:
        raise ValueError("녹음 원본 백업 여부를 선택해 주세요.")
    with _lock:
        if enabled and not folder():
            raise ValueError("먼저 백업할 클라우드 폴더를 골라 주세요.")
        db.set_settings({"backup_audio": "1" if enabled else "0"})
    if enabled:
        copy_now(force=True)
    return status()


def _inside(path, parent):
    try:
        return os.path.commonpath([os.path.realpath(path), os.path.realpath(parent)]) == os.path.realpath(parent)
    except ValueError:   # 윈도우에서 드라이브가 다를 때
        return False


def set_folder(path="", candidate=""):
    """폴더를 정하고 바로 한 번 백업한다. path 와 candidate 가 모두 비면 끈다 (이미 둔 사본은 지우지 않는다)."""
    if candidate:
        hit = next((c for c in candidates() if c["id"] == candidate), None)
        if not hit:
            raise ValueError("그 클라우드 폴더를 찾지 못했어요. 폴더 주소를 직접 적어 주세요.")
        path = hit["path"]
        os.makedirs(path, exist_ok=True)
    path = os.path.expanduser((path or "").strip().strip('"'))
    if not path:
        with _lock:
            db.set_settings({"backup_folder": "", "backup_folder_last": "", "backup_folder_error": "",
                             "backup_audio": "0", "backup_audio_last": "", "backup_audio_error": "",
                             "backup_audio_summary": ""})
        return status()
    if not os.path.isabs(path) or not os.path.isdir(path):
        raise ValueError("폴더를 찾을 수 없어요. 탐색기 · Finder 에서 폴더 주소를 복사해 붙여넣어 주세요.")
    if _inside(path, db.DATA_DIR):
        raise ValueError("쓰담 데이터 폴더 안은 고를 수 없어요. 컴퓨터가 고장 나면 함께 사라지는 곳이에요.")
    probe = os.path.join(path, ".sseudam-write-test")
    try:
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
    except OSError:
        raise ValueError("이 폴더에 파일을 쓸 수 없어요. 다른 폴더를 골라 주세요.")
    with _lock:
        vals = {"backup_folder": path, "backup_folder_last": "", "backup_folder_error": ""}
        if os.path.realpath(folder()) != os.path.realpath(path):
            vals.update({"backup_audio": "0", "backup_audio_last": "", "backup_audio_error": "",
                         "backup_audio_summary": ""})
        db.set_settings(vals)
    copy_now(force=True)
    return status()


# ───────────────────────── 사본 만들기 ─────────────────────────

def _name(kind, day=None):
    prefix, ext = kind
    return "%s%s-%s-%s%s" % (prefix, device_name(), _device_id(), (day or datetime.date.today()).strftime("%Y%m%d"), ext)


def _mine(folder_path, kind):
    """이 컴퓨터가 이 폴더에 둔 사본 이름들 (날짜순)."""
    prefix, ext = kind
    # 컴퓨터 이름을 바꿔도 같은 ID의 사본은 찾는다. ID가 없는 예전 파일은 지우지 않는다.
    pattern = re.compile(r"^%s.+-%s-(\d{8})%s$" % (re.escape(prefix), _device_id(), re.escape(ext)))
    out = []
    for raw in os.listdir(folder_path):
        name = _nfc(raw)
        match = pattern.fullmatch(name)
        if match and os.path.isfile(os.path.join(folder_path, raw)):
            out.append((match.group(1), raw))
    return [raw for _, raw in sorted(out)]


def _write(folder_path, name, data):
    """임시 이름으로 다 쓴 뒤 제 이름을 붙인다 — 쓰는 도중의 덜 쓴 파일이 그날 사본이 되지 않게."""
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=folder_path, prefix="." + name + ".", suffix=".tmp", delete=False) as f:
            tmp = f.name
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, os.path.join(folder_path, name))
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass  # 교체 성공 시 이미 없어짐. 실패 원인은 원래 예외로 전달한다.


CELL_CHARS = 30000   # 엑셀 한 칸은 32,767자까지 — 긴 글은 여러 줄로 나눠 담는다


def _pieces(text):
    text = text or ""
    return [text[i:i + CELL_CHARS] for i in range(0, len(text), CELL_CHARS)] or [""]


def archive_sheets(conn):
    """보관용 엑셀에만 더 넣는 시트: 초안의 모든 버전, 녹음을 받아쓴 글 원문.
    ('전체 엑셀로 저장' · 구글시트 반영에는 넣지 않는다 — 거기는 지금 쓰는 최신 초안만 보는 용도)"""
    drafts = db.rows(conn, """SELECT c.year, c.semester, c.grade, c.class_no, c.subject, c.kind AS ckind, s.number, s.name,
                d.area, d.status, d.bytes, d.created_at, d.content
                FROM drafts d JOIN students s ON s.id=d.student_id JOIN classes c ON c.id=s.class_id
                ORDER BY c.year, c.semester, c.grade, c.class_no, c.subject, s.number, s.name, d.area, d.id""")
    draft_rows = []
    for d in drafts:
        label = "%s (%s-%s학기)" % (db.class_label(dict(d, kind=d["ckind"])), d["year"], d["semester"])
        parts = _pieces(d["content"])
        for i, part in enumerate(parts):
            draft_rows.append([label, d["number"] if d["number"] is not None else "", d["name"], db.area_name(d["area"]),
                               d["status"] or "", d["bytes"] or 0, d["created_at"] or "",
                               "%d/%d" % (i + 1, len(parts)) if len(parts) > 1 else "", part])
    recs = db.rows(conn, """SELECT r.recorded_at, r.title, r.kind, r.status, r.original_name, r.transcript,
                c.year, c.semester, c.grade, c.class_no, c.subject, c.kind AS ckind, c.id AS cid
                FROM recordings r LEFT JOIN classes c ON c.id=r.class_id
                WHERE r.transcript IS NOT NULL AND r.transcript != ''
                ORDER BY r.recorded_at, r.id""")
    rec_rows = []
    for r in recs:
        label = db.class_label(dict(r, kind=r["ckind"])) if r["cid"] else ""
        parts = _pieces(r["transcript"])
        for i, part in enumerate(parts):
            rec_rows.append([r["recorded_at"] or "", r["title"] or r["original_name"] or "", label, r["kind"] or "",
                             "%d/%d" % (i + 1, len(parts)) if len(parts) > 1 else "", part])
    return [("초안 전체 버전", ["학급", "번호", "이름", "기재 영역", "상태", "바이트", "만든 때", "나눔", "내용"],
             draft_rows, [22, 6, 9, 10, 8, 8, 17, 6, 80]),
            ("녹음 받아쓴 글", ["녹음한 때", "제목", "학급", "유형", "나눔", "받아쓴 글"],
             rec_rows, [17, 24, 16, 8, 6, 100])]


def _xlsx_bytes():
    import sheets
    import tempfile
    import xlsx
    conn = db.connect()
    try:
        books = sheets.workbook(conn) + archive_sheets(conn)
    finally:
        conn.close()
    tmp = tempfile.mkdtemp(prefix="seteuk-xl-")
    try:
        path = os.path.join(tmp, "b.xlsx")
        xlsx.write(path, books)
        with open(path, "rb") as f:
            return f.read()
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def copy_now(force=False):
    """오늘 사본이 없으면(또는 force) 만들어 둔다. 실패해도 예외를 내지 않고 설정에 이유를 적는다."""
    with _lock:
        f = folder()
        if not f:
            return {"ok": False, "off": True}
        audio_stage = False
        try:
            if not os.path.isdir(f):
                raise OSError("폴더를 찾을 수 없어요 (%s). 클라우드 프로그램이 켜져 있는지, USB 가 꽂혀 있는지 확인해 주세요." % f)
            import sheets
            made = []
            for kind, build in ((KINDS[0], sheets._db_zip_bytes), (KINDS[1], _xlsx_bytes)):
                name = _name(kind)
                if force or not os.path.exists(os.path.join(f, name)):
                    _write(f, name, build())
                    made.append(name)
                for old in _mine(f, kind)[:-KEEP]:
                    try:
                        os.remove(os.path.join(f, old))
                    except OSError:
                        pass
            if made:
                db.set_settings({"backup_folder_last": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "backup_folder_error": ""})
            audio = None
            if db.get_settings().get("backup_audio") == "1":
                import cloudaudio
                audio_stage = True
                _audio_busy.set()
                try:
                    audio = cloudaudio.sync(f, _device_id())
                    db.set_settings({"backup_audio_last": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                                     "backup_audio_error": "", "backup_audio_summary": json.dumps(audio, ensure_ascii=False)})
                except Exception as e:
                    db.set_settings({"backup_audio_error": str(e)})
                    raise
                finally:
                    _audio_busy.clear()
            # 오늘 파일이 있어 쓰기를 건너뛴 경우에는 앞선 실패가 복구됐다고 판단하지 않는다.
            return {"ok": True, "made": made, "audio": audio}
        except Exception as e:  # noqa — 폴더 없음 · 권한 · 디스크 가득 등. 다음 차례에 다시
            if not audio_stage:
                db.set_settings({"backup_folder_error": "%s · %s" % (datetime.datetime.now().strftime("%m-%d %H:%M"), e)})
            return {"ok": False, "error": str(e)}


def _loop():
    time.sleep(90)
    while True:
        try:
            copy_now()
        except Exception as e:  # noqa
            print("클라우드 폴더 백업 실패:", e)
        time.sleep(CHECK_SECONDS)


def start():
    threading.Thread(target=_loop, daemon=True, name="cloud-folder").start()
