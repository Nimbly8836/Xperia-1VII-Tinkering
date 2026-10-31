"""Offline contract tests: only synthetic files and mocked device/process calls.

The tiny boot payload is intentionally not a real SIN/TAR: unwrap_bootloader's
contract here is pinned bytes, size and source stability, not TAR semantics.
No test opens firmware packages or pre-existing session/device logs.
"""
import contextlib
import copy
import gzip
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

import build_trial
import flashkit


def load_local(name):
    spec = importlib.util.spec_from_file_location(
        'upgrade_test_' + name, Path(__file__).with_name(name + '.py'))
    if spec is None or spec.loader is None:
        raise RuntimeError('Cannot load local test target: ' + name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Do not accidentally import an installed package named trial. Keep these local
# modules wired to the same shared core without replacing other tests' imports.
trial = load_local('trial')
with patch.dict(sys.modules, {'trial': trial}):
    upgrade = load_local('upgrade_trial')
    with patch.dict(sys.modules, {'upgrade_trial': upgrade}):
        builder = load_local('build_upgrade')


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Tty(io.StringIO):
    def isatty(self):
        return True


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.patched = {}
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(
            prefix='upgrade-offline-tests-')))
        # All process entry points fail closed unless a test explicitly installs
        # a fake. Native and legacy material paths have separate tripwires.
        for name in ('Popen', 'run', 'call', 'check_call', 'check_output'):
            self.mock(subprocess, name, side_effect=AssertionError('No subprocess/device access'))
        self.mock(os, 'system', side_effect=AssertionError('No shell access'))
        for obj, name in ((flashkit, 'adb_read'), (flashkit, 'preflight'),
                          (flashkit, 'verify'), (flashkit, 'source_snapshot'),
                          (trial, 'native'), (trial, 'checked_build'),
                          (trial, 'snapshot_images'), (upgrade.prepare_upgrade, 'verify'),
                          (upgrade.prepare_upgrade, 'prepare'),
                          (upgrade.upgrade_preflight, 'android_baseline')):
            self.mock(obj, name, side_effect=AssertionError('Unmocked device or firmware access: ' + name))
        self.mock(upgrade, 'ROOT', self.root)
        self.mock(upgrade, 'BUILD', self.root / 'build-upgrade')
        self.mock(upgrade, 'BINARY', upgrade.BUILD / 'fs54-265-to-35-v40')
        self.mock(upgrade, 'RECEIPT', upgrade.BUILD / 'build-receipt.json')
        self.mock(upgrade, 'RAW_BOOT', upgrade.BUILD / 'bootloader-uncompressed.sin')
        self.mock(upgrade.prepare_upgrade, 'DESTINATION', self.root / 'candidate-35')
        self.materials = upgrade.UpgradeMaterials()

    def mock(self, obj, name, *args, **kwargs):
        replacement = self.stack.enter_context(patch.object(obj, name, *args, **kwargs))
        self.patched[obj, name] = replacement
        return replacement

    def images(self):
        return [{'partition': p, 'name': p + '.sin', 'bytes': 7,
                     'sha256': upgrade.prepare_upgrade.BOOTLOADER_SHA256 if p == 'bootloader' else sha(p.encode()),
                     'sin_members': ['discard this source-only metadata']}
                for p in [*build_trial.ORDER, 'bootloader']]

    def receipt_fixture(self) -> dict[str, Any]:
        raw = b'synthetic boot TAR bytes'
        self.mock(upgrade, 'RAW_BOOT_BYTES', len(raw))
        self.mock(upgrade, 'RAW_BOOT_SHA256', sha(raw))
        for name in upgrade.INPUTS:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('fixture:' + name).encode())
        upgrade.RAW_BOOT.write_bytes(raw)
        upgrade.BINARY.write_bytes(b'not an executable')
        generated = upgrade.BUILD / 'upgrade-writer.c'
        generated.write_bytes(b'synthetic generated source')
        record = {'trial_plan': 'upgrade-35',
                      'source_zip_sha256': upgrade.prepare_upgrade.RELEASE['sha256'],
                      'confirmation': trial.UPGRADE_PHRASE,
                      'host_system': upgrade.platform.system(), 'host_machine': upgrade.platform.machine(),
                      'input_sha256': {n: sha((self.root / n).read_bytes()) for n in upgrade.INPUTS},
                      'generated_sha256': sha(generated.read_bytes()),
                      'binary_sha256': sha(upgrade.BINARY.read_bytes())}
        self.save_receipt(record)
        return record

    def save_receipt(self, record):
        upgrade.RECEIPT.write_text(json.dumps(record))

    def gzip_fixture(self, encoded=None):
        raw = b'small synthetic bootloader payload'
        encoded = gzip.compress(raw, mtime=0) if encoded is None else encoded
        path = self.root / 'boot.gz'
        path.write_bytes(encoded)
        self.mock(upgrade.prepare_upgrade, 'BOOTLOADER_SHA256', sha(encoded))
        self.mock(upgrade, 'RAW_BOOT_BYTES', len(raw))
        self.mock(upgrade, 'RAW_BOOT_SHA256', sha(raw))
        return path, raw


