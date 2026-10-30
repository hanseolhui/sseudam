# -*- coding: utf-8 -*-
"""내 맥에서 직접 받아쓰기 (whisper.cpp). 인터넷·API 키 없이 동작, 녹음이 맥 밖으로 나가지 않음.

- 실행 파일: 앱 안(Resources/bin/whisper-cli) — Apple Silicon(M1 이상) 전용, Metal GPU 사용
- 모델: 처음 한 번 설정 화면에서 내려받음 → ~/Library/Application Support/쓰담/models
"""
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request

import db
import gemini

class NoSpeechDetected(RuntimeError):
    """녹음은 보관하되 사용자가 용도를 확인해야 하는 경우."""


HF = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
MODELS = [
    {"id": "turbo-q5", "file": "ggml-large-v3-turbo-q5_0.bin", "size": 574041195,
     "label": "권장", "desc": "정확도 높음 · 550MB · 1시간 녹음에 M1 맥 약 10~20분 (윈도우 일반 PC는 더 오래 걸릴 수 있음)"},
    {"id": "small-q5", "file": "ggml-small-q5_1.bin", "size": 190085487,
     "label": "가벼움", "desc": "빠르지만 이름·전문용어 정확도 낮음 · 190MB"},
    {"id": "turbo", "file": "ggml-large-v3-turbo.bin", "size": 1624555275,
     "label": "최고 정확도", "desc": "1.6GB · 메모리 16GB 이상 권장"},
]
VAD = {"file": "ggml-silero-v5.1.2.bin", "size": 885098,
       "url": "https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin"}
MODEL_DIR = os.path.join(db.SUPPORT_DIR, "models")

_downloads = {}  # id → {"done", "total", "error", "status"}
_dl_lock = threading.Lock()


def supported():
    import platform_util
    if platform_util.IS_MAC:
        return platform.machine() == "arm64"
    if platform_util.IS_WIN:
        return platform.machine().lower() in ("amd64", "x86_64")
    return False


def _exe(name):
    import platform_util
    return name + ".exe" if platform_util.IS_WIN else name


def binary():
    name = _exe("whisper-cli")
    cands = [os.path.join(os.environ.get("SETEUK_BIN", ""), name),
             os.path.join(os.environ.get("SETEUK_BIN", ""), "whisper", name),
             os.path.join(db.SUPPORT_DIR, "bin", name),
             os.path.join(db.BASE_DIR, "macos", "bin", name)]  # 개발 실행
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


# 윈도우: 휴대폰 녹음(m4a)을 바꾸려면 ffmpeg가 필요 → 모델 내려받을 때 함께 받음
FFMPEG_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"


def ffmpeg():
    name = _exe("ffmpeg")
    for c in (os.path.join(os.environ.get("SETEUK_BIN", ""), name), os.path.join(db.SUPPORT_DIR, "bin", name)):
        if c and os.path.isfile(c):
            return c
    return shutil.which("ffmpeg")


def to_wav16k(src, dest):
    """녹음을 Whisper가 읽는 16kHz 모노 WAV로 변환. 맥은 내장 afconvert, 윈도우는 ffmpeg."""
    if shutil.which("afconvert"):
        r = subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", src, dest], capture_output=True)
    else:
        ff = ffmpeg()
        if not ff:
            raise RuntimeError("오디오 변환 도구(ffmpeg)가 없습니다. 설정 → 받아쓰기 엔진에서 모델을 다시 내려받으면 함께 설치됩니다.")
        r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", src, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", dest],
                           capture_output=True, **_no_window())
    if r.returncode != 0 or not os.path.exists(dest):
        raise RuntimeError("오디오를 변환하지 못했습니다: %s" % r.stderr.decode("utf-8", "replace")[:200])


def _no_window():
    import platform_util
    return {"creationflags": 0x08000000} if platform_util.IS_WIN else {}  # CREATE_NO_WINDOW


