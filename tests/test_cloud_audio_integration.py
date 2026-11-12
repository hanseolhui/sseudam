"""Audio opt-in, cloud-folder scheduling, and restore boundaries using temporary data only."""
import io
import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import cloudfolder
import db
import sheets


class CloudAudioIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / 'data'
        self.audio = self.data / 'audio'
        self.backups = self.data / 'backups'
        self.cloud = self.root / 'cloud'
        self.other_cloud = self.root / 'other-cloud'
        for directory in (self.data, self.audio, self.backups, self.cloud, self.other_cloud):
            directory.mkdir(parents=True, exist_ok=True)
        for name, value in {
            'DATA_DIR': str(self.data), 'AUDIO_DIR': str(self.audio),
            'BACKUP_DIR': str(self.backups), 'DB_PATH': str(self.data / 'test.db'),
        }.items():
            self.start_patch(patch.object(db, name, value))
        self.start_patch(patch.object(db, 'init'))
        self.start_patch(patch.object(sheets, '_call', side_effect=AssertionError('Network forbidden')))
        self.start_patch(patch.object(cloudfolder, 'candidates', return_value=[]))
        self.start_patch(patch.object(cloudfolder, '_machine_fingerprint', return_value='synthetic-audio-machine'))
        self.start_patch(patch.object(cloudfolder.socket, 'gethostname', return_value='Synthetic-Audio-PC'))
        self.start_patch(patch.object(cloudfolder, '_audio_busy', threading.Event()))
        conn = db.connect()
        conn.executescript(db.SCHEMA)
        db._migrate_columns(conn)
        conn.executemany('INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)', db.DEFAULT_SETTINGS.items())
        conn.execute("INSERT INTO classes(id,year,semester,grade,class_no,label) VALUES(1,2026,2,1,1,'가상반')")
        conn.execute("INSERT INTO students(id,class_id,number,name) VALUES(1,1,1,'가상학생')")
        conn.execute("INSERT INTO notes(student_id,date,content) VALUES(1,'2026-11-13','가상 관찰')")
        conn.commit()
        conn.close()
        self.device_id = cloudfolder._device_id()
        self.archive_names = [cloudfolder._name(kind) for kind in cloudfolder.KINDS]
        self.audio_result = {
            'ok': True, 'folder': str(self.cloud / ('쓰담-녹음-' + self.device_id)),
            'files': 1, 'bytes': 23, 'copied': 1, 'copied_bytes': 23,
        }
        self.sync = Mock(return_value=self.audio_result)
        # cloudfolder imports this module only when opted in. The real copying
        # implementation is exercised separately, while these tests verify wiring.
        self.audio_module_patch = patch.dict(sys.modules, {'cloudaudio': types.SimpleNamespace(sync=self.sync)})
        self.start_patch(self.audio_module_patch)

    def start_patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def select_folder(self):
        return cloudfolder.set_folder(str(self.cloud))

    def archive_bytes(self):
        return {name: (self.cloud / name).read_bytes() for name in self.archive_names}

    def test_audio_is_off_by_default_even_with_existing_recordings(self):
        (self.audio / 'synthetic.m4a').write_bytes(b'fake audio, never a real recording')
        state = self.select_folder()
        self.assertEqual(db.get_settings()['backup_audio'], '0')
        self.assertFalse(state['audio_enabled'])
        self.assertEqual(state['audio_last'], '')
        self.assertEqual(state['audio_summary'], {})
        self.sync.assert_not_called()
        self.assertEqual(set(os.listdir(self.cloud)), set(self.archive_names))

    def test_audio_opt_in_requires_an_existing_destination_and_a_boolean(self):
        with self.assertRaises(ValueError):
            cloudfolder.set_audio_enabled(True)
        self.select_folder()
        for invalid in (None, 0, 1, '0', '1', [], {}):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                cloudfolder.set_audio_enabled(invalid)
        self.assertEqual(db.get_settings()['backup_audio'], '0')
        self.sync.assert_not_called()

    def test_explicit_opt_in_copies_immediately_and_records_success(self):
        self.select_folder()

        def observe_busy(folder, device_id):
            self.assertTrue(cloudfolder.status()['audio_busy'])
            return self.audio_result

        self.sync.side_effect = observe_busy
        state = cloudfolder.set_audio_enabled(True)
        self.sync.assert_called_once_with(str(self.cloud), self.device_id)
        self.assertTrue(state['audio_enabled'])
        self.assertTrue(state['audio_last'])
        self.assertFalse(state['audio_busy'])
        self.assertEqual(state['audio_error'], '')
        self.assertEqual(state['audio_summary'], self.audio_result)

    def test_existing_daily_zip_and_xlsx_do_not_skip_new_audio(self):
        self.select_folder()
        before = self.archive_bytes()
        db.set_settings({'backup_audio': '1'})
        with patch.object(sheets, '_db_zip_bytes', side_effect=AssertionError('Daily ZIP should be reused')), \
                patch.object(cloudfolder, '_xlsx_bytes', side_effect=AssertionError('Daily XLSX should be reused')):
            result = cloudfolder.copy_now()
        self.assertTrue(result['ok'])
        self.assertEqual(result['made'], [])
        self.assertEqual(result['audio'], self.audio_result)
        self.assertEqual(self.archive_bytes(), before)
        self.sync.assert_called_once_with(str(self.cloud), self.device_id)

    def test_disabling_audio_keeps_existing_audio_and_record_archives(self):
        self.select_folder()
        cloudfolder.set_audio_enabled(True)
        mirror = self.cloud / 'synthetic-existing-audio.m4a'
        mirror.write_bytes(b'existing private synthetic backup')
        before = self.archive_bytes()
        self.sync.reset_mock()
        state = cloudfolder.set_audio_enabled(False)
        self.assertFalse(state['audio_enabled'])
        self.assertTrue(cloudfolder.copy_now()['ok'])
        self.sync.assert_not_called()
        self.assertEqual(mirror.read_bytes(), b'existing private synthetic backup')
        self.assertEqual(self.archive_bytes(), before)

    def test_turning_off_cloud_backup_clears_audio_opt_in_and_status(self):
        self.select_folder()
        cloudfolder.set_audio_enabled(True)
        before = self.archive_bytes()
        self.sync.reset_mock()
        state = cloudfolder.set_folder('')
        self.assertEqual(state['folder'], '')
        self.assertFalse(state['audio_enabled'])
        self.assertEqual(state['audio_last'], '')
        self.assertEqual(state['audio_error'], '')
        self.assertEqual(state['audio_summary'], {})
        self.assertEqual(db.get_settings()['backup_audio'], '0')
        self.assertTrue(cloudfolder.copy_now()['off'])
        self.sync.assert_not_called()
        self.assertEqual(self.archive_bytes(), before)

    def test_new_destination_does_not_inherit_audio_consent(self):
        self.select_folder()
        cloudfolder.set_audio_enabled(True)
        old_archives = self.archive_bytes()
        self.sync.reset_mock()
        state = cloudfolder.set_folder(str(self.other_cloud))
        self.assertEqual(state['folder'], str(self.other_cloud))
        self.assertFalse(state['audio_enabled'])
        self.assertEqual(state['audio_last'], '')
        self.assertEqual(state['audio_summary'], {})
        self.sync.assert_not_called()
        self.assertEqual(self.archive_bytes(), old_archives)
        self.assertEqual(set(os.listdir(self.other_cloud)), set(self.archive_names))

    def test_selecting_the_same_destination_keeps_audio_consent(self):
        self.select_folder()
        cloudfolder.set_audio_enabled(True)
        self.sync.reset_mock()
        state = cloudfolder.set_folder(str(self.cloud) + os.sep)
        self.assertTrue(state['audio_enabled'])
        self.sync.assert_called_once()
        self.assertEqual(os.path.realpath(self.sync.call_args.args[0]), str(self.cloud.resolve()))
        self.assertEqual(self.sync.call_args.args[1], self.device_id)

    def test_audio_failure_keeps_last_success_and_retries_after_daily_archives_exist(self):
        self.select_folder()
        old_audio = {'ok': True, 'files': 5, 'bytes': 50, 'copied': 0}
        db.set_settings({'backup_audio': '1', 'backup_audio_last': '2001-01-01 01:01',
                         'backup_audio_summary': json.dumps(old_audio), 'backup_folder_last': '2000-01-01 01:01'})
        self.sync.side_effect = OSError('Synthetic audio disk failure')
        result = cloudfolder.copy_now(force=True)
        self.assertFalse(result['ok'])
        state = cloudfolder.status()
        self.assertIn('Synthetic audio disk failure', state['audio_error'])
        self.assertEqual(state['audio_last'], '2001-01-01 01:01')
        self.assertEqual(state['audio_summary'], old_audio)
        self.assertFalse(state['audio_busy'])
        self.assertEqual(state['error'], '')  # Record archives succeeded independently.
        self.assertNotEqual(state['last'], '2000-01-01 01:01')
        before = self.archive_bytes()
        self.sync.side_effect = None
        result = cloudfolder.copy_now()
        self.assertTrue(result['ok'])
        self.assertEqual(result['made'], [])
        self.assertEqual(self.archive_bytes(), before)
        state = cloudfolder.status()
        self.assertEqual(state['audio_error'], '')
        self.assertNotEqual(state['audio_last'], '2001-01-01 01:01')
        self.assertEqual(state['audio_summary'], self.audio_result)
        self.assertFalse(state['audio_busy'])
        self.assertEqual(self.sync.call_count, 2)

    def test_first_audio_failure_does_not_claim_a_success_time(self):
        self.select_folder()
        self.sync.side_effect = OSError('Synthetic first-copy failure')
        state = cloudfolder.set_audio_enabled(True)
        self.assertTrue(state['audio_enabled'])  # Remains opted in so the scheduler retries.
        self.assertEqual(state['audio_last'], '')
        self.assertEqual(state['audio_summary'], {})
        self.assertIn('Synthetic first-copy failure', state['audio_error'])
        self.assertFalse(state['audio_busy'])

    def test_record_backup_failure_does_not_run_audio_or_change_its_last_success(self):
        self.select_folder()
        db.set_settings({'backup_audio': '1', 'backup_audio_last': '2001-01-01 01:01',
                         'backup_folder_last': '2000-01-01 01:01'})
        with patch.object(sheets, '_db_zip_bytes', side_effect=OSError('Synthetic record-backup failure')):
            result = cloudfolder.copy_now(force=True)
        self.assertFalse(result['ok'])
        state = cloudfolder.status()
        self.assertEqual(state['last'], '2000-01-01 01:01')
        self.assertEqual(state['audio_last'], '2001-01-01 01:01')
        self.assertIn('Synthetic record-backup failure', state['error'])
        self.assertFalse(state['audio_busy'])
        self.sync.assert_not_called()

    def test_export_scrubs_audio_opt_in_destination_and_status(self):
        self.select_folder()
        db.set_settings({'backup_audio': '1', 'backup_audio_last': '2099-12-31 23:59',
                         'backup_audio_error': 'SYNTHETIC-AUDIO-ERROR',
                         'backup_audio_summary': '{"private":"SYNTHETIC-AUDIO-STATUS"}'})
        with zipfile.ZipFile(io.BytesIO(sheets._db_zip_bytes())) as archive:
            raw = archive.read('seteuk.db')
        self.assertNotIn(b'SYNTHETIC-AUDIO-ERROR', raw)
        self.assertNotIn(b'SYNTHETIC-AUDIO-STATUS', raw)
        extracted = self.root / 'scrubbed.db'
        extracted.write_bytes(raw)
        conn = sqlite3.connect(extracted)
        settings = dict(conn.execute('SELECT key,value FROM settings'))
        conn.close()
        self.assertEqual(settings['backup_audio'], '0')
        for key in ('backup_folder', 'backup_audio_last', 'backup_audio_error', 'backup_audio_summary'):
            self.assertEqual(settings[key], '')
        self.assertEqual(db.get_settings()['backup_audio'], '1')  # Scrubbing only touched the copy.

    def test_restoring_export_keeps_current_audio_opt_in_and_status(self):
        self.select_folder()
        saved = sheets._db_zip_bytes()
        current = {'backup_audio': '1', 'backup_audio_last': '2099-12-31 23:59',
                   'backup_audio_error': 'Synthetic pending retry', 'backup_audio_summary': '{"files":7}'}
        db.set_settings(current)
        self.assertTrue(sheets.restore_from_bytes(saved)['ok'])
        actual = db.get_settings()
        self.assertEqual(actual['backup_folder'], str(self.cloud))
        for key, value in current.items():
            self.assertEqual(actual[key], value)
        self.sync.assert_not_called()  # Restore itself does not upload audio.

    def test_restoring_old_local_database_keeps_current_audio_off(self):
        self.select_folder()
        db.set_settings({'backup_audio': '1'})
        previous = self.root / 'previous-local.db'
        db.backup_to(str(previous))
        cloudfolder.set_audio_enabled(False)
        self.assertTrue(sheets.restore_from_bytes(previous.read_bytes())['ok'])
        self.assertEqual(db.get_settings()['backup_audio'], '0')
        self.assertFalse(cloudfolder.status()['audio_enabled'])
        self.sync.assert_not_called()

    def test_restoring_old_local_database_cannot_reenable_a_disabled_destination(self):
        self.select_folder()
        db.set_settings({'backup_audio': '1'})
        previous = self.root / 'previous-enabled-local.db'
        db.backup_to(str(previous))
        cloudfolder.set_folder('')
        self.assertTrue(sheets.restore_from_bytes(previous.read_bytes())['ok'])
        state = cloudfolder.status()
        self.assertEqual(state['folder'], '')
        self.assertFalse(state['audio_enabled'])
        self.assertEqual(db.get_settings()['backup_audio'], '0')
        self.sync.assert_not_called()

    def test_real_audio_sync_copies_new_files_and_retains_changed_and_deleted_versions(self):
        self.select_folder()
        self.audio_module_patch.stop()
        real_audio = importlib.import_module('cloudaudio')
        self.assertTrue(callable(real_audio.sync))
        relative = Path('2026') / '11' / 'synthetic.m4a'
        original = self.audio / relative
        original.parent.mkdir(parents=True)
        first_payload = b'SYNTHETIC-AUDIO-FIRST-VERSION'
        original.write_bytes(first_payload)
        state = cloudfolder.set_audio_enabled(True)
        self.assertEqual(state['audio_error'], '')
        self.assertEqual(state['audio_summary']['files'], 1)
        self.assertEqual(state['audio_summary']['copied'], 1)
        mirror_root = Path(state['audio_summary']['folder'])
        mirrored = mirror_root / 'audio' / relative
        self.assertEqual(mirrored.read_bytes(), first_payload)

        # A new audio file is backed up even though today's record ZIP/XLSX exist.
        second = self.audio / 'second.wav'
        second.write_bytes(b'SYNTHETIC-SECOND-RECORDING')
        result = cloudfolder.copy_now()
        self.assertTrue(result['ok'])
        self.assertEqual(result['made'], [])
        self.assertEqual(result['audio']['files'], 2)
        self.assertEqual(result['audio']['copied'], 1)
        self.assertEqual((mirror_root / 'audio' / second.name).read_bytes(), second.read_bytes())

        # Changed content keeps an actual old copy, not only the old hash.
        original.write_bytes(b'SYNTHETIC-AUDIO-CHANGED-VERSION')
        result = cloudfolder.copy_now()
        self.assertTrue(result['ok'])
        self.assertEqual(result['audio']['copied'], 1)
        self.assertEqual(result['audio']['versions_saved'], 1)
        self.assertEqual(mirrored.read_bytes(), original.read_bytes())
        old_hash = hashlib.sha256(first_payload).hexdigest()
        previous = mirror_root / '.history' / relative / (old_hash + '.m4a')
        self.assertEqual(previous.read_bytes(), first_payload)

        original.unlink()  # Only a test fixture is removed.
        result = cloudfolder.copy_now()
        self.assertTrue(result['ok'])
        self.assertEqual(result['audio']['files'], 1)
        self.assertEqual(result['audio']['missing'], 1)
        self.assertEqual(result['audio']['copied'], 0)
        self.assertEqual(mirrored.read_bytes(), b'SYNTHETIC-AUDIO-CHANGED-VERSION')
        self.assertEqual(previous.read_bytes(), first_payload)
        manifest = json.loads(Path(result['audio']['manifest']).read_text())
        self.assertFalse(manifest['files'][relative.as_posix()]['source_present'])


if __name__ == '__main__':
    unittest.main()
