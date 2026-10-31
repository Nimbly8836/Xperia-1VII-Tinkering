#!/usr/bin/env python3
"""Stage fixed .35 images for offline upgrade review. Never flash or access USB."""
import argparse
import fcntl
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

import audit_upgrade
import build_trial
import flashkit

RELEASE = audit_upgrade.RELEASES['fs54-eu-71.2.A.2.35']
SOURCE = audit_upgrade.PACKAGES / 'fs54-eu-71.2.A.2.35' / RELEASE['name']
DESTINATION = flashkit.KIT / 'candidate-upgrade-fs54-71.2.A.2.35-NOT-APPROVED'
BOOTLOADER = 'bootloader_X_BOOT_SM8750_LA1_0_V_40_X-FLASH-ALL-B083.sin'
BOOTLOADER_SHA256 = '260b0ce3c9d143d3627b7b3e363aa5ae5502522729dda7ecbe3a53e15ace0bd8'
BOOT_CONFIG_SHA256 = '7ef4cb79b9c44a0ddf3d4545976ee196f5cfe1e131afb6c5a04ebb69cfd3a9d8'
MARKER = '''OFFLINE UPGRADE REVIEW ONLY / NOT APPROVED FOR FLASHING

These are 14 original FS54 .35 system/radio SINs and one original commercial
V40 bootloader container. They are review materials, NOT an authorized write
sequence. No TA, GPT, userdata, metadata, persist or modemst images are staged.

Do not put Newflasher in this directory or flash these files manually.
The existing .265 writer and prebuilt .265 bundles cannot perform this upgrade.
A fresh device preflight, bootloader-routing review and separate explicit
write authorization are still required. No phone operations occurred here.
'''


def inspect_sin(path, partition):
    members = []
    with tarfile.open(path, 'r:*') as archive:
        for index, member in enumerate(archive):
            expected = partition + ('.cms' if index == 0 else f'.{index - 1:03d}')
            if (index >= 512 or member.name != expected or not member.isfile()
                    or member.issparse() or not 0 < member.size <= 100 * 1024**2):
                raise flashkit.SafetyError('Unexpected SIN member or target')
            if index == 0 and member.size > 1024**2:
                raise flashkit.SafetyError('Unexpected CMS size')
            stream = archive.extractfile(member)
            if stream is None:
                raise flashkit.SafetyError('SIN member has no data')
            with stream:
                digest, size = flashkit.sha256_stream(stream)
            if size != member.size:
                raise flashkit.SafetyError('Truncated SIN member')
            members.append({'name': member.name, 'bytes': size, 'sha256': digest})
    if len(members) < 2:
        raise flashkit.SafetyError('SIN has no payload')
    return members


def stage_member(stream, target, expected_size, partition):
    digest = hashlib.sha256()
    count = 0
    with target.open('xb') as output:
        for block in iter(lambda: stream.read(flashkit.CHUNK_BYTES), b''):
            if shutil.disk_usage(target.parent).free < flashkit.RESERVE_BYTES + len(block):
                raise flashkit.SafetyError('Disk reserve reached; no complete candidate published')
            output.write(block)
            digest.update(block)
            count += len(block)
    if count != expected_size or flashkit.sha256_file(target) != digest.hexdigest():
        raise flashkit.SafetyError('Staged image size/digest mismatch')
    members = inspect_sin(target, partition)
    target.chmod(0o400)
    return {'name': target.name, 'partition': partition, 'bytes': count,
            'sha256': digest.hexdigest(), 'sin_members': members}


