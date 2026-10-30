"""기기 내 Apple AI로 기록을 학생별로 정리한다. 별도 모델은 사용하지 않는다."""
import json
import os
import subprocess
import time
import db

APPLE_TEXT = {
    "ready": "이 맥에서 바로 쓸 수 있어요.",
    "notEnabled": "시스템 설정 → Apple Intelligence 및 Siri에서 Apple Intelligence를 켜면 쓸 수 있어요.",
    "notReady": "기기 안 AI 모델을 내려받는 중이에요. 잠시 뒤 다시 확인해 주세요.",
    "notEligible": "이 맥은 기기 안 AI를 지원하지 않아요 (Apple Silicon 맥 + 지원 지역·언어 필요).",
    "unsupportedOS": "macOS 26 이상에서 쓸 수 있어요.",
    "notMac": "지원되는 맥에서 사용할 수 있어요. 다른 기기에서는 이름 기준으로 정리해요.",
    "missing": "기기 안 AI 도우미가 없어요 (개발 실행이면 macos/bin/sseudam-ai 를 빌드하세요).",
}

_apple_cache = {"t": 0, "state": None}

def helper():
    name = "sseudam-ai"
    for c in (os.environ.get("SSEUDAM_AI_HELPER", ""),
              os.path.join(os.environ.get("SETEUK_BIN", ""), name),
              os.path.join(db.BASE_DIR, "macos", "bin", name)):  # 개발 실행
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None

def apple_state(fresh=False):
    if not fresh and _apple_cache["state"] and time.time() - _apple_cache["t"] < 60:
        return _apple_cache["state"]
    if not _is_mac():
        _apple_cache.update(t=time.time(), state="notMac")
        return "notMac"
    st = "missing"
    h = helper()
    if h:
        try:
            out = subprocess.run([h, "status"], capture_output=True, text=True, timeout=15).stdout
            st = json.loads(out.strip().splitlines()[-1]).get("state") or "notEligible"
        except Exception:  # noqa
            st = "notEligible"
    _apple_cache.update(t=time.time(), state=st)
    return st

def apple_ready():
    return apple_state() == "ready"

def _apple(cmd, payload, timeout=180):
    h = helper()
    if not h:
        raise RuntimeError(APPLE_TEXT["missing"])
    p = subprocess.run([h, cmd], input=json.dumps(payload, ensure_ascii=False), capture_output=True,
                       text=True, timeout=timeout)
    lines = (p.stdout or "").strip().splitlines()
    data = json.loads(lines[-1]) if lines else {}
    if data.get("error") or p.returncode != 0:
        raise RuntimeError(data.get("error") or (p.stderr or "기기 안 AI 오류").strip()[:300])
    return data

def owners(engine, settings, sentences, names, known, batch=30):
    """문장마다 학생 번호(1부터) 또는 0. known = {문장 index(0부터): 학생 번호} (이름이 나온 문장).
    긴 녹음은 30문장씩 나눠서 (작은 모델의 문맥 길이 때문)."""
    out = []
    for b in range(0, len(sentences), batch):
        chunk = sentences[b:b + batch]
        kn = {i - b: k for i, k in known.items() if b <= i < b + batch}
        if engine == "apple":
            res = _apple("owners", {"sentences": chunk, "names": names,
                                    "known": {str(i + 1): k for i, k in kn.items()}})["owners"]
        else:
            raise ValueError("기기 안 AI만 지원해요.")
        out += [x if 0 <= x <= len(names) else 0 for x in res][:len(chunk)] + [0] * max(0, len(chunk) - len(res))
    return out

def _is_win():
    import platform_util
    return platform_util.IS_WIN

def _is_mac():
    import platform_util
    return platform_util.IS_MAC

def machine_info():
    import platform
    ram = mac_ram_gb()
    if _is_mac():
        try:
            chip = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
        except Exception:  # noqa
            chip = ""
        chip = chip or ("Apple Silicon" if _arch() == "arm64" else "인텔")
        return {"os": "mac", "chip": chip, "ram": ram}
    return {"os": "win" if _is_win() else "other", "chip": (platform.processor() or platform.machine())[:60], "ram": ram}

def mac_ram_gb():
    """컴퓨터 메모리(GB). 맥은 sysctl, 윈도우는 GlobalMemoryStatusEx."""
    try:
        if _is_win():
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return round(m.ullTotalPhys / 2**30)
        return round(int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout) / 2**30)
    except Exception:  # noqa
        return 0


def status(settings):
    st = apple_state(fresh=True)
    return {"apple": {"state": st, "text": APPLE_TEXT.get(st, "")}}
