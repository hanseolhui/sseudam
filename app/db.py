# -*- coding: utf-8 -*-
"""SQLite 저장소. Python 3.9 표준 라이브러리만 사용."""
import os
import shutil
import sqlite3
import datetime
import json

import platform_util

APP_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(APP_DIR)
# 데이터는 프로그램(코드)과 분리해 사용자 라이브러리에 둔다 → 업데이트·재설치해도 기록이 보존됨
SUPPORT_DIR = platform_util.support_dir()
DATA_DIR = os.environ.get("SETEUK_DATA") or os.path.join(SUPPORT_DIR, "data")
AUDIO_DIR = os.path.join(DATA_DIR, "audio")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
DB_PATH = os.path.join(DATA_DIR, "seteuk.db")

DEFAULT_SETTINGS = {
    "mode": "api",                      # api | manual
    "gemini_api_key": "",
    "gemini_model": "gemini-2.5-flash",
    "api_provider": "gemini",           # 외부 AI API: gemini | openai | claude
    "openai_api_key": "",
    "openai_model": "",                 # 비우면 키로 받은 목록에서 가장 좋은 모델
    "claude_api_key": "",
    "claude_model": "claude-opus-5-5",
    "plus_token": "",                   # 쓰담 플러스(구독) 로그인 — 이 컴퓨터 토큰
    "plus_email": "",
    "plus_active": "0",
    "plus_status": "",
    "plus_checked": "0",
    "relay_peer_sig": "",               # 컴퓨터끼리 맞추기: 마지막으로 올린 내 기록
    "relay_peer_at": "0",
    "byte_limit": "1500",
    "school_level": "고등학교",
    "teacher_subject": "",
    "style_examples": "",
    "draft_guidance": "",
    "inbox_dir": os.path.join(platform_util.icloud_drive_dir(), "쓰담 녹음"),
    "auto_process": "1",                # 수신 폴더 파일을 자동 전사·분리
    "sheets_url": "",
    "sheets_token": "",
    # 아이폰 음성메모 자동 가져오기 (iCloud 동기화된 맥의 음성메모 보관함)
    "voicememo_enabled": "0",
    "voicememo_since": "",          # 이 시각 이후 녹음만 가져옴 (켜는 순간으로 설정)
    "voicememo_keyword": "",        # 제목에 이 단어가 있는 녹음만 (비우면 전부)
    # 메모 앱(받아쓰기) 가져오기
    "notes_enabled": "0",
    "notes_folder": "세특",
    # 시간표: 녹음 시각으로 학급 자동 지정
    "period_times": "09:00-09:50\n10:00-10:50\n11:00-11:50\n12:00-12:50\n13:40-14:30\n14:40-15:30\n15:40-16:30",
    "timetable": "{}",              # {"1-3": 학급id} = 월요일 3교시
    "update_check": "1",
    # 받아쓰기 엔진: whisper(기본, 내 맥 안에서만) | gemini(외부 전송)
    "stt_engine": "whisper",
    # 학생별 분리 엔진: auto | gemini | local(Ollama·LM Studio) | apple(기기 안 AI) | rules(이름 기준)
    "seg_engine": "auto",
    # 사용 정보 보내기 (문제 해결·업데이트 지원): 익명 사양은 기본 켬, 이름·학교·이메일은 선생님이 켤 때만
    "telemetry": "1",
    # QR 연동 (휴대폰 ↔ 컴퓨터, 종단 암호화): 채널·열쇠는 이 컴퓨터와 연결한 폰만 앎
    "relay_channel": "",
    "relay_key": "",
    "relay_url": "",
    "relay_devices": "",
    "relay_acks": "{}",          # 폰마다 받은 녹음 이름 (폰에 '컴퓨터가 받음' 알림 · 다시 보낸 것 한 번만 담기)
    "relay_doc_sig": "",
    "install_id": "",
    "last_ping": "",
    "share_info": "0",              # 선생님 정보 보내기 = 개인정보 수집·이용 동의
    "contact_email": "",
    "school_name": "",
    "org_type": "",                 # 소속 유형: 학교 · 유치원·어린이집 · 학원·교습소 · 방과후·돌봄 · 기타 기관
    "region_sido": "",
    "region_sigungu": "",
    "teacher_grades": "",           # 맡은 학년 (예: 1, 2)
    "homeroom": "",                 # 1 담임 · 0 비담임 · 빈칸 모름
    "phone": "",
    "marketing_ok": "0",            # (선택) 새 기능·지원 사업·연수 소식 받기
    "profile_asked": "0",           # 이미 쓰던 선생님께 정보 적기를 한 번 물어봤는지
    "ai_choice": "",                # 설정의 AI 고르기: builtin | apple | gemini | external | manual (비면 기존 설정으로 추정)
    "local_ai_url": "",             # 예: http://127.0.0.1:11434/v1 (Ollama), http://127.0.0.1:1234/v1 (LM Studio)
    "local_ai_model": "",
    "draft_local": "1",
    "draft_light_ok": "0",          # 가벼운 쓰담 AI 모델(8GB용)로도 초안 쓰기 — 기본은 끔             # Gemini 키가 없으면 세특 초안도 내 맥 AI 앱으로
    "whisper_model": "",
    # 구글시트 자동 동기화 + 구글 드라이브 백업
    "sheets_auto": "1",
    "drive_backup": "1",
    "sheets_last_hash": "",
    "sheets_last_sync": "",
    "sheets_last_error": "",
    "drive_last_backup": "",
    # 휴대폰 앱(아이폰·안드로이드) → 구글 드라이브 → 이 컴퓨터
    "drive_inbox": "1",
    "upload_token": "",
    # 기재 영역별 NEIS 바이트 한도 (학교 기재요령에 맞게 조정)
    "area_limits": "",
    "onboarded": "0",
    # 다운로드 폴더(AirDrop·퀵 셰어)로 받은 '쓰담 …' 파일·AirDrop 녹음 자동 가져오기
    "downloads_import": "1",
    "downloads_since": "",
    "teacher_name": "",
    # 자동 업데이트 (쉬는 틈에 새 버전으로) + 업데이트 뒤 한 번 보여 줄 안내
    "auto_update": "1",
    "updated_from": "",
    "updated_to": "",
    "updated_notes": "",
}

