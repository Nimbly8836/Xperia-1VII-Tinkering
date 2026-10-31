import contextlib
import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import flashkit as kit


def fake_sin(partition):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        for name, content in [(partition + '.cms', b'fixture-not-a-real-signature'),
                              (partition + '.000', b'fixture-payload')]:
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    return buffer.getvalue()


def fake_archive(path, *, wrong_boot_target=False, extra=None):
    with zipfile.ZipFile(path, mode='w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(kit.EXPECTED_MEMBERS):
            if name in {p + kit.SUFFIX for p in kit.CANDIDATE_PARTITIONS}:
                partition = name.removesuffix(kit.SUFFIX)
                if wrong_boot_target and partition == 'boot':
                    partition = 'userdata'
                content = fake_sin(partition)
            else:
                content = b'fixture: excluded source content'
            archive.writestr(name, content)
        if extra:
            archive.writestr(extra, b'unreviewed')
    return hashlib.sha256(path.read_bytes()).hexdigest()


class KitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='fs72-kit-tests.')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source.zip'
        self.target = self.root / 'candidate'
        self.sha = fake_archive(self.source)
        self.network_guard = patch.object(kit.subprocess, 'run', side_effect=AssertionError('No real process/ADB in tests'))
        self.network_guard.start()
        self.addCleanup(self.network_guard.stop)

    def prepare(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return kit.prepare(self.source, self.target, self.sha)

    def test_audit_roles_and_goal(self):
        result = kit.audit_source(self.source, self.sha)
        self.assertEqual(len(result['members']), 31)
        self.assertEqual(sum(r['role'] == 'candidate_only_not_approved' for r in result['members']), 14)
        self.assertEqual(sum(r['role'] == 'preserve_do_not_stage' for r in result['members']), 8)
        self.assertFalse(result['policy']['flash_allowed'])
        self.assertEqual(result['policy']['goal'], 'dual_physical_sim_preserved_and_esim_switchable')

    def test_wrong_source_hash(self):
        with self.assertRaises(kit.SafetyError):
            kit.audit_source(self.source, '0' * 64)

    def test_source_symlink_rejected(self):
        link = self.root / 'link.zip'
        link.symlink_to(self.source)
        with self.assertRaises(kit.SafetyError):
            kit.audit_source(link, self.sha)

    def test_unreviewed_member_rejected(self):
        other = self.root / 'extra.zip'
        digest = fake_archive(other, extra='../userdata.sin')
        with self.assertRaises(kit.SafetyError):
            kit.audit_source(other, digest)

    def test_prepare_and_verify_with_no_preserved_files(self):
        original = self.source.read_bytes()
        self.prepare()
        result = kit.verify(self.source, self.target, self.sha)
        self.assertTrue(result['candidate_integrity_verified'])
        self.assertFalse(result['flash_allowed'])
        self.assertFalse(result['goal_verified'])
        names = {p.name for p in (self.target / 'images').iterdir()}
        self.assertEqual(names, {p + kit.SUFFIX for p in kit.CANDIDATE_PARTITIONS})
        self.assertEqual(self.source.read_bytes(), original)

    def test_inner_target_spoof_rejected(self):
        other = self.root / 'wrong-target.zip'
        digest = fake_archive(other, wrong_boot_target=True)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(kit.SafetyError):
            kit.prepare(other, self.target, digest)
        self.assertFalse(self.target.exists())

    def test_existing_destination_not_overwritten(self):
        self.target.mkdir()
        marker = self.target / 'user-file'
        marker.write_text('keep me')
        with self.assertRaises(kit.SafetyError):
            self.prepare()
        self.assertEqual(marker.read_text(), 'keep me')

    def test_insufficient_disk_stops_before_build(self):
        with patch.object(kit.shutil, 'disk_usage', return_value=SimpleNamespace(free=1)), self.assertRaises(kit.SafetyError):
            self.prepare()
        self.assertFalse(self.target.exists())
        self.assertFalse(list(self.root.glob('*.building-*')))

    def test_extra_flasher_or_approval_rejected(self):
        self.prepare()
        for name in ['newflasher', 'APPROVED']:
            added = self.target / name
            added.write_text('not authorization')
            with self.assertRaises(kit.SafetyError):
                kit.verify(self.source, self.target, self.sha)
            added.unlink()

    def test_policy_cannot_be_changed_to_allow_flash(self):
        self.prepare()
        p = self.target / 'manifest.json'
        record = json.loads(p.read_text())
        record['policy']['flash_allowed'] = True
        p.write_text(json.dumps(record))
        with self.assertRaises(kit.SafetyError):
            kit.verify(self.source, self.target, self.sha)

    def test_image_tamper_not_hidden_by_edited_manifest(self):
        self.prepare()
        path = self.target / 'images' / ('boot' + kit.SUFFIX)
        path.chmod(0o600)
        changed = path.read_bytes() + b'changed'
        path.write_bytes(changed)
        manifest_path = self.target / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        entry = next(r for r in manifest['images'] if r['partition'] == 'boot')
        entry['sha256'] = hashlib.sha256(changed).hexdigest()
        entry['bytes'] = len(changed)
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaises(kit.SafetyError):
            kit.verify(self.source, self.target, self.sha)

    def test_symlink_in_candidate_rejected(self):
        self.prepare()
        link = self.target / 'images' / ('boot' + kit.SUFFIX)
        copy = self.root / 'elsewhere.sin'
        copy.write_bytes(link.read_bytes())
        link.unlink()
        link.symlink_to(copy)
        with self.assertRaises(kit.SafetyError):
            kit.verify(self.source, self.target, self.sha)

    def test_execute_never_calls_adb_or_preparer(self):
        with patch.object(kit, 'prepare', side_effect=AssertionError('Must not prepare on execute')), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(kit.main(['execute']), kit.BLOCKED_EXIT)
            self.assertEqual(kit.main(['status']), kit.BLOCKED_EXIT)

    def test_no_force_option(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            kit.main(['execute', '--force'])
        self.assertEqual(error.exception.code, 2)

    def replacement_zip(self):
        other = self.root / 'replacement.zip'
        fake_archive(other)
        with zipfile.ZipFile(other, 'a') as archive:
            archive.comment = b'replacement-source'
        self.assertNotEqual(hashlib.sha256(other.read_bytes()).hexdigest(), self.sha)
        return other

    def test_source_replaced_after_hash_is_rejected(self):
        other = self.replacement_zip()
        original_hash = kit.sha256_stream
        def replace_after_hash(stream):
            result = original_hash(stream)
            other.replace(self.source)
            return result
        with patch.object(kit, 'sha256_stream', side_effect=replace_after_hash), self.assertRaises(kit.SafetyError):
            kit.audit_source(self.source, self.sha)

    def test_source_replaced_during_prepare_is_not_published(self):
        other = self.replacement_zip()
        original_inspect = kit.inspect_sin
        changed = False
        def change_source(path, partition):
            nonlocal changed
            if not changed:
                changed = True
                other.replace(self.source)
            return original_inspect(path, partition)
        with patch.object(kit, 'inspect_sin', side_effect=change_source), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(kit.SafetyError):
            self.prepare()
        self.assertFalse(self.target.exists())

    def test_source_modified_in_place_with_restored_mtime_is_rejected(self):
        before = self.source.stat()
        original_inspect = kit.inspect_sin
        changed = False
        def change_source(path, partition):
            nonlocal changed
            if not changed:
                changed = True
                # Change a DOS timestamp in a local header, not any payload;
                # ZIP reads still work, but the pinned source is no longer equal.
                with self.source.open('r+b') as stream:
                    stream.seek(10)
                    value = stream.read(1)
                    stream.seek(10)
                    stream.write(bytes([value[0] ^ 1]))
                os.utime(self.source, ns=(before.st_atime_ns, before.st_mtime_ns))
            return original_inspect(path, partition)
        with patch.object(kit, 'inspect_sin', side_effect=change_source), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(kit.SafetyError):
            self.prepare()
        self.assertFalse(self.target.exists())

    def test_source_replaced_during_verify_is_rejected(self):
        self.prepare()
        other = self.replacement_zip()
        original_hash = kit.sha256_file
        changed = False
        def change_source(path):
            nonlocal changed
            digest = original_hash(path)
            if not changed:
                changed = True
                other.replace(self.source)
            return digest
        with patch.object(kit, 'sha256_file', side_effect=change_source), self.assertRaises(kit.SafetyError):
            kit.verify(self.source, self.target, self.sha)

    def test_non_regular_source_is_rejected_without_blocking(self):
        fifo = self.root / 'source-fifo'
        os.mkfifo(fifo)
        with self.assertRaises(kit.SafetyError):
            kit.audit_source(fifo, self.sha)

    def test_manifest_must_be_object(self):
        self.prepare()
        (self.target / 'manifest.json').write_text('[]')
        with self.assertRaises(kit.SafetyError):
            kit.verify(self.source, self.target, self.sha)

    def test_manifest_images_shapes_rejected(self):
        self.prepare()
        path = self.target / 'manifest.json'
        valid = json.loads(path.read_text())
        for malformed in [None, {}, ['boot'], [{'partition': []}]]:
            changed = dict(valid)
            changed['images'] = malformed
            path.write_text(json.dumps(changed))
            with self.assertRaises(kit.SafetyError):
                kit.verify(self.source, self.target, self.sha)

    def test_manifest_blockers_cannot_be_removed(self):
        self.prepare()
        path = self.target / 'manifest.json'
        changed = json.loads(path.read_text())
        changed['blockers'] = []
        path.write_text(json.dumps(changed))
        with self.assertRaises(kit.SafetyError):
            kit.verify(self.source, self.target, self.sha)

    def mock_adb(self, command, **kwargs):
        self.assertEqual(command[:4], ['adb', '-s', 'TEST_DEVICE', 'shell'])
        args = command[4:]
        if args == ['dumpsys', 'battery']:
            return SimpleNamespace(returncode=0, stdout='  level: 80\n')
        self.assertEqual(args[0], 'getprop')
        self.assertIn(args[1], kit.BASELINE)
        return SimpleNamespace(returncode=0, stdout=kit.BASELINE[args[1]] + '\n')

    def test_preflight_is_read_only_not_flash_ready(self):
        with patch.object(kit.subprocess, 'run', side_effect=self.mock_adb) as run:
            result = kit.preflight('TEST_DEVICE')
        self.assertTrue(result['baseline_matches'])
        self.assertFalse(result['flash_allowed'])
        self.assertFalse(result['capability_verified'])
        self.assertEqual(run.call_count, len(kit.BASELINE) + 1)
        self.assertNotIn('TEST_DEVICE', json.dumps(result))

    def test_mutating_adb_commands_rejected(self):
        for args in [['reboot'], ['shell', 'su'], ['dumpsys', 'battery', 'set', 'level', '0'],
                     ['getprop', 'ro.serialno']]:
            with self.assertRaises(kit.SafetyError):
                kit.adb_read('TEST_DEVICE', args)

    def test_timeout_fails_without_serial_in_message(self):
        with patch.object(kit.subprocess, 'run', side_effect=subprocess.TimeoutExpired('TEST_DEVICE', 15)), self.assertRaises(kit.SafetyError) as error:
            kit.preflight('TEST_DEVICE')
        self.assertNotIn('TEST_DEVICE', str(error.exception))

    def test_unknown_battery_is_not_pass(self):
        def no_battery(command, **kwargs):
            result = self.mock_adb(command, **kwargs)
            return SimpleNamespace(returncode=0, stdout='unknown') if command[-2:] == ['dumpsys', 'battery'] else result
        with patch.object(kit.subprocess, 'run', side_effect=no_battery), self.assertRaises(kit.SafetyError):
            kit.preflight('TEST_DEVICE')


if __name__ == '__main__':
    unittest.main()
