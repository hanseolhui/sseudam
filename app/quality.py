# -*- coding: utf-8 -*-
"""초안 품질 통계 — 숫자만 모은다 (초안 · 관찰기록 내용은 보내지 않음).

이 컴퓨터의 draft_stats 표에 사건을 쌓고, 하루 한 번 사용 정보(telemetry)에 합계만 실어 보낸다.
사건: draft(첫 초안) · regen(다시 뽑기) · shorten(줄이기) · confirm(확정, 고친 비율) · up · down(👍👎)
엔진: plus · plus-deep · local(쓰담 AI 모델) · api(선생님 키) · manual(ChatGPT·Gemini 붙여넣기) · none(직접 씀)
"""
import difflib
import time

import db

SCHEMA = """CREATE TABLE IF NOT EXISTS draft_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, event TEXT, engine TEXT, area TEXT,
    ms INTEGER, edit_pct REAL, sent INTEGER DEFAULT 0)"""


def migrate(conn):
    conn.execute(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(drafts)")}
    if "ai_text" not in cols:     # AI가 처음 쓴 글 (선생님이 고쳐도 그대로 둠 → 확정할 때 고친 비율 계산)
        conn.execute("ALTER TABLE drafts ADD COLUMN ai_text TEXT DEFAULT ''")
    if "origin" not in cols:      # 이 초안을 쓴 엔진
        conn.execute("ALTER TABLE drafts ADD COLUMN origin TEXT DEFAULT ''")


def engine_of(settings, op_params=None):
    """지금 설정으로 초안을 쓰면 어느 엔진인지."""
    import pipeline
    import cloudai
    eng = pipeline.draft_engine(settings)
    if eng == "gemini":
        return "plus-deep" if (op_params or {}).get("deep") else "plus"
    return "manual"


def record(conn, event, engine, area, ms=None, edit_pct=None):
    try:
        conn.execute("INSERT INTO draft_stats(ts, event, engine, area, ms, edit_pct) VALUES (?,?,?,?,?,?)",
                     (time.time(), event, engine or "none", area or "subject",
                      int(ms) if ms is not None else None, edit_pct))
    except Exception as e:  # noqa — 통계 때문에 초안 저장이 막히면 안 됨
        print("[초안 통계] 기록 못 함:", e)


def edit_pct(ai_text, final):
    """AI 초안에서 얼마나 고쳤는지 (0~100). 글자 단위 비교."""
    a, b = (ai_text or "").strip(), (final or "").strip()
    if not a:
        return None
    if a == b:
        return 0.0
    return round((1 - difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()) * 100, 1)


def on_confirm(conn, student_id, area, final):
    """확정할 때: 가장 최근 AI 초안과 비교해 고친 비율을 남긴다. AI 초안이 없으면 '직접 씀'."""
    src = db.row(conn, "SELECT ai_text, origin FROM drafts WHERE student_id=? AND area=? AND ai_text<>'' "
                       "ORDER BY id DESC LIMIT 1", (student_id, area))
    if src:
        record(conn, "confirm", src["origin"], area, edit_pct=edit_pct(src["ai_text"], final))
    else:
        record(conn, "confirm", "none", area)


def summary(mark_sent=False):
    """보내지 않은 사건의 엔진별 합계 (사용 정보에 실어 보냄)."""
    conn = db.connect()
    try:
        rows = db.rows(conn, "SELECT * FROM draft_stats WHERE sent=0 ORDER BY id")
        out = {}
        for r in rows:
            e = out.setdefault(r["engine"] or "none", {"draft": 0, "regen": 0, "shorten": 0, "confirm": 0, "up": 0, "down": 0,
                                                       "edit_sum": 0.0, "edit_n": 0, "ms_sum": 0, "ms_n": 0})
            if r["event"] in e:
                e[r["event"]] += 1
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
