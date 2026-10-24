"""QR 연동 — 휴대폰(아이폰·안드로이드) ↔ 컴퓨터(맥·윈도우), 어떤 조합이든.

컴퓨터가 무작위 채널(128비트)과 열쇠(256비트)를 만들어 QR로 보여 주고, 폰이 찍어서 나눠 가진다.
녹음·학생 기록은 이 열쇠로 암호화한 덩어리만 중계 서버(Cloudflare)를 거친다 → 서버는 내용을 볼 수 없다.
받은 쪽이 지우고, 14일 지난 것은 서버가 지운다.

암호 방식 (파이썬 기본 기능 · iOS CryptoKit · 안드로이드 javax.crypto 모두 그대로 계산 가능):
  kEnc = HMAC-SHA256(열쇠, "sseudam-enc"), kMac = HMAC-SHA256(열쇠, "sseudam-mac"), 토큰 = hex(HMAC-SHA256(열쇠, "sseudam-relay-auth"))
  덩어리 = "SSD1"(4) + nonce(16) + 암호문 + tag(32)
  암호문 = 평문 XOR (HMAC-SHA256(kEnc, nonce ‖ 블록번호 8바이트 big-endian) 을 이어 붙인 키 스트림)
  tag   = HMAC-SHA256(kMac, "SSD1" ‖ nonce ‖ 암호문)        (암호화한 뒤 MAC — 위조·변조 확인)
  평문   = 메타 JSON 길이(4바이트 big-endian) + 메타 JSON(UTF-8) + 본문(녹음 바이트, 없으면 빈)
상자 이름: phone → pc 는 'pc' 상자 (rec-….bin 녹음, doc-<기기>.bin 학생 기록), pc → phone 은 'phone' 상자 (doc-pc.bin).
컴퓨터 ↔ 컴퓨터(쓰담 플러스): 다른 컴퓨터가 이 컴퓨터의 '연결 코드'로 같은 채널에 들어오면, 둘 다 'peer' 상자에
자기 학생 기록(doc-<기기>.bin)을 올려 두고 서로의 것을 읽어 합친다 (지우지 않고 덮어씀 · sync_text 가 최신 것을 고름).
폰이 보낸 녹음은 먼저 받은 컴퓨터가 가져가고, 거기서 나온 학생 기록은 peer 로 다른 컴퓨터에도 간다.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import socket
import tempfile
import threading
import time
import urllib.request

import db

URL = os.environ.get("SSEUDAM_RELAY_URL", "https://sseudam-relay.hanseolhui.workers.dev")
MAGIC = b"SSD1"
POLL = 60                      # 폰에서 온 게 있나 1분마다 (쓰담이 켜져 있을 때만)
_status = {"state": "꺼짐", "last": 0, "error": "", "received": 0}
_lock = threading.Lock()


# ───────────────────────── 암호 ─────────────────────────

def _h(key, data):
    return hmac.new(key, data, hashlib.sha256).digest()


def keys(master):
    return _h(master, b"sseudam-enc"), _h(master, b"sseudam-mac"), _h(master, b"sseudam-relay-auth").hex()


def _stream(k_enc, nonce, n):
    out = bytearray()
    i = 0
    while len(out) < n:
        out += _h(k_enc, nonce + i.to_bytes(8, "big"))
        i += 1
    return bytes(out[:n])


def _xor(a, b):
    return (int.from_bytes(a, "big") ^ int.from_bytes(b, "big")).to_bytes(len(a), "big") if a else b""


def seal(master, meta, body=b""):
    k_enc, k_mac, _ = keys(master)
    m = json.dumps(meta, ensure_ascii=False).encode("utf-8")
    plain = len(m).to_bytes(4, "big") + m + (body or b"")
    nonce = secrets.token_bytes(16)
    ct = _xor(plain, _stream(k_enc, nonce, len(plain)))
    return MAGIC + nonce + ct + _h(k_mac, MAGIC + nonce + ct)


def open_(master, blob):
    if len(blob) < 4 + 16 + 32 or blob[:4] != MAGIC:
        raise ValueError("쓰담 연동 형식이 아니에요")
    k_enc, k_mac, _ = keys(master)
    nonce, ct, tag = blob[4:20], blob[20:-32], blob[-32:]
    if not hmac.compare_digest(tag, _h(k_mac, MAGIC + nonce + ct)):
        raise ValueError("열쇠가 맞지 않거나 손상된 덩어리예요")
    plain = _xor(ct, _stream(k_enc, nonce, len(ct)))
    n = int.from_bytes(plain[:4], "big")
    return json.loads(plain[4:4 + n].decode("utf-8")), plain[4 + n:]


def b64u(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def unb64u(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ───────────────────────── 연결 정보 ─────────────────────────

def paired():
    s = db.get_settings()
    return bool(s.get("relay_channel") and s.get("relay_key"))


def _creds():
    s = db.get_settings()
    ch, key = s.get("relay_channel") or "", s.get("relay_key") or ""
    if not (ch and key):
        return None
    return ch, unb64u(key), (s.get("relay_url") or URL).rstrip("/")


def pair_info(new=False):
    """QR에 넣을 연결 정보. 처음이거나 new 면 새 채널·열쇠를 만든다."""
    if new or not paired():
        if paired():
            unpair(remote=True)
        db.set_settings({"relay_channel": secrets.token_hex(16), "relay_key": b64u(secrets.token_bytes(32)), "relay_url": URL})
    ch, master, url = _creds()
    name = db.get_settings().get("teacher_name") or socket.gethostname().replace(".local", "")
    q = "sseudam://pair?v=1&u=%s&c=%s&k=%s&n=%s" % (urllib.request.quote(url, safe=""), ch, b64u(master), urllib.request.quote(name, safe=""))
    return {"qr": q, "channel": ch[:6], "url": url}


def peer_enabled():
    """컴퓨터끼리 자동 맞추기: 쓰담 플러스 기능."""
    import plus
    return paired() and plus.ENABLED and plus.active()


def join(code):
    """다른 컴퓨터의 연결 코드(sseudam://pair…)로 그 컴퓨터와 같은 채널에 들어가기 (이 컴퓨터의 휴대폰 연결은 바뀜)."""
    import urllib.parse
    u = urllib.parse.urlparse((code or "").strip())
    q = dict(urllib.parse.parse_qsl(u.query))
    if u.scheme != "sseudam" or u.netloc != "pair" or q.get("v") != "1":
        raise ValueError("연결 코드가 아니에요. 다른 컴퓨터의 쓰담 → 설정 → 휴대폰에서 '연결 코드 복사'로 받은 글을 붙여넣어 주세요.")
    ch, key, url = q.get("c", ""), q.get("k", ""), q.get("u", "")
    if not (len(ch) == 32 and all(c in "0123456789abcdef" for c in ch) and url.startswith("https://") and len(unb64u(key)) == 32):
        raise ValueError("연결 코드가 올바르지 않아요.")
    if paired() and db.get_settings().get("relay_channel") == ch:
        return pair_info()
    db.set_settings({"relay_channel": ch, "relay_key": key, "relay_url": url.rstrip("/"), "relay_devices": "", "relay_doc_sig": "", "relay_peer_sig": ""})
    _status.update(state="연결됨")
    return pair_info()


def _peer_id():
    import sync_text
    conn = db.connect()
    try:
        return "".join(c for c in sync_text._device(conn) if c.isalnum() or c in "-_")[:40] or "pc"
    finally:
        conn.close()


def push_peer(doc):
    """다른 컴퓨터가 읽게 'peer' 상자에 내 기록 — 바뀌었거나 사흘 지났으면 (14일 자동 삭제 전에 다시 올림)."""
    c = _creds()
    if not c or not peer_enabled():
        return False
    body = json.dumps({k: v for k, v in doc.items() if k != "updated_at"}, sort_keys=True, default=str)
    sig = hashlib.sha256(body.encode()).hexdigest()
    s = db.get_settings()
    last = float(s.get("relay_peer_at") or 0)
    if s.get("relay_peer_sig") == sig and time.time() - last < 3 * 86400:
        return False
    meta = {"type": "doc", "device": _peer_id(), "device_name": socket.gethostname().replace(".local", "")[:40], "peer": True}
    _req("PUT", "/peer/doc-%s.bin" % _peer_id(), c, seal(c[1], meta, json.dumps(doc, ensure_ascii=False, default=str).encode("utf-8")))
    db.set_settings({"relay_peer_sig": sig, "relay_peer_at": str(time.time())})
    return True


_peer_seen = {}


def poll_peers(c):
    """다른 컴퓨터들이 올린 기록 받아 오기 (지우지 않음 · 바뀐 것만)."""
    if not peer_enabled():
        return 0
    me = "doc-%s.bin" % _peer_id()
    got = 0
    try:
        items = json.loads(_req("GET", "/peer", c)).get("items", [])
    except Exception:  # noqa — 예전 중계 서버 등
        return 0
    names = []
    for it in items:
        name = it["name"]
        if name == me or not name.startswith("doc-"):
            continue
        stamp = "%s/%s" % (it.get("size"), it.get("at"))
        if _peer_seen.get(name) == stamp:
            names.append(name)
            continue
        try:
            meta, body = open_(c[1], _req("GET", "/peer/" + name, c, timeout=120))
        except Exception as e:  # noqa
            print("[컴퓨터 맞추기] 열지 못함:", name, e)
            continue
        dev = "".join(ch for ch in str(meta.get("device") or name) if ch.isalnum() or ch in "-_")[:40]
        with open(os.path.join(inbox_dir(), "relay-peer-%s.json" % dev), "wb") as f:
            f.write(body)
        _peer_seen[name] = stamp
        names.append(name)
        got += 1
    _status["peers"] = len(names)
    return got


def unpair(remote=True):
    c = _creds()
    if c and remote:
        try:
            _req("DELETE", "", c)
        except Exception:  # noqa
            pass
    db.set_settings({"relay_channel": "", "relay_key": "", "relay_devices": ""})
    _status.update(state="꺼짐")


# ───────────────────────── 서버와 주고받기 ─────────────────────────

def _req(method, path, c, body=None, timeout=60):
    ch, master, url = c
    req = urllib.request.Request("%s/v1/%s%s" % (url, ch, path), data=body, method=method,
                                 headers={"x-relay-token": keys(master)[2], "User-Agent": "sseudam",
                                          **({"Content-Type": "application/octet-stream"} if body is not None else {})})
    import gemini
    with urllib.request.urlopen(req, timeout=timeout, context=gemini._CTX) as r:
        return r.read()


def push_doc(doc):
    """내 학생 기록(동기화 문서)을 폰 상자에 올림 — 바뀐 경우만."""
    c = _creds()
    if not c:
        return False
    body = json.dumps({k: v for k, v in doc.items() if k != "updated_at"}, sort_keys=True, default=str)
    sig = hashlib.sha256(body.encode()).hexdigest()
    if db.get_settings().get("relay_doc_sig") == sig:
        return False
    _req("PUT", "/phone/doc-pc.bin", c, seal(c[1], {"type": "doc"}, json.dumps(doc, ensure_ascii=False, default=str).encode("utf-8")))
    db.set_settings({"relay_doc_sig": sig})
    return True


def inbox_dir():
    """폰에서 받은 학생 기록 문서를 두는 곳 (sync_text 가 iCloud 폴더처럼 읽음)."""
    if not paired():
        return None
    d = os.path.join(db.DATA_DIR, "relay-sync")
    os.makedirs(d, exist_ok=True)
    return d


def poll_once():
    """폰이 보낸 녹음·기록 받아 오기."""
    c = _creds()
    if not c:
        return {"ok": False, "message": "연결 안 됨"}
    with _lock:
        got = 0
        items = json.loads(_req("GET", "/pc", c)).get("items", [])
        devices = set(filter(None, (db.get_settings().get("relay_devices") or "").split(",")))
        for it in items:
            name = it["name"]
            try:
                meta, body = open_(c[1], _req("GET", "/pc/" + name, c, timeout=180))
            except Exception as e:  # noqa — 열쇠가 다르거나 깨진 것은 지운다
                print("[QR 연동] 열지 못함:", name, e)
                _req("DELETE", "/pc/" + name, c)
                continue
            if meta.get("device_name"):
                devices.add(str(meta["device_name"])[:40])
            if meta.get("type") == "rec":
                _import_recording(meta, body)
            elif meta.get("type") == "doc":
                dev = "".join(ch for ch in str(meta.get("device") or "phone") if ch.isalnum() or ch in "-_")[:40] or "phone"
                with open(os.path.join(inbox_dir(), "relay-%s.json" % dev), "wb") as f:
                    f.write(body)
            _req("DELETE", "/pc/" + name, c)
            got += 1
        db.set_settings({"relay_devices": ",".join(sorted(devices))})
        got += poll_peers(c)
        _status.update(state="연결됨", last=time.time(), error="", received=_status["received"] + got)
        return {"ok": True, "received": got}


def _import_recording(meta, audio):
    import watcher
    ext = meta.get("ext") or ".m4a"
    if not ext.startswith(".") or len(ext) > 6:
        ext = ".m4a"
    fd, tmp = tempfile.mkstemp(suffix=ext, prefix="sseudam-qr-")
    with os.fdopen(fd, "wb") as f:
        f.write(audio)
    try:
        name = meta.get("name") or ("휴대폰 녹음" + ext)
        watcher.create_recording(
            class_id=None, kind=meta.get("kind"), title=meta.get("title") or os.path.splitext(name)[0],
            recorded_at=meta.get("recorded_at"), audio_src=tmp if audio else None,
            transcript=meta.get("transcript") or "", original_name=name, copy=True)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def status():
    s = db.get_settings()
    return dict(_status, paired=paired(), devices=[d for d in (s.get("relay_devices") or "").split(",") if d],
                peer_enabled=peer_enabled())


def _loop():
    time.sleep(5)
    while True:
        if paired():
            try:
                poll_once()
                import sync_text
                sync_text.sync_once()
            except Exception as e:  # noqa — 인터넷이 안 될 때 등
                _status.update(state="잠시 연결 안 됨", error=str(e))
        time.sleep(POLL)


def start():
    if os.environ.get("SETEUK_DATA") and os.environ.get("SSEUDAM_RELAY_TEST") != "1":
        return   # 테스트 데이터 서버는 실제 연결을 돌리지 않음
    threading.Thread(target=_loop, daemon=True, name="relay").start()
