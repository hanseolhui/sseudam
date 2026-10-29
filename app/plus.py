# -*- coding: utf-8 -*-
"""쓰담 플러스 (구독) — 이메일로 로그인하면 키 없이 서리아트 서버를 거쳐 Claude로 분리·초안.
학생 이름은 보내기 전에 가린다(namemask). 서버는 내용을 저장하지 않고 횟수만 센다."""
import json
import os
import secrets
import socket
import time
import threading
import urllib.error
import urllib.request

import db
import gemini
import version

URL = os.environ.get("SSEUDAM_PLUS_URL", "https://apps.seoriarts.com/api/sseudam-plus")
# 베타로 열어 둠: 로그인 → 베타 신청 → 관리자가 고른 선생님께 1달 시험 구독. 정식 결제는 서버가 열면(pay) 보임.
# 급히 숨겨야 하면 SSEUDAM_PLUS=0
ENABLED = os.environ.get("SSEUDAM_PLUS", "1") != "0"
# 구글 로그인: 브라우저에서 이 페이지로 로그인하면 127.0.0.1 의 쓰담(plus-done.html)으로 토큰을 돌려준다
LOGIN_PAGE = os.environ.get("SSEUDAM_LOGIN_URL", "https://apps.seoriarts.com/sseudam/login")
_REFRESH_LOCK = threading.Lock()
STATUS_TTL_SECONDS = 6 * 3600
_STATE = secrets.token_urlsafe(18)   # 이 쓰담이 연 로그인인지 확인 (켤 때마다 바뀜)


class PlusError(Exception):
    def __init__(self, msg, logged_out=False, expired=False):
        super().__init__(msg)
        self.logged_out, self.expired = logged_out, expired


def _call(action, timeout=30, **body):
    import telemetry
    body.update(action=action, installId=telemetry.install_id())
    req = urllib.request.Request(URL, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "sseudam/" + version.VERSION})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=gemini._CTX) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            d = json.loads(e.read().decode("utf-8", "replace"))
        except Exception:  # noqa
            d = {}
        if d.get("loggedOut"):
            db.set_settings({"plus_token": "", "plus_active": "0"})
        if d.get("expired"):
            db.set_settings({"plus_active": "0"})
        raise PlusError(d.get("error") or "쓰담 플러스 서버 오류 (%d)" % e.code, d.get("loggedOut", False), d.get("expired", False))
    except (socket.timeout, TimeoutError):
        raise PlusError("쓰담 플러스 응답이 늦어지고 있어요. 잠시 뒤 다시 시도해 주세요.")
    except urllib.error.URLError as e:
        raise PlusError("쓰담 플러스 서버에 연결하지 못했어요 — 인터넷 연결을 확인해 주세요 (%s)" % e.reason)


def token():
    return db.get_settings().get("plus_token") or ""


def active(settings=None):
    s = db.get_settings() if settings is None else settings
    return bool(s.get("plus_token")) and s.get("plus_active") == "1"


def _cached_status(settings):
    try:
        cached = json.loads(settings.get("plus_status") or "{}")
    except (ValueError, TypeError):
        return {}
    if not isinstance(cached, dict):
        return {}
    sub = cached.get("sub")
    if isinstance(sub, dict):
        # 서버가 만료를 알려 줬다면 오래된 캐시가 다시 활성으로 보이면 안 된다.
        if settings.get("plus_active") != "1":
            sub["active"] = False
    return cached


def _remember(d):
    sub = d.get("sub") or {}
    db.set_settings({"plus_email": d.get("email") or "", "plus_active": "1" if sub.get("active") else "0",
                     "plus_status": json.dumps(d, ensure_ascii=False, default=str), "plus_checked": str(int(time.time()))})


def start(email):
    return _call("start", email=email)


def _device_name():
    name = (db.get_settings().get("teacher_name") or "").strip()
    host = socket.gethostname().replace(".local", "")
    return (host + (" · " + name if name else ""))[:60]


def verify(email, code):
    d = _call("verify", email=email, code=str(code).strip(), deviceName=_device_name())
    db.set_settings({"plus_token": d["token"]})
    _remember(d)
    return d


