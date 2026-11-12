"""매일 자동 백업 정리: 날짜 사본만 30개로 세고, 다른 사본은 건드리지 않는다. 임시 폴더만 쓴다."""
import datetime, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import db


class BackupRotationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.backups = os.path.join(self.tmp.name, 'backups')
        os.makedirs(self.backups)
        for attr, value in [('DB_PATH', os.path.join(self.tmp.name, 'test.db')), ('BACKUP_DIR', self.backups)]:
            p = patch.object(db, attr, value); p.start(); self.addCleanup(p.stop)
        c = db.connect(); c.executescript(db.SCHEMA); c.commit(); c.close()
        self.today = datetime.date.today()

    def touch(self, name):
        Path(self.backups, name).write_bytes(b'x')

    def daily(self, days_ago):
        return 'seteuk-%s.db' % (self.today - datetime.timedelta(days=days_ago)).strftime('%Y%m%d')

    def names(self):
        return set(os.listdir(self.backups))

    def test_other_copies_do_not_push_out_daily_copies(self):
        for d in range(1, 30):                      # 어제부터 29일 전까지 29개 + 오늘 = 30개
            self.touch(self.daily(d))
        others = ['seteuk-manual-202611%02d-090000.db' % d for d in range(1, 29)]     # 수동 백업 28개
        others += ['seteuk-before-update-20261101-1000%02d.db' % i for i in range(8)]
        others += ['seteuk-before-restore-20261103-090000.db',
                   'seteuk-before-auto-update-20261104-090000.db', 'seteuk-before-app-update-20261105-090000.db']
        for name in others:
            self.touch(name)
        db.daily_backup()
        left = self.names()
        self.assertEqual(sum(1 for n in left if db._is_daily_backup(n)), 30)
        self.assertIn(self.daily(0), left)
        self.assertIn(self.daily(29), left)
        self.assertTrue(set(others) <= left)        # 한도 안의 다른 사본은 하나도 지우지 않는다

    def test_update_copies_keep_latest_ten(self):
        # 세 가지 '업데이트 전' 사본을 한 묶음으로 보고 시각순으로 최근 10개
        old = ['seteuk-before-update-20260901-1000%02d.db' % i for i in range(6)]
        old += ['seteuk-before-app-update-20260915-090000.db', 'seteuk-before-auto-update-20260920-090000.db']
        new = ['seteuk-before-auto-update-202610%02d-090000.db' % d for d in range(1, 8)]
        new += ['seteuk-before-update-20261020-090000.db', 'seteuk-before-app-update-20261101-090000.db',
                'seteuk-before-update-20261105-090000.db']
        for name in old + new:
            self.touch(name)
        db.daily_backup()
        left = self.names()
        self.assertTrue(set(new) <= left)
        self.assertFalse(set(old) & left)

    def test_restore_copies_are_counted_apart_from_update_copies(self):
        restores = ['seteuk-before-restore-202605%02d-090000.db' % d for d in range(1, 13)]   # 오래된 복원 전 12개
        updates = ['seteuk-before-update-202611%02d-090000.db' % d for d in range(1, 16)]     # 그 뒤 업데이트 15번
        for name in restores + updates:
            self.touch(name)
        db.daily_backup()
        left = self.names()
        self.assertEqual(sorted(n for n in left if 'before-restore' in n), restores[2:])
        self.assertEqual(sorted(n for n in left if 'before-update' in n), updates[5:])

    def test_manual_and_unknown_copies_are_never_pruned(self):
        keep = ['seteuk-manual-2026%02d01-090000.db' % m for m in range(1, 13)] * 1
        keep += ['seteuk-manual-202601%02d-090000.db' % d for d in range(2, 20)]
        keep += ['seteuk-before-store-only-20261101-090000.db', 'seteuk-before-update-1.10.30.db',
                 'before-store-only-1.10.30.db', 'seteuk-before-update-20261101-090000.db.bak']
        for name in keep:
            self.touch(name)
        db.daily_backup()
        self.assertTrue(set(keep) <= self.names())

    def test_auto_copy_name_rule(self):
        self.assertEqual(db._auto_copy('seteuk-before-update-20261112-101500.db'), ('update', '20261112-101500'))
        self.assertEqual(db._auto_copy('seteuk-before-app-update-20261112-101500.db'), ('update', '20261112-101500'))
        self.assertEqual(db._auto_copy('seteuk-before-auto-update-20261112-101500.db'), ('update', '20261112-101500'))
        self.assertEqual(db._auto_copy('seteuk-before-restore-20261112-101500.db'), ('restore', '20261112-101500'))
        for name in ('seteuk-manual-20261112-101500.db', 'seteuk-20261112.db', 'seteuk-before-update-20261112.db',
                     'seteuk-before-update-2026111a-101500.db', 'seteuk-before-update-20261112_101500.db',
                     'seteuk-before-update-20261112-101500.db-wal', 'x-before-update-20261112-101500.db', 'seteuk-.db'):
            self.assertIsNone(db._auto_copy(name), name)

    def test_keeps_only_latest_thirty_daily_copies(self):
        for d in range(1, 41):
            self.touch(self.daily(d))
        db.daily_backup()
        left = self.names()
        self.assertEqual(len(left), 30)
        self.assertIn(self.daily(0), left)
        self.assertIn(self.daily(29), left)
        self.assertNotIn(self.daily(30), left)
        self.assertNotIn(self.daily(40), left)

    def test_unrelated_files_are_left_alone(self):
        for d in range(1, 35):
            self.touch(self.daily(d))
        # (-wal 은 오늘 날짜를 피한다: 오늘 백업 파일의 보조 파일 이름이라 SQLite 가 스스로 치운다)
        keep = ['before-store-only-1.10.30.db', 'seteuk-20200101.db-wal', 'seteuk-2026111.db', '메모.txt']
        for name in keep:
            self.touch(name)
        db.daily_backup()
        self.assertTrue(set(keep) <= self.names())

    def test_new_day_gets_a_copy_while_running(self):
        db.daily_backup()
        tomorrow = self.today + datetime.timedelta(days=1)

        class Tomorrow(datetime.date):
            @classmethod
            def today(cls):
                return tomorrow

        with patch.object(db.datetime, 'date', Tomorrow):
            db.daily_backup()
        left = self.names()
        self.assertIn(self.daily(0), left)
        self.assertIn('seteuk-%s.db' % tomorrow.strftime('%Y%m%d'), left)

    def test_copy_is_complete_and_leaves_no_temp_file(self):
        Path(self.backups, self.daily(0) + '.tmp').write_bytes(b'half written')   # 지난번에 쓰다 만 것
        db.daily_backup()
        self.assertFalse([n for n in self.names() if n.endswith('.tmp')])
        import sqlite3
        c = sqlite3.connect(os.path.join(self.backups, self.daily(0)))
        try:
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertTrue(c.execute("SELECT 1 FROM sqlite_master WHERE name='students'").fetchone())
        finally:
            c.close()

    def test_loop_checks_again_and_survives_errors(self):
        calls = []

        def fake_backup():
            calls.append(1)
            if len(calls) == 1:
                raise OSError('디스크 가득')

        sleeps = []

        def fake_sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) > 3:
                raise SystemExit

        import time
        with patch.object(db, 'daily_backup', fake_backup), patch.object(time, 'sleep', fake_sleep), \
                patch('builtins.print'):
            with self.assertRaises(SystemExit):
                db._backup_loop()
        self.assertEqual(len(calls), 3)               # 첫 번째가 실패해도 계속 돈다
        self.assertEqual(sleeps[0], db.BACKUP_CHECK_SECONDS)

    def test_daily_name_rule(self):
        self.assertTrue(db._is_daily_backup('seteuk-20261112.db'))
        for name in ('seteuk-before-update-20261112-101500.db', 'seteuk-manual-20261112-101500.db',
                     'seteuk-20261112-101500.db', 'seteuk-.db', 'seteuk-2026111a.db', 'other-20261112.db'):
            self.assertFalse(db._is_daily_backup(name), name)


if __name__ == '__main__':
    unittest.main()
