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
    expected = os.environ.get("EXPECTED_APP_VERSION")
    assert not expected or v["version"] == expected, "Installed version differs from the release source"
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


def t_whisper_direct():
    """설치된 whisper-cli 를 직접 돌려 옵션 호환 확인 (실패하면 원인 줄을 그대로 보여 줌)."""
    import glob
    import subprocess
    bin_dir = os.environ.get("SETEUK_BIN") or ""
    exe = (glob.glob(os.path.join(bin_dir, "whisper", "whisper-cli.exe")) + glob.glob(os.path.join(bin_dir, "whisper-cli.exe")))[:1]
    if not exe:
        return {"skipped": "SETEUK_BIN 없음 (스토어판은 앱이 직접 찾음)"}
    out = subprocess.run([exe[0], "--help"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    helptext = out.stdout + out.stderr
    need = ["-pp", "--prompt", "--vad", "-vm"]
    missing = [o for o in need if (" " + o + " ").replace("  ", " ") not in helptext and (o + ",") not in helptext]
    return {"exe": exe[0], "missing_options": missing, "help_head": helptext.strip().splitlines()[:3]}


def t_llm_engine():
    st = call("/api/ai/state")
    return {"record_engine": st.get("active_seg"), "draft_engine": st.get("draft")}


def t_feedback_preview():
    p = call("/api/feedback/preview")
    assert "쓰담 진단 정보" in p.get("text", ""), p
    return "ok"


def t_plus():
    p = call("/api/plus")
    return p


def t_device_help():
    """Open the installed UI in real Windows Edge while blocking external network requests."""
    from pathlib import Path
    from playwright.sync_api import sync_playwright

    assert os.environ.get("GITHUB_ACTIONS") == "true" and sys.platform == "win32"
    call("/api/settings", {"onboarded": "1", "profile_asked": "1"})
    screenshots = Path("output/playwright")
    screenshots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        try:
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            context.route("**/*", lambda route: route.continue_()
                          if urllib.parse.urlparse(route.request.url).hostname in ("127.0.0.1", "localhost")
                          else route.abort())
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(B + "/#/settings", wait_until="domcontentloaded")
            guide = page.locator("#device-offline-guide")
            guide.wait_for(state="visible", timeout=30000)
            assert guide.get_attribute("open") is None, "Help should be collapsed initially"
            page.screenshot(path=str(screenshots / "windows-help-collapsed.png"))
            guide.locator("summary").click()
            assert guide.get_attribute("open") is not None, "Help did not expand"
            text = guide.inner_text()
            for phrase in ("Windows 10·11", "인터넷이 없어도", "QR 연동은 인터넷", "로그인", "동기화", "백업", "컴퓨터 쓰담"):
                assert phrase in text, "Missing help content: " + phrase
            assert guide.locator('a[href$="#devices"]').count() == 1
            assert guide.locator('a[href$="#offline-online"]').count() == 1
            assert page.get_by_text("지금: 이 컴퓨터 안에서 받아쓰기 — 외부 전송 없음", exact=True).is_visible()
            layouts = []
            for width in (1280, 960):
                page.set_viewport_size({"width": width, "height": 900})
                layout = page.evaluate("({viewport: innerWidth, width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight})")
                layouts.append(layout)
                assert layout["width"] <= layout["viewport"], "Settings overflow at %spx: %s" % (width, layout)
                page.screenshot(path=str(screenshots / ("windows-help-offline-expanded-%s.png" % width)))
            guide.locator("summary").click()
            assert guide.get_attribute("open") is None, "Help did not collapse again"
            assert not errors, errors
        finally:
            browser.close()
    return {"windows_edge": True, "bundled_help_with_external_network_blocked": True,
            "expand_and_collapse": True, "layouts": layouts, "horizontal_overflow": False}


def t_cloud_audio():
    """설치된 API로 원본 음성의 동의·증분 복사·중지 동작을 시험한다 (CI 가짜 자료만)."""
    import hashlib
    from pathlib import Path
    import shutil
    import tempfile

    assert os.environ.get("GITHUB_ACTIONS") == "true", "Cloud audio smoke requires an isolated Actions runner"
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    actual_data = Path(call("/api/settings")["data_dir"]).resolve()
    if os.environ.get("SSEUDAM_SMOKE_MSIX") == "1":
        data = Path(os.environ["USERPROFILE"]).resolve() / "쓰담" / "data"
    else:
        data = Path(os.environ["SETEUK_DATA"]).resolve()
        assert data == workspace / "testdata", "Unexpected smoke data directory"
    assert actual_data == data, "Installed server is not using the expected isolated runner data directory"
    original_state = call("/api/backup-folder")
    assert not original_state.get("folder"), "Fresh smoke database unexpectedly has a backup folder"
    assert not original_state.get("audio_enabled"), original_state
    relative = Path("2099/01/synthetic-cloud-audio.wav")
    source = data / "audio" / relative
    assert not source.exists(), "Synthetic source already exists"
    source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(workspace / "sample.wav", source)
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="smoke-cloud-audio-", dir=workspace) as temporary:
        destination = Path(temporary).resolve()
        try:
            selected = call("/api/backup-folder", {"path": str(destination)})
            assert selected.get("folder") and not selected.get("audio_enabled"), selected
            enabled = call("/api/backup-folder/audio", {"enabled": True})
            assert enabled.get("audio_enabled") and not enabled.get("audio_error"), enabled
            summary = enabled.get("audio_summary") or {}
            assert summary.get("copied", 0) >= 1 and summary.get("ok"), summary
            mirror_root = Path(summary["folder"]).resolve()
            assert mirror_root.parent == destination, "Audio mirror escaped the synthetic destination"
            saved = mirror_root / "audio" / relative
            assert hashlib.sha256(saved.read_bytes()).hexdigest() == original_hash, "Audio copy differs"
            manifest = json.loads((mirror_root / "manifest.json").read_text(encoding="utf-8"))
            assert manifest["files"][relative.as_posix()]["sha256"] == original_hash, "Manifest hash differs"
            repeated = call("/api/backup-folder/now", {})
            assert not repeated.get("audio_error") and not repeated.get("error"), repeated
            assert repeated["audio_summary"]["copied"] == 0, repeated["audio_summary"]
            assert repeated["audio_summary"]["versions_saved"] == 0, repeated["audio_summary"]
            disabled = call("/api/backup-folder/audio", {"enabled": False})
            assert not disabled.get("audio_enabled"), disabled
            # 끈 뒤 새 원본이 생겨도 복사하지 않으며 이미 보관한 사본은 유지한다.
            disabled_source = source.with_name("synthetic-after-disabled.wav")
            assert not disabled_source.exists(), "Disabled-test source already exists"
            shutil.copyfile(source, disabled_source)
            after_disabled = call("/api/backup-folder/now", {})
            assert not after_disabled.get("audio_enabled"), after_disabled
            assert not (saved.parent / disabled_source.name).exists(), "Audio copied after opt-out"
            assert hashlib.sha256(saved.read_bytes()).hexdigest() == original_hash, "Opt-out removed or changed the saved copy"
            assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash, "Source audio changed"
            return {"copied_and_hashed": True, "repeat_copied": 0, "disabled_preserves_copy": True,
                    "disabled_skips_new_audio": True, "remote_cloud_sync_tested": False}
        finally:
            call("/api/backup-folder/audio", {"enabled": False})
            cleared = call("/api/backup-folder", {"path": ""})
            assert not cleared.get("folder"), "Could not clear synthetic backup setting"


for name, fn in [("서버 켜짐 · 버전", t_version), ("윈도우 경로 · 한글 폴더", t_korean_paths),
                 ("학생 명단 · 이름 기준 분리", t_segment), ("QR 연동(실제 중계 서버)", t_relay),
                 ("Whisper 실행 파일 옵션", t_whisper_direct), ("Whisper 받기 · 녹음 받아쓰기", t_whisper),
                 ("원본 음성 백업 · 중복 방지 · 끄기", t_cloud_audio), ("내장 AI 엔진 상태", t_llm_engine),
                 ("아이디어·오류 진단 정보", t_feedback_preview), ("쓰담 플러스 상태", t_plus),
                 ("Windows Edge · 오프라인 기기 안내", t_device_help)]:
    check(name, fn)

lines = ["%-4s %-28s %6ss  %s" % (r[0], r[1], r[2], json.dumps(r[3], ensure_ascii=False)[:300]) for r in results]
report = "\n".join(lines)
print(report)
open("smoke-report.txt", "w", encoding="utf-8").write(report + "\n")
sys.exit(1 if any(r[0] == "FAIL" for r in results) else 0)