# 학교생활기록부 기재 영역. 학급 유형에 따라 쓸 수 있는 영역이 정해진다.
AREAS = [
    {"id": "subject", "name": "교과 세특", "full": "과목별 세부능력 및 특기사항", "bytes": 1500, "kinds": ["교과"]},
    {"id": "individual", "name": "개인별 세특", "full": "개인별 세부능력 및 특기사항", "bytes": 1500, "kinds": ["담임"]},
    {"id": "behavior", "name": "행동특성", "full": "행동특성 및 종합의견", "bytes": 900, "kinds": ["담임"]},
    {"id": "autonomy", "name": "자율·자치", "full": "자율·자치활동 특기사항", "bytes": 1500, "kinds": ["담임"]},
    {"id": "career", "name": "진로활동", "full": "진로활동 특기사항", "bytes": 2100, "kinds": ["담임"]},
    {"id": "club", "name": "동아리", "full": "동아리활동 특기사항", "bytes": 1500, "kinds": ["동아리"]},
    # 학교 밖 선생님 (유치원 · 학원 · 과외 · PT · 필라테스): NEIS가 아니라 보내는 글이라 분량은 넉넉하게 기본값만
    {"id": "kinder_obs", "name": "관찰 기록", "full": "유아 관찰 기록 (누리과정 5개 영역)", "bytes": 1500, "kinds": ["유아반"], "school": False},
    {"id": "kinder_eval", "name": "발달 평가", "full": "학기말 유아 발달 종합 의견", "bytes": 1500, "kinds": ["유아반"], "school": False},
    {"id": "kinder_home", "name": "가정 알림", "full": "학부모에게 보내는 알림장 글", "bytes": 900, "kinds": ["유아반"], "school": False},
    {"id": "lesson_report", "name": "학습 리포트", "full": "학부모에게 보내는 학습 리포트", "bytes": 1500, "kinds": ["학원·과외"], "school": False},
    {"id": "lesson_msg", "name": "수업 피드백", "full": "수업 뒤 학부모에게 보내는 피드백 문자", "bytes": 600, "kinds": ["학원·과외"], "school": False},
    {"id": "fit_log", "name": "수업 일지", "full": "회원 수업 일지 (운동 · 자세 · 다음 목표)", "bytes": 1200, "kinds": ["PT·필라테스"], "school": False},
    {"id": "fit_report", "name": "회원 리포트", "full": "회원에게 보내는 진행 리포트", "bytes": 1500, "kinds": ["PT·필라테스"], "school": False},
    {"id": "fit_msg", "name": "회원 메시지", "full": "수업 뒤 회원에게 보내는 메시지", "bytes": 600, "kinds": ["PT·필라테스"], "school": False},
]
AREA_IDS = [a["id"] for a in AREAS]
CLASS_KINDS = ["교과", "담임", "동아리", "유아반", "학원·과외", "PT·필라테스", "기타"]
SCHOOL_AREA_IDS = [a["id"] for a in AREAS if a.get("school", True)]
NAMED_KINDS = ["유아반", "학원·과외", "PT·필라테스"]   # 학년 · 반 없이 이름만 있는 학급


