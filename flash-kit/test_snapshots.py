"""Independent-copy tests; never access ADB or USB."""
import hashlib
import importlib.util
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import flashkit

_spec = importlib.util.spec_from_file_location('snapshot_trial_under_test', Path(__file__).with_name('trial.py'))
if _spec is None or _spec.loader is None:
    raise RuntimeError('Cannot load trial.py')
trial = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(trial)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='snapshot-tests-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source.sin'
        self.target = self.root / 'copy.sin'
        self.payload = b'not real firmware\n'
        self.source.write_bytes(self.payload)
        self.entry = {'bytes': len(self.payload), 'sha256': hashlib.sha256(self.payload).hexdigest(), 'name': 'source.sin'}
        for context in (
            patch.object(trial.platform, 'system', return_value='Linux'),
            patch.object(trial.subprocess, 'run', side_effect=AssertionError('No subprocess in Linux snapshot tests')),
            patch.object(trial.shutil, 'disk_usage', return_value=SimpleNamespace(free=100 * 1024**3)),
        ):
            context.start()
            self.addCleanup(context.stop)

    def copy(self):
        trial.copy_image_snapshot(self.source, self.target, self.entry)

    def test_linux_copy_is_independent_readonly_and_hashed(self):
        self.copy()
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assertNotEqual(self.source.stat().st_ino, self.target.stat().st_ino)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o400)
        self.source.write_bytes(b'changed source')
        self.assertEqual(self.target.read_bytes(), self.payload)

    def test_existing_destination_is_not_overwritten(self):
        self.target.write_bytes(b'keep')
        with self.assertRaises(flashkit.SafetyError):
            self.copy()
        self.assertEqual(self.target.read_bytes(), b'keep')

    def test_symlinks_and_fifo_are_refused(self):
        real = self.root / 'real.sin'
        self.source.rename(real)
        self.source.symlink_to(real)
        with self.assertRaises(OSError):
            self.copy()
        self.assertFalse(self.target.exists())
        self.source.unlink()
        os.mkfifo(self.source)
        with self.assertRaises(flashkit.SafetyError):
            self.copy()
        self.assertFalse(self.target.exists())

    def test_destination_symlink_is_refused(self):
        self.target.symlink_to(self.source)
        with self.assertRaises(flashkit.SafetyError):
            self.copy()
        self.assertEqual(self.source.read_bytes(), self.payload)

    def test_wrong_size_or_hash_is_refused(self):
        self.entry['bytes'] += 1
        with self.assertRaises(flashkit.SafetyError):
            self.copy()
        self.assertFalse(self.target.exists())
        self.entry['bytes'] -= 1
        self.entry['sha256'] = '0' * 64
        with self.assertRaises(flashkit.SafetyError):
            self.copy()

    def test_disk_reserve_is_enforced(self):
        with patch.object(trial.shutil, 'disk_usage', return_value=SimpleNamespace(free=1)), self.assertRaises(flashkit.SafetyError):
            self.copy()

    def test_modified_source_rejected_even_if_size_is_unchanged(self):
        original = flashkit.assert_source_stable
        calls = 0
        def change_before_second_check(path, stream, signature):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.source.write_bytes(b'X' * len(self.payload))
            original(path, stream, signature)
        with patch.object(flashkit, 'assert_source_stable', side_effect=change_before_second_check), self.assertRaises(flashkit.SafetyError):
            self.copy()

    def test_macos_keeps_clone_path_and_verifies_result(self):
        def fake_clone(command, **kwargs):
            self.assertEqual(command, ['/bin/cp', '-c', str(self.source), str(self.target)])
            self.target.write_bytes(self.payload)
        with patch.object(trial.platform, 'system', return_value='Darwin'), patch.object(trial.subprocess, 'run', side_effect=fake_clone) as run:
            self.copy()
        run.assert_called_once()
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o400)

    def test_hard_link_is_never_accepted_as_snapshot(self):
        def fake_clone(*args, **kwargs):
            os.link(self.source, self.target)
        with patch.object(trial.platform, 'system', return_value='Darwin'), patch.object(trial.subprocess, 'run', side_effect=fake_clone), self.assertRaises(flashkit.SafetyError):
            self.copy()

    def test_full_linux_budget_checked_before_copy(self):
        session = self.root / 'session'
        session.mkdir()
        manifest = {'images': [self.entry]}
        with patch.object(flashkit, 'verify'), patch.object(flashkit, 'read_json', return_value=manifest), patch.object(trial.shutil, 'disk_usage', return_value=SimpleNamespace(free=flashkit.RESERVE_BYTES)), self.assertRaises(flashkit.SafetyError):
            trial.snapshot_images(session)
        self.assertFalse((session / 'images').exists())

    def test_unsupported_os_stops_before_copy(self):
        with patch.object(trial.platform, 'system', return_value='Windows'), self.assertRaises(flashkit.SafetyError):
            self.copy()
        self.assertFalse(self.target.exists())


if __name__ == '__main__':
    unittest.main()
