#!/usr/bin/env python3
"""Offline .265 -> .35 package comparison. Never authorizes or performs flashing.

Checks pinned original ZIPs, streams every member through SHA-256/ZIP CRC,
then compares boot delivery and package contents. No ADB, USB or network calls.
"""
import argparse
import hashlib
import importlib
import io
import json
import stat
import sys
import zipfile
from pathlib import Path

import flashkit

PACKAGES = flashkit.PROJECT / 'firmware-downloads/packages'
RELEASES = {
    'fs54-eu-71.1.A.2.265': {
        'name': flashkit.SOURCE.name,
        'sha256': flashkit.SOURCE_SHA256,
        'bytes': None,
    },
    'fs54-eu-71.2.A.2.35': {
        'name': 'APP-SW_PDX256_GLOBALEEA-A4_USER_71.2.A.2.35_X-FLASH-ALL-B083_COM.zip',
        'sha256': 'aeab7cab467dff1e3fc71b6becc87532d54789df79a6b7b3289cdf86ab707056',
        'bytes': 4665814296,
    },
    'fs72-hk-71.2.A.2.35': {
        'name': 'APP-SW_PDX256_GLOBAL-C2_USER_71.2.A.2.35_X-FLASH-ALL-B083_COM.zip',
        'sha256': '70f5513f7dd3c6fbb3a341962b430fc1831a7a46019e2e3fa7438242ee7fd992',
        'bytes': 4665768932,
    },
}
BLOCKERS = [
    'The .265 -> .35 path changes Android generation and boot delivery V36 -> V40.',
    'No verified V36 compatibility or reviewed V40/boot-config migration is implemented.',
    'Package AVB and super layout passed offline checks; device counters and user-data migration/recovery remain unverified.',
    'USB Flash-mode bootloader routing and boot-config inspection is still required; this tool does not authorize writes.',
    'The .265 writer is not an upgrade writer; no image list is authorized for .35.',
]


def checked_entries(archive, *, max_entries, max_total):
    entries = archive.infolist()
    names = [entry.filename for entry in entries]
    if not entries or len(entries) > max_entries or len(names) != len(set(names)):
        raise flashkit.SafetyError('Unexpected or duplicate archive entries')
    if sum(entry.file_size for entry in entries) > max_total:
        raise flashkit.SafetyError('Archive uncompressed size exceeds audit budget')
    for entry in entries:
        if (entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16)
                or Path(entry.filename).name != entry.filename or '\\' in entry.filename
                or entry.flag_bits & 1):
            raise flashkit.SafetyError('Unsafe or encrypted archive entry')
    return entries


def member_hashes(archive, entries):
    result = {}
    for entry in entries:
        # Reading every entry through EOF also performs zipfile's CRC check.
        with archive.open(entry) as stream:
            digest, count = flashkit.sha256_stream(stream)
        if count != entry.file_size:
            raise flashkit.SafetyError('Archive member length mismatch')
        result[entry.filename] = {'bytes': count, 'sha256': digest, 'crc32': f'{entry.CRC:08x}'}
    return result


def require_xml_parser():
    try:
        return importlib.import_module('defusedxml.ElementTree')
    except ImportError as exc:
        raise flashkit.SafetyError('Offline XML audit requires defusedxml==0.7.1; use the firmware-downloads venv') from exc


def inspect_boot(payload):
    xml_parser = require_xml_parser()
    with zipfile.ZipFile(io.BytesIO(payload)) as boot:
        entries = checked_entries(boot, max_entries=64, max_total=128 * 1024**2)
        members = member_hashes(boot, entries)
        info = boot.getinfo('boot_delivery.xml')
        if info.file_size > 64 * 1024:
            raise flashkit.SafetyError('Boot delivery XML exceeds audit budget')
        raw = boot.read(info)
        text = raw.decode('utf-8')
        if '\x00' in text or '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
            raise flashkit.SafetyError('DTD/entities/alternate XML encodings are not accepted')
        root = xml_parser.fromstring(text, forbid_dtd=True, forbid_entities=True, forbid_external=True)
        if root.tag != 'BOOT_DELIVERY' or root.get('PRODUCT') != 'pdx256' or not root.get('VERSION'):
            raise flashkit.SafetyError('Unexpected boot delivery identity')
        configurations = []
        for node in root.findall('CONFIGURATION'):
            images = [item.get('PATH') for item in node.findall('BOOT_IMAGES/FILE')]
            controls = [item.get('PATH') for item in node.findall('BOOT_CONFIG/FILE')]
            if not images or any(name not in members for name in images + controls):
                raise flashkit.SafetyError('Boot delivery refers to missing members')
            attributes = node.find('ATTRIBUTES')
            configurations.append({'name': node.get('NAME'), 'boot_images': images,
                                   'boot_config_files': controls,
                                   'match_attributes': attributes.get('VALUE') if attributes is not None else None})
        if not configurations:
            raise flashkit.SafetyError('Missing boot configurations')
        return {'version': root.get('VERSION'), 'product': root.get('PRODUCT'),
                'xml_sha256': hashlib.sha256(raw).hexdigest(),
                'configurations': configurations, 'members': members}