def login_url(port):
    """구글로 로그인 — 브라우저로 여는 서리아트 로그인 페이지 주소"""
    import telemetry
    import urllib.parse
    return LOGIN_PAGE + "?" + urllib.parse.urlencode({"i": telemetry.install_id(), "n": _device_name(), "p": port, "s": _STATE})


def adopt(tok, state):
    """로그인 페이지가 돌려준 토큰을 이 컴퓨터에 저장"""
    if not tok or not secrets.compare_digest(str(state or ""), _STATE):
        raise PlusError("로그인 요청이 맞지 않아요. 쓰담 설정 → AI에서 '구글로 로그인'을 다시 눌러 주세요.")
    d = _call("status", token=str(tok))
    db.set_settings({"plus_token": str(tok)})
    _remember(d)
    return d


def status(refresh=True):
    s = db.get_settings()
    if not s.get("plus_token"):
        return {"loggedIn": False}
    if refresh:
        try:
            d = _call("status", token=s["plus_token"])
            _remember(d)
            return dict(d, loggedIn=True)
        except PlusError as e:
            if e.logged_out:
                return {"loggedIn": False, "error": str(e)}
            if e.expired:
                cached = _cached_status(db.get_settings())
                return dict(cached, loggedIn=True, error=str(e))
            cached = _cached_status(s)
            return dict(cached, loggedIn=True, offline=str(e))
    return dict(_cached_status(s), loggedIn=True)


def beta_request(message=""):
    t = token()
    if not t:
        raise PlusError("먼저 로그인해 주세요.", logged_out=True)
    d = _call("beta-request", token=t, message=(message or "")[:300])
    status(True)
    return d


def logout():
    t = token()
    if t:
        try:
            _call("logout", token=t, timeout=10)
        except PlusError:
            pass
    db.set_settings({"plus_token": "", "plus_active": "0", "plus_status": ""})


def generate(prompt, system=None, deep=False, cache=False):
    """이름을 가리고 서버 AI로 → 답에서 이름 되돌리기.
    deep=False: 가벼운 AI(분리 · 기본 초안 · 다시 뽑기 · 줄이기, 사실상 무제한)
    deep=True : 정성 초안(더 깊게 쓰는 AI, 요금제별 횟수) / cache: 같은 학생을 연달아 다시 뽑을 때 입력 재사용"""
    import namemask
    t = token()
    if not t:
        raise PlusError("쓰담 플러스에 로그인해 주세요 (설정 → AI).", logged_out=True)
    m = namemask.for_all_students()
    d = _call("ai", timeout=310, token=t, tier="deep" if deep else "light", cache=bool(cache),
              prompt=m.mask(prompt), system=m.mask(system or ""))
    if d.get("deepCap") is not None:     # 남은 정성 초안 횟수를 화면에 바로 보이게
        try:
            st = json.loads(db.get_settings().get("plus_status") or "{}")
            st.setdefault("sub", {}).update(deepUsed=d.get("deepUsed", 0), deepCap=d.get("deepCap", 0), used=d.get("used"))
            db.set_settings({"plus_status": json.dumps(st, ensure_ascii=False, default=str)})
        except Exception:  # noqa
            pass
    if d.get("refusal"):
        raise PlusError("AI가 이 요청에 답하지 않았어요")
    text = m.unmask(d.get("text") or "")
    if not text.strip():
        raise PlusError("AI 응답이 비어 있어요")
    if d.get("stop") == "max_tokens":
        text += "\n\n[주의: 응답 길이 한도에 도달해 잘렸을 수 있습니다]"
    return text


def refresh_if_stale():
    """Refresh at most once per six hours; concurrent callers share the cached state."""
    if not _REFRESH_LOCK.acquire(blocking=False):
        return
    try:
        s = db.get_settings()
        try:
            checked = int(s.get("plus_checked") or 0)
        except (ValueError, TypeError, OverflowError):
            checked = 0
        now = time.time()
        if s.get("plus_token") and (checked > now or now - checked > STATUS_TTL_SECONDS):
            status(True)
    finally:
        _REFRESH_LOCK.release()
