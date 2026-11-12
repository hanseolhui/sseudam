"""내 클라우드 폴더 백업: 고른 폴더에 날마다 복원용 zip 과 엑셀을 둔다. 임시 폴더와 가짜 값만 쓴다."""
import contextlib, datetime, hashlib, io, os, shutil, sqlite3, sys, tempfile, types, unicodedata, unittest, zipfile
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
                           ((cloudfolder, '_machine_fingerprint'), {'return_value': 'fake-machine-a'}),
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
        self.device_id = cloudfolder._device_id()
        self.zip = cloudfolder._name(cloudfolder.KINDS[0])
        self.xlsx = cloudfolder._name(cloudfolder.KINDS[1])

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
            for name in ('쓰담-백업-가상의-MacBook-Pro-%s-%s.zip' % (self.device_id, stamp),
                         '쓰담-기록-가상의-MacBook-Pro-%s-%s.xlsx' % (self.device_id, stamp)):
                Path(self.cloud, name).write_bytes(b'x'); mine.append(name)
        others = ['쓰담-백업-학교PC-20200101.zip', '쓰담-기록-학교PC-20200101.xlsx', '쓰담-백업-20200101-0900.zip',
                  '쓰담-백업-가상의-MacBook-Pro-20200101.zip',  # 예전 같은 이름도 소유 기기를 확정할 수 없다
                  '쓰담-백업-가상의-MacBook-Pro-fedcba9876543210-20200101.zip',
                  '가족사진.jpg', '쓰담-백업-가상의-MacBook-Pro-메모.zip']
        for name in others:
            Path(self.cloud, name).write_bytes(b'x')
        cloudfolder.set_folder(self.cloud)
        left = self.files()
        self.assertTrue(set(others) <= left)                              # 다른 컴퓨터 · 다른 파일은 건드리지 않는다
        self.assertEqual(len(cloudfolder._mine(self.cloud, cloudfolder.KINDS[0])), 30)
        self.assertEqual(len(cloudfolder._mine(self.cloud, cloudfolder.KINDS[1])), 30)
        self.assertIn(self.zip, left)
        oldest = (today - datetime.timedelta(days=40)).strftime('%Y%m%d')
        self.assertNotIn('쓰담-백업-가상의-MacBook-Pro-%s-%s.zip' % (self.device_id, oldest), left)

    def test_names_in_decomposed_hangul_are_still_recognised(self):
        os.makedirs(self.cloud, exist_ok=True)
        nfd = unicodedata.normalize('NFD', '쓰담-백업-가상의-MacBook-Pro-%s-20200101.zip' % self.device_id)
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

    def test_failed_manual_backup_warning_survives_a_skipped_automatic_run(self):
        cloudfolder.set_folder(self.cloud)
        before = {name: Path(self.cloud, name).read_bytes() for name in (self.zip, self.xlsx)}
        with patch.object(cloudfolder.os, 'replace', side_effect=PermissionError('가상 쓰기 실패')):
            self.assertFalse(cloudfolder.copy_now(force=True)['ok'])
        error = cloudfolder.status()['error']
        self.assertIn('가상 쓰기 실패', error)
        self.assertEqual(cloudfolder.copy_now()['made'], [])
        self.assertEqual(cloudfolder.status()['error'], error)
        self.assertEqual({name: Path(self.cloud, name).read_bytes() for name in before}, before)
        self.assertEqual(self.files(), set(before))  # 실패한 임시 파일을 남기지 않는다
        self.assertTrue(cloudfolder.copy_now(force=True)['ok'])
        self.assertEqual(cloudfolder.status()['error'], '')

    def test_partial_failure_retries_only_missing_file_and_clears_error_after_success(self):
        db.set_settings({'backup_folder': self.cloud})
        with patch.object(cloudfolder, '_xlsx_bytes', side_effect=OSError('가상 엑셀 실패')):
            self.assertFalse(cloudfolder.copy_now()['ok'])
        self.assertTrue(Path(self.cloud, self.zip).is_file())
        self.assertFalse(Path(self.cloud, self.xlsx).exists())
        self.assertEqual(cloudfolder.copy_now()['made'], [self.xlsx])
        self.assertEqual(cloudfolder.status()['error'], '')

    def test_same_computer_names_and_cloned_settings_have_different_file_identities(self):
        cloudfolder.set_folder(self.cloud)
        original_zip = Path(self.cloud, self.zip).read_bytes()
        second = os.path.join(self.tmp.name, 'other-data'); os.makedirs(second)
        # DB에 install_id 등 설정이 그대로 복사되어도 로컬 sidecar는 복원용 zip/DB에 없다.
        shutil.copyfile(db.DB_PATH, os.path.join(second, 'test.db'))
        with patch.object(db, 'DATA_DIR', second), patch.object(db, 'DB_PATH', os.path.join(second, 'test.db')):
            self.assertNotEqual(cloudfolder._device_id(), self.device_id)
            other_zip = cloudfolder._name(cloudfolder.KINDS[0])
            self.assertNotEqual(other_zip, self.zip)
            self.assertTrue(cloudfolder.copy_now()['ok'])
            self.assertEqual(cloudfolder._mine(self.cloud, cloudfolder.KINDS[0]), [other_zip])
        self.assertEqual(Path(self.cloud, self.zip).read_bytes(), original_zip)
        self.assertEqual(len(self.files()), 4)

    def test_entire_data_clone_on_another_machine_does_not_reuse_the_file_identity(self):
        original = cloudfolder._device_id()
        # seed와 경로가 같은 완전 복제라도 기기 지문이 다르면 최종 ID는 달라진다.
        with patch.object(cloudfolder, '_machine_fingerprint', return_value='fake-machine-b'):
            self.assertNotEqual(cloudfolder._device_id(), original)
        self.assertEqual(cloudfolder._device_id(), original)

    def test_restore_and_computer_rename_preserve_identity_and_own_retention(self):
        cloudfolder.set_folder(self.cloud)
        data = Path(self.cloud, self.zip).read_bytes()
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertNotIn('.cloud-backup-id', z.namelist())
        sheets.restore_from_bytes(data)
        self.assertEqual(cloudfolder._device_id(), self.device_id)
        with patch.object(cloudfolder.socket, 'gethostname', return_value='Renamed PC'):
            self.assertEqual(cloudfolder._device_id(), self.device_id)
            self.assertIn(self.zip, cloudfolder._mine(self.cloud, cloudfolder.KINDS[0]))

    def test_temporary_write_does_not_overwrite_an_existing_tmp_file(self):
        old_tmp = Path(self.cloud, self.zip + '.tmp'); old_tmp.write_bytes(b'belongs to another attempt')
        cloudfolder._write(self.cloud, self.zip, b'complete')
        self.assertEqual(old_tmp.read_bytes(), b'belongs to another attempt')
        self.assertEqual(Path(self.cloud, self.zip).read_bytes(), b'complete')
        self.assertEqual(self.files(), {self.zip, old_tmp.name})

    def test_failed_identity_creation_can_be_retried_without_a_broken_sidecar(self):
        Path(self.data, '.cloud-backup-id').unlink()
        with patch.object(cloudfolder.os, 'fsync', side_effect=OSError('가상 디스크 오류')):
            with self.assertRaises(OSError):
                cloudfolder._device_id()
        self.assertFalse(Path(self.data, '.cloud-backup-id').exists())
        self.assertRegex(cloudfolder._device_id(), r'^[0-9a-f]{16}$')

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


