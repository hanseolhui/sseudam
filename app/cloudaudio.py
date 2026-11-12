# -*- coding: utf-8 -*-
"""로컬 audio 보관함의 기기별 증분 사본. 제공자의 원격 업로드는 확인하지 않는다."""
import hashlib
import json
import os
import re
import stat
import tempfile
import threading
import unicodedata

import db

AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".aac", ".mp4", ".caf", ".aiff", ".aif", ".flac", ".ogg", ".qta", ".3gp"}
CHUNK_SIZE = 1024 * 1024
_lock = threading.Lock()
RESTORE_GUIDE = """쓰담 녹음 원본 사본\n\n기록 ZIP과 이 폴더의 audio/ 원본 녹음은 별도입니다. 복원에 대비해 함께 보관하세요.\n같은 컴퓨터에서 복원할 때는 쓰담을 종료하고, 기존 data/audio를 별도로 보존한 뒤 audio/의 상대 폴더 구조를 유지하여 data/audio에 복사하세요.\n다른 컴퓨터에서는 기록 DB의 녹음 경로를 다시 연결해야 합니다. 그대로 덮어쓰지 말고 지원을 요청하세요.\n.history/는 변경 전 사본이며 manifest.json은 상대경로·크기·SHA-256 검증 정보입니다.\n원본을 삭제해도 이곳의 녹음 사본과 이전 버전은 자동 삭제하지 않습니다.\n이 폴더에 저장됐다는 사실과 iCloud·OneDrive의 업로드 완료는 다릅니다. 업로드 상태는 해당 클라우드 앱에서 확인하세요.\n"""


class CloudAudioError(OSError):
    """백업을 완전히 마치지 못했음. 호출자는 성공 시각을 갱신하지 않아야 한다."""


def _within(path, root):
    try:
        return os.path.commonpath([os.path.realpath(path), root]) == root
    except ValueError:
        return False


def _relative(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise CloudAudioError("녹음 사본의 상대경로가 올바르지 않아요.")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts) or os.path.isabs(value) or re.match(r"^[A-Za-z]:", value):
        raise CloudAudioError("녹음 사본의 상대경로가 올바르지 않아요.")
    return parts


def _guard(path, root, missing=False):
    """승인된 루트 내부의 모든 구성요소를 검사한다. 링크는 안쪽을 가리켜도 거부한다."""
    path = os.path.abspath(path)
    if not _within(path, root):
        raise CloudAudioError("녹음 사본 경로가 지정한 폴더 밖을 가리켜요.")
    rel = os.path.relpath(path, root)
    current = root
    for part in ([] if rel == "." else rel.split(os.sep)):
        current = os.path.join(current, part)
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            if missing:
                continue
            raise
        if stat.S_ISLNK(info.st_mode):
            raise CloudAudioError("심볼릭 링크는 녹음 원본 백업에 사용할 수 없어요.")
    if not _within(path, root):
        raise CloudAudioError("녹음 사본 경로가 바뀌었어요. 다시 시도해 주세요.")
    return path


def _root(path):
    path = os.path.abspath(os.fspath(path))
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise CloudAudioError("녹음 원본과 백업 위치는 실제 폴더여야 해요.")
    return os.path.realpath(path)


def _mkdirs(path, root):
    _guard(path, root, missing=True)
    os.makedirs(path, exist_ok=True)
    _guard(path, root)
    if not stat.S_ISDIR(os.lstat(path).st_mode):
        raise CloudAudioError("녹음 사본 폴더를 만들 수 없어요.")


def _signature(info):
    return {"size": info.st_size, "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns,
            "dev": info.st_dev, "ino": info.st_ino}


def _content_signature(info):
    # 제공자가 xattr 등 메타데이터만 바꾸면 ctime은 달라질 수 있다.
    # 읽는 파일의 정체성·크기·수정 시각과 별도 SHA-256 검증은 그대로 유지한다.
    return {"size": info.st_size, "mtime_ns": info.st_mtime_ns, "dev": info.st_dev, "ino": info.st_ino}


def _destination_signature(info):
    # 클라우드의 온라인 전용 전환은 inode/ctime을 바꿀 수 있다. 본문 재다운로드를 강제하지 않는다.
    return {"size": info.st_size, "mtime_ns": info.st_mtime_ns}


def _regular(path, root):
    _guard(path, root)
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        raise CloudAudioError("녹음 사본은 일반 파일만 보관할 수 있어요.")
    return info


