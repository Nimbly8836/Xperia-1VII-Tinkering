import contextlib
import hashlib
import io
import json
import re
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import flashkit
import trial
import upgrade_preflight as upgrade


def probe_text(slot='yes'):
    return '\n'.join([
        'TRIAL_COMMAND getvar:has-slot:bootloader',
        'TRIAL_DEVICE has-slot:bootloader=' + slot,
        'TRIAL_COMMAND Read-TA:2:2127',
        'UPGRADE_BOOT_CONFIG_MATCH Read-TA:2:2127=yes',
        'TRIAL_COMMAND Read-TA:2:2301',
        'UPGRADE_BOOT_CONFIG_MATCH Read-TA:2:2301=yes',
        'UPGRADE_READONLY_PROBE_OK_NO_WRITES',
    ])


class UpgradePreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='upgrade-preflight-tests-')
        self.addCleanup(temporary.cleanup)
        self.session = Path(temporary.name)
        for guard in [patch.object(upgrade.subprocess, 'run', side_effect=AssertionError('No real ADB')),
                      patch.object(trial, 'native', side_effect=AssertionError('No real USB')),
                      patch.object(trial, 'checked_build', return_value={})]:
            guard.start()
            self.addCleanup(guard.stop)

    def baseline(self):
        return {'serial': 'TEST', 'baseline_matches': True, 'observed': dict(upgrade.BASELINE),
                'vbmeta_digest': upgrade.SOURCE_VBMETA_DIGEST, 'battery_percent': 80,
                'battery_observed_at': int(time.time()), 'battery_observed_monotonic': time.monotonic()}

    def test_reference_bytes_match_pinned_factory_ta(self):
        policy = (trial.ROOT / 'trial_policy.c.in').read_text()
        match = re.search(r'trial_boot_config_2127\[\] = \{(.*?)\};', policy, re.S)
        self.assertIsNotNone(match)
        if match is None:
            self.fail('Missing fixed TA comparison data')
        data = bytes(int(value, 16) for value in re.findall(r'0x([a-f0-9]{2})', match.group(1)))
        self.assertEqual(len(data), 82)
        self.assertEqual(hashlib.sha256(data).hexdigest(), 'e85b904b6a73da2b8d4726b5ff3ffd3b7813500d381ee6c362ec6e350caacb1a')
        self.assertIn('trial_boot_config_2301[] = {0}', policy)

    def test_source_baseline_is_the_cross_flashed_system_not_stock_fs72(self):
        self.assertEqual(upgrade.BASELINE['ro.product.model'], 'XQ-FS54')
        self.assertEqual(upgrade.BASELINE['ro.build.display.id'], '71.1.A.2.265 release-keys')
        self.assertEqual(trial.TRIAL_BASELINE['ro.product.model'], 'XQ-FS72')
        self.assertEqual(upgrade.BASELINE['ro.boot.hardware.sku'], 'c001526')

    def test_android_digest_checked_without_changing_phone(self):
        baseline = self.baseline()
        response = subprocess.CompletedProcess([], 0, upgrade.SOURCE_VBMETA_DIGEST + '\n', '')
        with patch.object(flashkit, 'preflight', return_value=baseline) as preflight, patch.object(upgrade.subprocess, 'run', return_value=response) as run:
            result = upgrade.android_baseline('TEST')
        preflight.assert_called_once_with('TEST', expected=upgrade.BASELINE)
        self.assertEqual(run.call_args.args[0], ['adb', '-s', 'TEST', 'shell', 'getprop', 'ro.boot.vbmeta.digest'])
        self.assertEqual(result['vbmeta_digest'], upgrade.SOURCE_VBMETA_DIGEST)

    def test_wrong_digest_low_battery_and_wrong_model_stop(self):
        with patch.object(flashkit, 'preflight', return_value={'baseline_matches': False}), self.assertRaises(flashkit.SafetyError):
            upgrade.android_baseline('TEST')
        with patch.object(flashkit, 'preflight', return_value=self.baseline()), patch.object(upgrade.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '0' * 64, '')), self.assertRaises(flashkit.SafetyError):
            upgrade.android_baseline('TEST')

    def test_probe_uses_only_the_upgrade_readonly_mode(self):
        def fake_native(arguments, cwd, log):
            self.assertEqual(arguments[:2], ['--upgrade-probe', 'TEST'])
            self.assertEqual(arguments[2:4], ['--android-battery', '80'])
            self.assertNotIn('--accept-recorded-battery', arguments)
            log.write_text(probe_text())
            return 0
        with patch.object(trial, 'native', side_effect=fake_native) as native:
            result = upgrade.probe_from_baseline(self.baseline(), self.session)
        native.assert_called_once()
        self.assertTrue(result['read_only_probe_complete'])
        self.assertFalse(result['phone_write_requested'])
        self.assertFalse(result['flash_allowed'])
        self.assertEqual(json.loads((self.session / 'result.json').read_text()), result)

    def test_stale_or_modified_baseline_never_starts_native(self):
        for key, value in [('observed', {}), ('vbmeta_digest', '0' * 64), ('battery_observed_at', int(time.time()) - 601), ('serial', '-invalid;serial')]:
            baseline = self.baseline()
            baseline[key] = value
            with self.subTest(key=key), self.assertRaises(flashkit.SafetyError):
                upgrade.probe_from_baseline(baseline, self.session)

    def test_slotted_and_nonslotted_are_observations_not_write_permission(self):
        for slot in ['yes', 'no']:
            result = upgrade.summarize(0, probe_text(slot))
            self.assertTrue(result['read_only_probe_complete'])
            self.assertEqual(result['bootloader_has_slot'], slot)
            self.assertFalse(result['flash_allowed'])

    def test_unknown_slot_mismatch_or_failed_exit_cannot_report_completion(self):
        for code, text in [(0, probe_text('unknown')), (1, probe_text()),
                           (0, probe_text().replace('Read-TA:2:2127=yes', 'Read-TA:2:2127=no')),
                           (0, probe_text() + '\nTRIAL_DEVICE has-slot:bootloader=yes')]:
            self.assertFalse(upgrade.summarize(code, text)['read_only_probe_complete'])

    def test_unexpected_commands_and_empty_logs_are_refused(self):
        for command in ['Write-TA:2:2127', 'flash:bootloader_a', 'erase:userdata', 'getvar:unknown', 'reboot']:
            with self.subTest(command=command), self.assertRaises(flashkit.SafetyError):
                upgrade.summarize(0, probe_text() + '\nTRIAL_COMMAND ' + command)
        with self.assertRaises(flashkit.SafetyError):
            upgrade.summarize(0, '')

    def test_simulation_never_selects_or_reads_a_phone(self):
        def fake_native(arguments, cwd, log):
            self.assertEqual(arguments, ['--upgrade-probe-simulate'])
            log.write_text(probe_text())
            return 0
        with patch.object(trial, 'new_session', return_value=self.session), patch.object(trial, 'native', side_effect=fake_native), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(upgrade.simulate(), 0)

    def test_no_noninteractive_run_or_write_flags(self):
        with patch.object(upgrade.sys, 'stdin', io.StringIO()), self.assertRaises(flashkit.SafetyError):
            upgrade.run()
        for args in [['run', '--force'], ['run', '--accept-recorded-battery'], ['flash']]:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                upgrade.main(args)


if __name__ == '__main__':
    unittest.main()
