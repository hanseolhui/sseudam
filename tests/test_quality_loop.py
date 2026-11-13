"""Local-only quality feedback and evidence checks; no student data or paid APIs."""
import json
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import test_draft_sources as sources_fixture
import db
import pipeline
import quality
import server


connection = sources_fixture.connection


class QualityLoopTests(unittest.TestCase):
    setUp = sources_fixture.DraftSourcesTests.setUp

    def draft(self, text, engine="plus", sources=None):
        pipeline.apply_draft(self.sid, text, engine=engine, sources=sources)
        with connection() as c:
            return db.row(c, "SELECT * FROM drafts ORDER BY id DESC LIMIT 1")

    def test_confirm_uses_selected_version_not_latest(self):
        first = self.draft("실험 결과를 표로 정리함.")
        self.draft("토론에서 다른 의견을 듣고 설명함.", engine="manual")
        server.drafts_save(None, {}, {"student_id": self.sid, "content": first["content"],
                           "source_draft_id": first["id"], "status": "확정"})
        with connection() as c:
            stat = db.row(c, "SELECT * FROM draft_stats WHERE event='confirm'")
        self.assertEqual(stat["engine"], "plus")
        self.assertEqual(stat["edit_pct"], 0)

    def test_manual_confirmation_does_not_borrow_previous_ai(self):
        self.draft("이전 AI 초안임.")
        server.drafts_save(None, {}, {"student_id": self.sid, "content": "직접 작성한 내용임.", "status": "확정"})
        with connection() as c:
            stat = db.row(c, "SELECT * FROM draft_stats WHERE event='confirm'")
        self.assertEqual(stat["engine"], "none")
        self.assertIsNone(stat["edit_pct"])

    def test_confirmation_retry_and_feedback_retry_do_not_inflate_counts(self):
        d = self.draft("실험 결과를 표로 정리함.")
        data = {"student_id": self.sid, "id": d["id"], "content": d["content"], "status": "확정"}
        for _ in range(2):
            server.drafts_save(None, {}, data)
            server.drafts_rate(None, {}, {"id": d["id"], "up": False, "reason": "missing"})
        summary, _ = quality.summary()
        self.assertEqual(summary["plus"]["confirm"], 1)
        self.assertEqual(summary["plus"]["down"], 1)
        self.assertEqual(summary["plus"]["reason_missing"], 1)
        details = server.student_detail(None, {}, {}, self.sid)
        self.assertTrue(details["drafts"][0]["rated"])

    def test_reason_validation_excludes_raw_content(self):
        d = self.draft("실험 결과를 표로 정리함.")
        for up, reason in [(False, "학생 이름 등 자유입력"), ("false", "missing"), (True, "missing")]:
            with self.assertRaises(server.ApiError):
                server.drafts_rate(None, {}, {"id": d["id"], "up": up, "reason": reason})
        summary, _ = quality.summary()
        self.assertEqual(summary["plus"]["down"], 0)
        self.assertNotIn("학생", json.dumps(summary, ensure_ascii=False))

    def test_cross_student_update_preserves_final(self):
        d = self.draft("실험 결과를 표로 정리함.")
        with connection() as c:
            c.execute("UPDATE drafts SET status='확정' WHERE id=?", (d["id"],))
        with self.assertRaises(server.ApiError):
            server.drafts_save(None, {}, {"student_id": self.sid + 100, "id": d["id"], "content": "다른 학생", "status": "확정"})
        with connection() as c:
            after = db.row(c, "SELECT * FROM drafts WHERE id=?", (d["id"],))
        self.assertEqual(after["content"], d["content"])
        self.assertEqual(after["status"], "확정")

    def test_failed_generation_is_counted_without_message_or_student(self):
        with patch.object(pipeline, "_execute_api", side_effect=RuntimeError("가상학생의 비공개 원문")), \
             patch.object(quality, "engine_of", return_value="plus"):
            with self.assertRaises(RuntimeError):
                pipeline._run_api("draft", {"student_id": self.sid})
        summary, _ = quality.summary()
        self.assertEqual(summary["plus"]["failed"], 1)
        self.assertEqual(summary["plus"]["draft"], 0)
        self.assertNotIn("가상학생", json.dumps(summary, ensure_ascii=False))
        self.assertNotIn("student_id", json.dumps(summary))

    def test_stats_connection_failure_preserves_the_generation_error(self):
        original = RuntimeError("synthetic generation failure")
        with patch.object(db, "get_settings", return_value={}), \
             patch.object(db, "connect", side_effect=OSError("synthetic statistics failure")), \
             patch.object(pipeline, "_execute_api", side_effect=original), \
             patch.object(quality, "engine_of", return_value="plus"):
            with self.assertRaises(RuntimeError) as raised:
                pipeline._run_api("draft", {"student_id": self.sid})
        self.assertIs(raised.exception, original)

    def test_edited_review_uses_snapshot_and_never_calls_ai(self):
        d = self.draft("실험 결과를 표로 정리함.", sources=[{"content": "실험 결과를 표로 정리함."}])
        with connection() as c:
            c.execute("UPDATE notes SET content='점차 나아짐' WHERE id=?", (self.nid,))
        with patch("cloudai.generate", side_effect=AssertionError("No external AI")):
            result = server.drafts_review(None, {}, {"student_id": self.sid, "source_draft_id": d["id"],
                                                    "content": "실험 결과를 표로 정리하며 점차 나아짐."})
        self.assertTrue(result["hasSources"])
        self.assertTrue(result["review"]["added"])
        with connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM drafts").fetchone()[0], 1)

    def test_unknown_or_foreign_source_never_claims_review(self):
        d = self.draft("실험 결과를 표로 정리함.", sources=[{"content": "근거 기록"}])
        for did, sid in [(None, self.sid), (d["id"], self.sid + 100)]:
            result = server.drafts_review(None, {}, {"student_id": sid, "source_draft_id": did, "content": "점차 나아짐"})
            self.assertFalse(result["hasSources"])
            self.assertEqual(result["review"], {})

    def test_migration_is_repeatable_and_preserves_existing_stats(self):
        d = self.draft("실험 결과를 표로 정리함.")
        server.drafts_rate(None, {}, {"id": d["id"], "up": True})
        with connection() as c:
            quality.migrate(c)
            quality.migrate(c)
        summary, _ = quality.summary()
        self.assertEqual(summary["plus"]["up"], 1)

    def test_rating_and_confirmation_stay_deduplicated_after_stats_expire(self):
        d = self.draft("가상 관찰 내용을 기록함.")
        final = {"student_id": self.sid, "id": d["id"], "content": d["content"], "status": "확정"}
        server.drafts_save(None, {}, final)
        server.drafts_rate(None, {}, {"id": d["id"], "up": False, "reason": "missing"})
        with connection() as c:
            c.execute("UPDATE draft_stats SET ts=?", (time.time() - 91 * 86400,))
        _, last = quality.summary()
        quality.mark_sent(last)
        self.assertEqual(quality.summary()[0], {})
        self.assertTrue(server.student_detail(None, {}, {}, self.sid)["drafts"][0]["rated"])
        self.assertFalse(server.drafts_rate(None, {}, {"id": d["id"], "up": True})["recorded"])
        server.drafts_save(None, {}, final)
        self.assertEqual(quality.summary()[0], {})
        with connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM draft_quality_marks").fetchone()[0], 2)
            self.assertEqual({r[1] for r in c.execute("PRAGMA table_info(draft_quality_marks)")}, {"draft_id", "kind"})

    def test_migration_backfills_markers_before_event_cleanup(self):
        d = self.draft("가상 관찰 내용을 기록함.")
        server.drafts_rate(None, {}, {"id": d["id"], "up": True})
        with connection() as c:
            c.execute("DROP TABLE draft_quality_marks")
            quality.migrate(c)
            self.assertTrue(quality.is_rated(c, d["id"]))
            c.execute("UPDATE draft_stats SET ts=?", (time.time() - 91 * 86400,))
        _, last = quality.summary()
        quality.mark_sent(last)
        self.assertFalse(server.drafts_rate(None, {}, {"id": d["id"], "up": False})["recorded"])

    def test_stats_error_does_not_hide_student_or_block_confirmation(self):
        d = self.draft("가상 관찰 내용을 기록함.")
        with connection() as c:
            c.execute("DROP TABLE draft_stats")
            c.execute("DROP TABLE draft_quality_marks")
        details = server.student_detail(None, {}, {}, self.sid)
        self.assertEqual(details["drafts"][0]["content"], d["content"])
        self.assertFalse(details["drafts"][0]["rating_available"])
        server.drafts_save(None, {}, {"student_id": self.sid, "id": d["id"],
                           "content": "교사가 수정한 가상 기록", "status": "확정"})
        with connection() as c:
            row = db.row(c, "SELECT content,status FROM drafts WHERE id=?", (d["id"],))
        self.assertEqual(row, {"content": "교사가 수정한 가상 기록", "status": "확정"})

    def test_failed_stats_insert_rolls_back_marker_and_can_be_retried(self):
        d = self.draft("가상 관찰 내용을 기록함.")
        with connection() as c:
            c.execute("CREATE TRIGGER reject_quality BEFORE INSERT ON draft_stats "
                      "BEGIN SELECT RAISE(FAIL, 'forced test statistics failure'); END")
        with self.assertRaises(server.ApiError):
            server.drafts_rate(None, {}, {"id": d["id"], "up": True})
        final = {"student_id": self.sid, "id": d["id"], "content": d["content"], "status": "확정"}
        server.drafts_save(None, {}, final)
        with connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM draft_quality_marks").fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT status FROM drafts WHERE id=?", (d["id"],)).fetchone()[0], "확정")
            c.execute("DROP TRIGGER reject_quality")
        self.assertTrue(server.drafts_rate(None, {}, {"id": d["id"], "up": True})["recorded"])
        server.drafts_save(None, {}, final)
        summary, _ = quality.summary()
        self.assertEqual(summary["plus"]["up"], 1)
        self.assertEqual(summary["plus"]["confirm"], 1)

    def test_stats_record_does_not_commit_the_callers_transaction(self):
        d = self.draft("가상 관찰 내용을 기록함.")
        c = db.connect()
        try:
            self.assertTrue(quality.rate(c, d["id"], True))
            c.rollback()
            self.assertFalse(quality.is_rated(c, d["id"]))
            self.assertEqual(c.execute("SELECT COUNT(*) FROM draft_stats WHERE event='up'").fetchone()[0], 0)
        finally:
            c.close()

    def test_concurrent_ratings_count_the_version_once(self):
        d = self.draft("가상 관찰 내용을 기록함.")
        ready = Barrier(2)

        def vote(up):
            ready.wait(timeout=5)
            return server.drafts_rate(None, {}, {"id": d["id"], "up": up})["recorded"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(vote, [True, False]))
        self.assertEqual(sorted(results), [False, True])
        summary, _ = quality.summary()
        self.assertEqual(summary["plus"]["up"] + summary["plus"]["down"], 1)

    def test_broken_optional_stats_schema_does_not_block_migration(self):
        with connection() as c:
            c.execute("DROP TABLE draft_stats")
            c.execute("CREATE TABLE draft_stats(unexpected INTEGER)")
            quality.migrate(c)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM students").fetchone()[0], 1)
            self.assertIn("ai_text", {r[1] for r in c.execute("PRAGMA table_info(drafts)")})

    def test_edit_comparison_failure_does_not_undo_confirmation(self):
        d = self.draft("가상 관찰 내용을 기록함.")
        with patch.object(quality, "edit_pct", side_effect=RuntimeError("comparison unavailable")):
            server.drafts_save(None, {}, {"student_id": self.sid, "id": d["id"],
                               "content": "수정된 가상 관찰", "status": "확정"})
        with connection() as c:
            self.assertEqual(c.execute("SELECT status FROM drafts WHERE id=?", (d["id"],)).fetchone()[0], "확정")