def prepare(source=SOURCE, destination=DESTINATION):
    if os.path.lexists(destination):
        raise flashkit.SafetyError('Destination already exists; do not merge or overwrite upgrade materials')
    destination.parent.mkdir(parents=True, exist_ok=True)
    work = None
    try:
        with flashkit.source_snapshot(source, RELEASE['sha256']) as archive:
            entries = audit_upgrade.checked_entries(archive, max_entries=64, max_total=25 * 1024**3)
            if {item.filename for item in entries} != flashkit.EXPECTED_MEMBERS:
                raise flashkit.SafetyError('Unexpected .35 source inventory')
            boot_info = archive.getinfo('boot.zip')
            if boot_info.file_size > 64 * 1024**2:
                raise flashkit.SafetyError('Boot delivery exceeds review budget')
            with zipfile.ZipFile(io.BytesIO(archive.read(boot_info))) as boot:
                audit_upgrade.checked_entries(boot, max_entries=64, max_total=128 * 1024**2)
                config = boot.read('PDX256_XBootConfig_MiscTA.ta')
                boot_bytes = boot.read(BOOTLOADER)
                if hashlib.sha256(config).hexdigest() != BOOT_CONFIG_SHA256 or hashlib.sha256(boot_bytes).hexdigest() != BOOTLOADER_SHA256:
                    raise flashkit.SafetyError('Unexpected commercial V40 boot delivery')
            needed = sum(archive.getinfo(part + flashkit.SUFFIX).file_size for part in build_trial.ORDER) + len(boot_bytes)
            if shutil.disk_usage(destination.parent).free < needed + flashkit.RESERVE_BYTES:
                raise flashkit.SafetyError('Not enough space for upgrade materials and reserve')
            work = Path(tempfile.mkdtemp(prefix='.upgrade-preparing-', dir=destination.parent))
            images = work / 'images'
            images.mkdir(mode=0o700)
            records = []
            for partition in build_trial.ORDER:
                name = partition + flashkit.SUFFIX
                with archive.open(name) as stream:
                    records.append(stage_member(stream, images / name, archive.getinfo(name).file_size, partition))
                print('STAGED FOR REVIEW:', name, flush=True)
            records.append(stage_member(io.BytesIO(boot_bytes), images / BOOTLOADER, len(boot_bytes), 'bootloader'))
            manifest = {'schema': 1, 'purpose': 'offline_upgrade_review_only', 'flash_allowed': False,
                        'not_a_write_sequence': True, 'source_zip_name': source.name,
                        'source_zip_sha256': RELEASE['sha256'], 'target_version': '71.2.A.2.35',
                        'boot_config_reference_sha256': BOOT_CONFIG_SHA256,
                        'phone_accessed': False, 'images': records}
            (work / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
            (work / 'NOT_APPROVED.txt').write_text(MARKER)
        if os.path.lexists(destination):
            raise flashkit.SafetyError('Destination appeared during preparation; refusing replacement')
        work.rename(destination)
        return manifest
    except BaseException:
        if work is not None:
            print('Incomplete local preparation retained at: ' + str(work), file=sys.stderr)
        raise


def verify(source=SOURCE, destination=DESTINATION):
    if destination.is_symlink() or not destination.is_dir():
        raise flashkit.SafetyError('Upgrade candidate missing or linked')
    expected_names = [part + flashkit.SUFFIX for part in build_trial.ORDER] + [BOOTLOADER]
    expected_files = {'manifest.json', 'NOT_APPROVED.txt'} | {'images/' + name for name in expected_names}
    actual = set()
    for path in destination.rglob('*'):
        relative = path.relative_to(destination).as_posix()
        if path.is_symlink() or (path.is_dir() and relative != 'images'):
            raise flashkit.SafetyError('Unexpected directory/link in upgrade candidate')
        if path.is_file():
            actual.add(relative)
        elif not path.is_dir():
            raise flashkit.SafetyError('Special files are not permitted')
    if actual != expected_files or (destination / 'manifest.json').stat().st_size > 1024 * 1024:
        raise flashkit.SafetyError('Upgrade candidate file set differs from the fixed review material')
    manifest = flashkit.read_json(destination / 'manifest.json')
    if (not isinstance(manifest, dict) or type(manifest.get('schema')) is not int or manifest['schema'] != 1
            or manifest.get('purpose') != 'offline_upgrade_review_only' or manifest.get('flash_allowed') is not False
            or manifest.get('not_a_write_sequence') is not True or manifest.get('source_zip_name') != source.name
            or manifest.get('source_zip_sha256') != RELEASE['sha256'] or manifest.get('target_version') != '71.2.A.2.35'
            or manifest.get('boot_config_reference_sha256') != BOOT_CONFIG_SHA256
            or (destination / 'NOT_APPROVED.txt').read_text() != MARKER):
        raise flashkit.SafetyError('Upgrade review policy/source metadata changed')
    records = manifest.get('images')
    if not isinstance(records, list) or len(records) != 15 or any(not isinstance(item, dict) for item in records):
        raise flashkit.SafetyError('Invalid upgrade image records')
    expected = []
    with flashkit.source_snapshot(source, RELEASE['sha256']) as archive:
        entries = audit_upgrade.checked_entries(archive, max_entries=64, max_total=25 * 1024**3)
        if {entry.filename for entry in entries} != flashkit.EXPECTED_MEMBERS:
            raise flashkit.SafetyError('Unexpected upgrade ZIP inventory')
        for partition in build_trial.ORDER:
            name = partition + flashkit.SUFFIX
            with archive.open(name) as stream:
                digest, size = flashkit.sha256_stream(stream)
            expected.append({'partition': partition, 'name': name, 'bytes': size, 'sha256': digest})
        if archive.getinfo('boot.zip').file_size > 64 * 1024**2:
            raise flashkit.SafetyError('Unexpected boot delivery size')
        with zipfile.ZipFile(io.BytesIO(archive.read('boot.zip'))) as boot:
            audit_upgrade.checked_entries(boot, max_entries=64, max_total=128 * 1024**2)
            boot_bytes = boot.read(BOOTLOADER)
            config = boot.read('PDX256_XBootConfig_MiscTA.ta')
        if hashlib.sha256(boot_bytes).hexdigest() != BOOTLOADER_SHA256 or hashlib.sha256(config).hexdigest() != BOOT_CONFIG_SHA256:
            raise flashkit.SafetyError('Boot delivery does not match fixed references')
        expected.append({'partition': 'bootloader', 'name': BOOTLOADER, 'bytes': len(boot_bytes), 'sha256': BOOTLOADER_SHA256})
        for record, original in zip(records, expected, strict=True):
            path = destination / 'images' / original['name']
            if (any(record.get(key) != value for key, value in original.items())
                    or path.stat().st_size != original['bytes'] or flashkit.sha256_file(path) != original['sha256']):
                raise flashkit.SafetyError('Staged upgrade image differs from the fixed original: ' + original['name'])
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DESTINATION)
    parser.add_argument('--verify', action='store_true', help='Verify existing materials without recreating them')
    args = parser.parse_args()
    os.umask(0o077)
    with (flashkit.KIT / '.prepare-upgrade.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = verify(destination=args.output) if args.verify else prepare(destination=args.output)['images']
    print(json.dumps({'images_staged': len(result), 'directory': str(args.output),
                      'flash_allowed': False, 'phone_accessed': False}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (flashkit.SafetyError, OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print('PREPARATION STOPPED: ' + str(exc), file=sys.stderr)
        sys.exit(2)
