"""사용 정보 보내기 — 문제 해결·업데이트 지원용 (하루 한 번).

늘 보내는 것(익명): 무작위 설치 번호, 버전, 운영체제, 컴퓨터 사양(칩·메모리·그래픽), 고른 AI, 받아쓰기 방식,
                  학급·학생·기록·녹음 '개수'(숫자만).
선생님이 직접 적고 '개인정보 수집·이용'에 동의한 경우만: 이름, 이메일, 학교, 지역, 학교급, 과목, 학년, 담임 여부,
휴대폰(적은 경우), 소식 받기 동의.
학생 이름·명단·녹음·관찰기록·초안 내용은 절대 보내지 않는다. 설정에서 끌 수 있다.
"""
import json
import os
import platform
import re
import subprocess
import threading
import time
import urllib.request
import uuid

import db
import version

URL = os.environ.get("SSEUDAM_PING_URL", "https://apps.seoriarts.com/api/ping")
# 선생님 정보 (설정 이름) — 바뀌면 바로 보냄
PROFILE_KEYS = ("share_info", "contact_email", "teacher_name", "org_type", "school_name", "school_level", "region_sido", "region_sigungu",
                "teacher_subject", "teacher_grades", "homeroom", "phone", "marketing_ok")
EVERY = 20 * 3600          # 하루 한 번쯤 (켜 둔 채로 다음 날이 되면)
_lock = threading.Lock()


def _enabled():
    # 테스트 데이터로 띄운 서버는 보내지 않음 (SSEUDAM_PING_TEST=1 일 때만)
    if os.environ.get("SETEUK_DATA") and os.environ.get("SSEUDAM_PING_TEST") != "1":
        return False
    return db.get_settings().get("telemetry", "1") == "1"


def install_id():
    s = db.get_settings()
    iid = s.get("install_id") or ""
    if not re.fullmatch(r"[0-9a-f-]{36}", iid):
        iid = str(uuid.uuid4())
        db.set_settings({"install_id": iid})
    return iid


def _run(cmd, timeout=5):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              **({"creationflags": 0x08000000} if os.name == "nt" else {})).stdout.strip()
    except Exception:  # noqa
        return ""


def _os_full():
    if os.name == "nt":
        return "Windows %s (%s)" % (platform.release(), platform.version())
    v = _run(["sw_vers", "-productVersion"])
    return "macOS %s" % v if v else platform.platform()


def _gpu():
    if os.name == "nt":
        out = _run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"], timeout=8)
        return ", ".join(x.strip() for x in out.splitlines() if x.strip())[:80]
    return ""   # 맥은 칩 안에 그래픽이 들어 있어 칩 이름으로 충분


def _ai(s):
    import pipeline
    c = s.get("ai_choice") or ""
    if not c:
        eng = pipeline.seg_engine(s)
        c = {"local": "builtin" if s.get("local_ai_url") == "builtin" else "external", "rules": "manual"}.get(eng, eng)
    model = {"builtin": s.get("local_ai_model"), "external": s.get("local_ai_model"), "gemini": s.get("gemini_model")}.get(c, "")
    return c, model or ""


def payload():
    import localai
    s = db.get_settings()
    info = localai.machine_info()
    conn = db.connect()
    try:
        count = lambda t: conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        counts = {k: count(k) for k in ("classes", "students", "notes", "recordings")}
    finally:
        conn.close()
    ai, ai_model = _ai(s)
    os_full = _os_full()
    body = {
        "id": install_id(), "app": "sseudam", "version": version.VERSION, "lang": "ko",
        "os": re.sub(r"\s+", "-", os_full.split(" (")[0]), "os_full": os_full,
        "platform": "win" if os.name == "nt" else "mac", "chip": info.get("chip") or "", "ram_gb": info.get("ram") or 0,
        "gpu": _gpu(), "ai": ai, "ai_model": ai_model, "stt": s.get("stt_engine") or "whisper",
        **counts,
        "share": False,
    }
    if s.get("share_info") == "1":
        g = lambda k: (s.get(k) or "").strip()
        body.update(share=True, email=g("contact_email"), name=g("teacher_name"), school=g("school_name"),
                    org_type=g("org_type"), region_sido=g("region_sido"), region_sigungu=g("region_sigungu"), school_level=g("school_level"),
                    subjects=g("teacher_subject"), grades=g("teacher_grades"), homeroom=g("homeroom"), phone=g("phone"),
                    marketing=s.get("marketing_ok") == "1")
    return body


def send(force=False):
    """보내기. force 가 아니면 하루에 한 번만."""
    if not _enabled():
        return False
    with _lock:
        last = float(db.get_settings().get("last_ping") or 0)
        if not force and time.time() - last < EVERY:
            return False
        try:
            data = json.dumps(payload(), ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(URL, data=data, headers={"Content-Type": "application/json", "User-Agent": "sseudam/" + version.VERSION})
            import gemini
            with urllib.request.urlopen(req, timeout=15, context=gemini._CTX) as r:
                r.read()
            db.set_settings({"last_ping": str(int(time.time()))})
            return True
        except Exception as e:  # noqa — 인터넷이 안 돼도 쓰담은 그대로
            print("[사용 정보] 보내지 못함:", e)
            return False


def send_async(force=False):
    threading.Thread(target=send, kwargs={"force": force}, daemon=True, name="ping-now").start()


def _loop():
    time.sleep(90)
    while True:
        send()
        time.sleep(3600)


def start():
    threading.Thread(target=_loop, daemon=True, name="ping").start()
