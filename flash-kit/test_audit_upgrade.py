import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

import audit_upgrade as upgrade
import flashkit

XML = b'''<BOOT_DELIVERY PRODUCT="pdx256" VERSION="TEST-V40">
<CONFIGURATION NAME="COMMERCIAL_TEST"><BOOT_IMAGES><FILE PATH="bootloader.sin"/></BOOT_IMAGES>
<BOOT_CONFIG><FILE PATH="config.ta"/></BOOT_CONFIG><ATTRIBUTES VALUE="TEST_ONLY"/>
</CONFIGURATION></BOOT_DELIVERY>'''


def boot_zip(xml=XML):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('boot_delivery.xml', xml)
        archive.writestr('bootloader.sin', b'not executable firmware')
        archive.writestr('config.ta', b'not real TA')
    return buffer.getvalue()


def package(path, *, extra=None, xml=XML):
    with zipfile.ZipFile(path, 'w') as archive:
        for name in sorted(flashkit.EXPECTED_MEMBERS):
            archive.writestr(name, boot_zip(xml) if name == 'boot.zip' else b'synthetic content')
        if extra:
            archive.writestr(extra, b'unexpected')
    return hashlib.sha256(path.read_bytes()).hexdigest()


class UpgradeGateTests(unittest.TestCase):
    def test_status_and_execute_never_read_packages_or_use_adb(self):
        for command, wanted in [('status', 0), ('execute', flashkit.BLOCKED_EXIT)]:
            with patch.object(upgrade, 'audit', side_effect=AssertionError('no file audit')), patch.object(flashkit.subprocess, 'run', side_effect=AssertionError('no ADB')), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(upgrade.main([command]), wanted)
            self.assertFalse(json.loads(output.getvalue())['flash_allowed'])

    def test_unknown_or_force_flags_are_rejected(self):
        for argv in [['execute', '--force'], ['audit', '--sha256', '0' * 64]]:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                upgrade.main(argv)

    def test_unpinned_input_is_rejected_before_open(self):
        with patch.object(flashkit, 'source_snapshot', side_effect=AssertionError('must not open')), self.assertRaises(flashkit.SafetyError):
            upgrade.inspect_package(Path('not-present'), None)

    def test_missing_xml_dependency_has_explicit_error(self):
        with patch.object(upgrade.importlib, 'import_module', side_effect=ImportError), self.assertRaisesRegex(flashkit.SafetyError, 'defusedxml'):
            upgrade.inspect_boot(b'')

    def test_member_comparison_uses_content_not_crc(self):
        left = {'same': {'sha256': 'a'}, 'changed': {'sha256': 'b'}, 'removed': {'sha256': 'c'}}
        right = {'same': {'sha256': 'a'}, 'changed': {'sha256': 'x'}, 'new': {'sha256': 'y'}}
        self.assertEqual(upgrade.compare_members(left, right), {'identical': ['same'], 'different_or_missing': ['changed', 'new', 'removed']})

    def test_original_writer_remains_pinned_to_265(self):
        self.assertIn('71.1.A.2.265', flashkit.SOURCE.name)
        self.assertEqual(flashkit.SOURCE_SHA256, 'd272727231a31b22402c4564f387ebd91b9958e5ba8485f8925ea2cb9d813465')
        for record in upgrade.RELEASES.values():
            self.assertRegex(record['sha256'], r'^[a-f0-9]{64}$')


@unittest.skipUnless(importlib.util.find_spec('defusedxml') is not None, 'Install optional defusedxml==0.7.1 to test offline firmware XML auditing')
class PackageAuditTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='upgrade-audit-tests-')
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'synthetic.zip'

    def test_all_members_and_nested_boot_are_hashed(self):
        digest = package(self.path)
        result = upgrade.inspect_package(self.path, digest, self.path.stat().st_size)
        self.assertEqual(len(result['members']), 31)
        self.assertEqual(len(result['boot_delivery']['members']), 3)
        self.assertEqual(result['boot_delivery']['version'], 'TEST-V40')
        self.assertTrue(result['zip_crc_verified'])
        self.assertFalse(result['sony_signature_verified'])

    def test_bad_hash_and_length_are_refused(self):
        digest = package(self.path)
        for checksum, size in [('0' * 64, None), (digest, self.path.stat().st_size + 1)]:
            with self.assertRaises(flashkit.SafetyError):
                upgrade.inspect_package(self.path, checksum, size)

    def test_extra_and_duplicate_members_are_refused(self):
        for name in ['unreviewed.sin', '../escape', 'boot.zip']:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                digest = package(self.path, extra=name)
            with self.assertRaises(flashkit.SafetyError):
                upgrade.inspect_package(self.path, digest)

    def test_symlink_source_is_refused(self):
        digest = package(self.path)
        link = self.path.with_name('link.zip')
        link.symlink_to(self.path)
        with self.assertRaises(flashkit.SafetyError):
            upgrade.inspect_package(link, digest)

    def test_missing_boot_reference_or_wrong_product_are_refused(self):
        for xml in [XML.replace(b'bootloader.sin', b'missing.sin'), XML.replace(b'pdx256', b'wrong-device')]:
            with self.assertRaises(flashkit.SafetyError):
                upgrade.inspect_boot(boot_zip(xml))

    def test_dtd_and_alternate_xml_encoding_are_refused(self):
        for xml in [b'<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///test">]>' + XML, XML.decode().encode('utf-16')]:
            with self.assertRaises((flashkit.SafetyError, UnicodeError)):
                upgrade.inspect_boot(boot_zip(xml))

    def test_uncompressed_budget_is_enforced(self):
        with zipfile.ZipFile(io.BytesIO(boot_zip())) as archive, self.assertRaises(flashkit.SafetyError):
            upgrade.checked_entries(archive, max_entries=64, max_total=1)


if __name__ == '__main__':
    unittest.main()