def inspect_package(path, expected_sha, expected_bytes=None):
    if not expected_sha:
        raise flashkit.SafetyError('Release has no pinned complete-package digest; download/review first')
    with flashkit.source_snapshot(path, expected_sha) as archive:
        if expected_bytes is not None and path.stat().st_size != expected_bytes:
            raise flashkit.SafetyError('Original package size mismatch')
        entries = checked_entries(archive, max_entries=64, max_total=25 * 1024**3)
        if {entry.filename for entry in entries} != flashkit.EXPECTED_MEMBERS:
            raise flashkit.SafetyError('Package differs from the reviewed 31-member inventory')
        members = member_hashes(archive, entries)
        if archive.getinfo('boot.zip').file_size > 64 * 1024**2:
            raise flashkit.SafetyError('Boot ZIP exceeds audit budget')
        boot = inspect_boot(archive.read('boot.zip'))
        return {'name': path.name, 'sha256': expected_sha, 'bytes': path.stat().st_size,
                'zip_crc_verified': True, 'sony_signature_verified': False,
                'members': members, 'boot_delivery': boot}


def compare_members(left, right):
    names = set(left) | set(right)
    return {'identical': sorted(name for name in names if name in left and name in right and left[name]['sha256'] == right[name]['sha256']),
            'different_or_missing': sorted(name for name in names if name not in left or name not in right or left[name]['sha256'] != right[name]['sha256'])}


def audit(packages):
    require_xml_parser()  # Fail before hashing multi-gigabyte packages if missing.
    records = {}
    for key, release in RELEASES.items():
        print('AUDITING ' + key, file=sys.stderr, flush=True)
        records[key] = inspect_package(packages / key / release['name'], release['sha256'], release['bytes'])
    old, target, hk = (records[key] for key in RELEASES)
    return {'mode': 'offline_upgrade_audit', 'flash_allowed': False, 'phone_accessed': False,
            'source': 'previously cross-flashed FS72 hardware / FS54 .265', 'target': 'FS54 .35',
            'blockers': BLOCKERS, 'packages': records,
            'old_vs_target': compare_members(old['members'], target['members']),
            'hk_vs_target': compare_members(hk['members'], target['members']),
            'hk_vs_target_boot': compare_members(hk['boot_delivery']['members'], target['boot_delivery']['members'])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    commands.add_parser('execute', help='Always refuses: .35 live writes are not implemented')
    audit_parser = commands.add_parser('audit')
    audit_parser.add_argument('--packages', type=Path, default=PACKAGES, help='Parent of the three fixed package directories')
    args = parser.parse_args(argv)
    if args.command != 'audit':
        print(json.dumps({'flash_allowed': False, 'target_version': '71.2.A.2.35', 'blockers': BLOCKERS}, indent=2))
        return flashkit.BLOCKED_EXIT if args.command == 'execute' else 0
    print(json.dumps(audit(args.packages), indent=2))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (flashkit.SafetyError, OSError, ValueError, KeyError, zipfile.BadZipFile, SyntaxError) as exc:
        # No raw path or private metadata is emitted on failures.
        message = str(exc) if isinstance(exc, flashkit.SafetyError) else type(exc).__name__
        print('AUDIT STOPPED WITHOUT PHONE ACCESS: ' + message, file=sys.stderr)
        sys.exit(2)
