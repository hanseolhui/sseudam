# -*- coding: utf-8 -*-
"""백업 파일에 넣지 않는 연결 정보 · 복원해도 이 컴퓨터의 것을 그대로 두는 연결 정보.

밖으로 나가는 백업(구글 드라이브)에는 AI 키 · 쓰담 플러스 로그인 · 휴대폰 연결 열쇠 · 학교 연결을 넣지 않는다.
백업 파일을 본 사람이 그 값으로 선생님 계정이나 휴대폰 연결을 쓸 수 없게 하기 위해서다.
복원할 때는 이 컴퓨터에 지금 연결돼 있는 것을 그대로 둔다 (옛 백업의 낡은 로그인 · 열쇠로 되돌아가지 않게).
이 컴퓨터 안의 자동 백업(backups 폴더)은 그대로 전체 사본이다.
"""
import sqlite3

import db

# (연결돼 있는지 보는 설정, 함께 움직이는 설정들)
CONNECTIONS = (
    ("gemini_api_key", ("gemini_api_key",)),
    ("openai_api_key", ("openai_api_key",)),
    ("claude_api_key", ("claude_api_key",)),
    ("plus_token", ("plus_token", "plus_email", "plus_active", "plus_status", "plus_checked")),
    ("relay_key", ("relay_channel", "relay_key", "relay_url", "relay_devices", "relay_acks",
                   "relay_doc_sig", "relay_peer_sig", "relay_peer_at")),
    ("school_link_token", ("school_link_token", "school_link_device", "school_link_name", "school_link_teacher")),
    # 비밀은 아니지만 이 컴퓨터의 폴더 주소라 다른 컴퓨터로 따라가면 안 된다
    ("backup_folder", ("backup_folder", "backup_folder_last", "backup_folder_error")),
)
# 구글 연결은 백업에 그대로 둔다. 백업이 놓이는 곳이 바로 그 구글 드라이브이고, 같은 토큰이 그 계정의
# Apps Script 에 적혀 있어 빼도 지켜지는 것이 없다. 빼면 새 컴퓨터에서 스크립트를 다시 배포해야 한다.
GOOGLE = ("sheets_url", ("sheets_url", "sheets_token", "upload_token"))

LEFT_OUT = tuple(k for _, keys in CONNECTIONS for k in keys)


def scrub(path):
    """DB 사본(path)에서 연결 정보를 기본값으로 비운다. 지운 값이 파일의 빈 자리에 남지 않게 새로 써서 줄인다."""
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA secure_delete = ON")
        with conn:
            for k in LEFT_OUT:
                conn.execute("UPDATE settings SET value=? WHERE key=?", (db.DEFAULT_SETTINGS.get(k, ""), k))
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def remember(conn):
    """복원 전에: 이 컴퓨터에 지금 연결돼 있는 것들의 설정 값."""
    try:
        now = {r[0]: r[1] for r in conn.execute("SELECT key, value FROM settings")}
    except sqlite3.OperationalError:   # 설정 표가 아직 없는 새 DB
        return {}
    keep = {}
    for marker, keys in CONNECTIONS + (GOOGLE,):
        if now.get(marker):
            keep.update({k: now[k] for k in keys if k in now})
    return keep


def put_back(conn, keep):
    """복원 뒤에: remember 로 담아 둔 이 컴퓨터의 연결을 다시 넣는다."""
    for k, v in keep.items():
        conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (k, v))
