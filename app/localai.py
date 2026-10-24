"""내 맥 안에서 도는 AI — 녹음 내용이 맥 밖으로 나가지 않는다.

1) 기기 안 AI (애플 Foundation Models): macOS 26+ · 애플 인텔리전스. 설치할 것 없음. 앱 안의 sseudam-ai 도우미가 처리.
2) 내 맥 AI 앱 (Ollama · LM Studio): 선생님이 따로 설치한 모델. OpenAI 호환 주소(localhost)로 부른다.

학생별 분리는 아이폰 쓰담과 같은 방식: 이름이 나온 문장은 규칙으로 정하고, 이름 없이 이어지는 문장
("그 친구는…", "다만…")만 AI가 '그 녹음에 이름이 나온 학생' 중에서 고른다 → 없는 학생을 지어낼 수 없다.
"""
import json
import os
import re
import subprocess
import time
import urllib.request

import db

PRESETS = [
    {"name": "Ollama", "url": "http://127.0.0.1:11434/v1"},
    {"name": "LM Studio", "url": "http://127.0.0.1:1234/v1"},
]

APPLE_TEXT = {
    "ready": "이 맥에서 바로 쓸 수 있어요.",
    "notEnabled": "시스템 설정 → Apple Intelligence 및 Siri에서 Apple Intelligence를 켜면 쓸 수 있어요.",
    "notReady": "기기 안 AI 모델을 내려받는 중이에요. 잠시 뒤 다시 확인해 주세요.",
    "notEligible": "이 맥은 기기 안 AI를 지원하지 않아요 (Apple Silicon 맥 + 지원 지역·언어 필요).",
    "unsupportedOS": "macOS 26 이상에서 쓸 수 있어요.",
    "notMac": "맥에서만 있는 기능이에요. 윈도우는 아래 '쓰담 AI 모델'을 써 주세요.",
    "missing": "기기 안 AI 도우미가 없어요 (개발 실행이면 macos/bin/sseudam-ai 를 빌드하세요).",
}

SYSTEM = """너는 선생님이 수업 중 남긴 관찰 메모를 학생별로 나누는 도우미야.
각 문장이 학생 목록 중 누구에 대한 내용인지 학생 번호로 답해.
- "그 친구", "이 학생", "걔", "또한", "다만"처럼 이름 없이 이어지는 문장은 바로 앞 문장의 학생과 같은 학생이야.
- "오늘 수업", "반 전체", "모두", "분위기"처럼 여러 학생이나 수업 이야기면 0.
- 목록에 없는 학생은 절대 만들지 마.
- 답은 JSON 한 줄만: {"owners": [문장1의 학생번호, 문장2의 학생번호, ...]} (문장 수와 같은 개수)
예시) 학생: 1. 김민수 2. 이서연
[1] 오늘 실험을 했음.
[2] (김민수 언급) 김민수는 가설을 세웠음.
[3] 그 친구는 결과도 정리함.
[4] (이서연 언급) 이서연은 질문을 많이 함.
[5] 다만 기록이 부족했음.
[6] 모두 열심히 참여함.
답: {"owners": [0, 1, 1, 2, 2, 0]}"""

_apple_cache = {"t": 0, "state": None}


# ───────────────────────── 기기 안 AI (애플) ─────────────────────────

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


# ───────────────────────── 내 맥 AI 앱 (Ollama · LM Studio) ─────────────────────────

