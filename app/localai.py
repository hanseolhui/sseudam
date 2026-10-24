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
    return bool((settings.get("local_ai_url") or "").strip() and (settings.get("local_ai_model") or "").strip())


def chat(settings, system, prompt, timeout=300, temperature=0.2):
    url = _base(settings.get("local_ai_url"))
    if not is_local_url(url):
        raise RuntimeError("내 맥 AI 주소는 이 맥(127.0.0.1 / localhost)만 쓸 수 있어요.")
    body = {"model": settings.get("local_ai_model"), "temperature": temperature, "stream": False,
            "messages": ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]}
    data = _http(url + "/chat/completions", body, timeout=timeout)
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
    if local["url"]:
        try:
            local["models"] = list_models(local["url"])
            local["reachable"] = True
        except Exception:  # noqa
            pass
    return {"apple": {"state": st, "text": APPLE_TEXT.get(st, "")}, "local": local, "detected": detect()}
