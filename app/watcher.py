# -*- coding: utf-8 -*-
"""녹음·메모 가져오기.

세 가지 경로를 자동으로 감시한다.
1. 수신 폴더(iCloud Drive/쓰담 녹음 · 예전 세특녹음): 단축어나 '파일에 저장'으로 넣은 오디오·텍스트
2. 음성메모 보관함: 아이폰 음성메모가 iCloud로 맥에 동기화된 것 (전체 디스크 접근 권한 필요)
   - 아이폰이 이미 받아쓴 전사문이 파일 안에 있으면 그대로 사용 → AI 전사 생략
3. 메모 앱의 '세특' 폴더: 아이폰 키보드 받아쓰기(마이크 버튼)로 적은 메모
"""
import datetime
import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

import db
import pipeline

AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".aac", ".mp4", ".caf", ".aiff", ".aif", ".flac", ".ogg", ".qta", ".3gp"}
TEXT_EXTS = {".txt"}

VOICEMEMO_DIRS = [
    "~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings",
    "~/Library/Application Support/com.apple.voicememos/Recordings",
]
# 아이폰 '쓰담 녹음/받아쓰기' 단축어가 저장하는 곳 (iCloud Drive › Shortcuts › 쓰담) — 예전 이름 폴더도 계속 확인
SHORTCUTS_DIRS = ["~/Library/Mobile Documents/iCloud~is~workflow~my~workflows/Documents/쓰담",
                  "~/Library/Mobile Documents/iCloud~is~workflow~my~workflows/Documents/세특녹음"]
# 아이폰 '쓰담' 앱이 iCloud에 저장하는 곳 (같은 Apple ID면 자동 동기화)
RECORDER_CONTAINERS = ["iCloud~kr~sseudam~app", "iCloud~kr~seteuk~recorder"]
_status = {"inbox": "", "voicememo": "", "notes": "", "downloads": ""}
_seen_sizes = {}
_scan_lock = threading.Lock()


def _shq(s):
    return "'" + s.replace("'", "'\\''") + "'"


def status():
    return dict(_status)


# ───────────────────────── 공용: 기록 등록 ─────────────────────────

def _guess_class(conn, hint_text, recorded_at):
    cid = pipeline.guess_class(conn, hint_text or "")
    return cid or pipeline.guess_class_by_time(conn, recorded_at)


def _file_time(path):
    """파일명에 날짜·시각이 있으면 사용(음성메모 기본 이름 '20261012 103000-…'), 없으면 수정 시각."""
    base = os.path.basename(path)
    m = re.search(r"(20\d{2})[-.]?(\d{2})[-.]?(\d{2})[ _-]?(\d{2})?[:.]?(\d{2})?", base)
    if m:
        try:
            dt = datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                   int(m.group(4) or 0), int(m.group(5) or 0))
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass
    return datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")


def create_recording(class_id=None, kind=None, title="", recorded_at=None, audio_src=None, transcript="",
                     original_name="", hint_text="", copy=True, auto=None, phone_meta=""):
    """기록 하나를 만든다. 학급은 지정값 → 제목/파일명(2-3, 2학년 3반) → 시간표 순으로 찾는다."""
    recorded_at = recorded_at or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    hint_text = hint_text or title or original_name
    kind = kind or ("상담" if "상담" in hint_text else "수업")
    conn = db.connect()
    try:
        if not class_id:
            class_id = _guess_class(conn, hint_text + " " + (transcript or "")[:120], recorded_at)
        audio_path = None
        if audio_src:
            hint = ""
            if class_id:
                c = db.row(conn, "SELECT grade, class_no FROM classes WHERE id=?", (class_id,))
                if c:
                    hint = "%s-%s" % (c["grade"], c["class_no"])
            audio_path = db.move_audio_into_archive(audio_src, recorded_at, hint, kind, copy=copy)
        status = "전사완료" if (transcript or "").strip() else "보관됨"
        rid = conn.execute("INSERT INTO recordings(class_id, kind, title, recorded_at, audio_path, original_name, "
                           "transcript, status, phone_meta) VALUES (?,?,?,?,?,?,?,?,?)",
                           (class_id, kind, title, recorded_at, audio_path, original_name,
                            transcript or "", status, phone_meta or "")).lastrowid
        conn.commit()
    finally:
        conn.close()
    if auto is not False:
        pipeline.auto_process(rid, force=bool(auto))
    return rid