def _http(url, body=None, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    # localhost 전용 — 시스템 프록시를 거치지 않게
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _base(url):
    url = (url or "").strip().rstrip("/")
    if url and not url.endswith("/v1"):
        url += "/v1"
    return url


def is_local_url(url):
    if (url or "").strip() == BUILTIN:
        return True
    return bool(re.match(r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?(/|$)", (url or "").strip()))


def list_models(url, timeout=2):
    data = _http(_base(url) + "/models", timeout=timeout)
    ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
    # 임베딩 전용 모델은 빼기
    return [i for i in ids if "embed" not in i.lower()]


def detect():
    """설치된 Ollama · LM Studio 찾기 (켜져 있을 때만 보임)."""
    out = []
    for p in PRESETS:
        try:
            out.append(dict(p, models=list_models(p["url"], timeout=1), running=True))
        except Exception:  # noqa
            out.append(dict(p, models=[], running=False))
    return out


def local_configured(settings):
    if settings.get("local_ai_url") == BUILTIN:
        return builtin_ready(settings)
    return bool((settings.get("local_ai_url") or "").strip() and (settings.get("local_ai_model") or "").strip())


def chat(settings, system, prompt, timeout=300, temperature=0.2):
    if settings.get("local_ai_url") == BUILTIN:
        url = ensure_builtin(settings.get("local_ai_model"))
    else:
        url = _base(settings.get("local_ai_url"))
    if not is_local_url(url):
        raise RuntimeError("내 맥 AI 주소는 이 맥(127.0.0.1 / localhost)만 쓸 수 있어요.")
    body = {"model": settings.get("local_ai_model"), "temperature": temperature, "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},   # Qwen3.5 등: 생각 과정 없이 바로 답 (빠르고 짧게)
            "messages": ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]}
    data = _http(url + "/chat/completions", body, timeout=timeout)
    if settings.get("local_ai_url") == BUILTIN:
        _srv["last"] = time.time()
    text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()  # Qwen3 등 생각 과정 제거


# ───────────────────────── 공통: 문장 주인 고르기 ─────────────────────────

def _parse_owners(text, n):
    m = re.search(r"\{.*\}", text or "", re.S)
    if m:
        try:
            arr = json.loads(m.group(0)).get("owners")
            if isinstance(arr, list):
                return [int(x) if str(x).lstrip("-").isdigit() else 0 for x in arr][:n] + [0] * max(0, n - len(arr))
        except (ValueError, AttributeError):
            pass
    m = re.search(r"\[[\d,\s]+\]", text or "")
    if m:
        arr = json.loads(m.group(0))
        return arr[:n] + [0] * max(0, n - len(arr))
    raise RuntimeError("AI 답을 읽지 못했어요.")


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
            roster = "\n".join("%d. %s" % (i + 1, n) for i, n in enumerate(names))
            lines = "\n".join("[%d] %s%s" % (i + 1, "(%s 언급) " % names[kn[i] - 1] if i in kn else "", s)
                              for i, s in enumerate(chunk))
            res = _parse_owners(chat(settings, SYSTEM, "학생 목록:\n%s\n\n문장:\n%s" % (roster, lines)), len(chunk))
        out += [x if 0 <= x <= len(names) else 0 for x in res][:len(chunk)] + [0] * max(0, len(chunk) - len(res))
    return out


def generate(engine, settings, system, prompt):
    if engine == "apple":
        return _apple("generate", {"system": system or "", "prompt": prompt})["text"]
    return chat(settings, system, prompt, temperature=0.6)


def status(settings):
    st = apple_state(fresh=True)
    local = {"url": settings.get("local_ai_url") or "", "model": settings.get("local_ai_model") or "",
             "reachable": False, "models": []}
    if local["url"] == BUILTIN:
        local["reachable"] = builtin_ready(settings)
        local["models"] = [m["id"] for m in LLM_MODELS if llm_installed(m["id"])]
    elif local["url"]:
        try:
            local["models"] = list_models(local["url"])
            local["reachable"] = True
        except Exception:  # noqa
            pass
    return {"apple": {"state": st, "text": APPLE_TEXT.get(st, "")}, "local": local, "detected": detect(),
            "builtin": llm_status()}


# ───────────────────────── 쓰담 내장 AI (앱 안 llama.cpp + 내려받은 모델) ─────────────────────────
# Ollama·LM Studio를 모르는 선생님도: 설정에서 모델 '받기' 한 번 → 쓰담이 알아서 켜고 끈다.
import threading  # noqa: E402

BUILTIN = "builtin"          # local_ai_url 값이 이것이면 쓰담 내장 AI
BUILTIN_PORT = int(os.environ.get("SSEUDAM_LLM_PORT", "8781"))
IDLE_SEC = 10 * 60           # 10분 안 쓰면 꺼서 메모리 돌려주기
LLM_DIR = os.environ.get("SSEUDAM_LLM_DIR") or os.path.join(db.SUPPORT_DIR, "models", "llm")

LLM_MODELS = [
    {"id": "qwen35-4b", "name": "가볍게", "model": "Qwen3.5 4B (알리바바, Apache 2.0)",
     "file": "Qwen3.5-4B-Q4_K_M.gguf", "size": 2740937888, "ram": 8,
     "url": "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf",
     "desc": "메모리 8GB 맥도 괜찮아요. 학생 나누기 테스트 18문장 중 16개 정답."},
    {"id": "gemma4-e4b", "name": "추천", "model": "Gemma 4 E4B (구글)",
     "file": "gemma-4-E4B-it-Q4_K_M.gguf", "size": 4977171584, "ram": 16,
     "url": "https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q4_K_M.gguf",
     "desc": "메모리 16GB 이상 맥. 학생 나누기 테스트 18문장 모두 정답, 세특 초안도 가장 자연스러워요."},
    # 예전 버전(1.8.0)에서 받은 모델 — 받아 둔 맥에서만 보이고 계속 쓸 수 있음
    {"id": "qwen3-4b", "name": "예전 모델", "model": "Qwen3 4B", "legacy": True,
     "file": "Qwen3-4B-Instruct-2507-Q4_K_M.gguf", "size": 2497281120, "ram": 8,
     "url": "https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
     "desc": "새 '가볍게' 모델이 더 정확해요. 바꾸려면 위에서 받고 이건 지워 주세요."},
]

# 윈도우: 쓰담 설치 파일엔 엔진이 없어서, 모델 받을 때 llama.cpp 공식 윈도우 빌드(Vulkan — 인텔·AMD·엔비디아 그래픽 모두)를 함께 받는다
WIN_ENGINE = {
    "x64": ("https://github.com/ggml-org/llama.cpp/releases/download/b11851/llama-b11851-bin-win-vulkan-x64.zip",
            "36dcb7b6d2f3236c6f49762659a6eaf1c4832be947a42c9480123a0ff99a7468"),
    "arm64": ("https://github.com/ggml-org/llama.cpp/releases/download/b11851/llama-b11851-bin-win-vulkan-arm64.zip",
              "3def9d8d151695014e864a7a2b2bd4a4a19e6c021bd57b0cc6802d2529a2edd1"),
}
WIN_ENGINE_DIR = os.path.join(db.SUPPORT_DIR, "bin", "llama")


def _is_win():
    import platform_util
    return platform_util.IS_WIN


def _is_mac():
    import platform_util
    return platform_util.IS_MAC


def _arch():
    import platform
    m = platform.machine().lower()
    return "arm64" if m in ("arm64", "aarch64") else ("x64" if m in ("amd64", "x86_64") else m)


def engine_supported():
    """이 컴퓨터에서 쓰담 AI 모델(내장 엔진)을 쓸 수 있는지: Apple Silicon 맥, 윈도우(64비트)."""
    if _is_mac():
        return _arch() == "arm64"
    if _is_win():
        return _arch() in WIN_ENGINE
    return False


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


def recommend():
    """컴퓨터 사양에 맞는 모델과 이유."""
    info = machine_info()
    ram, name = info["ram"], ("이 맥" if info["os"] == "mac" else "이 컴퓨터")
    if not engine_supported():
        why = ("인텔 맥은 쓰담 AI 모델을 쓸 수 없어요. Gemini 키나 이름 기준 나누기를 써 주세요."
               if info["os"] == "mac" else "이 컴퓨터에서는 쓰담 AI 모델을 쓸 수 없어요.")
        return dict(info, model=None, why=why)
    if ram and ram < 8:
        return dict(info, model=None, why="%s 메모리(%dGB)로는 AI 모델이 너무 느려요. %s" % (
            name, ram, "기기 안 AI(Apple)나 이름 기준 나누기를 추천해요." if info["os"] == "mac" else "이름 기준 나누기를 추천해요."))
    if ram >= 16:
        why = "메모리 %dGB — 가장 정확한 '추천' 모델이 넉넉히 돌아가요." % ram
        if info["os"] == "win":
            why += " 그래픽 카드가 없는 노트북이면 조금 느릴 수 있어요(학생 나누기 수십 초)."
        return dict(info, model="gemma4-e4b", why=why)
    why = "메모리 %dGB — 가벼운 모델이 다른 프로그램과 같이 써도 무리 없어요." % ram if ram else "가벼운 모델부터 써 보세요."
    return dict(info, model="qwen35-4b", why=why)


_llm_dl = {}
_llm_lock = threading.Lock()
_srv = {"proc": None, "model": None, "last": 0}
_srv_lock = threading.Lock()


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


def llama_bin():
    name = "llama-server.exe" if _is_win() else "llama-server"
    for c in (os.path.join(os.environ.get("SETEUK_BIN", ""), name), os.path.join(db.SUPPORT_DIR, "bin", name),
              os.path.join(WIN_ENGINE_DIR, name), os.path.join(db.BASE_DIR, "macos", "bin", name)):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def _llm(mid):
    return next((m for m in LLM_MODELS if m["id"] == mid), None)


def llm_path(mid):
    m = _llm(mid)
    return os.path.join(LLM_DIR, m["file"]) if m else None


def llm_installed(mid):
    p, m = llm_path(mid), _llm(mid)
    return bool(p and os.path.exists(p) and os.path.getsize(p) == m["size"])


def builtin_ready(settings):
    return settings.get("local_ai_url") == BUILTIN and llm_installed(settings.get("local_ai_model")) and bool(llama_bin())


def llm_status():
    ram = mac_ram_gb()
    out = []
    for m in LLM_MODELS:
        d = dict(m)
        d["installed"] = llm_installed(m["id"])
        d["download"] = _llm_dl.get(m["id"])
        d["fits"] = not ram or ram >= m["ram"]
        part = llm_path(m["id"]) + ".part"
        d["partial"] = os.path.getsize(part) if os.path.exists(part) else 0
        out.append(d)
    out = [d for d in out if not d.get("legacy") or d["installed"] or d["partial"]]
    r = recommend()
    rec = r["model"]
    return {"models": out, "ram": ram, "recommended": rec, "machine": r,
            "engine": bool(llama_bin()) or (_is_win() and engine_supported()),
            "supported": engine_supported(),
            "running": bool(_srv["proc"] and _srv["proc"].poll() is None), "running_model": _srv["model"]}


def llm_download(mid):
    """이어받기 지원 (5GB라 중간에 끊겨도 처음부터 다시 받지 않게)."""
    m = _llm(mid)
    if not m:
        raise ValueError("알 수 없는 모델")
    with _llm_lock:
        cur = _llm_dl.get(mid)
        if cur and cur.get("status") == "downloading":
            return
        _llm_dl[mid] = {"status": "downloading", "done": 0, "total": m["size"], "error": ""}

    def run():
        import gemini
        dest = llm_path(mid)
        part = dest + ".part"
        try:
            os.makedirs(LLM_DIR, exist_ok=True)
            if not llama_bin() and _is_win():
                _llm_dl[mid]["stage"] = "AI 엔진 받는 중"
                fetch_win_engine()
                _llm_dl[mid]["stage"] = ""
            have = os.path.getsize(part) if os.path.exists(part) else 0
            headers = {"User-Agent": "sseudam"}
            if have:
                headers["Range"] = "bytes=%d-" % have
            req = urllib.request.Request(m["url"], headers=headers)
            with urllib.request.urlopen(req, timeout=60, context=gemini._CTX) as resp:
                if have and resp.status != 206:   # 서버가 이어받기를 안 받아 주면 처음부터
                    have = 0
                with open(part, "ab" if have else "wb") as f:
                    done = have
                    _llm_dl[mid]["done"] = done
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        _llm_dl[mid]["done"] = done
                        if _llm_dl[mid].get("cancel"):
                            raise InterruptedError("멈춤 — 다시 누르면 이어서 받아요")
            if os.path.getsize(part) != m["size"]:
                raise IOError("받은 파일 크기가 맞지 않아요. 다시 눌러 이어받아 주세요.")
            os.rename(part, dest)
            _llm_dl[mid]["status"] = "done"
            s = db.get_settings()
            if not (s.get("local_ai_url") or "").strip() or s.get("local_ai_url") == BUILTIN:
                db.set_settings({"local_ai_url": BUILTIN, "local_ai_model": mid})   # 받자마자 바로 쓰게
        except Exception as e:  # noqa
            _llm_dl[mid].update(status="error", error=str(e))
    threading.Thread(target=run, daemon=True, name="llm-dl").start()


def fetch_win_engine():
    """윈도우: llama.cpp 공식 빌드를 받아 쓰담 폴더에 풀기 (sha256 확인)."""
    import gemini
    import hashlib
    import shutil
    import tempfile
    import zipfile
    url, digest = WIN_ENGINE[_arch()]
    tmp = tempfile.mkdtemp(prefix="sseudam-llama-")
    try:
        z = os.path.join(tmp, "llama.zip")
        req = urllib.request.Request(url, headers={"User-Agent": "sseudam"})
        with urllib.request.urlopen(req, timeout=120, context=gemini._CTX) as resp, open(z, "wb") as f:
            shutil.copyfileobj(resp, f)
        h = hashlib.sha256()
        with open(z, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != digest:
            raise IOError("AI 엔진 파일이 손상됐어요. 다시 시도해 주세요.")
        os.makedirs(WIN_ENGINE_DIR, exist_ok=True)
        with zipfile.ZipFile(z) as zf:
            for m in zf.namelist():
                base = os.path.basename(m)
                if base and (base.endswith(".exe") or base.endswith(".dll")):   # 폴더 구조 없이 실행 파일·DLL만
                    with zf.open(m) as src, open(os.path.join(WIN_ENGINE_DIR, base), "wb") as out:
                        shutil.copyfileobj(src, out)
        if not llama_bin():
            raise IOError("AI 엔진을 풀지 못했어요.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def llm_cancel(mid):
    if mid in _llm_dl:
        _llm_dl[mid]["cancel"] = True


def llm_delete(mid):
    stop_builtin()
    for p in (llm_path(mid), (llm_path(mid) or "") + ".part"):
        if p and os.path.exists(p):
            os.remove(p)
    _llm_dl.pop(mid, None)
    s = db.get_settings()
    if s.get("local_ai_url") == BUILTIN and s.get("local_ai_model") == mid:
        db.set_settings({"local_ai_url": "", "local_ai_model": ""})


def stop_builtin():
    with _srv_lock:
        p = _srv["proc"]
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        _srv.update(proc=None, model=None)


def ensure_builtin(mid):
    """내장 AI 서버를 (필요하면) 켜고 주소를 돌려준다."""
    url = "http://127.0.0.1:%d/v1" % BUILTIN_PORT
    with _srv_lock:
        p = _srv["proc"]
        if p and p.poll() is None and _srv["model"] == mid:
            _srv["last"] = time.time()
            return url
    stop_builtin()
    _kill_stale()
    exe = llama_bin()
    if not exe:
        raise RuntimeError("쓰담 내장 AI 엔진이 없어요. 쓰담을 최신 버전으로 업데이트해 주세요.")
    if not llm_installed(mid):
        raise RuntimeError("AI 모델을 먼저 받아 주세요 (설정 → 학생별로 나누는 AI).")
    log = open(os.path.join(db.DATA_DIR, "llm.log"), "ab")
    extra = {"creationflags": 0x08000000} if _is_win() else {}   # 윈도우: 검은 창 안 띄우기
    for gpu_layers in ("99", "0"):   # 그래픽 가속이 안 되면(드라이버 등) CPU로 한 번 더
        proc = subprocess.Popen([exe, "-m", llm_path(mid), "--host", "127.0.0.1", "--port", str(BUILTIN_PORT),
                                 "-c", "8192", "-ngl", gpu_layers, "--jinja", "--no-webui"],
                                stdout=log, stderr=log, stdin=subprocess.DEVNULL, **extra)
        with _srv_lock:
            _srv.update(proc=proc, model=mid, last=time.time())
        for _ in range(360):   # 모델 올리는 데 최대 3분 (느린 노트북)
            if proc.poll() is not None:
                break
            try:
                _http("http://127.0.0.1:%d/health" % BUILTIN_PORT, timeout=2)
                return url
            except Exception:  # noqa
                time.sleep(0.5)
        stop_builtin()
    raise RuntimeError("내장 AI가 켜지지 않았어요 (data/llm.log 참고). 메모리가 부족하면 '가볍게' 모델을 써 보세요.")


def _kill_stale():
    """쓰담이 갑자기 꺼져서 남은 예전 내장 AI(같은 포트의 llama-server)를 정리."""
    if _is_win():
        try:
            out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                                 creationflags=0x08000000).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[1].endswith(":%d" % BUILTIN_PORT) and parts[3].upper() == "LISTENING":
                    task = subprocess.run(["tasklist", "/FI", "PID eq %s" % parts[4], "/NH"], capture_output=True,
                                          text=True, creationflags=0x08000000).stdout
                    if "llama-server" in task:
                        subprocess.run(["taskkill", "/F", "/PID", parts[4]], capture_output=True, creationflags=0x08000000)
        except Exception:  # noqa
            pass
        return
    try:
        pids = subprocess.run(["lsof", "-tiTCP:%d" % BUILTIN_PORT, "-sTCP:LISTEN"], capture_output=True, text=True).stdout.split()
        for pid in pids:
            cmd = subprocess.run(["ps", "-p", pid, "-o", "comm="], capture_output=True, text=True).stdout.strip()
            if cmd.endswith("llama-server"):
                os.kill(int(pid), 15)
        if pids:
            time.sleep(1)
    except Exception:  # noqa
        pass


import atexit  # noqa: E402
atexit.register(stop_builtin)


def _idle_reaper():
    while True:
        time.sleep(30)
        p = _srv["proc"]
        if p and p.poll() is None and time.time() - _srv["last"] > IDLE_SEC:
            stop_builtin()


threading.Thread(target=_idle_reaper, daemon=True, name="llm-idle").start()
