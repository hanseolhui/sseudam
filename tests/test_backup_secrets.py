"""밖으로 나가는 백업에는 연결 정보(AI 키 · 플러스 로그인 · 휴대폰 연결 열쇠)를 넣지 않고,
복원해도 이 컴퓨터의 연결은 그대로 둔다. 임시 SQLite 와 가짜 값만 쓴다."""
import io, json, os, sqlite3, sys, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import backupsafe, db, sheets

SECRETS = {
    'gemini_api_key': 'FAKE-GEMINI-KEY-aaaa1111', 'openai_api_key': 'FAKE-OPENAI-KEY-bbbb2222',
    'claude_api_key': 'FAKE-CLAUDE-KEY-cccc3333', 'plus_token': 'sdp_FAKE-PLUS-TOKEN-dddd4444',
    'relay_channel': 'fakechannel5555eeee', 'relay_key': 'FAKE-RELAY-KEY-ffff6666',
}
PLUS_STATE = {'plus_email': 'fake-teacher@example.com', 'plus_active': '1', 'plus_status': '{"sub": {"plan": "FAKE-PLAN-7777"}}'}
GOOGLE = {'sheets_url': 'https://script.example.com/FAKE-URL-8888/exec', 'sheets_token': 'FAKE-SHEETS-TOKEN-9999',
          'upload_token': 'uFAKE-UPLOAD-TOKEN-0000'}
PLAIN = {'teacher_subject': '가상과목', 'school_level': '중학교'}


class BackupSecretTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for attr, value in [('DB_PATH', self.tmp.name + '/test.db'), ('BACKUP_DIR', self.tmp.name)]:
            p = patch.object(db, attr, value); p.start(); self.addCleanup(p.stop)
        p = patch.object(sheets, '_call', side_effect=AssertionError('Network forbidden')); p.start(); self.addCleanup(p.stop)
        p = patch.object(db, 'init'); p.start(); self.addCleanup(p.stop)   # 복원 뒤 시작 정리는 이 시험 밖
        c = db.connect(); c.executescript(db.SCHEMA); db._migrate_columns(c)
        for k, v in db.DEFAULT_SETTINGS.items():
            c.execute('INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)', (k, v))
        c.execute("INSERT INTO classes(id,label,grade,class_no) VALUES(1,'가상1반',1,1)")
        c.execute("INSERT INTO students(id,class_id,number,name) VALUES(1,1,1,'김가상')")
        c.execute("INSERT INTO notes(student_id,content) VALUES(1,'가상 관찰')")
        c.commit(); c.close()
        db.set_settings({**SECRETS, **PLUS_STATE, **GOOGLE, **PLAIN})

    def settings(self, path=None):
        c = sqlite3.connect(path or db.DB_PATH)
        try:
            return dict(c.execute('SELECT key, value FROM settings').fetchall())
        finally:
            c.close()

    def notes(self):
        c = db.connect(); r = [x['content'] for x in db.rows(c, 'SELECT content FROM notes ORDER BY id')]; c.close(); return r

    def unzip_db(self, archive):
        path = os.path.join(self.tmp.name, 'unzipped.db')
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            Path(path).write_bytes(z.read('seteuk.db'))
            info = json.loads(z.read('info.json'))
        return path, info

    def test_outgoing_backup_has_no_connection_values(self):
        full = os.path.join(self.tmp.name, 'full-copy.db')
        db.backup_to(full)
        raw_full = Path(full).read_bytes()
        self.assertIn(SECRETS['plus_token'].encode(), raw_full)          # 비우기 전 사본에는 들어 있다
        path, info = self.unzip_db(sheets._db_zip_bytes())
        raw = Path(path).read_bytes()
        for value in list(SECRETS.values()) + ['FAKE-PLAN-7777', PLUS_STATE['plus_email']]:
            self.assertNotIn(value.encode(), raw, value)                  # 파일의 빈 자리에도 남아 있지 않다
        s = self.settings(path)
        for k in backupsafe.LEFT_OUT:
            self.assertEqual(s.get(k, ''), db.DEFAULT_SETTINGS.get(k, ''), k)   # 아직 없는 설정이면 빈 값으로 본다
        self.assertFalse(info['connections_included'])

    def test_outgoing_backup_keeps_records_and_plain_settings(self):
        path, _ = self.unzip_db(sheets._db_zip_bytes())
        s = self.settings(path)
        for k, v in {**PLAIN, **GOOGLE}.items():
            self.assertEqual(s[k], v, k)
        c = sqlite3.connect(path)
        try:
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(c.execute('SELECT content FROM notes').fetchall(), [('가상 관찰',)])
            self.assertEqual(c.execute('SELECT name FROM students').fetchall(), [('김가상',)])
        finally:
            c.close()

    def test_making_a_backup_does_not_change_this_computer(self):
        before = self.settings()
        sheets._db_zip_bytes()
        self.assertEqual(self.settings(), before)

    def test_restore_keeps_this_computers_connections(self):
        archive = sheets._db_zip_bytes()
        db.set_settings({'plus_token': 'sdp_NEWER-TOKEN', 'teacher_subject': '바뀐과목'})
        c = db.connect(); c.execute("UPDATE notes SET content='복원 직전 수정'"); c.commit(); c.close()
        result = sheets.restore_from_bytes(archive)
        s = self.settings()
        self.assertEqual(self.notes(), ['가상 관찰'])                     # 기록은 백업의 것으로
        self.assertEqual(s['teacher_subject'], '가상과목')                # 일반 설정도 백업의 것으로
        self.assertEqual(s['plus_token'], 'sdp_NEWER-TOKEN')             # 연결은 이 컴퓨터의 것 그대로
        for k, v in {**SECRETS, **PLUS_STATE, **GOOGLE}.items():
            if k != 'plus_token':
                self.assertEqual(s[k], v, k)
        self.assertIn('그대로', result['warning'])
        before = self.settings(result['before'])                         # 복원 직전 사본은 이 컴퓨터 안의 전체 사본
        self.assertEqual(before['plus_token'], 'sdp_NEWER-TOKEN')

    def test_restore_on_a_new_computer_starts_disconnected(self):
        archive = sheets._db_zip_bytes()
        db.set_settings({k: db.DEFAULT_SETTINGS.get(k, '') for k in list(backupsafe.LEFT_OUT) + list(GOOGLE)})   # 새 컴퓨터
        c = db.connect(); c.execute('DELETE FROM notes'); c.commit(); c.close()
        sheets.restore_from_bytes(archive)
        s = self.settings()
        self.assertEqual(self.notes(), ['가상 관찰'])
        for k in backupsafe.LEFT_OUT:
            self.assertEqual(s.get(k, ''), db.DEFAULT_SETTINGS.get(k, ''), k)    # 로그인 · 휴대폰 연결 · AI 키는 다시 해야 한다
        for k, v in GOOGLE.items():
            self.assertEqual(s[k], v, k)                                  # 구글 연결은 백업에서 돌아온다

    def test_old_full_backup_still_restores(self):
        old = os.path.join(self.tmp.name, 'old-full.db')                 # 예전 방식: 연결 값이 든 전체 사본
        db.backup_to(old)
        data = Path(old).read_bytes()
        # 연결이 없는 새 컴퓨터에서는 예전처럼 백업의 값이 그대로 들어온다
        db.set_settings({k: db.DEFAULT_SETTINGS.get(k, '') for k in list(backupsafe.LEFT_OUT) + list(GOOGLE)})
        sheets.restore_from_bytes(data)
        s = self.settings()
        for k, v in {**SECRETS, **GOOGLE}.items():
            self.assertEqual(s[k], v, k)
        # 이미 연결된 컴퓨터에서는 이 컴퓨터의 것이 남는다
        db.set_settings({'relay_channel': 'currentchannel', 'relay_key': 'CURRENT-RELAY-KEY', 'gemini_api_key': 'CURRENT-GEMINI'})
        sheets.restore_from_bytes(data)
        s = self.settings()
        self.assertEqual((s['relay_channel'], s['relay_key'], s['gemini_api_key']),
                         ('currentchannel', 'CURRENT-RELAY-KEY', 'CURRENT-GEMINI'))
        self.assertEqual(s['openai_api_key'], SECRETS['openai_api_key'])

    def test_left_out_keys_cover_every_credential_setting(self):
        # 새 토큰 · 열쇠 설정이 생기면 여기서 걸린다: 백업에서 뺄지, 구글 연결처럼 둘지 정해야 한다
        credential = {k for k in db.DEFAULT_SETTINGS if k.endswith(('_token', '_key'))}
        self.assertEqual(credential - set(backupsafe.LEFT_OUT) - set(backupsafe.GOOGLE[1]), set())


if __name__ == '__main__':
    unittest.main()
