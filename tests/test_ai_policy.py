from unittest.mock import patch
import test_draft_sources as fixtures
from test_draft_sources import connection
import unittest
import pipeline, server, db, localai

class AIPolicyTests(unittest.TestCase):
    setUp = fixtures.DraftSourcesTests.setUp
    tearDown = fixtures.DraftSourcesTests.tearDown
    def test_legacy_local_and_personal_keys_cannot_generate(self):
        for choice in ('builtin','external','gemini','apple','manual'):
            settings={'ai_choice':choice,'mode':'api','gemini_api_key':'old-key','local_ai_url':'builtin','local_ai_model':'old','draft_local':'1'}
            self.assertIsNone(pipeline.draft_engine(settings))
            with patch.object(db,'get_settings',return_value=settings):
                result=server.ai_run(None,{}, {'op':'draft','params':{'student_id':self.sid,'area':'subject'}})
                self.assertTrue(result['manual'])
                with self.assertRaises(ValueError):pipeline._run_api('draft',{'student_id':self.sid,'area':'subject'})
    def test_paid_draft_always_uses_plus_even_with_old_key(self):
        settings={'plus_token':'fake','plus_active':'1','api_provider':'gemini','gemini_api_key':'old','mode':'manual'}
        with patch('plus.ENABLED',True):
            self.assertEqual(pipeline.draft_engine(settings),'gemini')
            with patch.object(db,'get_settings',return_value=settings), patch('cloudai.generate',return_value='클라우드 초안') as generate, patch.object(pipeline,'_expand_if_short',side_effect=lambda text,*args:text):
                pipeline._run_api('draft',{'student_id':self.sid,'area':'subject'})
                self.assertEqual(generate.call_args.args[0]['api_provider'],'plus')
    def test_device_record_organization_is_preserved(self):
        with patch.object(localai,'apple_ready',return_value=True):
            self.assertEqual(pipeline.seg_engine({'seg_engine':'local'}),'apple')
            self.assertEqual(pipeline.seg_engine({'seg_engine':'rules'}),'rules')
        with patch.object(localai,'apple_ready',return_value=False):
            self.assertEqual(pipeline.seg_engine({'seg_engine':'local'}),'rules')
    def test_free_external_result_can_be_saved_and_edited(self):
        server.ai_apply(None,{}, {'op':'draft','params':{'student_id':self.sid,'area':'subject'},'text':'외부에서 작성한 초안'})
        server.drafts_save(None,{}, {'student_id':self.sid,'area':'subject','content':'수정한 초안'})
        with connection() as c:
            self.assertEqual(db.row(c,'SELECT content FROM drafts ORDER BY id DESC LIMIT 1')['content'],'수정한 초안')
    def test_retired_selection_rejected(self):
        for choice in ('builtin','external','gemini'):
            with self.assertRaises(server.ApiError):server.ai_choose(None,{}, {'choice':choice})
