"""내 클라우드 폴더 백업: 고른 폴더에 날마다 복원용 zip 과 엑셀을 둔다. 임시 폴더와 가짜 값만 쓴다."""
import datetime, io, os, sqlite3, sys, tempfile, unicodedata, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import cloudfolder, db, sheets


class CloudFolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = os.path.join(self.tmp.name, 'data'); os.makedirs(self.data)
        self.cloud = os.path.join(self.tmp.name, 'cloud'); os.makedirs(self.cloud)
        for attr, value in [('DATA_DIR', self.data), ('DB_PATH', self.data + '/test.db'), ('BACKUP_DIR', self.data)]:
            p = patch.object(db, attr, value); p.start(); self.addCleanup(p.stop)
        for target, kw in [((sheets, '_call'), {'side_effect': AssertionError('Network forbidden')}), ((db, 'init'), {}),
                           ((cloudfolder.socket, 'gethostname'), {'return_value': '가상의 MacBook Pro.local'})]:
            p = patch.object(*target, **kw); p.start(); self.addCleanup(p.stop)
        c = db.connect(); c.executescript(db.SCHEMA); db._migrate_columns(c)
        for k, v in db.DEFAULT_SETTINGS.items():
            c.execute('INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)', (k, v))
        c.execute("INSERT INTO classes(id,year,semester,label,grade,class_no) VALUES(1,2026,2,'가상1반',1,1)")
        c.execute("INSERT INTO students(id,class_id,number,name) VALUES(1,1,1,'김가상')")
        c.execute("INSERT INTO notes(student_id,date,content) VALUES(1,'2026-11-12','가상 관찰 기록')")
        c.commit(); c.close()
        db.set_settings({'plus_token': 'sdp_FAKE-PLUS-TOKEN-1234', 'relay_key': 'FAKE-RELAY-KEY-5678', 'relay_channel': 'fakechannel'})
        self.day = datetime.date.today().strftime('%Y%m%d')
        self.zip = '쓰담-백업-가상의-MacBook-Pro-%s.zip' % self.day
        self.xlsx = '쓰담-기록-가상의-MacBook-Pro-%s.xlsx' % self.day

    def files(self):
        return set(os.listdir(self.cloud))

    def test_turning_on_puts_a_restore_file_and_an_excel_file(self):
        st = cloudfolder.set_folder(self.cloud)
        self.assertEqual(st['folder'], self.cloud)
        self.assertTrue(st['last'])
        self.assertEqual(st['error'], '')
        self.assertEqual(self.files(), {self.zip, self.xlsx})

    def test_restore_file_is_a_backup_without_connection_values(self):
        cloudfolder.set_folder(self.cloud)
        data = Path(self.cloud, self.zip).read_bytes()
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            raw = z.read('seteuk.db')
        self.assertNotIn(b'sdp_FAKE-PLUS-TOKEN-1234', raw)
        self.assertNotIn(b'FAKE-RELAY-KEY-5678', raw)
        c = db.connect(); c.execute("UPDATE notes SET content='나중에 바뀐 글'"); c.commit(); c.close()
        sheets.restore_from_bytes(data)                                   # 이 파일로 복원이 된다
        s = db.get_settings()
        c = db.connect(); note = c.execute('SELECT content FROM notes').fetchone()[0]; c.close()
        self.assertEqual(note, '가상 관찰 기록')
        self.assertEqual(s['backup_folder'], self.cloud)                  # 복원해도 폴더 설정과 연결은 이 컴퓨터의 것
        self.assertEqual(s['plus_token'], 'sdp_FAKE-PLUS-TOKEN-1234')

    def test_excel_file_opens_without_the_app_and_has_the_records(self):
        cloudfolder.set_folder(self.cloud)
        with zipfile.ZipFile(os.path.join(self.cloud, self.xlsx)) as z:
            self.assertIn('[Content_Types].xml', z.namelist())
            text = b''.join(z.read(n) for n in z.namelist()).decode('utf-8')
        for word in ('김가상', '가상 관찰 기록', '관찰기록 전체', '요약'):
            self.assertIn(word, text)
        self.assertNotIn('FAKE', text)

    def sheets_of(self, path):
        """{시트 이름: 그 시트 XML 글}"""
        import re
        with zipfile.ZipFile(path) as z:
            names = re.findall(r'<sheet name="([^"]+)"', z.read('xl/workbook.xml').decode('utf-8'))
            return {n: z.read('xl/worksheets/sheet%d.xml' % (i + 1)).decode('utf-8') for i, n in enumerate(names)}

    def test_excel_archive_has_every_draft_version_and_transcripts(self):
        long_text = ('가' * 9999 + '끝') * 7                                # 70,000자: 엑셀 한 칸에 안 들어가는 받아쓴 글
        c = db.connect()
        c.executemany("INSERT INTO drafts(student_id,area,content,bytes,status,created_at) VALUES(1,'subject',?,?,?,?)",
                      [('첫 번째 초안 글', 21, '초안', '2026-11-01 10:00:00'), ('고쳐 쓴 두 번째 초안', 27, '초안', '2026-11-05 10:00:00'),
                       ('확정한 세 번째 초안', 27, '확정', '2026-11-10 10:00:00')])
        c.executemany("INSERT INTO recordings(class_id,title,recorded_at,transcript,kind) VALUES(?,?,?,?,'수업')",
                      [(1, '가상 수업 녹음', '2026-11-03 09:10', '김가상이 발표에서 근거를 들어 설명함.'),
                       (None, '학급 없는 긴 녹음', '2026-11-04 09:10', long_text),
                       (1, '아직 받아쓰지 않은 녹음', '2026-11-06 09:10', '')])
        c.commit(); c.close()
        cloudfolder.set_folder(self.cloud)
        sheets_xml = self.sheets_of(os.path.join(self.cloud, self.xlsx))
        self.assertEqual(list(sheets_xml)[-2:], ['초안 전체 버전', '녹음 받아쓴 글'])
        self.assertIn('요약', sheets_xml)                                    # 원래 있던 시트도 그대로
        drafts = sheets_xml['초안 전체 버전']
        for word in ('첫 번째 초안 글', '고쳐 쓴 두 번째 초안', '확정한 세 번째 초안', '김가상', '교과 세특', '2026-11-05 10:00:00'):
            self.assertIn(word, drafts)
        recs = sheets_xml['녹음 받아쓴 글']
        self.assertIn('김가상이 발표에서 근거를 들어 설명함.', recs)
        self.assertIn('가상 수업 녹음', recs)
        self.assertNotIn('아직 받아쓰지 않은 녹음', recs)
        for mark in ('>1/3<', '>2/3<', '>3/3<'):                            # 긴 글은 세 줄로 나뉜다
            self.assertIn(mark, recs)
        import re
        cells = re.findall(r'<t xml:space="preserve">([^<]*)</t>', recs)
        self.assertLessEqual(max(len(x) for x in cells), 32000)
        self.assertEqual(''.join(x for x in cells if set(x) <= set('가끝')), long_text)   # 잘린 글자 없이 이어진다

    def test_excel_archive_sheets_exist_even_when_empty(self):
        cloudfolder.set_folder(self.cloud)
        sheets_xml = self.sheets_of(os.path.join(self.cloud, self.xlsx))
        self.assertIn('초안 전체 버전', sheets_xml)
        self.assertIn('녹음 받아쓴 글', sheets_xml)

    def test_plain_excel_export_is_unchanged(self):
        c = db.connect(); books = sheets.workbook(c); c.close()
        self.assertNotIn('초안 전체 버전', [b[0] for b in books])            # '전체 엑셀로 저장' · 구글시트 반영은 그대로

    def test_one_copy_a_day_unless_asked(self):
        cloudfolder.set_folder(self.cloud)
        before = {n: os.path.getmtime(os.path.join(self.cloud, n)) for n in self.files()}
        Path(self.cloud, self.zip).write_bytes(b'marker')
        self.assertEqual(cloudfolder.copy_now()['made'], [])              # 오늘 것이 있으면 다시 만들지 않는다
        self.assertEqual(Path(self.cloud, self.zip).read_bytes(), b'marker')
        made = cloudfolder.copy_now(force=True)['made']                   # '지금 백업'은 새로 만든다
        self.assertEqual(set(made), set(before))
        self.assertEqual(Path(self.cloud, self.zip).read_bytes()[:2], b'PK')

    def test_keeps_thirty_days_of_this_computers_copies_only(self):
        today = datetime.date.today()
        mine = []
        for d in range(1, 41):
            stamp = (today - datetime.timedelta(days=d)).strftime('%Y%m%d')
            for name in ('쓰담-백업-가상의-MacBook-Pro-%s.zip' % stamp, '쓰담-기록-가상의-MacBook-Pro-%s.xlsx' % stamp):
                Path(self.cloud, name).write_bytes(b'x'); mine.append(name)
        others = ['쓰담-백업-학교PC-20200101.zip', '쓰담-기록-학교PC-20200101.xlsx', '쓰담-백업-20200101-0900.zip',
                  '가족사진.jpg', '쓰담-백업-가상의-MacBook-Pro-메모.zip']
        for name in others:
            Path(self.cloud, name).write_bytes(b'x')
        cloudfolder.set_folder(self.cloud)
        left = self.files()
        self.assertTrue(set(others) <= left)                              # 다른 컴퓨터 · 다른 파일은 건드리지 않는다
        self.assertEqual(sum(1 for n in left if n.startswith('쓰담-백업-가상의-MacBook-Pro-2')), 30)
        self.assertEqual(sum(1 for n in left if n.startswith('쓰담-기록-가상의-MacBook-Pro-2')), 30)
        self.assertIn(self.zip, left)
        oldest = (today - datetime.timedelta(days=40)).strftime('%Y%m%d')
        self.assertNotIn('쓰담-백업-가상의-MacBook-Pro-%s.zip' % oldest, left)

    def test_names_in_decomposed_hangul_are_still_recognised(self):
        os.makedirs(self.cloud, exist_ok=True)
        nfd = unicodedata.normalize('NFD', '쓰담-백업-가상의-MacBook-Pro-20200101.zip')
        Path(self.cloud, nfd).write_bytes(b'x')
        db.set_settings({'backup_folder': self.cloud})
        self.assertEqual(len(cloudfolder._mine(self.cloud, cloudfolder.KINDS[0])), 1)

    def test_missing_folder_is_reported_not_raised_and_recovers(self):
        cloudfolder.set_folder(self.cloud)
        gone = self.cloud + '-moved'
        os.rename(self.cloud, gone)
        r = cloudfolder.copy_now(force=True)
        self.assertFalse(r['ok'])
        self.assertIn('찾을 수 없어요', cloudfolder.status()['error'])
        self.assertFalse(cloudfolder.status()['exists'])
        os.rename(gone, self.cloud)
        self.assertTrue(cloudfolder.copy_now(force=True)['ok'])
        self.assertEqual(cloudfolder.status()['error'], '')

    def test_rejects_folders_that_cannot_protect_the_records(self):
        inside = os.path.join(self.data, 'backups2'); os.makedirs(inside)
        for bad in (os.path.join(self.tmp.name, '없는폴더'), '상대/경로', inside, self.data):
            with self.assertRaises(ValueError, msg=bad):
                cloudfolder.set_folder(bad)
        self.assertEqual(cloudfolder.folder(), '')

    def test_turning_off_leaves_the_files(self):
        cloudfolder.set_folder(self.cloud)
        st = cloudfolder.set_folder('')
        self.assertEqual(st['folder'], '')
        self.assertEqual(self.files(), {self.zip, self.xlsx})
        self.assertTrue(cloudfolder.copy_now().get('off'))

    def test_found_cloud_gets_its_own_subfolder(self):
        root = os.path.join(self.tmp.name, 'OneDrive'); os.makedirs(root)
        found = [{'id': 'onedrive', 'name': 'OneDrive', 'path': os.path.join(root, cloudfolder.SUBFOLDER)}]
        with patch.object(cloudfolder, 'candidates', return_value=found):
            st = cloudfolder.set_folder(candidate='onedrive')
            self.assertEqual(st['folder'], os.path.join(root, '쓰담 백업'))
            self.assertEqual(set(os.listdir(st['folder'])), {self.zip, self.xlsx})
            with self.assertRaises(ValueError):
                cloudfolder.set_folder(candidate='없는것')

    def test_candidates_list_only_existing_cloud_folders(self):
        home = os.path.join(self.tmp.name, 'home')
        os.makedirs(os.path.join(home, 'Dropbox'))
        with patch.object(cloudfolder.os.path, 'expanduser', lambda p: p.replace('~', home, 1)), \
                patch.object(cloudfolder.platform_util, 'icloud_drive_dir', return_value=os.path.join(home, 'no-icloud')), \
                patch.dict(os.environ, {'OneDrive': '', 'OneDriveConsumer': '', 'OneDriveCommercial': ''}):
            found = cloudfolder.candidates()
        self.assertEqual([(c['name'], c['path']) for c in found if c['path'].startswith(home)],
                         [('Dropbox', os.path.join(home, 'Dropbox', '쓰담 백업'))])


if __name__ == '__main__':
    unittest.main()