def _stream(path, root, output=None, cloud=False):
    before = _regular(path, root)
    signature = _content_signature if cloud else _signature
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    digest = hashlib.sha256()
    with os.fdopen(os.open(path, flags), "rb") as source:
        opened = os.fstat(source.fileno())
        if signature(opened) != signature(before):
            raise CloudAudioError("녹음 파일이 바뀌고 있어요. 잠시 후 다시 시도해 주세요.")
        _guard(path, root)
        for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
            digest.update(chunk)
            if output is not None:
                output.write(chunk)
        after = os.fstat(source.fileno())
    named = _regular(path, root)
    if signature(before) != signature(after) or signature(after) != signature(named):
        raise CloudAudioError("복사 중 녹음 파일이 바뀌었어요. 기존 사본을 유지했어요.")
    return digest.hexdigest(), after


def _stage(source, source_root, destination, destination_root, expected=None, source_is_cloud=False):
    _mkdirs(os.path.dirname(destination), destination_root)
    fd, temporary = tempfile.mkstemp(prefix=".sseudam-audio-", suffix=".tmp", dir=os.path.dirname(destination))
    try:
        with os.fdopen(fd, "wb") as output:
            _guard(temporary, destination_root)
            digest, info = _stream(source, source_root, output, cloud=source_is_cloud)
            if expected is not None and digest != expected:
                raise CloudAudioError("복사 중 녹음 내용이 바뀌었어요. 다시 시도해 주세요.")
            output.flush()
            os.fsync(output.fileno())
        saved_digest, saved_info = _stream(temporary, destination_root, cloud=True)
        if saved_digest != digest or saved_info.st_size != info.st_size:
            raise CloudAudioError("녹음 사본 검증에 실패했어요. 기존 사본을 유지했어요.")
        return temporary, digest, info
    except BaseException:
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise


def _atomic_text(path, root, content):
    _mkdirs(os.path.dirname(path), root)
    _guard(path, root, missing=True)
    if os.path.lexists(path):
        _regular(path, root)
    fd, temporary = tempfile.mkstemp(prefix=".sseudam-audio-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as output:
            _guard(temporary, root)
            output.write(content.encode("utf-8"))
            output.flush()
            os.fsync(output.fileno())
        _guard(path, root, missing=True)
        os.replace(temporary, path)
    finally:
        try:
            os.remove(temporary)
        except OSError:
            pass


def _load_manifest(path, root, device_id):
    if not os.path.lexists(path):
        return {}
    _regular(path, root)
    with open(path, encoding="utf-8") as source:
        data = json.load(source)
    if data.get("schema") != 1 or data.get("device_id") != device_id or not isinstance(data.get("files"), dict):
        raise CloudAudioError("기존 녹음 사본 목록을 확인할 수 없어요.")
    for relative, item in data["files"].items():
        _relative(relative)
        if not isinstance(item, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))):
            raise CloudAudioError("기존 녹음 사본 검증 정보가 올바르지 않아요.")
    return data["files"]


def _sources(root):
    files = []
    names = set()
    def failed(error):
        raise error
    for parent, dirs, children in os.walk(root, topdown=True, followlinks=False, onerror=failed):
        _guard(parent, root)
        for name in dirs:
            path = os.path.join(parent, name)
            _guard(path, root)
        for name in sorted(children):
            path = os.path.join(parent, name)
            _guard(path, root)  # 확장자가 달라도 링크는 따라가지 않고 실패한다.
            if os.path.splitext(name)[1].lower() not in AUDIO_EXTS:
                continue
            relative = os.path.relpath(path, root).replace(os.sep, "/")
            _relative(relative)
            canonical = unicodedata.normalize("NFC", relative).casefold()
            if canonical in names:
                raise CloudAudioError("대소문자나 한글 표기만 다른 녹음 경로가 있어요. 사본을 덮어쓰지 않았어요.")
            names.add(canonical)
            files.append((relative, path, _regular(path, root)))
    return sorted(files)


