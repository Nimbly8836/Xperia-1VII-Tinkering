"""Prebuilt package tests use tiny fake images/writer; never access a phone."""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_bundle
import bundle_runtime
import flashkit
import trial


class Tty(io.StringIO):
    def isatty(self):
        return True


class BundleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='bundle-unit-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / 'release'
        self.root.mkdir()
        self.candidate = self.base / 'candidate'
        (self.candidate / 'images').mkdir(parents=True)
        self.writer = self.base / 'fixture-writer'
        self.writer.write_text('#!/bin/sh\n[ "$1" = "--self-test" ] || exit 99\necho TRIAL_GUARD_SELF_TEST_OK_NO_USB\n')
        self.writer.chmod(0o755)
        images = []
        for partition in flashkit.CANDIDATE_PARTITIONS:
            name = partition + flashkit.SUFFIX
            content = ('synthetic:' + partition).encode()
            (self.candidate / 'images' / name).write_bytes(content)
            images.append({'partition': partition, 'name': name, 'bytes': len(content),
                           'sha256': hashlib.sha256(content).hexdigest()})
        receipt = {'input_sha256': {name: flashkit.sha256_file(build_bundle.ROOT / name)
                                   for name in ['trial.py', 'flashkit.py']},
                   'binary_sha256': flashkit.sha256_file(self.writer)}
        self.host = build_bundle.host_settings()
        # No host clone subprocess is needed for tiny test fixtures.
        def copy_fixture(source, target, expected):
            data = source.read_bytes()
            if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
                raise flashkit.SafetyError('fixture mismatch')
            target.write_bytes(data)
        self.copy = patch.object(trial, 'copy_image_snapshot', side_effect=copy_fixture)
        self.copy.start()
        self.addCleanup(self.copy.stop)
        with patch.object(trial, 'BINARY', self.writer), patch.object(flashkit, 'CANDIDATE', self.candidate):
            self.pin = build_bundle.assemble(self.root, 'fixture', 'v1', self.host, receipt, {'images': images})
        self.bundle = bundle_runtime.PrebuiltBundle(self.root, self.pin)

    def repin(self, change):
        path = self.root / 'manifest.json'
        manifest = json.loads(path.read_text())
        change(manifest)
        raw = json.dumps(manifest).encode()
        path.write_bytes(raw)
        # Test structural validation after a digest check, not a CLI bypass.
        return bundle_runtime.PrebuiltBundle(self.root, hashlib.sha256(raw).hexdigest())

    def test_package_checks_do_not_need_original_zip_or_source_receipt(self):
        with patch.object(flashkit, 'verify', side_effect=AssertionError('No original ZIP')), patch.object(trial, 'checked_build', side_effect=AssertionError('No source build receipt')):
            result = self.bundle.verify()
        self.assertEqual(len(result['images']), 14)
        self.assertEqual(result['binary_sha256'], flashkit.sha256_file(self.writer))
        self.assertFalse((self.root / 'build').exists())
        self.assertFalse((self.root / 'firmware-downloads').exists())

    def test_image_tamper_cannot_be_hidden_by_editing_manifest(self):
        relative = 'images/boot' + flashkit.SUFFIX
        image = self.root / relative
        image.chmod(0o600)
        image.write_bytes(b'bad')
        with self.assertRaises(flashkit.SafetyError):
            self.bundle.verify()
        self.repin(lambda m: m['files'][relative].update(bytes=3, sha256=hashlib.sha256(b'bad').hexdigest()))
        with self.assertRaisesRegex(flashkit.SafetyError, 'manifest changed'):
            self.bundle.checked_build()

    def test_runtime_and_binary_tampering_are_rejected(self):
        for relative in ['app/trial.py', 'bin/fs72-preserve-trial']:
            with self.subTest(file=relative):
                path = self.root / relative
                old = path.read_bytes()
                path.write_bytes(b'X' + old[1:])
                with self.assertRaises(flashkit.SafetyError):
                    self.bundle.checked_build()
                path.write_bytes(old)

    def test_symlink_and_unexpected_file_are_rejected(self):
        extra = self.root / 'userdata.sin'
        extra.write_text('not allowed')
        with self.assertRaises(flashkit.SafetyError):
            self.bundle.checked_build()
        extra.unlink()
        image = self.root / 'images' / ('boot' + flashkit.SUFFIX)
        image.unlink()
        image.symlink_to(self.writer)
        with self.assertRaises(flashkit.SafetyError):
            self.bundle.checked_build()

    def test_symlink_directory_is_rejected(self):
        (self.root / 'images').rename(self.base / 'elsewhere')
        (self.root / 'images').symlink_to(self.base / 'elsewhere', target_is_directory=True)
        with self.assertRaises(flashkit.SafetyError):
            self.bundle.checked_build()

    def test_finder_metadata_is_harmless(self):
        (self.root / '.DS_Store').write_bytes(b'finder data')
        self.bundle.checked_build()

    def test_wrong_host_or_baseline_is_rejected(self):
        changes = [lambda m: m['host'].update(machine='wrong'),
                   lambda m: m['host'].update(system='Windows'),
                   lambda m: m['baseline'].update({'ro.product.model': 'XQ-FS54'}),
                   lambda m: m.update(source_zip_sha256='0' * 64),
                   lambda m: m.update(profile='fs54-35'),
                   lambda m: m.update(schema=True)]
        original = (self.root / 'manifest.json').read_bytes()
        for change in changes:
            (self.root / 'manifest.json').write_bytes(original)
            with self.assertRaises(flashkit.SafetyError):
                self.repin(change).checked_build()

    def test_duplicate_images_and_path_traversal_are_rejected(self):
        original = (self.root / 'manifest.json').read_bytes()
        for change in [lambda m: m['images'].__setitem__(1, m['images'][0]),
                       lambda m: m['images'][0].update(name='../boot.sin'),
                       lambda m: m['files'].update({'../outside': {'bytes': 1, 'sha256': '0' * 64}}),
                       lambda m: m['files']['app/trial.py'].update(bytes=True)]:
            (self.root / 'manifest.json').write_bytes(original)
            with self.assertRaises(flashkit.SafetyError):
                self.repin(change).checked_build()

    def test_invalid_manifest_json_is_rejected(self):
        raw = b'{bad'
        (self.root / 'manifest.json').write_bytes(raw)
        bundle = bundle_runtime.PrebuiltBundle(self.root, hashlib.sha256(raw).hexdigest())
        with self.assertRaises(flashkit.SafetyError):
            bundle.checked_build()

    def test_snapshot_has_only_independent_images(self):
        session = self.base / 'session'
        session.mkdir()
        with patch.object(flashkit, 'verify', side_effect=AssertionError('No source ZIP')):
            images = self.bundle.snapshot_images(session)
        self.assertEqual(len(list(images.iterdir())), 14)
        self.assertNotEqual((images / ('boot' + flashkit.SUFFIX)).stat().st_ino,
                            (self.root / 'images' / ('boot' + flashkit.SUFFIX)).stat().st_ino)

    def test_materials_flow_retains_probe_confirmation_and_failure_stop(self):
        session = self.base / 'live'
        session.mkdir()
        calls = []
        def fake_native(arguments, cwd, log):
            calls.append(arguments)
            if arguments[0] == '--probe':
                log.write_text('TRIAL_PROBE_OK_NO_WRITES')
                return 0
            self.assertEqual(arguments[:3], ['--flash', 'TEST', trial.PHRASE])
            log.write_text('TRIAL_STOPPED')
            return 1
        with contextlib.redirect_stdout(Tty()), patch.object(trial.sys, 'stdin', Tty()), patch.object(trial, 'checked_build', side_effect=AssertionError('No source receipt')), patch.object(trial, 'snapshot_images', side_effect=AssertionError('No source ZIP')), patch.object(trial, 'new_session', return_value=session), patch.object(flashkit, 'preflight', return_value={'baseline_matches': True, 'battery_percent': 80}), patch.object(self.bundle, 'native', side_effect=fake_native), patch('builtins.input', side_effect=['', trial.PHRASE]):
            self.assertEqual(trial.run('TEST', materials=self.bundle), 1)
        self.assertEqual([c[0] for c in calls], ['--probe', '--flash'])
        self.assertFalse(json.loads((session / 'result.json').read_text())['write_sequence_complete'])

    def test_materials_flow_stops_before_usb_on_wrong_phone_baseline(self):
        session = self.base / 'live'
        session.mkdir()
        with contextlib.redirect_stdout(Tty()), patch.object(trial.sys, 'stdin', Tty()), patch.object(trial, 'new_session', return_value=session), patch.object(flashkit, 'preflight', return_value={'baseline_matches': False, 'battery_percent': 80}), patch.object(self.bundle, 'native', side_effect=AssertionError('No USB')), self.assertRaises(flashkit.SafetyError):
            trial.run('TEST', materials=self.bundle)

    def test_native_adapter_uses_only_packaged_writer(self):
        with patch.object(trial, 'native', return_value=0) as invoke:
            self.bundle.native(['--simulate'], self.root, self.base / 'log')
        self.assertEqual(invoke.call_args.kwargs, {'binary': (self.root / bundle_runtime.BINARY_FILE).resolve()})

    def test_isolated_entry_checks_package_without_adb_or_compiler(self):
        tools = self.base / 'tools'
        tools.mkdir()
        adb = tools / 'adb'
        adb.write_text('#!/bin/sh\necho UNEXPECTED_ADB >&2\nexit 99\n')
        adb.chmod(0o755)
        result = subprocess.run([sys.executable, '-I', '-S', '-B', str(self.root / 'start.py'), 'check'],
                                env={**os.environ, 'PATH': str(tools)}, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PACKAGE_OK', result.stdout)
        self.assertNotIn('UNEXPECTED_ADB', result.stderr)
        self.assertFalse((self.root / 'app/__pycache__').exists())

    def test_shell_launcher_works_from_another_directory_with_spaces(self):
        relocated = self.base / 'release with spaces'
        self.root.rename(relocated)
        result = subprocess.run(['/bin/sh', str(relocated / 'start.sh'), 'check'], cwd=self.base,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PACKAGE_OK', result.stdout)

    def test_bootstrap_rejects_runtime_before_import(self):
        module = self.root / 'app/bundle_runtime.py'
        module.write_text('raise RuntimeError("UNVERIFIED_CODE_EXECUTED")\n')
        result = subprocess.run([sys.executable, '-I', '-S', '-B', str(self.root / 'start.py'), 'check'], capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Runtime module checksum mismatch', result.stderr)
        self.assertNotIn('UNVERIFIED_CODE_EXECUTED', result.stderr)

    def test_bootstrap_refuses_package_stdlib_and_bytecode_shadows(self):
        for relative in ['bundle_runtime/__init__.py', 'argparse.py', '__pycache__/bundle_runtime.fake.pyc']:
            with self.subTest(shadow=relative):
                path = self.root / 'app' / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('raise RuntimeError("UNVERIFIED_CODE_EXECUTED")\n')
                result = subprocess.run([sys.executable, '-I', '-S', '-B', str(self.root / 'start.py'), 'check'], capture_output=True, text=True, timeout=20)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Unexpected runtime entry', result.stderr)
                self.assertNotIn('UNVERIFIED_CODE_EXECUTED', result.stderr)
                path.unlink()
                if path.parent != self.root / 'app':
                    path.parent.rmdir()

    def test_no_unattended_run_and_no_force(self):
        with patch.object(bundle_runtime.sys, 'stdin', io.StringIO()), patch.object(bundle_runtime, 'select_device', side_effect=AssertionError('No ADB')), self.assertRaises(flashkit.SafetyError):
            bundle_runtime.main(self.root, self.pin, [])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            bundle_runtime.main(self.root, self.pin, ['run', '--force'])

    def test_archive_validation_rejects_extra_files(self):
        archive = self.base / 'modified.zip'
        build_bundle.archive_bundle(self.root, archive, 'release')
        with build_bundle.zipfile.ZipFile(archive, 'a') as zipped:
            zipped.writestr('release/private.log', b'not allowed')
        with self.assertRaises(flashkit.SafetyError):
            build_bundle.verify_archive(archive, 'release', self.pin, flashkit.sha256_file(self.root / 'start.py'))

    def test_existing_release_is_not_overwritten(self):
        output = self.base / 'output'
        output.mkdir()
        name = build_bundle.release_name('v1', self.host)
        marker = output / (name + '.zip')
        marker.write_bytes(b'existing user release')
        with patch.object(build_bundle.build_trial, 'build', side_effect=AssertionError('Do not rebuild')), self.assertRaises(flashkit.SafetyError):
            build_bundle.build_bundle(output, 'v1')
        self.assertEqual(marker.read_bytes(), b'existing user release')

    def test_archive_has_no_source_zip_private_data_or_build_receipt(self):
        archive = self.base / 'release.zip'
        build_bundle.archive_bundle(self.root, archive, 'release')
        build_bundle.verify_archive(archive, 'release', self.pin, flashkit.sha256_file(self.root / 'start.py'))
        with build_bundle.zipfile.ZipFile(archive) as zipped:
            names = zipped.namelist()
            self.assertEqual(sum('/images/' in name for name in names), 14)
            self.assertNotIn('release/build-receipt.json', names)
            self.assertFalse(any('firmware-downloads' in name or name.endswith('.log') for name in names))
            self.assertTrue((zipped.getinfo('release/bin/fs72-preserve-trial').external_attr >> 16) & 0o111)
        with self.assertRaises(FileExistsError):
            build_bundle.archive_bundle(self.root, archive, 'release')


class DeviceSelectionTests(unittest.TestCase):
    def test_exactly_one_authorized_usb_device(self):
        with patch.object(bundle_runtime.shutil, 'which', return_value='/fake/adb'), patch.object(bundle_runtime.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'List of devices attached\nTEST\tdevice usb:1-2 transport_id:1\n', '')):
            self.assertEqual(bundle_runtime.select_device(), 'TEST')
            with self.assertRaises(flashkit.SafetyError):
                bundle_runtime.select_device('OTHER')

    def test_empty_multiple_offline_unauthorized_and_tcp_devices_are_rejected(self):
        for rows in ['', 'TEST\tunauthorized usb:1-2', 'TEST\toffline usb:1-2',
                     'ONE\tdevice usb:1-2\nTWO\tdevice usb:1-3', 'localhost:5555\tdevice',
                     'adb-TEST-example._adb-tls-connect._tcp\tdevice transport_id:1']:
            with patch.object(bundle_runtime.shutil, 'which', return_value='/fake/adb'), patch.object(bundle_runtime.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'List of devices attached\n' + rows + '\n', '')), self.assertRaises(flashkit.SafetyError):
                bundle_runtime.select_device()

    def test_wireless_duplicate_does_not_replace_usb_hardware_serial(self):
        output = 'List of devices attached\nadb-TEST-example._adb-tls-connect._tcp\tdevice transport_id:1\nTEST\tdevice usb:1-2 transport_id:2\n'
        with patch.object(bundle_runtime.shutil, 'which', return_value='/fake/adb'), patch.object(bundle_runtime.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, '')) as run:
            self.assertEqual(bundle_runtime.select_device(), 'TEST')
        self.assertEqual(run.call_args.args[0], ['adb', 'devices', '-l'])

    def test_missing_adb_never_starts_a_process(self):
        with patch.object(bundle_runtime.shutil, 'which', return_value=None), patch.object(bundle_runtime.subprocess, 'run', side_effect=AssertionError('no subprocess')), self.assertRaises(flashkit.SafetyError):
            bundle_runtime.select_device()

    def test_linux_release_requires_actual_openssl3_dependency(self):
        host = {'system': 'Linux', 'machine': 'x86_64'}
        for library in ['libcrypto.so.1.1', 'libcrypto.so.3']:
            output = '(NEEDED) Shared library: [libusb-1.0.so.0]\n(NEEDED) Shared library: [' + library + ']\n'
            with patch.object(build_bundle.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, '')):
                if library.endswith('.3'):
                    self.assertIn(library, build_bundle.inspect_runtime_dependencies(Path('fixture'), host))
                else:
                    with self.assertRaises(flashkit.SafetyError):
                        build_bundle.inspect_runtime_dependencies(Path('fixture'), host)

    def test_macos_release_rejects_private_library_paths(self):
        output = 'fixture:\n\t/custom/lib/libusb-1.0.0.dylib (version)\n'
        with patch.object(build_bundle.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, '')), self.assertRaises(flashkit.SafetyError):
            build_bundle.inspect_runtime_dependencies(Path('fixture'), {'system': 'Darwin', 'machine': 'arm64'})

    def test_release_name_cannot_escape_output_directory(self):
        for release in ['../v1', '/v1', 'v1;touch', 'v1/test', '']:
            with self.assertRaises(flashkit.SafetyError):
                build_bundle.release_name(release, {'system': 'Darwin', 'machine': 'arm64'})

    def test_version_comparison_and_invalid_versions(self):
        self.assertEqual(bundle_runtime.version_tuple('27'), bundle_runtime.version_tuple('27.0.0'))
        for version in [None, '', True, '27.x', '2.36-ubuntu']:
            with self.assertRaises(flashkit.SafetyError):
                bundle_runtime.version_tuple(version)


if __name__ == '__main__':
    unittest.main()