def areas_for_kind(kind):
    """학급 유형별 영역. 첫 번째가 기본 영역."""
    order = {"담임": ["behavior", "autonomy", "career", "individual"],
             "동아리": ["club"], "기타": SCHOOL_AREA_IDS,
             "유아반": ["kinder_obs", "kinder_eval", "kinder_home"],
             "학원·과외": ["lesson_report", "lesson_msg"],
             "PT·필라테스": ["fit_log", "fit_report", "fit_msg"]}.get(kind, ["subject"])
    return [next(a for a in AREAS if a["id"] == i) for i in order]


def area_name(area_id):
    a = next((x for x in AREAS if x["id"] == area_id), None)
    return a["name"] if a else (area_id or "")


def area_limit(area_id, settings=None):
    settings = settings or get_settings()
    try:
        custom = json.loads(settings.get("area_limits") or "{}")
    except ValueError:
        custom = {}
    if area_id in custom:
        try:
            return int(custom[area_id])
        except (TypeError, ValueError):
            pass
    if area_id == "subject" and settings.get("byte_limit"):
        return int(settings["byte_limit"])  # 1.x 설정 호환
    a = next((x for x in AREAS if x["id"] == area_id), None)
    return a["bytes"] if a else 1500

SCHEMA = """
CREATE TABLE IF NOT EXISTS classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER, semester INTEGER, grade INTEGER, class_no INTEGER,
    subject TEXT DEFAULT '', label TEXT, kind TEXT DEFAULT '교과',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    number INTEGER, name TEXT NOT NULL, aliases TEXT DEFAULT '', memo TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id INTEGER REFERENCES classes(id) ON DELETE SET NULL,
    kind TEXT DEFAULT '수업', title TEXT DEFAULT '',
    recorded_at TEXT, audio_path TEXT, original_name TEXT,
    transcript TEXT DEFAULT '', status TEXT DEFAULT '보관됨', error TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    recording_id INTEGER REFERENCES recordings(id) ON DELETE SET NULL,
    date TEXT, kind TEXT DEFAULT '수업', category TEXT DEFAULT '',
    content TEXT NOT NULL, evidence TEXT DEFAULT '', use_in_draft INTEGER DEFAULT 1,
    area TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS unmatched (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER REFERENCES recordings(id) ON DELETE CASCADE,
    name_heard TEXT, content TEXT, evidence TEXT DEFAULT '', category TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    area TEXT DEFAULT 'subject', content TEXT, bytes INTEGER, status TEXT DEFAULT '초안',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    op TEXT, params TEXT, label TEXT DEFAULT '', status TEXT DEFAULT '대기',
    message TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime')), finished_at TEXT
);
CREATE TABLE IF NOT EXISTS class_context (
    class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    area TEXT NOT NULL DEFAULT 'subject',
    topic TEXT DEFAULT '', competencies TEXT DEFAULT '', philosophy TEXT DEFAULT '',
    PRIMARY KEY (class_id, area)
);
CREATE TABLE IF NOT EXISTS student_targets (
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    area TEXT NOT NULL DEFAULT 'subject',
    bytes INTEGER,
    PRIMARY KEY (student_id, area)
);
CREATE TABLE IF NOT EXISTS imported (
    source TEXT, ext_id TEXT, sig TEXT DEFAULT '', body TEXT DEFAULT '', recording_id INTEGER,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (source, ext_id)
);
CREATE TABLE IF NOT EXISTS trash (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT, title TEXT DEFAULT '', detail TEXT DEFAULT '', payload TEXT,
    deleted_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_students_class ON students(class_id);
CREATE INDEX IF NOT EXISTS idx_notes_student ON notes(student_id);
CREATE INDEX IF NOT EXISTS idx_drafts_student ON drafts(student_id);
"""


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate_legacy_data():
    """1.0.x는 프로그램 폴더 안 data/ 에 저장했음 → 새 위치로 옮김."""
    legacy = os.path.join(BASE_DIR, "data")
    if os.path.abspath(legacy) == os.path.abspath(DATA_DIR):
        return
    if os.path.exists(os.path.join(legacy, "seteuk.db")) and not os.path.exists(DB_PATH):
        os.makedirs(os.path.dirname(DATA_DIR), exist_ok=True)
        if os.path.isdir(DATA_DIR):
            os.rmdir(DATA_DIR)  # 비어 있는 경우만
        shutil.copytree(legacy, DATA_DIR)
        # 녹음 경로를 새 위치로 고침
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE recordings SET audio_path = REPLACE(audio_path, ?, ?) WHERE audio_path IS NOT NULL",
                     (os.path.abspath(legacy), os.path.abspath(DATA_DIR)))
        conn.commit()
        conn.close()
        os.rename(legacy, legacy + "_옮겨짐")