def fetch_ffmpeg():
    import platform_util
    if platform_util.IS_STORE:   # 스토어판은 묶음 안에 들어 있음 (실행 파일을 나중에 받지 않음)
        return ffmpeg()
    import zipfile
    dest_dir = os.path.join(db.SUPPORT_DIR, "bin")
    os.makedirs(dest_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="seteuk-ff-")
    try:
        z = os.path.join(tmp, "ff.zip")
        req = urllib.request.Request(FFMPEG_URL, headers={"User-Agent": "sseudam"})
        with urllib.request.urlopen(req, timeout=120, context=gemini._CTX) as resp, open(z, "wb") as f:
            shutil.copyfileobj(resp, f)
        with zipfile.ZipFile(z) as zf:
            member = next(m for m in zf.namelist() if m.endswith("/bin/ffmpeg.exe"))
            with zf.open(member) as src, open(os.path.join(dest_dir, "ffmpeg.exe"), "wb") as out:
                shutil.copyfileobj(src, out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def model_path(mid):
    m = next((x for x in MODELS if x["id"] == mid), None)
    return os.path.join(MODEL_DIR, m["file"]) if m else None


def installed(mid):
    p = model_path(mid)
    m = next((x for x in MODELS if x["id"] == mid), None)
    return bool(p and os.path.exists(p) and os.path.getsize(p) == m["size"])


def best_installed(preferred=None):
    order = [preferred] if preferred else []
    order += ["turbo-q5", "turbo", "small-q5"]
    for mid in order:
        if mid and installed(mid):
            return mid
    return None


def available():
    """이 맥에서 Whisper 받아쓰기를 바로 쓸 수 있는지."""
    return supported() and binary() is not None and best_installed() is not None


def status():
    # 실행 파일이 없어도(예전 앱) 모델 내려받을 때 함께 받으므로 지원 맥이면 사용 가능으로 표시
    out = {"supported": supported(), "binary": bool(binary()) or supported(), "models": [], "vad": os.path.exists(os.path.join(MODEL_DIR, VAD["file"]))}
    for m in MODELS:
        d = dict(m)
        d["installed"] = installed(m["id"])
        d["download"] = _downloads.get(m["id"])
        out["models"].append(d)
    return out


# ───────────────────────── 모델 내려받기 ─────────────────────────

def _fetch(url, dest, expected, key):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "sseudam"})
    with urllib.request.urlopen(req, timeout=60, context=gemini._CTX) as resp, open(part, "wb") as f:
        total = int(resp.headers.get("Content-Length") or expected)
        if key:
            _downloads[key].update(total=total)
        done = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if key:
                if _downloads[key].get("cancel"):
                    raise InterruptedError("취소됨")
                _downloads[key]["done"] = done
    if os.path.getsize(part) != expected:
        os.remove(part)
        raise IOError("내려받은 파일 크기가 맞지 않습니다. 다시 시도하세요.")
    os.rename(part, dest)


def download(mid):
    m = next((x for x in MODELS if x["id"] == mid), None)
    if not m:
        raise ValueError("알 수 없는 모델")
    with _dl_lock:
        cur = _downloads.get(mid)
        if cur and cur.get("status") == "downloading":
            return
        if installed(mid) and binary():   # 이미 받아 둠 → 다시 받지 않음
            _downloads[mid] = {"status": "done", "done": m["size"], "total": m["size"], "error": ""}
            return
        _downloads[mid] = {"status": "downloading", "done": 0, "total": m["size"], "error": ""}

    def run():
        try:
            import platform_util
            if not binary() and platform_util.IS_MAC:  # 예전 맥 앱(실행 파일 미포함) → 릴리스에서 받기
                import update
                update.fetch_whisper_binary(os.path.join(db.SUPPORT_DIR, "bin"))
            if platform_util.IS_WIN and not ffmpeg():
                _downloads[mid]["status"] = "downloading"
                fetch_ffmpeg()
            vad = os.path.join(MODEL_DIR, VAD["file"])
            if not os.path.exists(vad):
                _fetch(VAD["url"], vad, VAD["size"], None)
            _fetch(HF + m["file"], model_path(mid), m["size"], mid)
            _downloads[mid]["status"] = "done"
            if not db.get_settings().get("whisper_model"):
                db.set_settings({"whisper_model": mid})
            import pipeline
            pipeline.process_pending()  # 기다리던 녹음 자동 받아쓰기
        except Exception as e:  # noqa
            _downloads[mid].update(status="error", error=str(e))
            try:
                os.remove(model_path(mid) + ".part")
            except OSError:
                pass
    threading.Thread(target=run, daemon=True, name="whisper-dl").start()


def cancel(mid):
    if mid in _downloads:
        _downloads[mid]["cancel"] = True


def delete(mid):
    p = model_path(mid)
    if p and os.path.exists(p):
        os.remove(p)
    _downloads.pop(mid, None)


# ───────────────────────── 받아쓰기 ─────────────────────────

