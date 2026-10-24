# -*- coding: utf-8 -*-
"""설정 → 의견 · 오류 보내기: 서리아트 문의함(help@seoriarts.com)으로.
진단 정보를 붙이면 컴퓨터 사양 · 설정 · 최근 실패한 작업을 보내되, 학생 이름은 가린다(namemask)."""
import json
import os
import urllib.error
import urllib.request

import db
import gemini
import version

URL = os.environ.get("SSEUDAM_FEEDBACK_URL", "https://apps.seoriarts.com/api/feedback")
KINDS = {"idea": "아이디어", "bug": "오류", "other": "기타"}


def diagnostics():
    """학생 기록 · 이름 없이 문제 해결에 필요한 것만."""
    import namemask
    import telemetry
    p = telemetry.payload()
    for k in ("id", "email", "name", "school", "share"):
        p.pop(k, None)
    s = db.get_settings()
    conn = db.connect()
    try:
        jobs = db.rows(conn, "SELECT op, status, message, created_at FROM jobs WHERE status='실패' ORDER BY id DESC LIMIT 15")
    finally:
        conn.close()
    m = namemask.for_all_students()
    lines = ["[쓰담 진단 정보]"] + ["%s: %s" % (k, v) for k, v in p.items()]
    lines += ["ai_choice: %s" % (s.get("ai_choice") or ""), "seg_engine: %s" % (s.get("seg_engine") or ""),
              "api_provider: %s" % (s.get("api_provider") or ""), "local_ai_model: %s" % (s.get("local_ai_model") or "")]
    lines.append("")
    lines.append("[최근 실패한 작업 — 학생 이름은 가림]")
    for j in jobs:
        lines.append("%s %s: %s" % (j["created_at"], j["op"], m.mask(j["message"] or "")))
    return "\n".join(lines)


def send(kind, message, email, with_diag=True):
    message = (message or "").strip()
    if len(message) < 2:
        raise ValueError("내용을 적어 주세요.")
    email = (email or "").strip()
    if "@" not in email:
        raise ValueError("답장 받을 이메일을 적어 주세요.")
    import telemetry
    s = db.get_settings()
    body = {"app": "쓰담 " + version.VERSION, "os": telemetry._os_full()[:20], "lang": "ko",
            "pro": s.get("ai_choice") == "plus", "email": email,
            "message": "[%s] %s" % (KINDS.get(kind, "기타"), message[:4800]),
            "log": diagnostics() if with_diag else ""}
    req = urllib.request.Request(URL, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "sseudam/" + version.VERSION})
    try:
        with urllib.request.urlopen(req, timeout=30, context=gemini._CTX) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8", "replace")).get("error")
        except Exception:  # noqa
            msg = None
        raise ValueError(msg or "보내지 못했어요 (%d). 잠시 후 다시 해 주세요." % e.code)
    except urllib.error.URLError:
        raise ValueError("인터넷에 연결되지 않아 보내지 못했어요.")