def import_file(path, class_id=None, kind=None, title=None, recorded_at=None, auto=None, copy=True):
    """오디오/텍스트 파일을 보관함에 등록. 생성된 recording id 반환."""
    ext = os.path.splitext(path)[1].lower()
    recorded_at = recorded_at or _file_time(path)
    name = os.path.basename(path)
    title = title or os.path.splitext(name)[0]
    if ext in TEXT_EXTS:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        rid = create_recording(class_id, kind, title, recorded_at, transcript=text, original_name=name,
                               auto=auto)
        if not copy:
            os.remove(path)
        return rid
    text = extract_iphone_transcript(path) if ext in (".m4a", ".qta", ".mp4") else ""
    return create_recording(class_id, kind, title, recorded_at, audio_src=path, transcript=text,
                            original_name=name, copy=copy, auto=auto)


def _imported(conn, source, ext_id):
    return db.row(conn, "SELECT * FROM imported WHERE source=? AND ext_id=?", (source, ext_id))


def _mark(source, ext_id, sig="", body="", rid=None):
    conn = db.connect()
    conn.execute("INSERT OR REPLACE INTO imported(source, ext_id, sig, body, recording_id) VALUES (?,?,?,?,?)",
                 (source, ext_id, sig, body, rid))
    conn.commit()
    conn.close()


# ───────────────────────── 아이폰 내장 전사문 추출 ─────────────────────────

def extract_iphone_transcript(path):
    """아이폰에서 받아쓴 글을 m4a 안에서 꺼낸다.
    - 쓰담 앱: 가사(©lyr) 메타데이터에 받아쓴 글을 넣어 보낸다.
    - iOS 18+ 음성메모: 'tsrp' 영역에 JSON으로 저장한다."""
    try:
        if os.path.getsize(path) > 400 * 1024 * 1024:
            return ""
        with open(path, "rb") as f:
            data = f.read()
        text = _lyrics_text(data)
        if text:
            return text
        idx = data.find(b"tsrp")
        while idx != -1:
            size = int.from_bytes(data[idx - 4:idx], "big")
            payload = data[idx + 4: idx - 4 + size] if size > 8 else data[idx + 4:]
            text = _runs_text(payload)
            if text:
                return text
            idx = data.find(b"tsrp", idx + 4)
    except Exception:  # noqa
        pass
    return ""


def _lyrics_text(data):
    """MP4 ilst의 ©lyr 아톰: [크기]©lyr[크기]data[형식 4][로캘 4][UTF-8 글]"""
    idx = data.find(b"\xa9lyr")
    while idx != -1:
        if data[idx + 8:idx + 12] == b"data":
            dsize = int.from_bytes(data[idx + 4:idx + 8], "big")
            text = data[idx + 20:idx + 4 + dsize].decode("utf-8", "ignore").strip()
            if text:
                return text
        idx = data.find(b"\xa9lyr", idx + 4)
    return ""


def _runs_text(payload):
    try:
        start = payload.find(b"{")
        j = json.loads(payload[start:].decode("utf-8", "ignore").rstrip("\x00"))
    except ValueError:
        return ""
    a = j.get("attributedString", j)
    runs = a.get("runs") if isinstance(a, dict) else a
    if not isinstance(runs, list):
        return ""
    text = "".join(x for x in runs if isinstance(x, str)).strip()
    return text


# ───────────────────────── 1. 수신 폴더 ─────────────────────────

def inbox_dirs():
    settings = db.get_settings()
    dirs = []
    import platform_util
    cands = [settings.get("inbox_dir") or "", os.path.join(platform_util.icloud_drive_dir(), "세특녹음")] + SHORTCUTS_DIRS \
        + [platform_util.icloud_container_dir(c) for c in RECORDER_CONTAINERS]
    if platform_util.IS_WIN:  # iCloud for Windows는 앱 폴더를 앱 이름으로 보여 줄 수도 있음
        cands += [os.path.join(platform_util.icloud_drive_dir(), n) for n in ("쓰담", "쓰담 녹음", "Shortcuts\\쓰담")]
    for d in cands:
        d = os.path.expanduser(d)
        if d and os.path.isdir(d) and d not in dirs:
            dirs.append(d)
    return dirs


def scan_inbox():
    dirs = inbox_dirs()
    if not dirs:
        _status["inbox"] = "폴더 없음"
        return 0
    imported = 0
    for folder in dirs:
        imported += _scan_folder(folder)
    _status["inbox"] = "정상"
    return imported