def init():
    try:
        _migrate_legacy_data()
    except OSError as e:
        print("이전 데이터 옮기기 실패:", e)
    for d in (DATA_DIR, AUDIO_DIR, BACKUP_DIR):
        os.makedirs(d, exist_ok=True)
    conn = connect()
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    _migrate_columns(conn)
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
    # 비정상 종료로 '진행중'에 남은 작업 정리
    conn.execute("UPDATE jobs SET status='실패', message='프로그램 재시작으로 중단됨' WHERE status IN ('대기','진행중')")
    conn.execute("UPDATE recordings SET status='오류', error='프로그램 재시작으로 중단됨' WHERE status IN ('전사중','분리중')")
    conn.commit()
    conn.close()
    daily_backup()
    try:
        import trash  # 30일 지난 휴지통 항목 비우기
        trash.purge()
    except Exception as e:  # noqa
        print("휴지통 정리 실패:", e)


def _migrate_columns(conn):
    """예전 버전 DB에 새 컬럼 추가."""
    def cols(t):
        return {r[1] for r in conn.execute("PRAGMA table_info(%s)" % t)}
    if "kind" not in cols("classes"):
        conn.execute("ALTER TABLE classes ADD COLUMN kind TEXT DEFAULT '교과'")
    if "area" not in cols("notes"):
        conn.execute("ALTER TABLE notes ADD COLUMN area TEXT DEFAULT ''")
    if "phone_meta" not in cols("recordings"):   # 휴대폰이 보낸 학생 이름표·⭐·교시 (JSON)
        conn.execute("ALTER TABLE recordings ADD COLUMN phone_meta TEXT DEFAULT ''")
    conn.execute("UPDATE drafts SET area='subject' WHERE area IS NULL OR area='' OR area='세특'")
    # 데이터 폴더 이름이 바뀐 경우(세특도우미 → 쓰담) 녹음 경로 고침
    old = os.sep + platform_util.OLD_APP_NAME + os.sep
    new = os.sep + platform_util.APP_NAME + os.sep
    conn.execute("UPDATE recordings SET audio_path = REPLACE(audio_path, ?, ?) WHERE audio_path LIKE ?",
                 (old, new, "%" + old + "%"))
    import sync_text  # 텍스트 동기화용 uid·source 컬럼
    sync_text.migrate(conn)


