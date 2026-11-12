"""녹음 원본 증분 사본. 임시 폴더와 가짜 바이트만 사용한다."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import tracemalloc
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import cloudaudio


class CloudAudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'audio'
        self.cloud = self.root / 'cloud'
        self.source.mkdir(); self.cloud.mkdir()
        self.device = 'abcd1234abcd1234'
        self.device_root = self.cloud / ('쓰담-녹음-' + self.device)
        self.manifest = self.device_root / 'manifest.json'
        setting = patch.object(cloudaudio.db, 'AUDIO_DIR', str(self.source))
        setting.start(); self.addCleanup(setting.stop)

    def audio(self, name='2026/11/가상 녹음.m4a', data=b'fake-audio-A'):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def run_sync(self, **kwargs):
        return cloudaudio.sync(str(self.cloud), self.device, **kwargs)

    def saved(self, source):
        return self.device_root / 'audio' / source.relative_to(self.source)

    def entries(self):
        return json.loads(self.manifest.read_text())['files']

    def assert_no_temp(self):
        self.assertEqual(list(self.cloud.rglob('*.tmp')), [])

    def test_initial_backup_preserves_relative_paths_and_has_restore_guide(self):
        source = self.audio()
        self.audio('2025/01/편집본.WAV', b'fake-edited-audio')
        self.audio('ignore.txt', b'not an audio file')
        result = self.run_sync()
        self.assertEqual((result['files'], result['copied'], result['versions_saved']), (2, 2, 0))
        self.assertEqual(result['bytes'], len(b'fake-audio-A') + len(b'fake-edited-audio'))
        self.assertEqual(self.saved(source).read_bytes(), source.read_bytes())
        self.assertFalse((self.device_root/'audio/ignore.txt').exists())
        item = self.entries()['2026/11/가상 녹음.m4a']
        self.assertEqual(item['sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertTrue(item['source_present'])
        self.assertIn('다른 컴퓨터', (self.device_root/'복원 안내.txt').read_text())
        self.assert_no_temp()

    def test_unchanged_fast_path_does_not_read_audio_or_copy_it(self):
        source = self.audio(); self.run_sync()
        before = self.saved(source).stat().st_mtime_ns
        with patch.object(cloudaudio, '_stream', side_effect=AssertionError('unchanged audio must not be read')):
            result = self.run_sync()
        self.assertEqual((result['copied'], result['unchanged'], result['versions_saved']), (0, 1, 0))
        self.assertEqual(self.saved(source).stat().st_mtime_ns, before)

    def test_explicit_verification_reads_but_does_not_recopy_identical_audio(self):
        self.audio(); self.run_sync()
        with patch.object(cloudaudio, '_stream', wraps=cloudaudio._stream) as stream:
            result = self.run_sync(verify=True)
        self.assertGreaterEqual(stream.call_count, 2)
        self.assertEqual(result['copied'], 0)

    def test_content_versions_are_preserved_once_per_hash(self):
        source = self.audio(data=b'version-A'); self.run_sync()
        for contents in (b'version-B', b'version-A', b'version-C'):
            source.write_bytes(contents)
            self.run_sync()
        histories = [p for p in (self.device_root/'.history').rglob('*.m4a') if p.is_file()]
        self.assertEqual({p.read_bytes() for p in histories}, {b'version-A', b'version-B'})
        self.assertEqual(len(histories), 2)
        self.assertEqual(self.saved(source).read_bytes(), b'version-C')

    def test_deleted_source_keeps_current_copy_and_marks_manifest(self):
        source = self.audio(); self.run_sync(); saved = self.saved(source)
        source.unlink()
        result = self.run_sync()
        self.assertEqual((result['files'], result['bytes'], result['missing']), (0, 0, 1))
        self.assertEqual(saved.read_bytes(), b'fake-audio-A')
        self.assertFalse(self.entries()['2026/11/가상 녹음.m4a']['source_present'])

    def test_unindexed_current_file_is_reused_after_manifest_failure(self):
        source = self.audio(); self.run_sync(); source.write_bytes(b'new-version')
        replace = os.replace
        def fail_manifest(a, b):
            if Path(b).resolve() == self.manifest.resolve():
                raise OSError('synthetic manifest failure')
            return replace(a, b)
        with patch.object(cloudaudio.os, 'replace', side_effect=fail_manifest):
            with self.assertRaises(cloudaudio.CloudAudioError): self.run_sync()
        self.assertEqual(self.saved(source).read_bytes(), b'new-version')
        result = self.run_sync()
        self.assertEqual((result['copied'], result['versions_saved']), (0, 0))
        self.assertEqual(self.entries()['2026/11/가상 녹음.m4a']['sha256'], hashlib.sha256(b'new-version').hexdigest())
        self.assert_no_temp()

    def test_failed_current_replace_preserves_previous_current_and_manifest(self):
        source = self.audio(); self.run_sync(); saved = self.saved(source)
        before_manifest = self.manifest.read_bytes(); source.write_bytes(b'new-version')
        replace = os.replace
        def fail_current(a, b):
            if Path(b).resolve() == saved.resolve(): raise PermissionError('synthetic replace failure')
            return replace(a, b)
        with patch.object(cloudaudio.os, 'replace', side_effect=fail_current):
            with self.assertRaises(cloudaudio.CloudAudioError): self.run_sync()
        self.assertEqual(saved.read_bytes(), b'fake-audio-A')
        self.assertEqual(self.manifest.read_bytes(), before_manifest)
        self.assert_no_temp()

    def test_fsync_failure_preserves_previous_current(self):
        source = self.audio(); self.run_sync(); source.write_bytes(b'new-version')
        with patch.object(cloudaudio.os, 'fsync', side_effect=OSError('synthetic full disk')):
            with self.assertRaises(cloudaudio.CloudAudioError): self.run_sync()
        self.assertEqual(self.saved(source).read_bytes(), b'fake-audio-A')
        self.assert_no_temp()

    def test_history_failure_preserves_previous_current(self):
        source = self.audio(); self.run_sync(); source.write_bytes(b'new-version')
        replace = os.replace
        def fail_history(a, b):
            if '.history' in Path(b).parts: raise OSError('synthetic history failure')
            return replace(a, b)
        with patch.object(cloudaudio.os, 'replace', side_effect=fail_history):
            with self.assertRaises(cloudaudio.CloudAudioError): self.run_sync()
        self.assertEqual(self.saved(source).read_bytes(), b'fake-audio-A')
        self.assert_no_temp()

    def test_source_mutating_during_hash_is_rejected(self):
        source = self.audio(data=b'old'); self.run_sync(); source.write_bytes(b'new-data' * 4)
        real_sha = hashlib.sha256
        mutated = []
        class MutatingHash:
            def __init__(self): self.inner = real_sha()
            def update(self, value):
                self.inner.update(value)
                if not mutated:
                    mutated.append(True)
                    with source.open('ab') as output: output.write(b'changed-during-read')
            def hexdigest(self): return self.inner.hexdigest()
        with patch.object(cloudaudio.hashlib, 'sha256', MutatingHash), patch.object(cloudaudio, 'CHUNK_SIZE', 4):
            with self.assertRaises(cloudaudio.CloudAudioError): self.run_sync()
        self.assertEqual(self.saved(source).read_bytes(), b'old')
        self.assert_no_temp()

    @staticmethod
    def changed_stat(info, **changes):
        values = {name: getattr(info, name) for name in
                  ('st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_dev', 'st_ino')}
        if hasattr(info, 'st_birthtime_ns'):
            values['st_birthtime_ns'] = info.st_birthtime_ns
        values.update(changes)
        return types.SimpleNamespace(**values)

    def test_windows_path_birthtime_and_handle_changetime_can_differ(self):
        source = self.audio()
        regular, fstat = cloudaudio._regular, os.fstat
        def by_path(path, root):
            return self.changed_stat(regular(path, root), st_ctime_ns=100, st_birthtime_ns=100)
        def by_handle(fd):
            return self.changed_stat(fstat(fd), st_ctime_ns=200, st_birthtime_ns=100)
        with patch.object(cloudaudio, '_WINDOWS', True), \
                patch.object(cloudaudio, '_regular', side_effect=by_path), \
                patch.object(cloudaudio.os, 'fstat', side_effect=by_handle):
            digest, info = cloudaudio._stream(str(source.resolve()), str(self.source.resolve()))
        self.assertEqual(digest, hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(info.st_ctime_ns, 100)  # Cache uses the same lstat domain as the next scan.

    def test_windows_handle_changetime_mutation_is_still_rejected(self):
        source = self.audio()
        regular, fstat = cloudaudio._regular, os.fstat
        calls = []
        def by_path(path, root):
            return self.changed_stat(regular(path, root), st_ctime_ns=100, st_birthtime_ns=100)
        def changed_handle(fd):
            calls.append(fd)
            return self.changed_stat(fstat(fd), st_ctime_ns=200 + len(calls), st_birthtime_ns=100)
        with patch.object(cloudaudio, '_WINDOWS', True), \
                patch.object(cloudaudio, '_regular', side_effect=by_path), \
                patch.object(cloudaudio.os, 'fstat', side_effect=changed_handle):
            with self.assertRaises(cloudaudio.CloudAudioError):
                cloudaudio._stream(str(source.resolve()), str(self.source.resolve()))
        self.assertEqual(len(calls), 2)

    def test_windows_path_handle_identity_and_content_mismatch_is_rejected_before_read(self):
        source = self.audio()
        regular, fstat = cloudaudio._regular, os.fstat
        def by_path(path, root):
            return self.changed_stat(regular(path, root), st_ctime_ns=100, st_birthtime_ns=100)
        for field in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_birthtime_ns'):
            with self.subTest(field=field):
                output = io.BytesIO()
                def wrong_handle(fd):
                    info = self.changed_stat(fstat(fd), st_ctime_ns=200, st_birthtime_ns=100)
                    return self.changed_stat(info, **{field: getattr(info, field) + 1})
                with patch.object(cloudaudio, '_WINDOWS', True), \
                        patch.object(cloudaudio, '_regular', side_effect=by_path), \
                        patch.object(cloudaudio.os, 'fstat', side_effect=wrong_handle):
                    with self.assertRaises(cloudaudio.CloudAudioError):
                        cloudaudio._stream(str(source.resolve()), str(self.source.resolve()), output)
                self.assertEqual(output.getvalue(), b'')

    def test_windows_different_ctime_domains_do_not_break_unchanged_cache(self):
        source = self.audio()
        fstat = os.fstat
        def by_handle(fd):
            info = fstat(fd)
            return self.changed_stat(info, st_ctime_ns=info.st_ctime_ns + 123456)
        with patch.object(cloudaudio, '_WINDOWS', True), \
                patch.object(cloudaudio.os, 'fstat', side_effect=by_handle):
            self.assertEqual(self.run_sync()['copied'], 1)
        with patch.object(cloudaudio, '_stream', side_effect=AssertionError('unchanged audio must not be read')):
            result = self.run_sync()
        self.assertEqual((result['copied'], result['unchanged']), (0, 1))
        self.assertEqual(self.saved(source).read_bytes(), source.read_bytes())

    def test_file_replaced_between_path_check_and_open_is_rejected_before_read(self):
        source = self.audio(data=b'same-bytes')
        replacement = self.audio('replacement.wav', data=b'same-bytes')
        original = source.stat()
        os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
        real_open = os.open
        def open_other_file(path, flags, *args, **kwargs):
            actual = replacement if Path(path) == source.resolve() else path
            return real_open(actual, flags, *args, **kwargs)
        for windows in (False, True):
            with self.subTest(windows=windows):
                output = io.BytesIO()
                with patch.object(cloudaudio, '_WINDOWS', windows), \
                        patch.object(cloudaudio.os, 'open', side_effect=open_other_file):
                    with self.assertRaises(cloudaudio.CloudAudioError):
                        cloudaudio._stream(str(source.resolve()), str(self.source.resolve()), output)
                self.assertEqual(output.getvalue(), b'')

    def test_cloud_stream_allows_ctime_only_change_during_read(self):
        cloud_file = self.cloud/'synthetic.m4a'; cloud_file.write_bytes(b'unchanged-audio')
        fstat = os.fstat
        calls = []
        def metadata_change(fd):
            info = fstat(fd); calls.append(fd)
            return self.changed_stat(info, st_ctime_ns=info.st_ctime_ns + len(calls))
        with patch.object(cloudaudio.os, 'fstat', side_effect=metadata_change):
            digest, _ = cloudaudio._stream(str(cloud_file.resolve()), str(self.cloud.resolve()), cloud=True)
        self.assertEqual(digest, hashlib.sha256(b'unchanged-audio').hexdigest())
        self.assertEqual(len(calls), 2)

    def test_local_source_still_rejects_ctime_only_change_during_read(self):
        source = self.audio(); fstat = os.fstat
        calls = []
        def metadata_change(fd):
            info = fstat(fd); calls.append(fd)
            if len(calls) == 2:
                return self.changed_stat(info, st_ctime_ns=info.st_ctime_ns + 1)
            return info
        with patch.object(cloudaudio.os, 'fstat', side_effect=metadata_change):
            with self.assertRaises(cloudaudio.CloudAudioError):
                cloudaudio._stream(str(source.resolve()), str(self.source.resolve()))
        self.assertEqual(len(calls), 2)

    def test_cloud_stream_still_rejects_identity_size_or_mtime_change(self):
        cloud_file = self.cloud/'synthetic.m4a'; cloud_file.write_bytes(b'unchanged-audio')
        fstat = os.fstat
        for field in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns'):
            with self.subTest(field=field):
                calls = []
                def content_change(fd):
                    info = fstat(fd); calls.append(fd)
                    if len(calls) == 2:
                        return self.changed_stat(info, **{field: getattr(info, field) + 1})
                    return info
                with patch.object(cloudaudio.os, 'fstat', side_effect=content_change):
                    with self.assertRaises(cloudaudio.CloudAudioError):
                        cloudaudio._stream(str(cloud_file.resolve()), str(self.cloud.resolve()), cloud=True)
                self.assertEqual(len(calls), 2)

    def test_cloud_ctime_changes_allow_temp_checks_history_and_current_replace(self):
        source = self.audio(data=b'version-A')
        regular = cloudaudio._regular
        changed = []
        cloud_root = str(self.cloud.resolve())
        def cloud_metadata_change(path, root):
            info = regular(path, root)
            if os.path.commonpath([os.path.realpath(path), cloud_root]) == cloud_root:
                changed.append(path)
                return self.changed_stat(info, st_ctime_ns=info.st_ctime_ns + len(changed))
            return info
        with patch.object(cloudaudio, '_regular', side_effect=cloud_metadata_change):
            self.assertEqual(self.run_sync()['copied'], 1)
            for value in (b'version-B', b'version-A', b'version-C'):
                source.write_bytes(value)
                self.assertEqual(self.run_sync()['copied'], 1)
        self.assertTrue(changed)
        self.assertEqual(self.saved(source).read_bytes(), b'version-C')
        histories = [p for p in (self.device_root/'.history').rglob('*.m4a') if p.is_file()]
        self.assertEqual({p.read_bytes() for p in histories}, {b'version-A', b'version-B'})
        self.assert_no_temp()

    def test_cloud_temp_checksum_mismatch_still_preserves_previous_copy(self):
        source = self.audio(data=b'version-A'); self.run_sync(); source.write_bytes(b'version-B')
        stream = cloudaudio._stream
        corrupted = []
        def corrupt_temporary(path, root, output=None, cloud=False):
            if Path(path).name.startswith('.sseudam-audio-') and not corrupted:
                info = os.stat(path)
                with open(path, 'r+b') as temporary: temporary.write(b'X')
                os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
                corrupted.append(path)
            return stream(path, root, output, cloud=cloud)
        with patch.object(cloudaudio, '_stream', side_effect=corrupt_temporary):
            with self.assertRaises(cloudaudio.CloudAudioError): self.run_sync()
        self.assertTrue(corrupted)
        self.assertEqual(self.saved(source).read_bytes(), b'version-A')
        self.assert_no_temp()

    def test_source_symlink_file_and_directory_are_rejected(self):
        outside = self.root/'outside'; outside.mkdir(); (outside/'private.m4a').write_bytes(b'fake-outside')
        for name, target, is_directory in [('link.m4a', outside/'private.m4a', False), ('linked-dir', outside, True)]:
            with self.subTest(name=name):
                link = self.source/name
                link.symlink_to(target, target_is_directory=is_directory)
                try:
                    with self.assertRaises(cloudaudio.CloudAudioError): self.run_sync()
                finally: link.unlink()
        self.assertFalse(self.device_root.exists())
        self.assertEqual((outside/'private.m4a').read_bytes(), b'fake-outside')

    def test_existing_destination_symlink_is_rejected(self):
        source = self.audio(); self.run_sync(); saved = self.saved(source)
        outside = self.root/'outside.m4a'; outside.write_bytes(b'fake-outside')
        saved.unlink(); saved.symlink_to(outside)
        with self.assertRaises(cloudaudio.CloudAudioError): self.run_sync()
        self.assertEqual(outside.read_bytes(), b'fake-outside')

    def test_destination_parent_symlink_is_rejected(self):
        self.audio()
        self.device_root.mkdir(); (self.device_root/'audio').mkdir()
        outside = self.root/'outside'; outside.mkdir()
        (self.device_root/'audio/2026').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(cloudaudio.CloudAudioError): self.run_sync()
        self.assertEqual(list(outside.iterdir()), [])

    def test_history_and_manifest_symlinks_are_rejected(self):
        source = self.audio(); self.run_sync(); source.write_bytes(b'new-version')
        outside = self.root/'outside'; outside.mkdir()
        history = self.device_root/'.history'; history.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(cloudaudio.CloudAudioError): self.run_sync()
        self.assertEqual(self.saved(source).read_bytes(), b'fake-audio-A')
        self.assertEqual(list(outside.iterdir()), [])
        history.unlink()
        external = outside/'manifest.json'; external.write_text('{}')
        self.manifest.unlink(); self.manifest.symlink_to(external)
        with self.assertRaises(cloudaudio.CloudAudioError): self.run_sync()
        self.assertEqual(external.read_text(), '{}')

    def test_missing_or_unreadable_source_is_not_a_successful_deletion(self):
        self.audio(); self.run_sync(); previous = self.manifest.read_bytes()
        def inaccessible(*args, **kwargs):
            kwargs['onerror'](PermissionError('synthetic source denied'))
            yield
        with patch.object(cloudaudio.os, 'walk', inaccessible):
            with self.assertRaises(cloudaudio.CloudAudioError): self.run_sync()
        self.assertEqual(self.manifest.read_bytes(), previous)
        with patch.object(cloudaudio.db, 'AUDIO_DIR', str(self.root/'missing')):
            with self.assertRaises(cloudaudio.CloudAudioError): self.run_sync()
        self.assertEqual(self.manifest.read_bytes(), previous)

    def test_nested_destination_and_unsafe_device_id_are_rejected(self):
        nested = self.source/'nested'; nested.mkdir()
        with self.assertRaises(cloudaudio.CloudAudioError): cloudaudio.sync(str(nested), self.device)
        for device in ('../escape', '', 'device/name'):
            with self.assertRaises(cloudaudio.CloudAudioError): cloudaudio.sync(str(self.cloud), device)
        self.assertEqual(list(nested.iterdir()), [])

    def test_same_path_names_on_different_devices_are_separate(self):
        source = self.audio(); self.run_sync()
        other = cloudaudio.sync(str(self.cloud), 'other-device')
        self.assertNotEqual(other['folder'], str(self.device_root))
        self.assertEqual(self.saved(source).read_bytes(), b'fake-audio-A')

    def test_large_synthetic_audio_is_streamed_with_bounded_memory(self):
        source = self.audio(data=b'')
        block = b'fictional-audio' * 8192
        with source.open('wb') as output:
            for _ in range(64): output.write(block)
        with patch.object(cloudaudio, 'CHUNK_SIZE', 65536):
            tracemalloc.start()
            try:
                result = self.run_sync()
                _, peak = tracemalloc.get_traced_memory()
            finally: tracemalloc.stop()
        self.assertEqual(result['copied_bytes'], len(block) * 64)
        self.assertLess(peak, 2 * 1024 * 1024)
        self.assertEqual(self.saved(source).stat().st_size, source.stat().st_size)


if __name__ == '__main__':
    unittest.main()
