"""Runtime for a pinned prebuilt .265 bundle; no source ZIP or compiler needed."""
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import flashkit
import trial

PROFILE = 'fs72-hk-265-to-fs54-eu-265'
APP_FILES = ('app/bundle_runtime.py', 'app/flashkit.py', 'app/trial.py')
BINARY_FILE = 'bin/fs72-preserve-trial'
SUPPORT_FILES = ('Start.command', 'start.sh', 'README.txt', 'LICENSE', 'THIRD_PARTY_NOTICES.md')


def stable_hash(path, expected_bytes=None):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or (expected_bytes is not None and info.st_size != expected_bytes):
            raise flashkit.SafetyError('Bundle file type/size mismatch: ' + path.name)
        signature = flashkit.file_signature(info)
        flashkit.assert_source_stable(path, stream, signature)
        digest, _ = flashkit.sha256_stream(stream)
        flashkit.assert_source_stable(path, stream, signature)
        return digest


def read_manifest(root, expected_sha):
    path = root / 'manifest.json'
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 1024 * 1024:
            raise flashkit.SafetyError('Invalid bundle manifest')
        raw = stream.read(1024 * 1024 + 1)
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise flashkit.SafetyError('Bundle manifest changed; obtain the original release again')
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise flashkit.SafetyError('Invalid JSON in bundle manifest') from exc


def version_tuple(text):
    if not isinstance(text, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+){0,3}', text):
        raise flashkit.SafetyError('Invalid host version in bundle')
    try:
        values = tuple(int(part) for part in text.split('.'))
    except ValueError as exc:
        raise flashkit.SafetyError('Invalid numeric host version') from exc
    return values + (0,) * (4 - len(values))


