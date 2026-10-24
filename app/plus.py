# -*- coding: utf-8 -*-
"""쓰담 플러스 (구독) — 이메일로 로그인하면 키 없이 서리아트 서버를 거쳐 Claude로 분리·초안.
학생 이름은 보내기 전에 가린다(namemask). 서버는 내용을 저장하지 않고 횟수만 센다."""
import json
import os
import socket
import time
import urllib.error
import urllib.request

import db
import gemini
import version

URL = os.environ.get("SSEUDAM_PLUS_URL", "https://apps.seoriarts.com/api/sseudam-plus")
# 아직 열지 않음: 결제(정기결제 심사)·서버 준비가 끝나면 True 로 바꿔 배포. 시험은 SSEUDAM_PLUS=1 로.
ENABLED = os.environ.get("SSEUDAM_PLUS") == "1"


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
    except urllib.error.URLError as e:
        raise PlusError("쓰담 플러스 서버에 연결하지 못했어요 — 인터넷 연결을 확인해 주세요 (%s)" % e.reason)


def token():
    return db.get_settings().get("plus_token") or ""


def active(settings=None):
    s = settings or db.get_settings()
    return bool(s.get("plus_token")) and s.get("plus_active") == "1"


def _remember(d):
    sub = d.get("sub") or {}
    db.set_settings({"plus_email": d.get("email") or "", "plus_active": "1" if sub.get("active") else "0",
                     "plus_status": json.dumps(d, ensure_ascii=False, default=str), "plus_checked": str(int(time.time()))})


def start(email):
    return _call("start", email=email)


def verify(email, code):
    name = (db.get_settings().get("teacher_name") or "").strip()
    host = socket.gethostname().replace(".local", "")
    d = _call("verify", email=email, code=str(code).strip(), deviceName=(host + (" · " + name if name else ""))[:60])
    db.set_settings({"plus_token": d["token"]})
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
            cached = json.loads(s.get("plus_status") or "{}")
            return dict(cached, loggedIn=True, offline=str(e))
    return dict(json.loads(s.get("plus_status") or "{}"), loggedIn=True)


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
    """하루 한 번 구독 상태 확인 (끝났으면 자동으로 다른 AI로 넘어가게)."""
    s = db.get_settings()
    if s.get("plus_token") and time.time() - int(s.get("plus_checked") or 0) > 6 * 3600:
        status(True)