def _scan_folder(folder):
    imported = 0
    done_dir = os.path.join(folder, "처리완료")
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        ext = os.path.splitext(name)[1].lower()
        if name.startswith(".") and name.endswith(".icloud"):
            # 아직 맥에 내려받지 않은 iCloud 파일 → 다운로드 요청 후 다음 검사 때 처리
            if sys.platform == "darwin":
                os.system("brctl download %s >/dev/null 2>&1" % _shq(path))
            continue
        if name.startswith(".") or not os.path.isfile(path) or ext not in AUDIO_EXTS | TEXT_EXTS:
            continue
        size = os.path.getsize(path)
        if _seen_sizes.get(path) != size:  # 동기화 중이면 크기가 안정될 때까지 대기
            _seen_sizes[path] = size
            continue
        try:
            import_file(path, copy=True)
            os.makedirs(done_dir, exist_ok=True)
            dest = os.path.join(done_dir, name)
            if os.path.exists(dest):
                dest = os.path.join(done_dir, "%s_%d%s" % (os.path.splitext(name)[0], int(time.time()), ext))
            os.rename(path, dest)
            imported += 1
        except Exception as e:  # noqa
            print("수신 폴더 가져오기 실패:", name, e)
        _seen_sizes.pop(path, None)
    return imported


# ───────────────────────── 1-1. 다운로드 폴더 (AirDrop · 퀵 셰어) ─────────────────────────

def _airdropped(path):
    """맥: AirDrop으로 받은 파일은 격리 속성에 'sharingd'가 붙는다."""
    if sys.platform != "darwin":
        return False
    try:
        r = subprocess.run(["xattr", "-p", "com.apple.quarantine", path], capture_output=True, text=True, timeout=5)
        return "sharingd" in r.stdout
    except Exception:  # noqa
        return False


def scan_downloads():
    """다운로드 폴더에서 '쓰담 '으로 시작하는 파일(휴대폰 앱에서 AirDrop·퀵 셰어로 보낸 것)과
    맥에서 AirDrop으로 받은 녹음을 가져온다. 원본은 그대로 두고 복사만 한다.
    기능을 켠 뒤에 들어온 파일만 대상 (예전 다운로드를 쓸어 오지 않게)."""
    import platform_util
    settings = db.get_settings()
    if settings.get("downloads_import") != "1":
        _status["downloads"] = "꺼짐"
        return 0
    since = settings.get("downloads_since") or ""
    if not since:
        db.set_settings({"downloads_since": str(time.time())})
        _status["downloads"] = "정상"
        return 0
    since_ts = float(since)
    folder = platform_util.downloads_dir()
    imported = 0
    conn = db.connect()
    try:
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            ext = os.path.splitext(name)[1].lower()
            if name.startswith(".") or not os.path.isfile(path) or ext not in AUDIO_EXTS | TEXT_EXTS:
                continue
            st = os.stat(path)
            if max(st.st_mtime, getattr(st, "st_birthtime", 0)) < since_ts:
                continue
            ours = name.startswith("쓰담 ") or name.startswith("쓰담_")
            if not ours and not (ext in AUDIO_EXTS and _airdropped(path)):
                continue
            key = "%s|%d|%d" % (name, st.st_size, int(st.st_mtime))
            if _imported(conn, "downloads", key):
                continue
            if _seen_sizes.get(path) != st.st_size:  # 받는 중이면 크기가 안정될 때까지 대기
                _seen_sizes[path] = st.st_size
                continue
            try:
                import_file(path, copy=True)
                _mark("downloads", key, "ok")
                imported += 1
            except Exception as e:  # noqa
                print("다운로드 폴더 가져오기 실패:", name, e)
            _seen_sizes.pop(path, None)
    finally:
        conn.close()
    _status["downloads"] = "정상"
    return imported


# ───────────────────────── 2. 음성메모 보관함 ─────────────────────────

def voicememo_dir():
    for d in VOICEMEMO_DIRS:
        d = os.path.expanduser(d)
        if os.path.isdir(d):
            return d
    return None


def voicememo_access():
    """('ok'|'no_permission'|'not_found', 경로)"""
    d = voicememo_dir()
    if not d:
        return "not_found", None
    try:
        os.listdir(d)
        return "ok", d
    except PermissionError:
        return "no_permission", d