class PrebuiltBundle:
    def __init__(self, root, expected_manifest_sha):
        self.root = Path(root).resolve()
        self.expected_manifest_sha = expected_manifest_sha
        self.binary = self.root / BINARY_FILE

    def checked_build(self):
        record = read_manifest(self.root, self.expected_manifest_sha)
        if (not isinstance(record, dict) or type(record.get('schema')) is not int or record['schema'] != 1
                or record.get('profile') != PROFILE or record.get('source_zip_sha256') != flashkit.SOURCE_SHA256
                or record.get('baseline') != trial.TRIAL_BASELINE):
            raise flashkit.SafetyError('Bundle is not the fixed HK FS72 .265 release')
        host = record.get('host')
        if not isinstance(host, dict) or host.get('system') != platform.system() or host.get('machine') != platform.machine():
            raise flashkit.SafetyError('Wrong package for this computer; use the matching OS/CPU release')
        if platform.system() == 'Darwin':
            if version_tuple(platform.mac_ver()[0]) < version_tuple(host.get('minimum_os')):
                raise flashkit.SafetyError('This package requires a newer macOS version; see README.txt')
        elif platform.system() == 'Linux':
            libc, version = platform.libc_ver()
            if libc != 'glibc' or version_tuple(version) < version_tuple(host.get('minimum_glibc')):
                raise flashkit.SafetyError('This package requires a matching glibc Linux system; see README.txt')
        else:
            raise flashkit.SafetyError('Unsupported bundle host')
        images = record.get('images')
        if not isinstance(images, list) or len(images) != len(flashkit.CANDIDATE_PARTITIONS):
            raise flashkit.SafetyError('Incomplete bundle image list')
        if any(not isinstance(item, dict) or not isinstance(item.get('partition'), str) for item in images):
            raise flashkit.SafetyError('Invalid bundle image record')
        if {item['partition'] for item in images} != set(flashkit.CANDIDATE_PARTITIONS):
            raise flashkit.SafetyError('Unexpected or duplicate image target')
        for item in images:
            if item.get('name') != item['partition'] + flashkit.SUFFIX:
                raise flashkit.SafetyError('Unexpected bundle image name')
        expected = set(APP_FILES) | {BINARY_FILE} | set(SUPPORT_FILES) | {'images/' + item['name'] for item in images}
        files = record.get('files')
        if not isinstance(files, dict) or set(files) != expected:
            raise flashkit.SafetyError('Bundle file list does not match the fixed layout')
        for relative, item in files.items():
            if (not isinstance(item, dict) or type(item.get('bytes')) is not int or item['bytes'] <= 0
                    or not isinstance(item.get('sha256'), str) or not re.fullmatch('[a-f0-9]{64}', item['sha256'])):
                raise flashkit.SafetyError('Invalid bundle size/digest record')
            path = self.root / relative
            if not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_size != item['bytes']:
                raise flashkit.SafetyError('Bundle file missing, replaced or truncated: ' + relative)
        for image in images:
            if files['images/' + image['name']] != {'bytes': image.get('bytes'), 'sha256': image.get('sha256')}:
                raise flashkit.SafetyError('Image digest disagrees with pinned file list')
        actual = set()
        for path in self.root.rglob('*'):
            info = path.lstat()
            relative = path.relative_to(self.root).as_posix()
            if stat.S_ISDIR(info.st_mode):
                if relative not in {'app', 'bin', 'images'}:
                    raise flashkit.SafetyError('Unexpected bundle directory: ' + relative)
            elif stat.S_ISREG(info.st_mode):
                if path.name != '.DS_Store':
                    actual.add(relative)
            else:
                raise flashkit.SafetyError('Links and special files are not allowed in a bundle')
        if actual != expected | {'manifest.json', 'start.py'}:
            raise flashkit.SafetyError('Unexpected or missing files in bundle; extract a clean copy')
        # The large images are hashed by verify() or while copying snapshots,
        # and again by the native writer before it can open USB.
        for relative in set(APP_FILES) | {BINARY_FILE} | set(SUPPORT_FILES):
            item = files[relative]
            if stable_hash(self.root / relative, item['bytes']) != item['sha256']:
                raise flashkit.SafetyError('Bundle file checksum mismatch: ' + relative)
        return {**record, 'binary_sha256': files[BINARY_FILE]['sha256']}

    def self_test(self):
        self.checked_build()
        try:
            if not os.access(self.binary, os.X_OK):
                raise flashkit.SafetyError('Writer is not executable; re-extract with an archive tool that preserves permissions')
            result = subprocess.run([str(self.binary), '--self-test'], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            raise flashkit.SafetyError('Cannot start included writer. Check runtime dependencies in README.txt') from exc
        if result.returncode or 'TRIAL_GUARD_SELF_TEST_OK_NO_USB' not in result.stdout:
            raise flashkit.SafetyError('Writer self-test failed. Check runtime dependencies in README.txt; no phone operation started')

    def verify(self):
        record = self.checked_build()
        for item in record['images']:
            if stable_hash(self.root / 'images' / item['name'], item['bytes']) != item['sha256']:
                raise flashkit.SafetyError('Image checksum mismatch: ' + item['name'])
        self.self_test()
        return record

    def snapshot_images(self, session):
        record = self.checked_build()
        if platform.system() == 'Linux':
            required = sum(item['bytes'] for item in record['images']) + flashkit.RESERVE_BYTES
            if shutil.disk_usage(session).free < required:
                raise flashkit.SafetyError('Not enough temporary disk space for image copies')
        images = session / 'images'
        images.mkdir(mode=0o700)
        for item in record['images']:
            trial.copy_image_snapshot(self.root / 'images' / item['name'], images / item['name'], item)
        (session / 'input-manifest.json').write_text(json.dumps({'images': record['images'],
            'bundle_manifest_sha256': self.expected_manifest_sha}, indent=2) + '\n')
        return images

    def native(self, arguments, cwd, log):
        self.checked_build()
        return trial.native(arguments, cwd, log, binary=self.binary)


def select_device(wanted=None):
    if shutil.which('adb') is None:
        raise flashkit.SafetyError('ADB is not installed. Install Android Platform Tools first')
    result = subprocess.run(['adb', 'devices'], capture_output=True, text=True, timeout=20)
    rows = result.stdout.splitlines()
    if result.returncode or not rows or rows[0].strip() != 'List of devices attached':
        raise flashkit.SafetyError('Cannot list ADB devices; check the USB connection')
    devices = [row.split() for row in rows[1:] if row.strip()]
    if len(devices) != 1 or len(devices[0]) != 2 or devices[0][1] != 'device':
        raise flashkit.SafetyError('Connect exactly one phone, unlock it and authorize USB debugging')
    serial = devices[0][0]
    trial.validate_serial(serial)
    if wanted is not None and wanted != serial:
        raise flashkit.SafetyError('Connected phone does not match the requested serial')
    return serial


def main(root, expected_manifest_sha, argv=None):
    parser = argparse.ArgumentParser(description='Prebuilt HK FS72 .265 to FS54 .265 flashing package')
    parser.add_argument('mode', nargs='?', choices=['run', 'check', 'simulate'], default='run')
    parser.add_argument('--serial', help='Optional explicit USB serial; otherwise require exactly one authorized phone')
    parser.add_argument('--fault', choices=['data-fail-prefix', 'data-okay-prefix', 'super-slot-failure', 'snapshot-merging'])
    args = parser.parse_args(argv)
    if args.fault and args.mode != 'simulate':
        parser.error('--fault is simulation-only')
    os.umask(0o077)
    if args.mode == 'run' and (not sys.stdin.isatty() or not sys.stdout.isatty()):
        raise flashkit.SafetyError('Open this package in your own terminal; interactive confirmation is required')
    bundle = PrebuiltBundle(root, expected_manifest_sha)
    if args.mode == 'check':
        bundle.verify()
        print('PACKAGE_OK: 14 images and included writer verified. No phone access.')
        return 0
    bundle.self_test()
    if args.mode == 'simulate':
        return trial.simulate(fault=args.fault, materials=bundle)
    serial = select_device(args.serial)
    print('One authorized phone found. Starting device checks; flashing still requires your confirmation.')
    return trial.run(serial, materials=bundle)
