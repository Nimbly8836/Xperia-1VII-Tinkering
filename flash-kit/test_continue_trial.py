import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import continue_trial as ct


class Tty(io.StringIO):
    def isatty(self):
        return True


class ContinueTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='continue-unit-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.name = 'fs72-trial-live-test'
        self.session = self.root / self.name
        self.session.mkdir(mode=0o700)
        (self.session / 'images').mkdir(mode=0o700)
        self.baseline = {'baseline_matches': True, 'observed': ct.trial.TRIAL_BASELINE,
                         'serial': 'TEST', 'battery_percent': 98,
                         'battery_observed_at': 1700000000, 'battery_observed_monotonic': 100.0}
        (self.session / 'baseline.json').write_text(json.dumps(self.baseline))
        (self.session / 'result.json').write_text(json.dumps(
            {'mode': 'blocked_at_read_only_probe', 'phone_write_requested': False, 'exit_code': 1}))
        (self.session / 'input-manifest.json').write_text('{}')
        (self.session / 'probe.log').write_text(
            'TRIAL_STOPPED completed_images=0 possible_device_write=no simulated_mutation=no; no retry\n')
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(ct.tempfile, 'gettempdir', return_value=str(self.root)))
        self.stack.enter_context(patch.object(ct.trial.time, 'time', return_value=1700000001))
        self.stack.enter_context(patch.object(ct.trial.time, 'monotonic', return_value=101.0))
        self.stack.enter_context(patch.object(ct.subprocess, 'Popen', side_effect=AssertionError('No real process/USB')))
        self.stack.enter_context(patch.object(ct.flashkit, 'adb_read', side_effect=AssertionError('No ADB')))

    def test_recent_read_only_session_accepted(self):
        session, baseline = ct.checked_session(self.name, 'TEST')
        self.assertEqual(session, self.session)
        self.assertEqual(baseline['battery_percent'], 98)

    def test_old_baseline_refused(self):
        with patch.object(ct.trial.time, 'time', return_value=1700000601), self.assertRaises(ct.flashkit.SafetyError):
            ct.checked_session(self.name, 'TEST')

    def test_recorded_battery_requires_explicit_acceptance(self):
        with patch.object(ct.trial.time, 'time', return_value=1700007200):
            with self.assertRaises(ct.flashkit.SafetyError):
                ct.checked_session(self.name, 'TEST')
            _, baseline = ct.checked_session(self.name, 'TEST', accept_recorded_battery=True)
            args = ct.battery_arguments(baseline, 'TEST', accept_recorded_battery=True)
        self.assertEqual(args, ['--android-battery', '98', '--battery-observed-at',
                                '1700000000', '--accept-recorded-battery'])
        self.assertEqual(json.loads((self.session / 'baseline.json').read_text()), self.baseline)

    def test_accepted_record_never_allows_wrong_identity_low_or_future_data(self):
        for changes in [{'serial': 'OTHER'}, {'battery_percent': 59}, {'battery_percent': 101},
                        {'battery_percent': True}, {'battery_observed_at': 0},
                        {'battery_observed_at': 1700000200}, {'battery_observed_monotonic': 200.0},
                        {'baseline_matches': False}]:
            with self.subTest(changes=changes), self.assertRaises(ct.flashkit.SafetyError):
                ct.battery_arguments(dict(self.baseline, **changes), 'TEST', accept_recorded_battery=True)

    def test_wrong_device_refused(self):
        with self.assertRaises(ct.flashkit.SafetyError):
            ct.checked_session(self.name, 'OTHER')

    def test_written_or_already_claimed_session_refused(self):
        for name in ['authorization.json', 'native.log', '.continue.lock', 'continue-probe.log']:
            path = self.session / name
            path.touch()
            with self.subTest(name=name), self.assertRaises(ct.flashkit.SafetyError):
                ct.checked_session(self.name, 'TEST')
            path.unlink()

    def test_mutating_probe_log_refused(self):
        with (self.session / 'probe.log').open('a') as output:
            output.write('TRIAL_COMMAND Write-TA:2:10100\n')
        with self.assertRaises(ct.flashkit.SafetyError):
            ct.checked_session(self.name, 'TEST')

    def test_symlink_evidence_refused(self):
        path = self.session / 'baseline.json'
        path.rename(self.root / 'outside.json')
        path.symlink_to(self.root / 'outside.json')
        with self.assertRaises(ct.flashkit.SafetyError):
            ct.checked_session(self.name, 'TEST')

    def run_fixture(self, probe_ok=True, confirmed=True, flash_code=0, accept_recorded_battery=False):
        calls = []
        def native(args, cwd, log):
            calls.append(args)
            suffix = ['--android-battery', '98', '--battery-observed-at', '1700000000']
            if accept_recorded_battery:
                suffix.append('--accept-recorded-battery')
            self.assertEqual(args[-len(suffix):], suffix)
            if args[0] == '--probe':
                log.write_text('TRIAL_PROBE_OK_NO_WRITES' if probe_ok else 'TRIAL_USB_REFUSED')
                return 0 if probe_ok else 1
            self.assertEqual(args[:3], ['--flash', 'TEST', ct.trial.PHRASE])
            log.write_text('TRIAL_COMPLETE_NO_REBOOT_FUNCTIONAL_RESULT_NOT_VERIFIED' if not flash_code else 'TRIAL_STOPPED')
            return flash_code
        with patch.object(ct.sys, 'stdin', Tty()), contextlib.redirect_stdout(Tty()), \
             patch.object(ct.trial, 'checked_build', return_value={'binary_sha256': 'mock'}), \
             patch.object(ct.trial, 'native', side_effect=native), \
             patch('builtins.input', return_value=ct.trial.PHRASE if confirmed else 'no'):
            code = ct.continue_trial(self.name, 'TEST', accept_recorded_battery=accept_recorded_battery)
        return code, calls

    def test_probe_failure_never_flashes(self):
        code, calls = self.run_fixture(probe_ok=False)
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 1)
        self.assertFalse((self.session / 'authorization.json').exists())

    def test_cancel_never_flashes(self):
        code, calls = self.run_fixture(confirmed=False)
        self.assertEqual(code, 2)
        self.assertEqual(len(calls), 1)
        self.assertFalse((self.session / 'native.log').exists())

    def test_mock_success_still_not_functional_success(self):
        code, calls = self.run_fixture()
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 2)
        result = json.loads((self.session / 'result.json').read_text())
        self.assertTrue(result['write_sequence_complete'])
        self.assertFalse(result['functional_goal_verified'])
        with self.assertRaises(ct.flashkit.SafetyError):
            ct.checked_session(self.name, 'TEST')

    def test_recorded_acceptance_is_logged_and_keeps_original_timestamp(self):
        with patch.object(ct.trial.time, 'time', return_value=1700007200):
            code, calls = self.run_fixture(accept_recorded_battery=True)
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 2)
        auth = json.loads((self.session / 'authorization.json').read_text())
        self.assertTrue(auth['recorded_battery_accepted'])
        self.assertEqual(auth['battery_observed_at'], 1700000000)
        self.assertEqual(auth['battery_percent'], 98)

    def test_partial_failure_never_retries(self):
        code, calls = self.run_fixture(flash_code=1)
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 2)
        with self.assertRaises(ct.flashkit.SafetyError):
            ct.checked_session(self.name, 'TEST')


if __name__ == '__main__':
    unittest.main()