class MaterialTests(OfflineTests):
    def test_valid_receipt_uses_only_temporary_upgrade_inputs(self):
        record = self.receipt_fixture()
        stable_hash = upgrade.bundle_runtime.stable_hash
        visited = []

        def confined_hash(path, *args):
            self.assertTrue(path.is_relative_to(self.root))
            visited.append(path)
            return stable_hash(path, *args)

        with patch.object(upgrade.bundle_runtime, 'stable_hash', side_effect=confined_hash):
            self.assertEqual(self.materials.checked_build(), record)
        self.assertEqual(set(visited), {self.root / n for n in upgrade.INPUTS} |
                         {upgrade.BINARY, upgrade.BUILD / 'upgrade-writer.c', upgrade.RAW_BOOT})
        self.patched[flashkit, 'verify'].assert_not_called()
        self.patched[flashkit, 'source_snapshot'].assert_not_called()

    def test_receipt_identity_and_input_set_rejected(self):
        record = self.receipt_fixture()
        for key, value in [('trial_plan', 'crossflash-265'), ('trial_plan', None),
                           ('source_zip_sha256', flashkit.SOURCE_SHA256),
                           ('confirmation', trial.PHRASE), ('host_system', 'wrong OS'),
                           ('host_machine', 'wrong CPU'), ('input_sha256', None),
                           ('input_sha256', {}),
                           ('input_sha256', dict(record['input_sha256'], unexpected='0'))]:
            with self.subTest(key=key, value=value):
                self.save_receipt(dict(record, **{key: value}))
                with self.assertRaises(flashkit.SafetyError):
                    self.materials.checked_build()
        for malformed in ([], None, 'old receipt'):
            with self.subTest(malformed=malformed):
                self.save_receipt(malformed)
                with self.assertRaises(flashkit.SafetyError):
                    self.materials.checked_build()
        missing = copy.deepcopy(record)
        missing['input_sha256'].pop('trial.py')
        self.save_receipt(missing)
        with self.assertRaises(flashkit.SafetyError):
            self.materials.checked_build()

    def test_each_source_generated_and_binary_tamper_rejected(self):
        self.receipt_fixture()
        paths = [self.root / n for n in sorted(upgrade.INPUTS)] + [
            upgrade.BINARY, upgrade.BUILD / 'upgrade-writer.c']
        for path in paths:
            with self.subTest(path=path.relative_to(self.root)):
                before = path.read_bytes()
                try:
                    path.write_bytes(before + b'tamper')
                    with self.assertRaises(flashkit.SafetyError):
                        self.materials.checked_build()
                finally:
                    path.write_bytes(before)

    def test_raw_boot_fixed_hash_is_independent_of_receipt_hash(self):
        record = self.receipt_fixture()
        upgrade.RAW_BOOT.write_bytes(b'X' * upgrade.RAW_BOOT_BYTES)
        record['input_sha256']['build-upgrade/bootloader-uncompressed.sin'] = sha(upgrade.RAW_BOOT.read_bytes())
        self.save_receipt(record)
        with self.assertRaisesRegex(flashkit.SafetyError, 'TAR mismatch'):
            self.materials.checked_build()

    def test_symlink_input_rejected_even_when_bytes_match(self):
        self.receipt_fixture()
        path = self.root / 'trial.py'
        target = self.root / 'same-bytes'
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
        with self.assertRaises((OSError, flashkit.SafetyError)):
            self.materials.checked_build()

    def test_normalization_changes_only_last_record_and_does_not_mutate(self):
        original = self.images()
        before = copy.deepcopy(original)
        normalized = upgrade.normalized_images(original)
        self.assertEqual(original, before)
        self.assertEqual(normalized[:-1], [{k: v for k, v in item.items() if k != 'sin_members'}
                                          for item in original[:-1]])
        self.assertEqual(normalized[-1], {'partition': 'bootloader', 'name': 'bootloader.sin',
            'bytes': 14085120, 'sha256': 'bff3c1cae37e77aa69be689ecba02b772e282e02edcc476003b859a1bf9c67a8'})

    def test_normalization_requires_15_and_original_gzip_last(self):
        original = self.images()
        for records in (original[:-1], original + [original[-1]],
                        list(reversed(original)),
                        original[:-1] + [dict(original[-1], sha256=upgrade.RAW_BOOT_SHA256)]):
            with self.subTest(records=records), self.assertRaises(flashkit.SafetyError):
                upgrade.normalized_images(records)

    def snapshot_fixture(self):
        original = self.images()
        record = {'images': upgrade.normalized_images(original)}
        self.mock(self.materials, 'checked_build', return_value=record)
        verify = self.mock(upgrade.prepare_upgrade, 'verify', return_value=original)
        self.mock(upgrade.platform, 'system', return_value='Linux')
        self.mock(upgrade.shutil, 'disk_usage', return_value=SimpleNamespace(free=10**12))
        copier = self.mock(trial, 'copy_image_snapshot')
        return record, verify, copier

    def test_snapshot_reverifies_then_copies_only_upgrade_sources(self):
        record, verify, copier = self.snapshot_fixture()
        events = []
        verify.side_effect = lambda: events.append('verify') or self.images()
        copier.side_effect = lambda *args: events.append('copy')
        destination = self.materials.snapshot_images(self.root)
        self.assertEqual(events, ['verify'] + ['copy'] * 15)
        self.assertEqual(destination, self.root / 'images')
        for call, item in zip(copier.call_args_list, record['images'], strict=True):
            source = upgrade.RAW_BOOT if item['partition'] == 'bootloader' else (
                upgrade.prepare_upgrade.DESTINATION / 'images' / item['name'])
            self.assertEqual(call.args, (source, destination / item['name'], item))
        manifest = json.loads((self.root / 'input-manifest.json').read_text())
        self.assertEqual(manifest, {'trial_plan': 'upgrade-35', 'images': record['images']})
        self.patched[flashkit, 'verify'].assert_not_called()
        trial.snapshot_images.assert_not_called()

    def test_snapshot_manifest_tampering_prevents_any_copy(self):
        record, verify, copier = self.snapshot_fixture()
        good = copy.deepcopy(record['images'])
        for key, value in [('name', 'other.sin'), ('partition', 'userdata'),
                           ('bytes', 1), ('sha256', '0' * 64)]:
            with self.subTest(key=key):
                record['images'] = copy.deepcopy(good)
                record['images'][0][key] = value
                with self.assertRaises(flashkit.SafetyError):
                    self.materials.snapshot_images(self.root)
                copier.assert_not_called()
                self.assertFalse((self.root / 'images').exists())
        self.assertEqual(verify.call_count, 4)

    def test_snapshot_verify_failure_or_low_space_prevents_copy(self):
        _, verify, copier = self.snapshot_fixture()
        verify.side_effect = flashkit.SafetyError('source changed')
        with self.assertRaises(flashkit.SafetyError):
            self.materials.snapshot_images(self.root)
        verify.side_effect = None
        with patch.object(upgrade.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)), self.assertRaises(flashkit.SafetyError):
            self.materials.snapshot_images(self.root)
        copier.assert_not_called()
        self.assertFalse((self.root / 'images').exists())

    def test_android_baseline_delegates_and_requires_slot_a(self):
        baseline = {'baseline_matches': True, 'battery_percent': 100}
        checked = self.mock(upgrade.upgrade_preflight, 'android_baseline', return_value=baseline)
        for code, stdout in [(0, '_a\n'), (0, '_b'), (0, 'a'), (0, ''), (1, '_a')]:
            with self.subTest(code=code, stdout=stdout), patch.object(subprocess, 'run', return_value=SimpleNamespace(
                    returncode=code, stdout=stdout)) as adb:
                if code == 0 and stdout == '_a\n':
                    self.assertIs(self.materials.android_baseline('TEST'), baseline)
                else:
                    with self.assertRaises(flashkit.SafetyError):
                        self.materials.android_baseline('TEST')
                adb.assert_called_once_with(['adb', '-s', 'TEST', 'shell', 'getprop',
                    'ro.boot.slot_suffix'], capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(checked.call_count, 5)

    def test_android_baseline_failure_does_not_read_slot(self):
        self.mock(upgrade.upgrade_preflight, 'android_baseline', side_effect=flashkit.SafetyError('baseline'))
        with self.assertRaises(flashkit.SafetyError):
            self.materials.android_baseline('TEST')
        self.patched[subprocess, 'run'].assert_not_called()

    def test_native_rechecks_and_selects_dedicated_binary(self):
        checked = self.mock(self.materials, 'checked_build', return_value={})
        invoke = self.mock(trial, 'native', return_value=9)
        args, log = ['--probe', 'TEST'], self.root / 'synthetic.log'
        self.assertEqual(self.materials.native(args, self.root, log), 9)
        invoke.assert_called_once_with(args, self.root, log, binary=upgrade.BINARY)
        checked.assert_called_once_with()
        checked.side_effect = flashkit.SafetyError('tamper')
        with self.assertRaises(flashkit.SafetyError):
            self.materials.native(args, self.root, log)
        self.assertEqual(invoke.call_count, 1)


class UnwrapTests(OfflineTests):
    def test_valid_synthetic_gzip_and_nofollow_flags(self):
        path, raw = self.gzip_fixture()
        real_open = os.open
        with patch.object(os, 'open', wraps=real_open) as opened:
            self.assertEqual(upgrade.unwrap_bootloader(path), raw)
        flags = opened.call_args.args[1]
        self.assertTrue(flags & os.O_NOFOLLOW)
        self.assertTrue(flags & os.O_NONBLOCK)

    def test_original_gzip_hash_rejected_before_decode(self):
        path, _ = self.gzip_fixture()
        path.write_bytes(b'not the pinned gzip')
        with patch.object(gzip, 'GzipFile', side_effect=AssertionError('must not decode')), self.assertRaisesRegex(flashkit.SafetyError, 'GZIP hash mismatch'):
            upgrade.unwrap_bootloader(path)

    def test_bad_gzip_and_truncated_gzip_rejected_even_with_matching_outer_hash(self):
        for data in (b'not gzip', gzip.compress(b'small', mtime=0)[:-5]):
            with self.subTest(data=data):
                path, _ = self.gzip_fixture(data)
                with self.assertRaises((OSError, EOFError, flashkit.SafetyError)):
                    upgrade.unwrap_bootloader(path)

    def test_raw_hash_and_short_or_oversize_raw_rejected(self):
        path, raw = self.gzip_fixture()
        for size, digest in [(len(raw), '0' * 64), (len(raw) - 1, sha(raw)),
                             (len(raw) + 1, sha(raw))]:
            with self.subTest(size=size, digest=digest), patch.object(upgrade, 'RAW_BOOT_BYTES', size), patch.object(
                    upgrade, 'RAW_BOOT_SHA256', digest), self.assertRaisesRegex(flashkit.SafetyError, 'TAR differs'):
                upgrade.unwrap_bootloader(path)

    def test_symlink_and_nonregular_source_rejected(self):
        path, _ = self.gzip_fixture()
        link = self.root / 'link.gz'
        link.symlink_to(path)
        with self.assertRaises(OSError):
            upgrade.unwrap_bootloader(link)
        fifo = self.root / 'fifo'
        os.mkfifo(fifo)
        with self.assertRaisesRegex(flashkit.SafetyError, 'regular file'):
            upgrade.unwrap_bootloader(fifo)

    def test_source_replacement_during_read_rejected(self):
        path, _ = self.gzip_fixture()
        original_hash = flashkit.sha256_stream

        def replace_after_hash(stream):
            result = original_hash(stream)
            replacement = self.root / 'replacement.gz'
            replacement.write_bytes(path.read_bytes())
            replacement.replace(path)
            return result

        with patch.object(flashkit, 'sha256_stream', side_effect=replace_after_hash), self.assertRaises(flashkit.SafetyError):
            upgrade.unwrap_bootloader(path)


class BuildTests(OfflineTests):
    def test_build_rejects_nonfixed_full_order_before_unwrap_or_compile(self):
        upgrade.prepare_upgrade.DESTINATION.mkdir()
        self.mock(builder.platform, 'system', return_value='Linux')
        unwrap = self.mock(upgrade, 'unwrap_bootloader', side_effect=AssertionError('too late'))
        original = self.images()
        for records in ([original[1], original[0], *original[2:]],
                        [original[0], original[0], *original[2:]],
                        [dict(original[0], partition='userdata'), *original[1:]]):
            with self.subTest(partitions=[r['partition'] for r in records]), patch.object(
                    upgrade.prepare_upgrade, 'verify', return_value=records), self.assertRaisesRegex(flashkit.SafetyError, 'Upgrade order'):
                builder.build()
        unwrap.assert_not_called()
        self.patched[subprocess, 'run'].assert_not_called()
        self.assertFalse(upgrade.BUILD.exists())


class RunTests(OfflineTests):
    def run_fixture(self, *, plan: str | None = 'upgrade-35',
                    receipt_plan: str | None = 'upgrade-35',
                    confirmation=None, probe_code=0, probe_marker=True,
                    write_code=0, write_marker=True, baseline_matches=True):
        # shared-core flow only: fake native writes solely into this temp session.
        self.mock(trial.sys, 'stdin', Tty())
        self.stack.enter_context(contextlib.redirect_stdout(Tty()))
        self.mock(trial, 'new_session', return_value=self.root)
        self.mock(trial.time, 'time_ns', return_value=1700000000_000000000)
        self.mock(trial.time, 'time', return_value=1700000001)
        self.mock(trial.time, 'monotonic', return_value=101.0)
        self.provider = Mock(spec=upgrade.UpgradeMaterials)
        receipt = {'binary_sha256': 'synthetic binary', 'source_zip_sha256': 'synthetic .35 source'}
        if receipt_plan is not None:
            receipt['trial_plan'] = receipt_plan
        self.provider.checked_build.return_value = receipt
        self.provider.snapshot_images.return_value = self.root / 'images'
        self.provider.android_baseline.return_value = {
            'baseline_matches': baseline_matches, 'battery_percent': 100}
        self.calls = []

        def fake_native(arguments, cwd, log):
            self.assertTrue(log.is_relative_to(self.root))
            self.assertEqual(arguments[-4:], ['--android-battery', '100', '--battery-observed-at', '1700000000'])
            self.calls.append(arguments[:-4])
            if arguments[0] == '--probe':
                self.assertEqual(cwd, self.root / 'probe')
                log.write_text('TRIAL_PROBE_OK_NO_WRITES' if probe_marker else 'probe failed')
                return probe_code
            self.assertEqual(arguments[:3], ['--flash', 'TEST', trial.UPGRADE_PHRASE])
            self.assertEqual(cwd, self.root / 'images')
            log.write_text('TRIAL_COMPLETE_NO_REBOOT_FUNCTIONAL_RESULT_NOT_VERIFIED' if write_marker else 'TRIAL_STOPPED')
            return write_code

        self.provider.native.side_effect = fake_native
        self.mock_input = self.stack.enter_context(patch('builtins.input', side_effect=[
            '', trial.UPGRADE_PHRASE if confirmation is None else confirmation]))
        kwargs = {} if plan is None else {'plan': plan}
        return trial.run('TEST', materials=self.provider, **kwargs)

    def assert_no_flash(self):
        self.assertFalse(any(c[0] == '--flash' for c in self.calls))
        self.assertFalse((self.root / 'authorization.json').exists())

    def test_upgrade_cancellation_never_flashes(self):
        self.assertEqual(self.run_fixture(confirmation='NO'), 2)
        self.assertEqual(self.calls, [['--probe', 'TEST']])
        self.assert_no_flash()

    def test_old_confirmation_cannot_authorize_upgrade(self):
        self.assertNotEqual(trial.PHRASE, trial.UPGRADE_PHRASE)
        self.assertEqual(self.run_fixture(confirmation=trial.PHRASE), 2)
        self.assert_no_flash()
        self.assertIn(trial.UPGRADE_PHRASE, self.mock_input.call_args.args[0])

    def test_failed_probe_never_flashes_even_with_success_marker(self):
        self.assertNotEqual(self.run_fixture(probe_code=1), 0)
        self.assert_no_flash()

    def test_probe_zero_without_marker_never_flashes(self):
        self.assertNotEqual(self.run_fixture(probe_marker=False), 0)
        self.assert_no_flash()

    def test_write_failure_is_not_retried(self):
        self.assertEqual(self.run_fixture(write_code=7, write_marker=False), 7)
        self.assertEqual(self.calls, [['--probe', 'TEST'], ['--flash', 'TEST', trial.UPGRADE_PHRASE]])
        report = json.loads((self.root / 'result.json').read_text())
        self.assertFalse(report['write_sequence_complete'])
        self.assertFalse(report['automatic_reboot'])
        self.assertFalse(report['functional_goal_verified'])

    def test_zero_write_without_completion_marker_fails_without_retry(self):
        self.assertEqual(self.run_fixture(write_marker=False), 2)
        self.assertEqual(len(self.calls), 2)

    def test_upgrade_success_uses_provider_baseline_and_separate_authorization(self):
        self.assertEqual(self.run_fixture(), 0)
        self.provider.android_baseline.assert_called_once_with('TEST')
        self.assertEqual(self.provider.checked_build.call_count, 3)
        self.patched[flashkit, 'preflight'].assert_not_called()
        trial.checked_build.assert_not_called()
        trial.snapshot_images.assert_not_called()
        trial.native.assert_not_called()
        authorization = json.loads((self.root / 'authorization.json').read_text())
        self.assertEqual(authorization['typed_confirmation'], trial.UPGRADE_PHRASE)
        self.assertEqual(authorization['trial_plan'], 'upgrade-35')
        self.assertTrue(authorization['bootloader_update'])
        report = json.loads((self.root / 'result.json').read_text())
        self.assertEqual(report['source_zip_sha256'], 'synthetic .35 source')
        self.assertTrue(report['write_sequence_complete'])
        self.assertFalse(report['functional_goal_verified'])

    def test_bad_upgrade_baseline_stops_before_probe(self):
        with self.assertRaises(flashkit.SafetyError):
            self.run_fixture(baseline_matches=False)
        self.assertEqual(self.calls, [])
        self.assert_no_flash()

    def test_old_receipt_cannot_be_used_for_upgrade(self):
        for receipt_plan in (None, 'crossflash-265', 'unknown'):
            with self.subTest(receipt_plan=receipt_plan):
                with self.assertRaisesRegex(flashkit.SafetyError, 'different flashing plan'):
                    self.run_fixture(receipt_plan=receipt_plan)
                self.provider.snapshot_images.assert_not_called()
                self.provider.android_baseline.assert_not_called()
                self.provider.native.assert_not_called()

    def test_default_and_explicit_old_plan_reject_upgrade_receipt(self):
        for plan in (None, 'crossflash-265'):
            with self.subTest(plan=plan):
                with self.assertRaisesRegex(flashkit.SafetyError, 'different flashing plan'):
                    self.run_fixture(plan=plan)
                self.provider.snapshot_images.assert_not_called()
                self.provider.native.assert_not_called()

    def test_upgrade_requires_materials_and_unknown_plan_is_rejected(self):
        self.mock(trial.sys, 'stdin', Tty())
        with contextlib.redirect_stdout(Tty()):
            for plan in ('upgrade-35', 'arbitrary'):
                with self.subTest(plan=plan), self.assertRaises(flashkit.SafetyError):
                    trial.run('TEST', plan=plan)
        trial.checked_build.assert_not_called()
        trial.native.assert_not_called()

    def test_new_confirmation_cannot_authorize_old_plan(self):
        # Reuse the shared-core fixture only up to confirmation, not legacy
        # firmware preparation. Any accidental write fails its upgrade-only spy.
        self.mock(flashkit, 'preflight', return_value={'baseline_matches': True, 'battery_percent': 100})
        self.assertEqual(self.run_fixture(plan=None, receipt_plan=None,
                                         confirmation=trial.UPGRADE_PHRASE), 2)
        self.provider.android_baseline.assert_not_called()
        self.patched[flashkit, 'preflight'].assert_called_once_with('TEST', expected=trial.TRIAL_BASELINE)
        self.assertIn(trial.PHRASE, self.mock_input.call_args.args[0])
        self.assert_no_flash()


if __name__ == '__main__':
    unittest.main()
