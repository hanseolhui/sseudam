# -*- coding: utf-8 -*-
"""초안 품질 통계 — 숫자만 모은다 (초안 · 관찰기록 내용은 보내지 않음).

이 컴퓨터의 draft_stats 표에 사건을 쌓고, 하루 한 번 사용 정보(telemetry)에 합계만 실어 보낸다.
사건: draft(첫 초안) · regen(다시 뽑기) · shorten(줄이기) · confirm(확정, 고친 비율) · up · down(👍👎)
엔진: plus · plus-deep · local(쓰담 AI 모델) · api(선생님 키) · manual(ChatGPT·Gemini 붙여넣기) · none(직접 씀)
"""
import difflib
import time

import db

REASONS = ("unsupported", "missing", "wording", "length", "other")

SCHEMA = """CREATE TABLE IF NOT EXISTS draft_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, event TEXT, engine TEXT, area TEXT,
    ms INTEGER, edit_pct REAL, sent INTEGER DEFAULT 0)"""


def migrate(conn):
    # These draft columns are used by the editor even without usage statistics.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(drafts)")}
    if "ai_text" not in cols:     # AI가 처음 쓴 글 (선생님이 고쳐도 그대로 둠 → 확정할 때 고친 비율 계산)
        conn.execute("ALTER TABLE drafts ADD COLUMN ai_text TEXT DEFAULT ''")
    if "origin" not in cols:      # 이 초안을 쓴 엔진
        conn.execute("ALTER TABLE drafts ADD COLUMN origin TEXT DEFAULT ''")
    conn.execute("SAVEPOINT quality_migration")
    try:
        conn.execute(SCHEMA)
        stat_cols = {r[1] for r in conn.execute("PRAGMA table_info(draft_stats)")}
        for name, spec in (("draft_id", "INTEGER"), ("reason", "TEXT DEFAULT ''")):
            if name not in stat_cols:
                conn.execute("ALTER TABLE draft_stats ADD COLUMN %s %s" % (name, spec))
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS draft_rating_once ON draft_stats(draft_id) "
                     "WHERE draft_id IS NOT NULL AND event IN ('up','down')")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS draft_confirm_once ON draft_stats(draft_id) "
                     "WHERE draft_id IS NOT NULL AND event='confirm'")
        # Local-only deduplication survives the 90-day event cleanup. No text,
        # student identifiers, reasons or timestamps are retained here.
        conn.execute("CREATE TABLE IF NOT EXISTS draft_quality_marks ("
                     "draft_id INTEGER NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('rating','confirm')), "
                     "PRIMARY KEY(draft_id, kind))")
        conn.execute("INSERT OR IGNORE INTO draft_quality_marks(draft_id, kind) "
                     "SELECT draft_id, CASE WHEN event='confirm' THEN 'confirm' ELSE 'rating' END "
                     "FROM draft_stats WHERE draft_id IS NOT NULL AND event IN ('up','down','confirm')")
    except Exception as e:  # optional statistics must not prevent opening records
        conn.execute("ROLLBACK TO quality_migration")
        print("[초안 통계] 준비 못 함:", e)
    finally:
        conn.execute("RELEASE quality_migration")


def engine_of(settings, op_params=None):
    """지금 설정으로 초안을 쓰면 어느 엔진인지."""
    import pipeline
    import cloudai
    eng = pipeline.draft_engine(settings)
    if eng == "gemini":
        return "plus-deep" if (op_params or {}).get("deep") else "plus"
    return "manual"


def record(conn, event, engine, area, ms=None, edit_pct=None, draft_id=None, reason=""):
    savepoint = False
    try:
        if not conn.in_transaction:
            conn.execute("BEGIN")  # releasing our savepoint must not commit the caller's work
        conn.execute("SAVEPOINT quality_record")
        savepoint = True
        kind = "rating" if event in ("up", "down") else "confirm" if event == "confirm" else None
        if draft_id is not None and kind:
            marker = conn.execute("INSERT OR IGNORE INTO draft_quality_marks(draft_id, kind) VALUES (?,?)", (draft_id, kind))
            if not marker.rowcount:
                conn.execute("RELEASE quality_record")
                return False
        cur = conn.execute("INSERT OR IGNORE INTO draft_stats(ts, event, engine, area, ms, edit_pct, draft_id, reason) VALUES (?,?,?,?,?,?,?,?)",
                     (time.time(), event, engine or "none", area or "subject",
                      max(0, int(ms)) if ms is not None else None, edit_pct, draft_id,
                      reason if reason in REASONS and event == "down" else ""))
        conn.execute("RELEASE quality_record")
        return bool(cur.rowcount)
    except Exception as e:  # noqa — 통계 때문에 초안 저장이 막히면 안 됨
        if savepoint:
            try:
                conn.execute("ROLLBACK TO quality_record")
                conn.execute("RELEASE quality_record")
            except Exception:
                pass
        print("[초안 통계] 기록 못 함:", e)
        return False


