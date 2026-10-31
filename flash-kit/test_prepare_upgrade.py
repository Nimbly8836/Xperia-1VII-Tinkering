import contextlib
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import flashkit
import prepare_upgrade as upgrade
from test_flashkit import fake_sin


class PrepareUpgradeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='prepare-upgrade-tests-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source.zip'
        self.destination = self.root / 'candidate'
        import gzip
        self.bootloader = gzip.compress(fake_sin('bootloader'))
        self.config = b'synthetic boot config; never a real TA write'
        boot = io.BytesIO()
        with zipfile.ZipFile(boot, 'w') as archive:
            archive.writestr(upgrade.BOOTLOADER, self.bootloader)
            archive.writestr('PDX256_XBootConfig_MiscTA.ta', self.config)
        with zipfile.ZipFile(self.source, 'w') as archive:
            for name in sorted(flashkit.EXPECTED_MEMBERS):
                if name == 'boot.zip':
                    data = boot.getvalue()
                elif name in {p + flashkit.SUFFIX for p in flashkit.CANDIDATE_PARTITIONS}:
                    data = fake_sin(name.removesuffix(flashkit.SUFFIX))
                else:
                    data = b'not to be staged'
                archive.writestr(name, data)
        self.sha = flashkit.sha256_file(self.source)
        for guard in [patch.object(upgrade, 'RELEASE', {'sha256': self.sha}),
                      patch.object(upgrade, 'BOOTLOADER_SHA256', hashlib.sha256(self.bootloader).hexdigest()),
                      patch.object(upgrade, 'BOOT_CONFIG_SHA256', hashlib.sha256(self.config).hexdigest()),
                      patch.object(flashkit.subprocess, 'run', side_effect=AssertionError('No processes, ADB or USB')),
                      patch.object(upgrade.shutil, 'disk_usage', return_value=SimpleNamespace(free=100 * 1024**3))]:
            guard.start()
            self.addCleanup(guard.stop)

    def prepare(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return upgrade.prepare(self.source, self.destination)

    def test_only_fourteen_system_images_and_commercial_bootloader_are_staged(self):
        report = self.prepare()
        names = {path.name for path in (self.destination / 'images').iterdir()}
        self.assertEqual(names, {p + flashkit.SUFFIX for p in flashkit.CANDIDATE_PARTITIONS} | {upgrade.BOOTLOADER})
        self.assertEqual(len(report['images']), 15)
        self.assertFalse(report['flash_allowed'])
        self.assertFalse(report['phone_accessed'])
        self.assertTrue(report['not_a_write_sequence'])
        self.assertEqual(json.loads((self.destination / 'manifest.json').read_text()), report)
        self.assertEqual((self.destination / 'NOT_APPROVED.txt').read_text(), upgrade.MARKER)
        self.assertFalse(any(path.suffix == '.ta' for path in self.destination.rglob('*')))

    def test_gzip_bootloader_target_is_validated(self):
        path = self.root / 'bootloader.sin'
        path.write_bytes(self.bootloader)
        self.assertEqual(len(upgrade.inspect_sin(path, 'bootloader')), 2)
        with self.assertRaises(flashkit.SafetyError):
            upgrade.inspect_sin(path, 'boot')

    def test_wrong_source_bootloader_or_config_hash_is_refused(self):
        for key, value in [('RELEASE', {'sha256': '0' * 64}), ('BOOTLOADER_SHA256', '0' * 64), ('BOOT_CONFIG_SHA256', '0' * 64)]:
            with patch.object(upgrade, key, value), self.assertRaises(flashkit.SafetyError):
                self.prepare()
            self.assertFalse(self.destination.exists())

    def test_existing_directory_is_never_overwritten(self):
        self.destination.mkdir()
        marker = self.destination / 'user-data'
        marker.write_bytes(b'keep')
        with self.assertRaises(flashkit.SafetyError):
            self.prepare()
        self.assertEqual(marker.read_bytes(), b'keep')

    def test_source_symlink_is_refused(self):
        link = self.root / 'link.zip'
        link.symlink_to(self.source)
        with self.assertRaises(flashkit.SafetyError):
            upgrade.prepare(link, self.destination)

    def test_insufficient_space_stops_before_publishing(self):
        with patch.object(upgrade.shutil, 'disk_usage', return_value=SimpleNamespace(free=1)), self.assertRaises(flashkit.SafetyError):
            self.prepare()
        self.assertFalse(self.destination.exists())

    def test_prepared_files_are_readonly_and_match_the_manifest(self):
        report = self.prepare()
        for item in report['images']:
            path = self.destination / 'images' / item['name']
            self.assertEqual(path.stat().st_mode & 0o222, 0)
            self.assertEqual(path.stat().st_size, item['bytes'])
            self.assertEqual(flashkit.sha256_file(path), item['sha256'])


if __name__ == '__main__':
    unittest.main()
