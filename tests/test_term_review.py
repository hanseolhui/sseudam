from test_draft_sources import DraftSourcesTests, connection
import server
import db

class TermReviewTests(DraftSourcesTests):
    def test_preview_select_save_preserves_paragraphs_and_versions(self):
        with connection() as c:
            cid = db.row(c, 'SELECT class_id FROM students WHERE id=?', (self.sid,))['class_id']
        b = {'class_id': cid, 'area': 'subject', 'text': '[1번] 첫 문단\n\n둘째 문단\n[999번] 모르는 학생'}
        preview = server.drafts_batch_preview(None, {}, b)
        self.assertEqual(preview['items'][0]['content'], '첫 문단\n\n둘째 문단')
        self.assertEqual(len(preview['issues']), 1)
        with connection() as c: self.assertEqual(c.execute('SELECT COUNT(*) FROM drafts').fetchone()[0], 0)
        payload = {**b, 'items': preview['items']}
        server.drafts_batch_reviewed_save(None, {}, payload)
        with self.assertRaises(server.ApiError): server.drafts_batch_reviewed_save(None, {}, payload)
        with connection() as c: self.assertEqual(c.execute('SELECT COUNT(*) FROM drafts').fetchone()[0], 1)
    def test_term_is_scoped_and_newer_draft_needs_review(self):
        server.drafts_save(None, {}, {'student_id': self.sid, 'content':'확정본', 'status':'확정'})
        server.drafts_save(None, {}, {'student_id': self.sid, 'content':'외부 수정본'})
        result = server.term_review(None, {'year':'2026','semester':'2'}, None)
        self.assertEqual(len(result['items']), 1)
        self.assertTrue(result['items'][0]['has_newer_draft'])
        self.assertEqual(server.term_review(None, {'year':'2026','semester':'1'}, None)['items'], [])