def rated_draft_ids(conn, student_id):
    """None means statistics are unavailable; the student page still opens."""
    try:
        return {r[0] for r in conn.execute("SELECT m.draft_id FROM draft_quality_marks m "
                    "JOIN drafts d ON d.id=m.draft_id WHERE m.kind='rating' AND d.student_id=?", (student_id,))}
    except Exception:
        return None


def is_rated(conn, draft_id):
    try:
        return bool(conn.execute("SELECT 1 FROM draft_quality_marks WHERE draft_id=? AND kind='rating'", (draft_id,)).fetchone())
    except Exception:
        return False


def edit_pct(ai_text, final):
    """AI 초안에서 얼마나 고쳤는지 (0~100). 글자 단위 비교."""
    a, b = (ai_text or "").strip(), (final or "").strip()
    if not a:
        return None
    if a == b:
        return 0.0
    return round((1 - difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()) * 100, 1)


def on_confirm(conn, student_id, area, final, draft_id=None):
    """확정한 버전의 생성 원문과만 비교한다. 다른 최신 초안을 대신 사용하지 않는다."""
    try:
        src = db.row(conn, "SELECT ai_text, origin FROM drafts WHERE id=? AND student_id=? AND area=?",
                     (draft_id, student_id, area)) or {}
        return record(conn, "confirm", src.get("origin") or "none", area,
                      edit_pct=edit_pct(src.get("ai_text"), final), draft_id=draft_id)
    except Exception as e:
        print("[초안 통계] 확정 집계 못 함:", e)
        return False


def rate(conn, draft_id, up, reason=""):
    if not isinstance(up, bool) or reason not in ("",) + REASONS or (up and reason):
        raise ValueError("평가 종류와 이유를 확인해 주세요.")
    draft = db.row(conn, "SELECT area, origin, ai_text FROM drafts WHERE id=?", (draft_id,))
    if not draft or not draft.get("ai_text"):
        raise ValueError("평가할 AI 초안을 찾지 못했어요.")
    return record(conn, "up" if up else "down", draft["origin"] or "none", draft["area"],
                  draft_id=draft_id, reason=reason)


def summary(mark_sent=False):
    """보내지 않은 사건의 엔진별 합계 (사용 정보에 실어 보냄)."""
    conn = db.connect()
    try:
        rows = db.rows(conn, "SELECT * FROM draft_stats WHERE sent=0 ORDER BY id")
        out = {}
        for r in rows:
            e = out.setdefault(r["engine"] or "none", {"draft": 0, "regen": 0, "shorten": 0, "confirm": 0, "up": 0, "down": 0, "failed": 0,
                                                       "edit_sum": 0.0, "edit_n": 0, "ms_sum": 0, "ms_n": 0,
                                                       **{"reason_" + reason: 0 for reason in REASONS}})
            if r["event"] in e:
                e[r["event"]] += 1
            if r["event"] == "down" and r.get("reason") in REASONS:
                e["reason_" + r["reason"]] += 1
            if r["edit_pct"] is not None:
                e["edit_sum"] += r["edit_pct"]
                e["edit_n"] += 1
            if r["ms"] is not None and r["event"] in ("draft", "regen"):
                e["ms_sum"] += r["ms"]
                e["ms_n"] += 1
        last = rows[-1]["id"] if rows else 0
        return out, last
    finally:
        conn.close()


def mark_sent(last_id):
    if not last_id:
        return
    conn = db.connect()
    try:
        conn.execute("UPDATE draft_stats SET sent=1 WHERE id<=?", (last_id,))
        conn.execute("DELETE FROM draft_stats WHERE sent=1 AND ts < ?", (time.time() - 90 * 86400,))   # 90일 지난 건 지움
        conn.commit()
    finally:
        conn.close()
