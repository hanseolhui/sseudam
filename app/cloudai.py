# -*- coding: utf-8 -*-
"""외부 AI API — Gemini · ChatGPT(OpenAI) · Claude(Anthropic) 중 선생님이 고른 하나로 분리·초안을 만든다.
표준 라이브러리 urllib만 사용. 받아쓰기(녹음 파일)는 Whisper(내 맥) 또는 Gemini만."""
import json
import re
import time
import urllib.error
import urllib.request

import gemini

PROVIDERS = {
    "gemini": {"label": "Gemini", "key": "gemini_api_key", "model": "gemini_model", "default": "gemini-2.5-flash",
               "site": "https://aistudio.google.com/apikey"},
    "openai": {"label": "ChatGPT", "key": "openai_api_key", "model": "openai_model", "default": "",
               "site": "https://platform.openai.com/api-keys"},
    "claude": {"label": "Claude", "key": "claude_api_key", "model": "claude_model", "default": "claude-opus-5-5",
               "site": "https://console.anthropic.com/settings/keys"},
    # 쓰담 플러스(구독): 키 대신 로그인 토큰, 모델은 서버가 고름
    "plus": {"label": "쓰담 플러스", "key": "plus_token", "model": "plus_model", "default": "Claude Sonnet",
             "site": "https://apps.seoriarts.com/sseudam"},
}
CLAUDE_MODELS = [  # 목록을 못 받아 올 때 보여 줄 기본 목록
    {"name": "claude-opus-5-5", "display": "Claude Opus 5.5 (가장 똑똑함)"},
    {"name": "claude-sonnet-5-5", "display": "Claude Sonnet 5.5 (빠르고 저렴)"},
    {"name": "claude-haiku-5-5", "display": "Claude Haiku 5.5 (가장 저렴)"},
]
ANTHROPIC_VERSION = "2026-10-21"


class CloudError(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


def provider(settings):
    p = settings.get("api_provider") or "gemini"
    return p if p in PROVIDERS else "gemini"


def _plus_enabled():
    import plus
    return plus.ENABLED


def key_of(settings, prov=None):
    prov = prov or provider(settings)
    if prov == "plus" and (settings.get("plus_active") != "1" or not _plus_enabled()):
        return ""                 # 구독이 끝났으면 키가 없는 것처럼 → 다른 방법으로 넘어감
    return (settings.get(PROVIDERS[prov]["key"]) or "").strip()


def model_of(settings, prov=None):
    info = PROVIDERS[prov or provider(settings)]
    return settings.get(info["model"]) or info["default"]


def label(settings, prov=None):
    return PROVIDERS[prov or provider(settings)]["label"]


# ───────────────────────── HTTP ─────────────────────────

_FRIENDLY = {
    400: "요청을 받아들이지 않았어요 — 모델 이름을 확인해 주세요",
    401: "API 키가 맞지 않아요 — 키를 다시 확인해 주세요",
    402: "결제 정보가 필요해요 — 해당 사이트에서 결제(크레딧)를 확인해 주세요",
    403: "이 키로는 쓸 수 없어요 — 권한·결제 상태를 확인해 주세요",
    404: "모델을 찾지 못했어요 — '연결 확인'으로 모델을 다시 골라 주세요",
    429: "사용 한도를 넘었거나 크레딧이 부족해요 — 잠시 뒤 다시 하거나 결제 상태를 확인해 주세요",
}


def _post(url, headers, body=None, timeout=600, method=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"),
                                 headers=dict(headers, **{"Content-Type": "application/json", "User-Agent": "sseudam"}))
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=gemini._CTX) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            err = json.loads(e.read().decode("utf-8", "replace"))
            detail = (err.get("error") or {}).get("message", "") if isinstance(err.get("error"), dict) else str(err.get("error") or "")
        except Exception:  # noqa
            pass
        msg = _FRIENDLY.get(e.code, "외부 AI 오류 (%d)" % e.code)
        if detail and e.code not in (401,):
            msg += " · " + detail[:200]
        raise CloudError(msg, e.code)
    except urllib.error.URLError as e:
        raise CloudError("외부 AI에 연결하지 못했어요 — 인터넷 연결을 확인해 주세요 (%s)" % e.reason)


def _retry(fn):
    attempt = 0
    while True:
        try:
            return fn()
        except CloudError as e:
            if e.code in (429, 500, 502, 503, 504, 529) and attempt < 3:
                attempt += 1
                time.sleep(15 * attempt)
                continue
            raise


