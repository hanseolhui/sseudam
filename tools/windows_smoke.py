# -*- coding: utf-8 -*-
"""윈도우 실제 PC 시험 (GitHub Actions windows-smoke 에서 실행).
설치된 쓰담 서버(127.0.0.1:SETEUK_PORT)에 실제 요청을 보내 핵심 기능을 확인하고 smoke-report.txt 에 남긴다."""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

PORT = int(os.environ.get("SETEUK_PORT", "8790"))
B = "http://127.0.0.1:%d" % PORT
results = []


def call(path, body=None, raw=None, timeout=120):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(B + path, data=data, method="POST" if data is not None else "GET",
                                 headers={"X-Seteuk": "1", "Content-Type": "application/octet-stream" if raw is not None else "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode("utf-8", "replace"), "status": e.code}


def check(name, fn):
    t0 = time.time()
    try:
        detail = fn()
        results.append(("OK", name, round(time.time() - t0, 1), detail))
    except Exception as e:  # noqa
        results.append(("FAIL", name, round(time.time() - t0, 1), repr(e)[:400]))


def wait_job(jid, limit=900):
    for _ in range(limit // 2):
        time.sleep(2)
        jobs = call("/api/jobs").get("jobs", [])
        me = [j for j in jobs if j["id"] == jid]
        if me and me[0]["status"] in ("완료", "실패"):
            return me[0]
    raise TimeoutError("작업이 끝나지 않음 #%s" % jid)


def t_version():
    v = call("/api/version")
    assert v.get("version"), v
    return v


def t_segment():
    call("/api/settings", {"onboarded": "1", "auto_process": "1", "stt_engine": "whisper"})
    c = call("/api/classes/save", {"year": 2026, "semester": 2, "grade": 2, "class_no": 3, "subject": "과학", "kind": "교과"})
    assert c.get("ok") or c.get("id"), c
    s = call("/api/students/bulk", {"class_id": 1, "text": "1 가나다\n2 테스트민\n3 샘플준"})
    assert s.get("added") == 3, s
    rid = call("/api/recordings/paste", {"class_id": 1, "transcript": "육반 테스트민이는 실험 대조군을 스스로 설계함. 샘플 준이는 발표 때 그래프 해석이 정확했음.", "title": "윈도우 시험"})["id"]
    r = call("/api/recordings/rule_segment", {"id": rid})
    assert r.get("matched", 0) >= 2, r
    return r


def t_korean_paths():
    st = call("/api/settings")
    assert st.get("platform") == "win", st.get("platform")
    return {"data_dir": st.get("data_dir")}


def t_relay():
    r = call("/api/relay/pair", {})
    assert r.get("qr", "").startswith("sseudam://pair"), r
    p = call("/api/relay/poll", {})
    assert "error" not in p, p
    call("/api/relay/unpair", {})
    return {"poll": p}


def t_whisper():
    d = call("/api/whisper/download", {"id": "small-q5"})
    assert "error" not in d, d
    assert call("/api/whisper").get("supported"), "이 윈도우에서 Whisper 지원 안 됨"
    for _ in range(300):
        time.sleep(2)
        st = call("/api/whisper")
        models = st.get("models") or []
        m = [x for x in models if x.get("id") == "small-q5"]
        if m and m[0].get("installed"):
            break
    else:
        raise TimeoutError("Whisper 모델 받기가 끝나지 않음: %s" % st)
    wav = open("sample.wav", "rb").read()
    q = urllib.parse.urlencode({"filename": "sample.wav", "class_id": 1, "title": "윈도우 받아쓰기"})
    up = call("/api/recordings/upload?" + q, raw=wav)
    assert up.get("id") or up.get("ok"), up
    rid = up.get("id")
    for _ in range(300):
        time.sleep(3)
        r = (call("/api/recordings/%s" % rid).get("recording") or {})
        if (r.get("transcript") or "").strip():
            return {"transcript": r["transcript"][:120], "status": r.get("status")}
        if r.get("error") and r.get("status") not in ("전사중", "대기"):
            raise RuntimeError(r["error"])
    raise TimeoutError("받아쓰기 결과가 나오지 않음")


def t_llm_engine():
    st = call("/api/localai/models")
    return {"supported": st.get("supported"), "engine": st.get("engine"), "machine": st.get("machine")}


def t_feedback_preview():
    p = call("/api/feedback/preview")
    assert "쓰담 진단 정보" in p.get("text", ""), p
    return "ok"


def t_plus():
    p = call("/api/plus")
    return p


for name, fn in [("서버 켜짐 · 버전", t_version), ("윈도우 경로 · 한글 폴더", t_korean_paths),
                 ("학생 명단 · 이름 기준 분리", t_segment), ("QR 연동(실제 중계 서버)", t_relay),
                 ("Whisper 받기 · 녹음 받아쓰기", t_whisper), ("내장 AI 엔진 상태", t_llm_engine),
                 ("아이디어·오류 진단 정보", t_feedback_preview), ("쓰담 플러스 상태", t_plus)]:
    check(name, fn)

lines = ["%-4s %-28s %6ss  %s" % (r[0], r[1], r[2], json.dumps(r[3], ensure_ascii=False)[:300]) for r in results]
report = "\n".join(lines)
print(report)
open("smoke-report.txt", "w", encoding="utf-8").write(report + "\n")
sys.exit(1 if any(r[0] == "FAIL" for r in results) else 0)
