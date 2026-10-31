import contextlib
import io
import subprocess
import unittest
from unittest.mock import patch

import switch_sim


class Tty(io.StringIO):
    def isatty(self):
        return True


class SwitchTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(switch_sim.subprocess, 'run', side_effect=AssertionError('No real ADB in tests'))
        self.mock_run = guard.start()
        self.addCleanup(guard.stop)
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def test_default_preview_does_not_invoke_adb(self):
        for mode in switch_sim.MODES:
            self.assertEqual(switch_sim.main([mode, '--serial', 'TEST']), 0)
        self.mock_run.assert_not_called()

    def test_exact_broadcast_and_no_slot_guess(self):
        for mode, number in switch_sim.MODES.items():
            self.assertEqual(switch_sim.broadcast_command('TEST', mode), [
                'adb', '-s', 'TEST', 'shell', 'am', 'broadcast', '--user', '0',
                '--receiver-foreground', '--receiver-permission',
                'android.permission.READ_PRIVILEGED_PHONE_STATE', '-a',
                switch_sim.ACTION, '-p', 'com.qti.phone', '--ei', switch_sim.EXTRA, str(number)])

    def test_serial_rejects_option_and_shell_injection(self):
        for serial in ['', '-d', 'x;reboot', 'x\ny', 'a b', 'x' * 101]:
            with self.subTest(serial=serial), self.assertRaises(switch_sim.SafetyError):
                switch_sim.broadcast_command(serial, 'esim')
        self.mock_run.assert_not_called()

    def test_noninteractive_execution_stops_before_adb(self):
        with patch.object(switch_sim.sys, 'stdin', io.StringIO()), self.assertRaises(switch_sim.SafetyError):
            switch_sim.main(['esim', '--serial', 'TEST', '--execute'])
        self.mock_run.assert_not_called()

    def run_confirmed_request(self, response, confirmation='SWITCH_TO_ESIM_MAPPING_CHECKED'):
        self.mock_run.side_effect = None
        self.mock_run.return_value = response
        with patch.object(switch_sim.sys, 'stdin', Tty()), patch.object(switch_sim, 'preflight'), patch('builtins.input', return_value=confirmation):
            return switch_sim.main(['esim', '--serial', 'TEST', '--execute'])

    def test_cancel_sends_nothing(self):
        with self.assertRaises(switch_sim.SafetyError):
            self.run_confirmed_request(None, 'NO')
        self.mock_run.assert_not_called()

    def test_confirmation_sends_once(self):
        self.assertEqual(self.run_confirmed_request(subprocess.CompletedProcess([], 0, 'Broadcast completed: result=0', '')), 0)
        self.mock_run.assert_called_once()

    def test_rejection_or_ambiguous_response_never_retries(self):
        for code, stdout, stderr in [(1, '', ''), (0, '', ''),
                                    (0, 'Broadcast completed:', 'SecurityException'),
                                    (0, 'Permission Denial', '')]:
            self.mock_run.reset_mock()
            with self.assertRaises(switch_sim.SafetyError):
                self.run_confirmed_request(subprocess.CompletedProcess([], code, stdout, stderr))
            self.mock_run.assert_called_once()

    def test_timeout_never_retries(self):
        self.mock_run.side_effect = subprocess.TimeoutExpired('adb', 30)
        with patch.object(switch_sim.sys, 'stdin', Tty()), patch.object(switch_sim, 'preflight'), patch('builtins.input', return_value='SWITCH_TO_ESIM_MAPPING_CHECKED'), self.assertRaises(subprocess.TimeoutExpired):
            switch_sim.main(['esim', '--serial', 'TEST', '--execute'])
        self.mock_run.assert_called_once()

    def test_preflight_checks_each_baseline_field_and_package(self):
        good = ['XQ-FS54', '71.1.A.2.265 release-keys', 'c001526', '1', 'green', 'dsds', 'package:/system/app/QtiTelephony.apk']
        for model in ['XQ-FS54', 'XQ-FS72']:
            with patch.object(switch_sim, 'adb_read', side_effect=[model, *good[1:]]):
                switch_sim.preflight('TEST')
        for index in range(len(good)):
            bad = list(good)
            bad[index] = 'unexpected'
            with patch.object(switch_sim, 'adb_read', side_effect=bad), self.assertRaises(switch_sim.SafetyError):
                switch_sim.preflight('TEST')

    def test_failed_preflight_never_sends_broadcast(self):
        with patch.object(switch_sim.sys, 'stdin', Tty()), patch.object(switch_sim, 'preflight', side_effect=switch_sim.SafetyError('mismatch')), self.assertRaises(switch_sim.SafetyError):
            switch_sim.main(['esim', '--serial', 'TEST', '--execute'])
        self.mock_run.assert_not_called()

    def test_adb_read_failure_stops(self):
        self.mock_run.side_effect = None
        self.mock_run.return_value = subprocess.CompletedProcess([], 1, '', 'device unauthorized')
        with self.assertRaises(switch_sim.SafetyError):
            switch_sim.adb_read('TEST', ['getprop', 'ro.product.model'])


if __name__ == '__main__':
    unittest.main()