def _voicememo_titles(folder):
    """CloudRecordings.db 에서 파일명 → 제목. 구조가 버전마다 달라 열 이름을 확인하며 읽는다."""
    src = os.path.join(folder, "CloudRecordings.db")
    if not os.path.exists(src):
        return {}
    tmp = tempfile.mkdtemp(prefix="seteuk-vm-")
    try:
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(src + suffix):
                shutil.copy2(src + suffix, os.path.join(tmp, "v.db" + suffix))
        conn = sqlite3.connect(os.path.join(tmp, "v.db"))
        cols = [r[1] for r in conn.execute("PRAGMA table_info(ZCLOUDRECORDING)")]
        if "ZPATH" not in cols:
            return {}
        title_cols = [c for c in ("ZENCRYPTEDTITLE", "ZCUSTOMLABELFORSORTING", "ZCUSTOMLABEL") if c in cols]
        if not title_cols:
            return {}
        out = {}
        for r in conn.execute("SELECT ZPATH, %s FROM ZCLOUDRECORDING" % ", ".join(title_cols)):
            title = next((t for t in r[1:] if t and str(t).strip()), "")
            if r[0]:
                out[os.path.basename(r[0])] = str(title)
        conn.close()
        return out
    except sqlite3.Error:
        return {}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def scan_voicememos():
    settings = db.get_settings()
    if settings.get("voicememo_enabled") != "1":
        _status["voicememo"] = "꺼짐"
        return 0
    state, folder = voicememo_access()
    if state != "ok":
        _status["voicememo"] = {"no_permission": "권한 필요", "not_found": "보관함 없음"}[state]
        return 0
    since = settings.get("voicememo_since") or ""
    keyword = (settings.get("voicememo_keyword") or "").strip()
    files = []
    for ext in ("m4a", "qta"):
        files += glob.glob(os.path.join(folder, "*." + ext)) + glob.glob(os.path.join(folder, "*", "*." + ext))
    titles = None
    imported = 0
    conn = db.connect()
    for path in sorted(files):
        name = os.path.basename(path)
        if _imported(conn, "voicememo", name):
            continue
        rec_at = _file_time(path)
        if since and rec_at < since[:16]:
            continue
        size = os.path.getsize(path)
        if size == 0 or _seen_sizes.get(path) != size:
            _seen_sizes[path] = size
            continue
        if titles is None:
            titles = _voicememo_titles(folder)
        title = titles.get(name) or "음성메모 " + rec_at
        if keyword and keyword not in title:
            _mark("voicememo", name, "skip")
            continue
        try:
            text = extract_iphone_transcript(path)
            rid = create_recording(title=title, recorded_at=rec_at, audio_src=path, transcript=text,
                                   original_name=name, copy=True)
            _mark("voicememo", name, "ok", rid=rid)
            imported += 1
        except Exception as e:  # noqa
            print("음성메모 가져오기 실패:", name, e)
        _seen_sizes.pop(path, None)
    conn.close()
    _status["voicememo"] = "정상"
    return imported


# ───────────────────────── 3. 메모 앱 ─────────────────────────

NOTES_JXA = r"""
function run(argv) {
  const app = Application('Notes');
  const target = argv[0];
  const out = [];
  app.accounts().forEach(function (acc) {
    acc.folders().forEach(function (f) {
      if (f.name() !== target) return;
      const ns = f.notes;
      const ids = ns.id(), names = ns.name(), bodies = ns.plaintext(), cds = ns.creationDate(), mds = ns.modificationDate();
      for (let i = 0; i < ids.length; i++) {
        out.push({id: ids[i], name: names[i], body: bodies[i], created: cds[i].getTime(), modified: mds[i].getTime()});
      }
    });
  });
  return JSON.stringify(out);
}
"""


def _ms_to_local(ms):
    return datetime.datetime.fromtimestamp(ms / 1000.0).strftime("%Y-%m-%d %H:%M")


