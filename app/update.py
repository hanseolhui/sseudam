# -*- coding: utf-8 -*-
"""GitHub 릴리스로 프로그램 업데이트.

- 코드(app 폴더)만 ~/Library/Application Support/쓰담/code/<버전>/ 에 내려받는다.
- 학생 데이터(data 폴더)는 건드리지 않는다.
- 앱 실행기는 '앱에 들어 있는 코드'와 '내려받은 코드' 중 가장 높은 버전을 실행한다.
"""
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import subprocess
import zipfile

import db
import gemini
import version

CODE_DIR = os.path.join(db.SUPPORT_DIR, "code")
_cache = {"at": 0, "data": None}


def vtuple(v):
    nums = re.findall(r"\d+", str(v or ""))
    return tuple(int(x) for x in nums[:3]) + (0,) * (3 - len(nums[:3]))


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "sseudam/" + version.VERSION,
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout, context=gemini._CTX)


def check(force=False):
    import platform_util
    if platform_util.IS_STORE:   # 스토어판은 마이크로소프트 스토어가 업데이트 (앱이 스스로 코드를 받지 않음)
        return {"enabled": False, "store": True, "current": version.VERSION, "message": "마이크로소프트 스토어에서 자동으로 업데이트돼요."}
    if not version.UPDATE_REPO:
        return {"enabled": False, "current": version.VERSION}
    if not force and _cache["data"] and time.time() - _cache["at"] < 3600:
        return _cache["data"]
    try:
        resp = _get("https://api.github.com/repos/%s/releases/latest" % version.UPDATE_REPO)
        rel = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            out = {"enabled": True, "current": version.VERSION, "available": False, "message": "아직 배포된 버전이 없습니다."}
            return out
        return {"enabled": True, "current": version.VERSION, "available": False, "error": "업데이트 확인 실패 (HTTP %s)" % e.code}
    except Exception as e:  # noqa
        return {"enabled": True, "current": version.VERSION, "available": False, "error": "업데이트 확인 실패: %s" % e}
    latest = (rel.get("tag_name") or "").lstrip("vV")
    asset = next((a for a in rel.get("assets", []) if a.get("name") == version.UPDATE_ASSET), None)
    out = {
        "enabled": True, "current": version.VERSION, "latest": latest,
        "available": bool(asset) and vtuple(latest) > vtuple(version.VERSION),
        "notes": rel.get("body") or "", "name": rel.get("name") or latest,
        "published_at": rel.get("published_at"),
        "url": asset.get("browser_download_url") if asset else None,
        "digest": (asset or {}).get("digest") or "",
    }
    _cache.update(at=time.time(), data=out)
    return out


