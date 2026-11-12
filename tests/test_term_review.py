from test_draft_sources import DraftSourcesTests, connection
import sqlite3
from unittest.mock import patch
import server
import db

class TermReviewTests(DraftSourcesTests):
    def call_with_closed_connections(self, function, *args, expected_error=None):
        opened = []
        connect = db.connect
        def track_connection():
            conn = connect()
            opened.append(conn)
            return conn
        result = None
        try:
            with patch.object(db, 'connect', side_effect=track_connection):
                if expected_error:
                    with self.assertRaises(expected_error):
                        function(*args)
                else:
                    result = function(*args)
            self.assertTrue(opened)
            for conn in opened:
                # fixture 정리 전에 앱 함수가 직접 close했는지 검사한다.
                with self.assertRaises(sqlite3.ProgrammingError):
                    conn.execute('SELECT 1')
            return result
        finally:
            # 회귀가 생겨도 다음 테스트의 임시 DB 삭제를 막지 않는다. 위 검사는 여전히 실패한다.
            for conn in opened:
                conn.close()

    def test_preview_select_save_preserves_paragraphs_and_versions(self):
        with connection() as c:
            cid = db.row(c, 'SELECT class_id FROM students WHERE id=?', (self.sid,))['class_id']
        b = {'class_id': cid, 'area': 'subject', 'text': '[1번] 첫 문단\n\n둘째 문단\n[999번] 모르는 학생'}
        preview = self.call_with_closed_connections(server.drafts_batch_preview, None, {}, b)
        self.assertEqual(preview['items'][0]['content'], '첫 문단\n\n둘째 문단')
        self.assertEqual(len(preview['issues']), 1)
        with connection() as c: self.assertEqual(c.execute('SELECT COUNT(*) FROM drafts').fetchone()[0], 0)
        payload = {**b, 'items': preview['items']}
        self.call_with_closed_connections(server.drafts_batch_reviewed_save, None, {}, payload)
        self.call_with_closed_connections(server.drafts_batch_reviewed_save, None, {}, payload, expected_error=server.ApiError)
        with connection() as c: self.assertEqual(c.execute('SELECT COUNT(*) FROM drafts').fetchone()[0], 1)
    def test_term_is_scoped_and_newer_draft_needs_review(self):
        server.drafts_save(None, {}, {'student_id': self.sid, 'content':'확정본', 'status':'확정'})
        server.drafts_save(None, {}, {'student_id': self.sid, 'content':'외부 수정본'})
        result = self.call_with_closed_connections(server.term_review, None, {'year':'2026','semester':'2'}, None)
        self.assertEqual(len(result['items']), 1)
        self.assertTrue(result['items'][0]['has_newer_draft'])
        self.assertEqual(self.call_with_closed_connections(server.term_review, None, {'year':'2026','semester':'1'}, None)['items'], [])

    def test_preview_error_closes_connection(self):
        self.call_with_closed_connections(server.drafts_batch_preview, None, {},
                                          {'class_id': -1, 'area': 'subject', 'text': '[1번] 가상'},
                                          expected_error=server.ApiError)

    def test_partial_batch_failure_rolls_back_before_closing(self):
        with connection() as conn:
            cid = db.row(conn, 'SELECT class_id FROM students WHERE id=?', (self.sid,))['class_id']
        payload = {'class_id': cid, 'area': 'subject', 'items': [
            {'student_id': self.sid, 'content': '먼저 처리되는 가상 초안', 'expected_id': None},
            {'student_id': -1, 'content': '없는 학생', 'expected_id': None},
        ]}
        self.call_with_closed_connections(server.drafts_batch_reviewed_save, None, {}, payload,
                                          expected_error=server.ApiError)
        with connection() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM drafts').fetchone()[0], 0)
