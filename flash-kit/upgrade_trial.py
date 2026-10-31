#!/usr/bin/env python3
"""Experimental fixed FS54 .265 -> .35 upgrade, including V40 bootloader A.

simulate/check never access a phone. run needs fresh Android checks, Flash-mode
checks and a separate full typed confirmation. No automatic reboot or retry.
"""
import argparse
import gzip
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import bundle_runtime
import flashkit
import prepare_upgrade
import trial
import upgrade_preflight

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / 'build-upgrade'
BINARY = BUILD / 'fs54-265-to-35-v40'
RECEIPT = BUILD / 'build-receipt.json'
RAW_BOOT = BUILD / 'bootloader-uncompressed.sin'
RAW_BOOT_BYTES = 14085120
RAW_BOOT_SHA256 = 'bff3c1cae37e77aa69be689ecba02b772e282e02edcc476003b859a1bf9c67a8'
INPUTS = {'upstream/newflasher-59f12e4.c.txt', 'build_trial.py', 'build_upgrade.py',
          'upgrade_trial.py', 'upgrade_preflight.py', 'prepare_upgrade.py', 'audit_upgrade.py',
          'flashkit.py', 'trial.py', 'bundle_runtime.py', 'trial_policy.c.in', 'trial_main.c.in',
          'build-upgrade/trial_images.h', 'build-upgrade/bootloader-uncompressed.sin'}
FAULTS = ['data-fail-prefix', 'data-okay-prefix', 'super-slot-failure', 'snapshot-merging', 'commit-cancel',
          'bootloader-slot-failure', 'boot-config-mismatch', 'bootloader-flash-failure']


def unwrap_bootloader(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise flashkit.SafetyError('Bootloader source must be a regular file')
        signature = flashkit.file_signature(info)
        if flashkit.sha256_stream(source)[0] != prepare_upgrade.BOOTLOADER_SHA256:
            raise flashkit.SafetyError('Original commercial bootloader GZIP hash mismatch')
        source.seek(0)
        with gzip.GzipFile(fileobj=source, mode='rb') as decoded:
            raw = decoded.read(RAW_BOOT_BYTES + 1)
        flashkit.assert_source_stable(path, source, signature)
    if len(raw) != RAW_BOOT_BYTES or hashlib.sha256(raw).hexdigest() != RAW_BOOT_SHA256:
        raise flashkit.SafetyError('Unwrapped bootloader TAR differs from the fixed original')
    return raw


def normalized_images(original):
    records = [{key: item[key] for key in ('partition', 'name', 'bytes', 'sha256')} for item in original]
    if len(records) != 15 or records[-1]['partition'] != 'bootloader' or records[-1]['sha256'] != prepare_upgrade.BOOTLOADER_SHA256:
        raise flashkit.SafetyError('Commercial bootloader must be the last fixed image')
    records[-1] = {**records[-1], 'bytes': RAW_BOOT_BYTES, 'sha256': RAW_BOOT_SHA256}
    return records


class UpgradeMaterials:
    def checked_build(self):
        record = flashkit.read_json(RECEIPT)
        if (not isinstance(record, dict) or record.get('trial_plan') != 'upgrade-35'
                or record.get('source_zip_sha256') != prepare_upgrade.RELEASE['sha256']
                or record.get('confirmation') != trial.UPGRADE_PHRASE
                or record.get('host_system') != platform.system() or record.get('host_machine') != platform.machine()):
            raise flashkit.SafetyError('Rebuild the fixed .35 upgrade on this host before using it')
        hashes = record.get('input_sha256')
        if not isinstance(hashes, dict) or set(hashes) != INPUTS:
            raise flashkit.SafetyError('Upgrade build input list mismatch')
        for relative, digest in hashes.items():
            if bundle_runtime.stable_hash(ROOT / relative) != digest:
                raise flashkit.SafetyError('Upgrade source/build input changed; rebuild and retest')
        if (bundle_runtime.stable_hash(BUILD / 'upgrade-writer.c') != record.get('generated_sha256')
                or bundle_runtime.stable_hash(BINARY) != record.get('binary_sha256')
                or bundle_runtime.stable_hash(RAW_BOOT, RAW_BOOT_BYTES) != RAW_BOOT_SHA256):
            raise flashkit.SafetyError('Upgrade binary or bootloader TAR mismatch')
        return record

    def snapshot_images(self, session):
        receipt = self.checked_build()
        images = normalized_images(prepare_upgrade.verify())
        if receipt.get('images') != images:
            raise flashkit.SafetyError('Build image list differs from fixed .35 source')
        if platform.system() == 'Linux' and shutil.disk_usage(session).free < sum(item['bytes'] for item in images) + flashkit.RESERVE_BYTES:
            raise flashkit.SafetyError('Not enough space for independent upgrade snapshots')
        destination = session / 'images'
        destination.mkdir(mode=0o700)
        for item in images:
            original = RAW_BOOT if item['partition'] == 'bootloader' else prepare_upgrade.DESTINATION / 'images' / item['name']
            trial.copy_image_snapshot(original, destination / item['name'], item)
        (session / 'input-manifest.json').write_text(json.dumps({'trial_plan': 'upgrade-35', 'images': images}, indent=2) + '\n')
        return destination

    def android_baseline(self, serial):
        baseline = upgrade_preflight.android_baseline(serial)
        result = subprocess.run(['adb', '-s', serial, 'shell', 'getprop', 'ro.boot.slot_suffix'], capture_output=True, text=True, timeout=20, check=False)
        if result.returncode or result.stdout.strip() != '_a':
            raise flashkit.SafetyError('The reviewed upgrade requires source slot A; stop for a different layout')
        return baseline

    def native(self, arguments, cwd, log):
        self.checked_build()
        return trial.native(arguments, cwd, log, binary=BINARY)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    modes.add_parser('check', help='Verify local build and self-test; no phone access')
    simulation = modes.add_parser('simulate', help='Fixed 15-image protocol simulation; no ADB/USB')
    faults = simulation.add_mutually_exclusive_group()
    faults.add_argument('--fault', choices=FAULTS)
    faults.add_argument('--fail-at', type=int)
    live = modes.add_parser('run', help='REAL writes only after fresh checks and explicit V40 confirmation')
    live.add_argument('--serial')
    args = parser.parse_args(argv)
    os.umask(0o077)
    materials = UpgradeMaterials()
    materials.checked_build()
    if args.mode == 'check':
        result = subprocess.run([str(BINARY), '--self-test'], capture_output=True, text=True, timeout=60, check=False)
        if result.returncode or 'TRIAL_GUARD_SELF_TEST_OK_NO_USB' not in result.stdout:
            raise flashkit.SafetyError('Upgrade native self-test failed')
        print('UPGRADE_BUILD_OK_NO_PHONE_ACCESS')
        return 0
    if args.mode == 'simulate':
        return trial.simulate(fail_at=args.fail_at, fault=args.fault, materials=materials)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise flashkit.SafetyError('Real upgrade requires your interactive terminal')
    serial = bundle_runtime.select_device(args.serial)
    return trial.run(serial, materials=materials, plan='upgrade-35')


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (flashkit.SafetyError, OSError, ValueError, subprocess.SubprocessError, KeyboardInterrupt, EOFError) as exc:
        message = str(exc) if isinstance(exc, flashkit.SafetyError) else type(exc).__name__
        print('UPGRADE STOPPED: ' + message, file=sys.stderr)
        sys.exit(2)