def apply():
    info = check(force=True)
    if not info.get("available"):
        raise ValueError(info.get("error") or "설치할 새 버전이 없습니다.")
    latest = info["latest"]
    os.makedirs(CODE_DIR, exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix="seteuk-update-", dir=CODE_DIR)
    try:
        zpath = os.path.join(tmpdir, "update.zip")
        with _get(info["url"], timeout=120) as resp, open(zpath, "wb") as f:
            shutil.copyfileobj(resp, f)
        if info["digest"].startswith("sha256:"):
            h = hashlib.sha256()
            with open(zpath, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != info["digest"].split(":", 1)[1]:
                raise ValueError("내려받은 파일이 손상되었습니다. 다시 시도하세요.")
        extract = os.path.join(tmpdir, "x")
        with zipfile.ZipFile(zpath) as z:
            for m in z.namelist():
                if m.startswith("/") or ".." in m.split("/"):
                    raise ValueError("잘못된 업데이트 파일입니다.")
            z.extractall(extract)
        ver_file = os.path.join(extract, "app", "version.py")
        if not os.path.exists(os.path.join(extract, "app", "server.py")) or not os.path.exists(ver_file):
            raise ValueError("업데이트 파일 구성이 올바르지 않습니다.")
        with open(ver_file, encoding="utf-8") as f:
            m = re.search(r'VERSION\s*=\s*"([^"]+)"', f.read())
        if not m or vtuple(m.group(1)) != vtuple(latest):
            raise ValueError("업데이트 파일의 버전 정보가 맞지 않습니다.")
        target = os.path.join(CODE_DIR, latest)
        if os.path.exists(target):
            shutil.rmtree(target)
        os.rename(extract, target)
        _cleanup_old(keep=latest)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    restart(os.path.join(CODE_DIR, latest, "app", "server.py"))
    return {"ok": True, "version": latest}


def _cleanup_old(keep):
    """최근 2개 버전만 남긴다 (문제 생기면 이전 버전으로 돌아갈 수 있게)."""
    vers = sorted((d for d in os.listdir(CODE_DIR) if re.match(r"^\d+\.\d+", d)), key=vtuple)
    for d in vers[:-2]:
        if d != keep:
            shutil.rmtree(os.path.join(CODE_DIR, d), ignore_errors=True)


def restart(server_path):
    import platform_util

    def go():
        time.sleep(1.0)
        os.environ["SETEUK_NO_BROWSER"] = "1"
        if platform_util.IS_WIN:  # 윈도우에는 진짜 execv가 없음 → 새 프로세스를 띄우고 종료
            subprocess.Popen([sys.executable, server_path], env=dict(os.environ), creationflags=0x00000008 | 0x00000200)
            os._exit(0)
        os.execv(sys.executable, [sys.executable, server_path])
    threading.Thread(target=go, daemon=True).start()


# ───────────────────────── 앱 셸(.app) 업데이트 ─────────────────────────

def shell_version():
    try:
        return int(os.environ.get("SETEUK_SHELL") or 1)
    except ValueError:
        return 1


def shell_outdated():
    """예전 맥 앱(1.1, 창 없는 실행기)에서 돌 때만 '새 앱으로 바꾸기'를 안내. 개발 실행·윈도우는 해당 없음."""
    import platform_util
    return bool(platform_util.IS_MAC and os.environ.get("SETEUK_APP")) and shell_version() < version.SHELL_REQUIRED


APP_BUNDLE = "쓰담.app"
OLD_BUNDLES = ["세특도우미.app"]


def _installed_app_path():
    """지금 설치된 앱 위치 (예전 이름 포함)."""
    p = os.environ.get("SETEUK_APP_PATH")
    if p and p.endswith(".app"):
        return p
    here = os.path.abspath(os.path.join(db.APP_DIR, "..", "..", ".."))
    if here.endswith(".app"):
        return here
    for folder in ("/Applications", os.path.expanduser("~/Applications")):
        for name in [APP_BUNDLE] + OLD_BUNDLES:
            if os.path.isdir(os.path.join(folder, name)):
                return os.path.join(folder, name)
    return os.path.join("/Applications", APP_BUNDLE)


def _asset_url(name):
    resp = _get("https://api.github.com/repos/%s/releases/latest" % version.UPDATE_REPO)
    rel = json.loads(resp.read().decode("utf-8"))
    a = next((x for x in rel.get("assets", []) if x.get("name") == name), None)
    if not a:
        raise ValueError("최신 릴리스에 %s 파일이 없습니다." % name)
    return a["browser_download_url"], a.get("digest") or ""


def _download(url, dest, digest=""):
    with _get(url, timeout=300) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)
    if digest.startswith("sha256:"):
        h = hashlib.sha256()
        with open(dest, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != digest.split(":", 1)[1]:
            raise ValueError("내려받은 파일이 손상되었습니다. 다시 시도하세요.")


def install_app():
    """최신 쓰담.app 을 받아 설치 위치에 교체하고, 새 앱을 실행한 뒤 지금 서버를 끝낸다."""
    url, digest = _asset_url(version.APP_ASSET)
    current = _installed_app_path()
    parent = os.path.dirname(current)
    if not os.access(parent, os.W_OK):
        parent = os.path.expanduser("~/Applications")
        os.makedirs(parent, exist_ok=True)
    target = os.path.join(parent, APP_BUNDLE)
    tmp = tempfile.mkdtemp(prefix="seteuk-app-")
    zpath = os.path.join(tmp, "app.zip")
    _download(url, zpath, digest)
    r = subprocess.run(["ditto", "-x", "-k", zpath, tmp], capture_output=True)
    apps = [d for d in os.listdir(tmp) if d.endswith(".app")]
    new_app = os.path.join(tmp, apps[0]) if apps else ""
    if r.returncode != 0 or not new_app:
        raise ValueError("앱 파일을 풀지 못했습니다.")
    old = target + ".old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.exists(target):
        os.rename(target, old)
    try:
        shutil.move(new_app, target)
    except Exception:
        if os.path.exists(old):
            os.rename(old, target)
        raise
    shutil.rmtree(old, ignore_errors=True)
    shutil.rmtree(tmp, ignore_errors=True)
    # 예전 이름(세특도우미.app)은 정리
    for name in OLD_BUNDLES:
        legacy = os.path.join(parent, name)
        if os.path.isdir(legacy) and legacy != target:
            shutil.rmtree(legacy, ignore_errors=True)
    # 지금 서버가 내려간 뒤 새 앱이 서버를 새로 띄우도록 잠시 뒤 실행
    subprocess.Popen(["/bin/bash", "-c", "sleep 2; open %s" % shlex_quote(target)], start_new_session=True)
    threading.Thread(target=lambda: (time.sleep(0.8), os._exit(0)), daemon=True).start()
    return {"ok": True, "path": target}


def shlex_quote(s):
    return "'" + s.replace("'", "'\\''") + "'"


def fetch_whisper_binary(dest_dir):
    """앱 안에 Whisper 실행 파일이 없을 때(예전 앱) 릴리스에서 받아온다."""
    url, digest = _asset_url(version.WHISPER_ASSET)
    os.makedirs(dest_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="seteuk-wbin-")
    try:
        zpath = os.path.join(tmp, "w.zip")
        _download(url, zpath, digest)
        with zipfile.ZipFile(zpath) as z:
            data = z.read("whisper-cli")
        out = os.path.join(dest_dir, "whisper-cli")
        with open(out, "wb") as f:
            f.write(data)
        os.chmod(out, 0o755)
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ───────────────────────── 자동 업데이트 ─────────────────────────
# 2시간마다(그리고 잠자기에서 깬 뒤) 새 버전을 확인하고, 선생님이 쉬는 틈
# (20분 동안 아무 조작 없음 · AI 작업 없음 · 모델 내려받기 없음)에만 바꿔 끼운다.

LAST_POST = [time.time()]          # server.Handler 가 POST 요청마다 갱신
_auto = {"pending": None, "fails": [], "last_check": 0, "state": "대기", "error": ""}


def _env_num(name, default):
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


IDLE_SEC = _env_num("SSEUDAM_UPDATE_IDLE_SEC", 20 * 60)
FIRST_SEC = _env_num("SSEUDAM_UPDATE_FIRST_SEC", 120)
EVERY_SEC = _env_num("SSEUDAM_UPDATE_EVERY_SEC", 2 * 3600)
TICK_SEC = _env_num("SSEUDAM_UPDATE_TICK_SEC", 60)


def _dry_run():
    # 테스트 데이터(SETEUK_DATA)로 띄운 서버는 진짜 코드 폴더·앱을 절대 바꾸지 않는다
    return bool(os.environ.get("SETEUK_DATA")) or os.environ.get("SSEUDAM_UPDATE_DRYRUN") == "1"


def _log(msg):
    print("[자동 업데이트] %s" % msg)
    try:
        with open(os.path.join(db.DATA_DIR, "update.log"), "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except OSError:
        pass


def _check_info():
    fake = os.environ.get("SSEUDAM_UPDATE_FAKE_LATEST")  # 테스트: 가짜 새 버전
    if fake and _dry_run():
        return {"enabled": True, "current": version.VERSION, "latest": fake, "notes": "테스트용 가짜 릴리스",
                "available": vtuple(fake) > vtuple(version.VERSION)}
    return check(force=True)


def busy_reason():
    """지금 업데이트하면 안 되는 이유 (없으면 빈 문자열)."""
    idle = time.time() - LAST_POST[0]
    if idle < IDLE_SEC:
        return "사용 중 (%d초 전 조작)" % idle
    conn = db.connect()
    try:
        n = conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('대기','진행중')").fetchone()[0]
    finally:
        conn.close()
    if n:
        return "AI 작업 %d개 진행 중" % n
    try:
        import whisper
        if any((m.get("download") or {}).get("status") == "downloading" for m in whisper.status().get("models", [])):
            return "받아쓰기 모델 내려받는 중"
    except Exception:  # noqa
        pass
    return ""


def mark_updating(frm, to, notes=""):
    db.set_settings({"updated_from": frm, "updated_to": to, "updated_notes": (notes or "")[:3000]})


def just_updated(consume=True):
    """방금 업데이트로 다시 켜졌으면 {from,to,notes} 한 번만 돌려준다."""
    s = db.get_settings()
    frm = s.get("updated_from") or ""
    if not frm:
        return None
    out = None
    if vtuple(version.VERSION) > vtuple(frm):
        out = {"from": frm, "to": version.VERSION, "notes": s.get("updated_notes") or "",
               "url": "https://github.com/%s/releases/tag/v%s" % (version.UPDATE_REPO, version.VERSION) if version.UPDATE_REPO else ""}
    elif s.get("updated_to") == "app" and shell_version() >= version.SHELL_REQUIRED:
        out = {"from": frm, "to": version.VERSION, "notes": "", "url": "", "app": True}
    if consume and (out or vtuple(version.VERSION) >= vtuple(frm)):
        db.set_settings({"updated_from": "", "updated_to": "", "updated_notes": ""})
    return out


def _backed_off():
    day = time.time() - 86400
    _auto["fails"] = [t for t in _auto["fails"] if t > day]
    return len(_auto["fails"]) >= 3


def _install(info):
    db.backup_to(os.path.join(db.BACKUP_DIR, "seteuk-before-auto-update-%s.db" % time.strftime("%Y%m%d-%H%M%S")))
    if info.get("shell"):
        mark_updating(version.VERSION, "app")
        if _dry_run():
            _log("(테스트) 새 앱 설치를 건너뜀")
            _auto["state"] = "테스트: 앱 설치했다고 가정"
            return
        install_app()
        return
    mark_updating(version.VERSION, info["latest"], info.get("notes"))
    if _dry_run():
        _log("(테스트) %s 설치를 건너뜀" % info["latest"])
        _auto["state"] = "테스트: %s 설치했다고 가정" % info["latest"]
        return
    apply()


def auto_tick(now=None):
    """한 번 돌기: 필요하면 확인하고, 쉬는 틈이면 설치. 테스트에서 직접 부를 수 있음."""
    now = now or time.time()
    if db.get_settings().get("auto_update", "1") != "1":
        _auto["state"] = "꺼짐"
        return "off"
    if _backed_off():
        _auto["state"] = "실패가 잦아 하루 쉬는 중"
        return "backoff"
    if now - _auto["last_check"] >= EVERY_SEC or (_auto["pending"] is None and _auto["last_check"] == 0):
        _auto["last_check"] = now
        if shell_outdated():
            _auto["pending"] = {"shell": True, "latest": "app"}
        else:
            info = _check_info()
            if info.get("error"):
                _log("확인 실패: %s" % info["error"])
            _auto["pending"] = info if info.get("available") else None
        if _auto["pending"]:
            _log("새 버전 있음: %s" % _auto["pending"].get("latest"))
    p = _auto["pending"]
    if not p:
        _auto["state"] = "최신"
        return "uptodate"
    why = busy_reason()
    if why:
        _auto["state"] = "새 버전 %s 대기 — %s" % (p.get("latest"), why)
        return "busy"
    try:
        _log("설치 시작: %s → %s" % (version.VERSION, p.get("latest")))
        _install(p)
        _auto["pending"] = None if _dry_run() else p
        return "installed"
    except Exception as e:  # noqa — 실패해도 지금 버전은 그대로 동작
        _auto["fails"].append(time.time())
        _auto["pending"] = None   # 다음 확인 주기(2시간 뒤)에 다시 시도
        _auto["error"] = str(e)
        db.set_settings({"updated_from": "", "updated_to": "", "updated_notes": ""})
        _log("설치 실패 (%d번째): %s" % (len(_auto["fails"]), e))
        return "failed"


def _auto_loop():
    time.sleep(FIRST_SEC)
    last = time.time()
    while True:
        now = time.time()
        if now - last > TICK_SEC + 300:   # 시계가 크게 건너뜀 = 잠자기에서 깸 → 바로 확인
            _auto["last_check"] = 0
            _auto["pending"] = None
        last = now
        try:
            auto_tick(now)
        except Exception as e:  # noqa
            _log("오류: %s" % e)
        time.sleep(TICK_SEC)


def auto_status():
    return {"state": _auto["state"], "error": _auto["error"], "pending": (_auto["pending"] or {}).get("latest")}


def start_auto():
    if os.environ.get("SETEUK_DATA") and os.environ.get("SSEUDAM_TEST_AUTOUPDATE") != "1":
        return False
    if not version.UPDATE_REPO and not os.environ.get("SSEUDAM_UPDATE_FAKE_LATEST"):
        return False
    threading.Thread(target=_auto_loop, daemon=True, name="auto-update").start()
    return True