class MachineFingerprintTests(unittest.TestCase):
    def test_mac_uuid_is_hashed_and_never_sent_to_a_provider(self):
        result = types.SimpleNamespace(stdout='"IOPlatformUUID" = "12345678-ABCD-4321-ABCD-123456789ABC"')
        with patch.object(cloudfolder.platform_util, 'IS_MAC', True), patch.object(cloudfolder.platform_util, 'IS_WIN', False), \
                patch.object(cloudfolder.subprocess, 'run', return_value=result) as run:
            value = cloudfolder._machine_fingerprint.__wrapped__()
        self.assertEqual(value, hashlib.sha256(b'12345678-abcd-4321-abcd-123456789abc').hexdigest())
        self.assertEqual(run.call_args.args[0], ['/usr/sbin/ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'])

    def test_windows_guid_is_read_from_the_64bit_local_registry(self):
        calls = []
        def open_key(*args):
            calls.append(args)
            return contextlib.nullcontext('fake-key')
        reg = types.SimpleNamespace(HKEY_LOCAL_MACHINE='HKLM', KEY_READ=1, KEY_WOW64_64KEY=256,
                                    OpenKey=open_key, QueryValueEx=lambda key, name: ('FAKE-WINDOWS-GUID', 1))
        with patch.object(cloudfolder.platform_util, 'IS_WIN', True), patch.dict(sys.modules, {'winreg': reg}):
            value = cloudfolder._machine_fingerprint.__wrapped__()
        self.assertEqual(value, hashlib.sha256(b'fake-windows-guid').hexdigest())
        self.assertEqual(calls, [('HKLM', r'SOFTWARE\Microsoft\Cryptography', 0, 257)])

    def test_random_getnode_fallback_is_not_used_as_a_stable_identity(self):
        with patch.object(cloudfolder.platform_util, 'IS_WIN', False), patch.object(cloudfolder.platform_util, 'IS_MAC', False), \
                patch.object(cloudfolder.uuid, 'getnode', return_value=(1 << 40) + 123):
            self.assertEqual(cloudfolder._machine_fingerprint.__wrapped__(), '')


if __name__ == '__main__':
    unittest.main()
