"""Subscription regressions; no user database or network access."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import plus


class StatusTests(unittest.TestCase):
    def settings(self, active='1', cache=None):
        return {'plus_token': 'test-token', 'plus_active': active,
                'plus_status': json.dumps(cache if cache is not None else {'sub': {'active': True}})}

    def test_confirmed_expiry_does_not_reactivate_cached_subscription(self):
        before, after = self.settings(), self.settings('0')
        with patch.object(plus.db, 'get_settings', side_effect=[before, after]), patch.object(plus, '_call', side_effect=plus.PlusError('expired', expired=True)):
            result = plus.status()
        self.assertFalse(result['sub']['active'])
        self.assertIn('error', result)
        self.assertNotIn('offline', result)

    def test_offline_keeps_last_known_state(self):
        with patch.object(plus.db, 'get_settings', return_value=self.settings()), patch.object(plus, '_call', side_effect=plus.PlusError('offline')):
            result = plus.status()
        self.assertTrue(result['sub']['active'])
        self.assertEqual(result['offline'], 'offline')

    def test_logged_out_does_not_return_cached_account(self):
        with patch.object(plus.db, 'get_settings', return_value=self.settings()), patch.object(plus, '_call', side_effect=plus.PlusError('revoked', logged_out=True)):
            self.assertFalse(plus.status()['loggedIn'])

    def test_cached_expired_state_is_inactive(self):
        with patch.object(plus.db, 'get_settings', return_value=self.settings('0')):
            self.assertFalse(plus.status(False)['sub']['active'])

    def test_corrupt_cache_does_not_crash_settings(self):
        for raw in ('{broken', '[]', 'null'):
            settings = self.settings(); settings['plus_status'] = raw
            with self.subTest(raw=raw), patch.object(plus.db, 'get_settings', return_value=settings):
                self.assertEqual(plus.status(False), {'loggedIn': True})

    def test_timeout_is_a_user_facing_error(self):
        with patch.object(plus.urllib.request, 'urlopen', side_effect=TimeoutError), patch('telemetry.install_id', return_value='test'):
            with self.assertRaises(plus.PlusError):
                plus._call('status')


    def test_empty_explicit_settings_do_not_load_another_account(self):
        with patch.object(plus.db, 'get_settings', side_effect=AssertionError('unexpected read')):
            self.assertFalse(plus.active({}))

    def test_bad_or_future_timestamp_refreshes_instead_of_crashing(self):
        for stamp in ('broken', '999999999999', None):
            with self.subTest(stamp=stamp), patch.object(plus.db, 'get_settings', return_value={'plus_token': 'test', 'plus_checked': stamp}), patch.object(plus, 'status') as refresh:
                plus.refresh_if_stale()
                refresh.assert_called_once_with(True)

    def test_concurrent_refresh_is_coalesced(self):
        import threading
        started, finish = threading.Event(), threading.Event()
        def refresh(_):
            started.set()
            self.assertTrue(finish.wait(2))
        with patch.object(plus.db, 'get_settings', return_value={'plus_token': 'test'}), patch.object(plus, 'status', side_effect=refresh) as request:
            worker = threading.Thread(target=plus.refresh_if_stale)
            worker.start()
            try:
                self.assertTrue(started.wait(2))
                plus.refresh_if_stale()
            finally:
                finish.set(); worker.join(2)
            self.assertEqual(request.call_count, 1)


if __name__ == '__main__':
    unittest.main()