def note_area(note, class_kind):
    """관찰기록의 영역. 비어 있으면 학급 유형의 기본 영역."""
    if note.get("area"):
        return note["area"]
    return areas_for_kind(class_kind or "교과")[0]["id"]


def note_in_area(note, class_kind, area):
    """이 영역 초안에 쓸 기록인지. 학교 밖 영역(수업 일지 · 리포트 · 문자)은 같은 관찰을 글 모양만 달리 쓰므로 모든 기록."""
    return area not in SCHOOL_AREA_IDS or note_area(note, class_kind) == area


def daily_backup():
    if not os.path.exists(DB_PATH):
        return
    today = datetime.date.today().strftime("%Y%m%d")
    target = os.path.join(BACKUP_DIR, "seteuk-%s.db" % today)
    if not os.path.exists(target):
        backup_to(target)
    files = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("seteuk-") and f.endswith(".db"))
    for f in files[:-30]:
        try:
            os.remove(os.path.join(BACKUP_DIR, f))
        except OSError:
            pass


def backup_to(path):
    src = connect()
    dst = sqlite3.connect(path)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    return path


def rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def row(conn, sql, args=()):
    r = conn.execute(sql, args).fetchone()
    return dict(r) if r else None


def get_settings(conn=None):
    own = conn is None
    conn = conn or connect()
    s = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}
    if own:
        conn.close()
    for k, v in DEFAULT_SETTINGS.items():
        s.setdefault(k, v)
    return s


def set_settings(values):
    conn = connect()
    for k, v in values.items():
        if k in DEFAULT_SETTINGS:
            conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (k, str(v)))
    conn.commit()
    conn.close()


def class_label(c):
    kind = c.get("kind") or "교과"
    if kind == "동아리":
        return "동아리 %s" % (c.get("subject") or "")
    if kind == "기타" and not c.get("grade"):
        return c.get("subject") or "모둠"
    if kind in NAMED_KINDS:   # 유치원 반 · 학원 반 · PT 수업은 이름 그대로
        return c.get("subject") or kind
    label = "%s학년 %s반" % (c.get("grade") or "?", c.get("class_no") or "?")
    if kind == "담임":
        label += " (담임)"
    elif c.get("subject"):
        label += " " + c["subject"]
    return label


def neis_bytes(text):
    """NEIS 기준 바이트: 한글 등 비ASCII 3B, ASCII 1B, 줄바꿈 2B."""
    if not text:
        return 0
    text = text.replace("\r\n", "\n")
    n = 0
    for ch in text:
        if ch == "\n":
            n += 2
        elif ord(ch) < 128:
            n += 1
        else:
            n += 3
    return n


def move_audio_into_archive(src_path, recorded_at, class_hint, kind, copy=True):
    """원본 녹음을 data/audio/YYYY/MM/ 아래로 보관하고 새 경로 반환."""
    try:
        dt = datetime.datetime.strptime(recorded_at[:16], "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        dt = datetime.datetime.now()
    folder = os.path.join(AUDIO_DIR, dt.strftime("%Y"), dt.strftime("%m"))
    os.makedirs(folder, exist_ok=True)
    ext = os.path.splitext(src_path)[1].lower() or ".m4a"
    safe_hint = "".join(ch for ch in (class_hint or "") if ch.isalnum() or ch in "-_")
    base = "%s_%s%s" % (dt.strftime("%Y%m%d-%H%M"), kind, ("_" + safe_hint) if safe_hint else "")
    dest = os.path.join(folder, base + ext)
    i = 2
    while os.path.exists(dest):
        dest = os.path.join(folder, "%s-%d%s" % (base, i, ext))
        i += 1
    if copy:
        shutil.copy2(src_path, dest)
    else:
        shutil.move(src_path, dest)
    return dest