def read_notes(folder_name):
    r = subprocess.run(["osascript", "-l", "JavaScript", "-e", NOTES_JXA, folder_name],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        err = r.stderr.strip()
        if "-1743" in err or "Not authorized" in err or "허가" in err:
            raise PermissionError("메모 앱 제어 권한이 없습니다. 시스템 설정 → 개인정보 보호 및 보안 → 자동화에서 허용하세요.")
        raise RuntimeError("메모 앱을 읽지 못했습니다: %s" % err[:200])
    return json.loads(r.stdout or "[]")


def scan_notes(force=False):
    """메모 앱 '세특' 폴더의 새 메모(또는 메모에 덧붙인 부분)를 가져온다.
    받아쓰는 중일 수 있으므로 마지막 수정 후 5분이 지난 메모만 가져온다(force=True면 즉시)."""
    settings = db.get_settings()
    if settings.get("notes_enabled") != "1":
        _status["notes"] = "꺼짐"
        return 0
    folder = (settings.get("notes_folder") or "세특").strip()
    try:
        notes = read_notes(folder)
    except PermissionError as e:
        _status["notes"] = "권한 필요"
        raise
    except Exception as e:  # noqa
        _status["notes"] = "오류: %s" % e
        raise
    imported = 0
    now_ms = time.time() * 1000
    conn = db.connect()
    for n in notes:
        body = (n.get("body") or "").strip()
        title = (n.get("name") or "").strip()
        # 제목만 있는 빈 메모 제외
        if not body or body == title:
            continue
        if not force and now_ms - n["modified"] < 5 * 60 * 1000:
            continue
        sig = str(n["modified"])
        prev = _imported(conn, "notes", n["id"])
        if prev and prev["sig"] == sig:
            continue
        rec_title, text, rec_at = title or "메모", body, _ms_to_local(n["created"])
        if prev:
            old = prev["body"] or ""
            if body == old:
                _mark("notes", n["id"], sig, body, prev["recording_id"])
                continue
            if body.startswith(old):
                text = body[len(old):].strip()
                rec_title, rec_at = "%s (추가분)" % (title or "메모"), _ms_to_local(n["modified"])
            else:
                rec_title, rec_at = "%s (수정본)" % (title or "메모"), _ms_to_local(n["modified"])
            if not text:
                _mark("notes", n["id"], sig, body, prev["recording_id"])
                continue
        try:
            rid = create_recording(title=rec_title, recorded_at=rec_at, transcript=text, original_name="메모 앱",
                                   hint_text=title)
            _mark("notes", n["id"], sig, body, rid)
            imported += 1
        except Exception as e:  # noqa
            print("메모 가져오기 실패:", title, e)
    conn.close()
    _status["notes"] = "정상"
    return imported


def notes_running():
    import platform_util
    if not platform_util.IS_MAC:
        return False
    return subprocess.run(["pgrep", "-x", "Notes"], capture_output=True).returncode == 0


# ───────────────────────── 감시 루프 ─────────────────────────

def scan_all(force_notes=False):
    with _scan_lock:
        out = {"inbox": 0, "voicememo": 0, "notes": 0, "downloads": 0, "errors": []}
        for key, fn in (("inbox", scan_inbox), ("voicememo", scan_voicememos), ("downloads", scan_downloads)):
            try:
                out[key] = fn()
            except Exception as e:  # noqa
                out["errors"].append("%s: %s" % (key, e))
        if force_notes:
            try:
                out["notes"] = scan_notes(force=True)
            except Exception as e:  # noqa
                out["errors"].append(str(e))
        return out


def scan_once():
    """(이전 버전 호환) 녹음함의 '가져오기' 버튼."""
    r = scan_all(force_notes=db.get_settings().get("notes_enabled") == "1")
    total = r["inbox"] + r["voicememo"] + r["notes"] + r["downloads"]
    msg = "새 기록 %d개 가져옴 (iCloud·폴더 %d · 음성메모 %d · 메모 %d · AirDrop/다운로드 %d)" % (
        total, r["inbox"], r["voicememo"], r["notes"], r["downloads"])
    if r["errors"]:
        msg += " / " + " / ".join(r["errors"])
    return {"ok": True, "imported": total, "message": msg, **r}


def _loop():
    tick = 0
    while True:
        try:
            scan_all()
        except Exception as e:  # noqa
            print("가져오기 오류:", e)
        # 메모 앱: 열려 있으면 3분마다, 닫혀 있으면 30분마다 (열어야 iCloud 동기화가 됨)
        import platform_util
        if platform_util.IS_MAC and db.get_settings().get("notes_enabled") == "1" and (tick % 9 == 0) \
                and (notes_running() or tick % 90 == 0):
            try:
                with _scan_lock:
                    scan_notes()
            except Exception as e:  # noqa
                print("메모 가져오기 오류:", e)
        tick += 1
        time.sleep(20)


def start():
    # 테스트용 데이터 폴더(SETEUK_DATA)로 띄운 서버는 진짜 iCloud·다운로드·음성메모를 건드리지 않는다
    if os.environ.get("SETEUK_DATA") and os.environ.get("SSEUDAM_REAL_INBOX") != "1":
        print("테스트 데이터 폴더 사용 중 — 자동 가져오기를 끕니다")
        return
    threading.Thread(target=_loop, daemon=True, name="importer").start()
