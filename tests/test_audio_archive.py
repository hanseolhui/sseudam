"""음성 보관의 완전한 파일 공개와 원본 보존을 검증한다. 임시 파일만 사용하며 DB는 열지 않는다."""
import os
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import db


class AudioArchiveTests(unittest.TestCase):
    recorded_at = "2026-11-13 00:15:42"
    hint = "가상 1반 /?"
    kind = "수업"
    basename = "20261113-0015_수업_가상1반"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sseudam-audio-archive-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inputs = self.root / "incoming"
        self.inputs.mkdir()
        self.data = self.root / "data"
        self.audio = self.data / "audio"
        self.folder = self.audio / "2026" / "11"
        for name, value in [
            ("SUPPORT_DIR", self.root),
            ("DATA_DIR", self.data),
            ("AUDIO_DIR", self.audio),
            ("BACKUP_DIR", self.data / "backups"),
            ("DB_PATH", self.data / "never-open.db"),
        ]:
            mock = patch.object(db, name, str(value))
            mock.start()
            self.addCleanup(mock.stop)
        mock = patch.object(db, "connect", side_effect=AssertionError("This test must not open a database"))
        mock.start()
        self.addCleanup(mock.stop)

    def source(self, name="가상 녹음.M4A", payload=b"synthetic recording\x00\xff" * 4096):
        path = self.inputs / name
        path.write_bytes(payload)
        return path

    def archive(self, source, copy=True):
        return Path(db.move_audio_into_archive(str(source), self.recorded_at, self.hint, self.kind, copy=copy))

    def files(self):
        return list(self.folder.iterdir()) if self.folder.exists() else []

    def completed_files(self):
        return [path for path in self.files() if not path.name.endswith(".tmp")]

    def assert_no_staging_files(self):
        self.assertFalse([path.name for path in self.files() if path.name.endswith(".tmp")])

    def test_copy_preserves_original_bytes_and_metadata(self):
        source = self.source()
        os.utime(source, (1600000000, 1600000000))
        original = source.read_bytes()
        modified = source.stat().st_mtime_ns

        archived = self.archive(source)

        self.assertEqual(archived, self.folder / (self.basename + ".m4a"))
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(archived.read_bytes(), original)
        self.assertEqual(archived.stat().st_mtime_ns, modified)
        self.assert_no_staging_files()

    def test_move_deletes_source_only_after_complete_archive_is_available(self):
        source = self.source()
        original = source.read_bytes()
        real_remove = os.remove
        source_removals = []

        def observe_remove(path, *args, **kwargs):
            if Path(path) == source:
                published = self.completed_files()
                self.assertEqual(len(published), 1)
                self.assertEqual(published[0].read_bytes(), original)
                self.assertEqual(source.read_bytes(), original)
                source_removals.append(path)
            return real_remove(path, *args, **kwargs)

        with patch.object(db.os, "remove", side_effect=observe_remove):
            archived = self.archive(source, copy=False)

        self.assertEqual(len(source_removals), 1)
        self.assertFalse(source.exists())
        self.assertEqual(archived.read_bytes(), original)
        self.assert_no_staging_files()

    def test_copy_in_progress_is_not_visible_as_a_completed_recording(self):
        source = self.source()
        original = source.read_bytes()
        copying = threading.Event()
        resume = threading.Event()

        def paused_copy(src, dst):
            payload = Path(src).read_bytes()
            halfway = len(payload) // 2
            with open(dst, "wb") as output:
                output.write(payload[:halfway])
                output.flush()
                copying.set()
                if not resume.wait(10):
                    raise TimeoutError("Test did not release the paused copy")
                output.write(payload[halfway:])
            return dst

        with patch.object(db.shutil, "copy2", side_effect=paused_copy):
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(self.archive, source)
                try:
                    self.assertTrue(copying.wait(10), "Copy did not reach the paused stage")
                    self.assertEqual(self.completed_files(), [])
                    self.assertEqual(source.read_bytes(), original)
                    staging = self.files()
                    self.assertEqual(len(staging), 1)
                    self.assertTrue(staging[0].name.endswith(".tmp"))
                    self.assertLess(staging[0].stat().st_size, len(original))
                finally:
                    resume.set()
                archived = pending.result(timeout=10)

        self.assertEqual(archived.read_bytes(), original)
        self.assert_no_staging_files()

    def test_partial_copy_failure_never_publishes_or_removes_source(self):
        source = self.source()
        original = source.read_bytes()

        def fail_mid_copy(src, dst):
            Path(dst).write_bytes(Path(src).read_bytes()[:17])
            self.assertEqual(self.completed_files(), [])
            raise OSError("Synthetic disk full")

        for copy in (True, False):
            with self.subTest(copy=copy):
                with patch.object(db.shutil, "copy2", side_effect=fail_mid_copy):
                    with self.assertRaisesRegex(OSError, "Synthetic disk full"):
                        self.archive(source, copy=copy)
                self.assertEqual(source.read_bytes(), original)
                self.assertEqual(self.files(), [])

    def test_flush_failure_keeps_original_and_does_not_publish(self):
        source = self.source()
        original = source.read_bytes()
        with patch.object(db.os, "fsync", side_effect=OSError("Synthetic flush failure")):
            with self.assertRaisesRegex(OSError, "Synthetic flush failure"):
                self.archive(source, copy=False)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(self.files(), [])

    def test_publication_failure_keeps_original_and_cleans_staging(self):
        source = self.source()
        original = source.read_bytes()
        with patch.object(db.os, "link", side_effect=PermissionError("Synthetic publication failure")):
            with self.assertRaisesRegex(PermissionError, "Synthetic publication failure"):
                self.archive(source, copy=False)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(self.files(), [])

    def test_existing_same_name_recordings_are_not_replaced(self):
        source = self.source()
        original = source.read_bytes()
        self.folder.mkdir(parents=True)
        first = self.folder / (self.basename + ".m4a")
        second = self.folder / (self.basename + "-2.m4a")
        first.write_bytes(b"older recording one")
        second.write_bytes(b"older recording two")

        archived = self.archive(source)

        self.assertEqual(first.read_bytes(), b"older recording one")
        self.assertEqual(second.read_bytes(), b"older recording two")
        self.assertEqual(archived, self.folder / (self.basename + "-3.m4a"))
        self.assertEqual(archived.read_bytes(), original)
        self.assertEqual(source.read_bytes(), original)
        self.assert_no_staging_files()

    def test_name_claimed_at_publication_is_not_overwritten(self):
        source = self.source()
        original = source.read_bytes()
        real_link = os.link
        claimed = []

        def competing_link(src, dst, *args, **kwargs):
            if not claimed:
                # Another process can claim the destination after a name was selected.
                competitor = Path(dst)
                competitor.write_bytes(b"other process recording")
                claimed.append(competitor)
            return real_link(src, dst, *args, **kwargs)

        with patch.object(db.os, "link", side_effect=competing_link):
            archived = self.archive(source)

        self.assertNotEqual(archived, claimed[0])
        self.assertEqual(claimed[0].read_bytes(), b"other process recording")
        self.assertEqual(archived.read_bytes(), original)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(len(self.completed_files()), 2)
        self.assert_no_staging_files()

    def test_concurrent_copy_and_move_keep_every_distinct_recording(self):
        count = 8
        payloads = [bytes([i + 1]) * (65536 + i) for i in range(count)]
        sources = [self.source("incoming-%d.M4A" % i, payload) for i, payload in enumerate(payloads)]
        ready = threading.Barrier(count)

        def import_recording(index):
            ready.wait(timeout=15)
            return self.archive(sources[index], copy=(index % 2 == 0))

        with ThreadPoolExecutor(max_workers=count) as pool:
            jobs = [pool.submit(import_recording, i) for i in range(count)]
            archives = [job.result(timeout=20) for job in jobs]

        self.assertEqual(len(set(archives)), count)
        self.assertEqual(set(self.completed_files()), set(archives))
        for i, archived in enumerate(archives):
            self.assertEqual(archived.read_bytes(), payloads[i])
            if i % 2 == 0:
                self.assertEqual(sources[i].read_bytes(), payloads[i])
            else:
                self.assertFalse(sources[i].exists())
        self.assert_no_staging_files()


if __name__ == "__main__":
    unittest.main()
