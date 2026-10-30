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

    def test_custom_profile_target_persists(self):
        db.set_settings({'school_level': '직접 입력', 'school_level_custom': '시니어 입문 회원'})
        self.assertEqual(db.get_settings()['school_level_custom'], '시니어 입문 회원')

    def test_external_audio_survives_trash_cleanup(self):
        import os, tempfile, trash
        from pathlib import Path
        with tempfile.TemporaryDirectory() as ext:
            original = Path(ext)/'original.wav'; original.write_bytes(b'original')
            archive = Path(db.AUDIO_DIR); archive.mkdir(exist_ok=True)
            local = archive/'copy.wav'; local.write_bytes(b'copy')
            link = archive/'linked.wav'; link.symlink_to(original)
            with connection() as c:
                trash._drop_files(c, {'delete_audio':[str(original), str(link), str(local)]})
            self.assertEqual(original.read_bytes(),b'original')
            self.assertTrue(link.exists())
            self.assertFalse(local.exists())

    def test_old_silent_recording_moves_to_review(self):
        with connection() as c:
            rid=c.execute("INSERT INTO recordings(title,status,error) VALUES('silent','오류','녹음에서 말소리를 찾지 못했습니다.')").lastrowid
        db.init()
        with connection() as c:
            self.assertEqual(db.row(c,'SELECT status FROM recordings WHERE id=?',(rid,))['status'],'확인필요')

    def test_bulk_exclude_preserves_audio_and_restore(self):
        import trash
        from pathlib import Path
        audio=Path(db.AUDIO_DIR)/'test.wav';audio.parent.mkdir(exist_ok=True);audio.write_bytes(b'keep')
        with connection() as c:
            ids=[c.execute("INSERT INTO recordings(title,status,audio_path) VALUES('review','확인필요',?)",(str(audio),)).lastrowid for _ in range(2)]
        result=server.recordings_review(None,{}, {'ids':ids,'action':'exclude','delete_audio':True})
        self.assertEqual(result['processed'],2)
        with connection() as c:
            items=db.rows(c,"SELECT id,payload FROM trash WHERE kind='recording'")
            self.assertEqual(len(items),2)
            self.assertTrue(all('delete_audio' not in __import__('json').loads(t['payload']) for t in items))
        trash.restore(items[0]['id']);trash.purge(everything=True)
        self.assertEqual(audio.read_bytes(),b'keep')

    def test_bulk_review_is_atomic_on_stale_selection(self):
        with connection() as c:
            rid=c.execute("INSERT INTO recordings(title,status) VALUES('review','확인필요')").lastrowid
        with self.assertRaises(server.ApiError):server.recordings_review(None,{}, {'ids':[rid,99999],'action':'general'})
        with connection() as c:self.assertEqual(db.row(c,'SELECT status FROM recordings WHERE id=?',(rid,))['status'],'확인필요')
        server.recordings_review(None,{}, {'ids':[rid,rid],'action':'general'})
        with connection() as c:self.assertEqual(db.row(c,'SELECT status FROM recordings WHERE id=?',(rid,))['status'],'일반메모')