def sync(folder, device_id, verify=False):
    """변경된 파일만 저장한다. verify=True는 캐시를 건너뛰고 본문 SHA-256를 대조한다.

    일부 파일 저장 뒤 실패할 수 있으나, 실패 파일의 기존 사본은 유지한다.
    전체 성공 뒤에만 manifest를 갱신하며 원본에서 사라진 사본·이력은 삭제하지 않는다.
    """
    if not isinstance(device_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", device_id):
        raise CloudAudioError("백업 기기 번호가 올바르지 않아요.")
    with _lock:
        try:
            return _sync(folder, device_id, verify)
        except CloudAudioError:
            raise
        except (OSError, ValueError, TypeError) as error:
            raise CloudAudioError("녹음 원본 백업을 마치지 못했어요: %s" % error) from error


def _sync(folder, device_id, verify):
    source_root = _root(db.AUDIO_DIR)
    cloud_root = _root(folder)
    device_root = os.path.join(cloud_root, "쓰담-녹음-" + device_id)
    if _within(cloud_root, source_root) or _within(source_root, device_root):
        raise CloudAudioError("녹음 원본 폴더 안에 백업 폴더를 둘 수 없어요.")
    # 모두 탐색한 뒤 쓰기 시작: 접근 실패를 원본 삭제로 오인하지 않는다.
    sources = _sources(source_root)
    _mkdirs(device_root, cloud_root)
    audio_root = os.path.join(device_root, "audio")
    _mkdirs(audio_root, device_root)
    manifest_path = os.path.join(device_root, "manifest.json")
    previous = _load_manifest(manifest_path, device_root, device_id)
    current_names = {relative for relative, _, _ in sources}
    entries = {name: dict(item, source_present=False) for name, item in previous.items() if name not in current_names}
    result = {"ok": True, "folder": device_root, "files": len(sources), "bytes": 0, "copied": 0,
              "copied_bytes": 0, "unchanged": 0, "missing": len(entries), "versions_saved": 0,
              "manifest": manifest_path}
    for relative, source, scanned in sources:
        source_info = _regular(source, source_root)
        if _signature(source_info) != _signature(scanned):
            raise CloudAudioError("검사 중 녹음 파일이 바뀌었어요. 다시 시도해 주세요.")
        destination = os.path.join(audio_root, *_relative(relative))
        _guard(destination, device_root, missing=True)
        old_info = _regular(destination, device_root) if os.path.lexists(destination) else None
        cached = previous.get(relative, {})
        if (not verify and old_info is not None and cached.get("source") == _signature(source_info)
                and cached.get("destination") == _destination_signature(old_info)):
            digest = cached["sha256"]
            result["unchanged"] += 1
        else:
            digest, source_info = _stream(source, source_root)
            old_digest = None
            if old_info is not None:
                old_digest, old_info = _stream(destination, device_root, cloud=True)
            if old_digest == digest:
                result["unchanged"] += 1
            else:
                temporary, copied_digest, copied_info = _stage(source, source_root, destination, device_root, digest)
                try:
                    if _signature(source_info) != _signature(copied_info):
                        raise CloudAudioError("녹음 파일이 바뀌고 있어요. 기존 사본을 유지했어요.")
                    if old_info is not None:
                        ext = os.path.splitext(relative)[1].lower()
                        history = os.path.join(device_root, ".history", *_relative(relative), old_digest + ext)
                        _guard(history, device_root, missing=True)
                        if os.path.lexists(history):
                            history_digest, _ = _stream(history, device_root, cloud=True)
                            if history_digest != old_digest:
                                raise CloudAudioError("이전 녹음 사본의 해시가 일치하지 않아요. 기존 파일을 유지했어요.")
                        else:
                            history_tmp, _, _ = _stage(destination, device_root, history, device_root, old_digest,
                                                       source_is_cloud=True)
                            try:
                                _guard(history, device_root, missing=True)
                                os.replace(history_tmp, history)
                                result["versions_saved"] += 1
                            finally:
                                if os.path.exists(history_tmp):
                                    os.remove(history_tmp)
                        if _content_signature(_regular(destination, device_root)) != _content_signature(old_info):
                            raise CloudAudioError("기존 녹음 사본이 변경됐어요. 덮어쓰지 않았어요.")
                    elif os.path.lexists(destination):
                        raise CloudAudioError("같은 위치에 다른 녹음 사본이 생겼어요. 덮어쓰지 않았어요.")
                    _guard(destination, device_root, missing=True)
                    os.replace(temporary, destination)
                    result["copied"] += 1
                    result["copied_bytes"] += copied_info.st_size
                finally:
                    if os.path.exists(temporary):
                        os.remove(temporary)
        saved_info = _regular(destination, device_root)
        entries[relative] = {"sha256": digest, "bytes": source_info.st_size, "source_present": True,
                             "source": _signature(source_info), "destination": _destination_signature(saved_info)}
        result["bytes"] += source_info.st_size
    guide = os.path.join(device_root, "복원 안내.txt")
    if not os.path.lexists(guide):
        _atomic_text(guide, device_root, RESTORE_GUIDE)
    else:
        _regular(guide, device_root)
    manifest = {"schema": 1, "device_id": device_id, "files": entries}
    if previous != entries or not os.path.exists(manifest_path):
        _atomic_text(manifest_path, device_root, json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return result
