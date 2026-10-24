# -*- coding: utf-8 -*-
"""쓰담 윈도우 실행기 (pythonw.exe 로 실행 — 검은 창 없음).
서버가 안 떠 있으면 띄우고, Edge '앱 모드' 창으로 화면을 연다."""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("SETEUK_PORT", "8765"))
URL = "http://127.0.0.1:%d/" % PORT
# 마이크로소프트 스토어판(sseudam_launch 가 SSEUDAM_MSIX=1 로 실행): AppData 가 앱 전용으로 격리되므로 사용자 폴더 아래에
STORE = os.environ.get("SSEUDAM_MSIX") == "1"
SUPPORT = (os.path.join(os.environ.get("USERPROFILE") or os.path.expanduser("~"), "쓰담") if STORE
           else os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "쓰담"))
PYTHONW = os.path.join(HERE, "python", "pythonw.exe")
NO_WINDOW = 0x08000000
DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def alive():
    try:
        with urllib.request.urlopen(URL + "api/version", timeout=1) as r:
            return json.loads(r.read().decode("utf-8")).get("version")
    except Exception:
        return None


def ver(app_dir):
    try:
        with open(os.path.join(app_dir, "version.py"), encoding="utf-8") as f:
            m = re.search(r'VERSION\s*=\s*"([^"]+)"', f.read())
        return tuple(int(x) for x in re.findall(r"\d+", m.group(1))[:3])
    except Exception:
        return None


def pick_code():
    """설치된 코드와 앱 안 업데이트로 받은 코드 중 높은 버전 (스토어판은 스토어가 업데이트하므로 설치된 코드만)"""
    best, best_v = os.path.join(HERE, "app"), ver(os.path.join(HERE, "app")) or (0,)
    if STORE:
        return best
    root = os.path.join(SUPPORT, "code")
    if os.path.isdir(root):
        for d in os.listdir(root):
            app = os.path.join(root, d, "app")
            v = ver(app)
            if v and v > best_v and os.path.exists(os.path.join(app, "server.py")):
                best, best_v = app, v
    return best


def message(text):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, "쓰담", 0x40)
    except Exception:
        pass


def start_server():
    os.makedirs(SUPPORT, exist_ok=True)
    env = dict(os.environ, SETEUK_APP="1", SETEUK_NO_BROWSER="1", SETEUK_BIN=os.path.join(HERE, "bin"),
               SETEUK_PORT=str(PORT), PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    log = open(os.path.join(SUPPORT, "server.log"), "a", encoding="utf-8")
    log.write("=== %s 시작: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), pick_code()))
    log.flush()
    subprocess.Popen([PYTHONW, os.path.join(pick_code(), "server.py")], env=env, stdout=log, stderr=log,
                     stdin=subprocess.DEVNULL, creationflags=DETACHED | NO_WINDOW, close_fds=True, cwd=HERE)


def edge():
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
        if base:
            p = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
            if os.path.exists(p):
                return p
    return None


def open_window():
    e = edge()
    if e:
        profile = os.path.join(SUPPORT, "window")
        subprocess.Popen([e, "--app=" + URL, "--user-data-dir=" + profile, "--no-first-run", "--no-default-browser-check",
                          "--window-size=1280,860", "--disable-features=Translate,msEdgeSidebarV2"], creationflags=DETACHED)
    else:
        webbrowser.open(URL)


def main():
    if not alive():
        start_server()
        for _ in range(60):
            time.sleep(0.5)
            if alive():
                break
        else:
            message("쓰담을 시작하지 못했습니다.\n로그: %s" % os.path.join(SUPPORT, "server.log"))
            return
    open_window()


if __name__ == "__main__":
    main()