def _initial_prompt(students, kind):
    names = ", ".join(s["name"] for s in students[:45])
    base = "다음은 한국 학교의 %s 녹음입니다. 교사가 학생 이름을 부르며 관찰한 내용을 말합니다." % (
        "수업" if kind != "상담" else "상담")
    return (base + (" 학생: " + names + "." if names else ""))[:600]


def transcribe(audio_path, students=None, kind="수업", on_progress=None, model_id=None):
    """녹음을 이 맥 안에서만 글자로 바꾼다 (외부 전송 없음)."""
    if not supported():
        raise RuntimeError("이 컴퓨터에서는 Whisper 받아쓰기를 쓸 수 없습니다 (Apple Silicon 맥 또는 64비트 윈도우 필요).")
    exe = binary()
    if not exe:
        raise RuntimeError("Whisper 실행 파일이 없습니다. 쓰담을 최신 버전으로 다시 설치하세요.")
    mid = best_installed(model_id or db.get_settings().get("whisper_model"))
    if not mid:
        raise RuntimeError("Whisper 모델이 없습니다. 설정 → 받아쓰기 엔진에서 모델을 내려받으세요.")
    import platform_util
    # 윈도우판 whisper-cli 는 한글 경로를 '??'로 읽음 ("쓰담" 폴더, 한글 사용자 이름) →
    # 작업 폴더를 모델 폴더로 두고 파일 이름만 넘김. 한글 시작 문구도 깨지므로 윈도우에서는 넣지 않음
    win = platform_util.IS_WIN
    tmp = os.path.join(MODEL_DIR, "_work", "%d-%d" % (os.getpid(), int(time.time() * 1000))) if win else tempfile.mkdtemp(prefix="seteuk-wh-")
    os.makedirs(tmp, exist_ok=True)
    try:
        wav = os.path.join(tmp, "a.wav")
        to_wav16k(audio_path, wav)
        threads = max(2, min(8, (os.cpu_count() or 4) - 2))
        vad = os.path.join(MODEL_DIR, VAD["file"])
        if win:
            cmd = [exe, "-m", os.path.basename(model_path(mid)), "-f", os.path.relpath(wav, MODEL_DIR),
                   "-l", "ko", "-t", str(threads), "-pp"]
            if os.path.exists(vad):
                cmd += ["--vad", "-vm", VAD["file"]]
        else:
            cmd = [exe, "-m", model_path(mid), "-f", wav, "-l", "ko", "-t", str(threads), "-pp",
                   "--prompt", _initial_prompt(students or [], kind)]
            if os.path.exists(vad):
                cmd += ["--vad", "-vm", vad]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=MODEL_DIR if win else None, **_no_window())
        err_tail = []

        def read_err():
            for raw in proc.stderr:
                line = raw.decode("utf-8", "replace").strip()
                m = re.search(r"progress\s*=\s*(\d+)%", line)
                if m and on_progress:
                    on_progress(int(m.group(1)))
                else:
                    err_tail.append(line)
                    del err_tail[:-200]
        t = threading.Thread(target=read_err, daemon=True)
        t.start()
        out = proc.stdout.read().decode("utf-8", "replace")
        proc.wait()
        t.join(2)
        if proc.returncode != 0:
            # 사용법이 길게 찍히면 원인 줄(error: …)이 묻히므로 그 줄을 먼저
            cause = [l for l in err_tail if "error" in l.lower() or "unknown" in l.lower() or "failed" in l.lower()]
            raise RuntimeError("Whisper 실행 오류: %s" % " / ".join((cause or err_tail)[-3:]))
        text = format_segments(out)
        if not text.strip():
            raise NoSpeechDetected("말소리를 찾지 못했어요. 녹음을 듣고 일반 메모로 보관하거나 쓰담에서 제외해 주세요.")
        return text
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def format_segments(out):
    """'[00:01:02.000 --> 00:01:05.000]  텍스트' → '[01:02] 텍스트' (같은 말 반복 환각 제거)"""
    lines, last = [], None
    for line in out.splitlines():
        m = re.match(r"\[(\d+):(\d+):(\d+)\.\d+\s*-->\s*[^\]]+\]\s*(.*)", line)
        if not m:
            continue
        text = m.group(4).strip()
        if not text or text == last:
            continue
        last = text
        h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        stamp = "%02d:%02d" % (h * 60 + mi, s)
        lines.append("[%s] %s" % (stamp, text))
    return "\n".join(lines)