# ───────────────────────── 모델 목록 ─────────────────────────

def _openai_rank(name):
    """대화용 GPT 모델만, 최신·큰 모델이 앞으로."""
    if not re.match(r"^(gpt-|o\d)", name) or re.search(r"audio|realtime|image|tts|transcribe|search|instruct|embedding|codex|moderation|preview|\d{4}-\d{2}-\d{2}", name):
        return None
    nums = re.findall(r"\d+(?:\.\d+)?", name)
    s = float(nums[0]) * 10 if nums and name.startswith("gpt-") else 0
    if "nano" in name: s -= 8
    elif "mini" in name: s -= 4
    return s


def list_models(prov, key):
    if prov == "gemini":
        return gemini.list_models(key)
    if prov == "openai":
        data = _post("https://api.openai.com/v1/models", {"Authorization": "Bearer " + key}, timeout=30)
        names = [(m["id"], _openai_rank(m["id"])) for m in data.get("data", [])]
        names = sorted([n for n in names if n[1] is not None], key=lambda x: -x[1])
        return [{"name": n, "display": n} for n, _ in names]
    if prov == "claude":
        data = _post("https://api.anthropic.com/v1/models?limit=100",
                     {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}, timeout=30)
        out = [{"name": m["id"], "display": m.get("display_name") or m["id"]} for m in data.get("data", [])]
        return out or CLAUDE_MODELS
    raise CloudError("알 수 없는 외부 AI")


# ───────────────────────── 글 만들기 ─────────────────────────

def generate(settings, prompt, system=None, json_mode=False, temperature=0.4, on_model_change=None, deep=False, cache=False):
    """고른 외부 AI로 글 만들기. 받아쓰기(파일 첨부)는 여기 말고 gemini.generate 직접."""
    prov, key, model = provider(settings), key_of(settings), model_of(settings)
    if prov == "plus":
        import plus
        try:
            return plus.generate(prompt, system, deep=deep, cache=cache)
        except plus.PlusError as e:
            raise CloudError(str(e))
    if not key:
        raise CloudError("%s API 키가 없어요. 설정 → AI → 고급에서 넣어 주세요." % label(settings))
    if prov == "gemini":
        return gemini.generate(key, model, prompt, system=system, json_mode=json_mode,
                               temperature=temperature, on_model_change=on_model_change)
    if prov == "openai":
        if not model:      # 모델을 안 골랐으면 목록에서 가장 좋은 것
            ms = list_models("openai", key)
            if not ms:
                raise CloudError("쓸 수 있는 ChatGPT 모델이 없어요")
            model = ms[0]["name"]
            if on_model_change:
                on_model_change(model)
        return _retry(lambda: _openai(key, model, prompt, system, json_mode))
    return _retry(lambda: _claude(key, model, prompt, system))


def _openai(key, model, prompt, system, json_mode):
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    body = {"model": model, "messages": msgs}   # 온도는 보내지 않음 (추론 모델은 기본값만 받음)
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    data = _post("https://api.openai.com/v1/chat/completions", {"Authorization": "Bearer " + key}, body, timeout=900)
    ch = (data.get("choices") or [{}])[0]
    text = ((ch.get("message") or {}).get("content") or "")
    if (ch.get("message") or {}).get("refusal"):
        raise CloudError("ChatGPT가 이 요청에 답하지 않았어요")
    if not text.strip():
        raise CloudError("ChatGPT 응답이 비어 있어요 (%s)" % ch.get("finish_reason"))
    if ch.get("finish_reason") == "length":
        text += "\n\n[주의: 응답 길이 한도에 도달해 잘렸을 수 있습니다]"
    return text


def _claude(key, model, prompt, system):
    body = {"model": model, "max_tokens": 16000, "messages": [{"role": "user", "content": prompt}]}
    if system:
        body["system"] = system
    data = _post("https://api.anthropic.com/v1/messages",
                 {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}, body, timeout=900)
    if data.get("stop_reason") == "refusal":
        raise CloudError("Claude가 이 요청에 답하지 않았어요")
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    if not text.strip():
        raise CloudError("Claude 응답이 비어 있어요 (%s)" % data.get("stop_reason"))
    if data.get("stop_reason") == "max_tokens":
        text += "\n\n[주의: 응답 길이 한도에 도달해 잘렸을 수 있습니다]"
    return text
