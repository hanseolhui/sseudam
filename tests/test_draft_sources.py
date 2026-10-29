from contextlib import contextmanager
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import db
import pipeline
import server

@contextmanager
def connection():
    c = db.connect()
    try:
        with c: yield c
    finally: c.close()

class DraftSourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(db, 'DATA_DIR', self.tmp.name), patch.object(db, 'DB_PATH', str(Path(self.tmp.name)/'test.db')), patch.object(db, 'BACKUP_DIR', str(Path(self.tmp.name)/'backups')), patch.object(db, 'AUDIO_DIR', str(Path(self.tmp.name)/'audio'))]
        for p in self.patches: p.start()
        db.init()
        with connection() as c:
            cid = c.execute("INSERT INTO classes(year,semester,grade,class_no,subject,kind) VALUES(2026,2,2,3,'과학','교과')").lastrowid
            self.sid = c.execute("INSERT INTO students(class_id,number,name) VALUES(?,1,'가상학생')", (cid,)).lastrowid
            self.nid = c.execute("INSERT INTO notes(student_id,date,content,use_in_draft,area) VALUES(?,'2026-10-29','실험 결과를 표로 정리함',1,'subject')",(self.sid,)).lastrowid
            c.execute("INSERT INTO notes(student_id,date,content,use_in_draft,area) VALUES(?,'2026-10-29','초안 제외 기록',0,'subject')",(self.sid,))
    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()
    def test_input_snapshot_survives_later_edits(self):
        params={'student_id':self.sid,'area':'subject'}
        pipeline.build_prompt('draft',params)
        self.assertEqual(len(params['_sources']),1)
        with connection() as c: c.execute('UPDATE notes SET content=? WHERE id=?',('수정된 기록',self.nid))
        pipeline.apply('draft',params,'실험 결과를 표로 정리하는 모습을 보임.')
        with connection() as c: row=db.row(c,'SELECT * FROM drafts ORDER BY id DESC LIMIT 1')
        self.assertEqual(json.loads(row['sources'])[0]['content'],'실험 결과를 표로 정리함')
        server.drafts_save(None,{}, {'student_id':self.sid,'area':'subject','content':'직접 고친 초안','source_draft_id':row['id']})
        with connection() as c: copy=db.row(c,'SELECT * FROM drafts ORDER BY id DESC LIMIT 1')
        self.assertEqual(copy['sources'],row['sources'])
    def test_legacy_or_manual_draft_has_no_invented_sources(self):
        pipeline.apply_draft(self.sid,'직접 작성한 초안')
        with connection() as c: row=db.row(c,'SELECT * FROM drafts ORDER BY id DESC LIMIT 1')
        self.assertEqual(json.loads(row['sources']),[])
    def test_shorten_inherits_selected_version_not_latest(self):
        pipeline.apply_draft(self.sid,'첫 버전',sources=[{'content':'첫 근거'}])
        with connection() as c: first=db.row(c,'SELECT id FROM drafts ORDER BY id DESC LIMIT 1')['id']
        pipeline.apply_draft(self.sid,'새 버전',sources=[{'content':'새 근거'}])
        params={'student_id':self.sid,'area':'subject','text':'첫 버전 수정','source_draft_id':first}
        pipeline.build_prompt('shorten',params)
        self.assertEqual(params['_sources'],[{'content':'첫 근거'}])
