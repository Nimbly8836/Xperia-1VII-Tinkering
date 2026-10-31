#!/usr/bin/env python3
"""Build a precompiled .265 flashing ZIP on this computer. Never access a phone."""
import argparse
import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import build_trial
import bundle_runtime
import flashkit
import trial

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
LAUNCHER = '''#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export PATH
if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\\n' 'Python 3.10+ is required. See README.txt.' >&2
    exit 2
fi
exec python3 -I -S -B "$HERE/start.py" "$@"
'''


def host_settings():
    system, machine = platform.system(), platform.machine()
    if system not in {'Darwin', 'Linux'} or machine not in {'arm64', 'aarch64', 'x86_64'}:
        raise flashkit.SafetyError('Build on a supported 64-bit macOS or Linux host')
    host = {'system': system, 'machine': machine}
    if system == 'Darwin':
        host['minimum_os'] = platform.mac_ver()[0]
        bundle_runtime.version_tuple(host['minimum_os'])
    else:
        libc, version = platform.libc_ver()
        if libc != 'glibc':
            raise flashkit.SafetyError('Linux release builds currently require glibc')
        bundle_runtime.version_tuple(version)
        host['minimum_glibc'] = version
    return host


def inspect_runtime_dependencies(binary, host):
    if host['system'] == 'Darwin':
        result = subprocess.run(['otool', '-L', str(binary)], capture_output=True, text=True, check=True)
        libraries = [line.strip().split()[0] for line in result.stdout.splitlines()[1:] if line.strip()]
        prefix = '/opt/homebrew' if host['machine'] == 'arm64' else '/usr/local'
        usb = prefix + '/opt/libusb/lib/libusb-1.0.0.dylib'
        if usb not in libraries or any(path != usb and not path.startswith(('/usr/lib/', '/System/Library/Frameworks/')) for path in libraries):
            raise flashkit.SafetyError('macOS release requires standard Homebrew libusb and system libraries only')
    else:
        result = subprocess.run(['readelf', '-d', str(binary)], capture_output=True, text=True, check=True)
        libraries = re.findall(r'\(NEEDED\).*?\[([^\]]+)\]', result.stdout)
        allowed = {'libusb-1.0.so.0', 'libcrypto.so.3', 'libz.so.1', 'libexpat.so.1',
                   'libc.so.6', 'libpthread.so.0', 'libdl.so.2', 'librt.so.1', 'libm.so.6', 'libgcc_s.so.1'}
        if not {'libusb-1.0.so.0', 'libcrypto.so.3'} <= set(libraries) or not set(libraries) <= allowed:
            raise flashkit.SafetyError('Linux release requires OpenSSL 3/libcrypto.so.3 and standard runtime libraries')
    return libraries


def release_name(release, host):
    if not re.fullmatch(r'v[0-9]+(?:\.[0-9]+){0,2}', release):
        raise flashkit.SafetyError('Use a release name such as v1 or v1.1; no paths')
    system = 'macos' if host['system'] == 'Darwin' else 'linux'
    machine = 'arm64' if host['machine'] in {'arm64', 'aarch64'} else 'x86_64'
    return f'Xperia-1VII-FS72-to-FS54-71.1.A.2.265-{system}-{machine}-{release}'


def readme_text(name, host):
    if host['system'] == 'Darwin':
        requirements = ('macOS ' + host['minimum_os'] + ' or newer, ' + host['machine'] + '\n'
                        'Install Python 3.10+, libusb and Android Platform Tools.\n'
                        'Homebrew: brew install python libusb\n'
                        '          brew install --cask android-platform-tools\n'
                        'Keep this package on a local APFS volume. Start: double-click Start.command.')
    else:
        requirements = ('64-bit glibc Linux, ' + host['machine'] + ', glibc >= ' + host['minimum_glibc'] + '\n'
                        'Runtime: Python 3.10+, adb, libusb-1.0, OpenSSL libcrypto.so.3, zlib, expat.\n'
                        'Debian 12: sudo apt-get install python3 adb libusb-1.0-0 libssl3 zlib1g libexpat1\n'
                        'Set Sony USB permissions as documented in the project. Start: bash start.sh')
    return f'''{name}

HIGH RISK: flashing can cause data loss or an unbootable phone. Use at your own risk.
Back up important data and eSIM recovery information first. No recovery guarantee.

PHONE: stock HK XQ-FS72, SKU c001526, 71.1.A.2.265 release-keys,
locked bootloader, Verified Boot green, DSDS, battery >=60%, V36 bootloader.
TARGET: FS54 EU/UK 71.1.A.2.265. NOT a .35 upgrade or a universal flasher.

COMPUTER:
{requirements}
No compiler, original firmware ZIP or source checkout is needed by the user.
Python, ADB and runtime libraries are NOT bundled.
Allow at least 3 GiB spare disk space; Linux sessions additionally copy ~5 GiB.
On Linux, use a disk-backed TMPDIR if /tmp is a small tmpfs.

USE:
1. Verify the ZIP SHA-256 against the publisher's independent release page.
2. Extract the whole package. Do not mix files from different releases.
3. Start Android normally, unlock the phone and authorize USB debugging.
4. Connect only that phone and run the launcher above. Follow its instructions.
5. Actual writes require the full confirmation phrase after device checks.
6. Wait for completion and program exit. Reboot manually as instructed.

The launcher does not automatically retry, wipe user data or reboot.
If a write fails, keep the private session logs; do not blindly retry or reset.

Offline package check: bash start.sh check
Offline simulation:   bash start.sh simulate
These two modes do not access ADB or USB. Do not add output files to this folder.

Source and full instructions:
https://github.com/Nimbly8836/Xperia-1VII-Tinkering
This package contains original selected Sony images, not modified image payloads.
MIT applies to project code, not Sony firmware or external runtime dependencies.
'''


def add_payload(root, relative, content, files, mode=0o644):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(content)
    path.chmod(mode)
    files[relative] = {'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}


def copy_payload(root, relative, source, files, expected=None, mode=0o644):
    if expected is None:
        expected = {'bytes': source.lstat().st_size, 'sha256': bundle_runtime.stable_hash(source)}
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    trial.copy_image_snapshot(source, destination, expected)
    destination.chmod(mode)
    files[relative] = {'bytes': expected['bytes'], 'sha256': expected['sha256']}


def assemble(root, name, release, host, receipt, candidate):
    files = {}
    for relative in bundle_runtime.APP_FILES:
        source = ROOT / Path(relative).name
        expected = None
        if source.name in {'trial.py', 'flashkit.py'}:
            expected = {'bytes': source.stat().st_size, 'sha256': receipt['input_sha256'][source.name]}
        copy_payload(root, relative, source, files, expected)
    copy_payload(root, bundle_runtime.BINARY_FILE, trial.BINARY, files,
                 {'bytes': trial.BINARY.stat().st_size, 'sha256': receipt['binary_sha256']}, 0o755)
    for filename in ['LICENSE', 'THIRD_PARTY_NOTICES.md']:
        copy_payload(root, filename, PROJECT / filename, files)
    for filename in ['Start.command', 'start.sh']:
        add_payload(root, filename, LAUNCHER.encode(), files, 0o755)
    add_payload(root, 'README.txt', readme_text(name, host).encode(), files)
    images = []
    for item in candidate['images']:
        record = {key: item[key] for key in ['partition', 'name', 'bytes', 'sha256']}
        copy_payload(root, 'images/' + item['name'], flashkit.CANDIDATE / 'images' / item['name'], files, record, 0o400)
        images.append(record)
    manifest = {'schema': 1, 'profile': bundle_runtime.PROFILE, 'release': release,
                'host': host, 'source_zip_sha256': flashkit.SOURCE_SHA256,
                'baseline': trial.TRIAL_BASELINE, 'images': images, 'files': files,
                'native_build_inputs': receipt['input_sha256'], 'native_guard_self_test': True,
                'native_runtime_libraries': receipt.get('runtime_libraries', []),
                'runtime_dependencies_bundled': False, 'real_device_flashing_tested_during_build': False}
    raw = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()
    (root / 'manifest.json').write_bytes(raw)
    pinned = hashlib.sha256(raw).hexdigest()
    template = (ROOT / 'bundle_start.py.in').read_text()
    launcher = build_trial.replace_once(template, '__MANIFEST_SHA256__', pinned)
    (root / 'start.py').write_text(launcher)
    return pinned


def archive_bundle(root, destination, name):
    # Caller creates destination with .partial suffix; ZIP64 supports super >4GiB.
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
        for path in sorted(root.rglob('*')):
            if path.is_file():
                archive.write(path, name + '/' + path.relative_to(root).as_posix())


def verify_archive(path, name, manifest_sha, start_sha):
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        prefix = name + '/'
        if len(names) != len(set(names)):
            raise flashkit.SafetyError('Duplicate release ZIP members')
        info = archive.getinfo(prefix + 'manifest.json')
        if info.file_size > 1024 * 1024:
            raise flashkit.SafetyError('Unexpected archive manifest size')
        raw = archive.read(info)
        if hashlib.sha256(raw).hexdigest() != manifest_sha:
            raise flashkit.SafetyError('Archived manifest differs from built release')
        try:
            manifest = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise flashkit.SafetyError('Invalid archived release manifest') from exc
        expected = {prefix + relative: record['sha256'] for relative, record in manifest['files'].items()}
        expected.update({prefix + 'manifest.json': manifest_sha, prefix + 'start.py': start_sha})
        if set(names) != set(expected):
            raise flashkit.SafetyError('Release ZIP contains missing or unexpected files')
        for entry in entries:
            with archive.open(entry) as stream:
                digest, count = flashkit.sha256_stream(stream)
            if count != entry.file_size or digest != expected[entry.filename]:
                raise flashkit.SafetyError('Archived file does not match the built release')


def build_bundle(output_dir, release):
    host = host_settings()
    name = release_name(release, host)
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    final = output_dir / name
    archive = output_dir / (name + '.zip')
    checksum = output_dir / (name + '.zip.sha256')
    with (output_dir / '.bundle-build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if any(os.path.lexists(path) for path in (final, archive, checksum)):
            raise flashkit.SafetyError('Release output already exists; choose a new release name')
        if not flashkit.CANDIDATE.exists():
            flashkit.prepare()
        # build() rechecks every candidate against the fixed original ZIP.
        build_trial.build()
        receipt = trial.checked_build()
        receipt['runtime_libraries'] = inspect_runtime_dependencies(trial.BINARY, host)
        candidate = flashkit.read_json(flashkit.CANDIDATE / 'manifest.json')
        required = 2 * sum(item['bytes'] for item in candidate['images']) + flashkit.RESERVE_BYTES
        if shutil.disk_usage(output_dir).free < required:
            raise flashkit.SafetyError('Not enough space for release directory, ZIP and reserve')
        work = Path(tempfile.mkdtemp(prefix='.bundle-building-', dir=output_dir))
        partial = output_dir / (name + '.zip.partial')
        if os.path.lexists(partial):
            raise flashkit.SafetyError('Incomplete archive exists; inspect it before building again')
        try:
            pin = assemble(work, name, release, host, receipt, candidate)
            # This uses ONLY the assembled package, under isolated Python: no
            # source checkout imports, original ZIP, compiler, ADB or USB.
            subprocess.run([sys.executable, '-I', '-S', '-B', str(work / 'start.py'), 'check'], check=True)
            trial.checked_build()  # Refuse if original build inputs changed while copying.
            start_sha = bundle_runtime.stable_hash(work / 'start.py')
            archive_bundle(work, partial, name)
            verify_archive(partial, name, pin, start_sha)
            archive_sha = bundle_runtime.stable_hash(partial)
            if any(os.path.lexists(path) for path in (final, archive, checksum)):
                raise flashkit.SafetyError('Output appeared during build; refusing replacement')
            # Hard-link publication is only for the completed ZIP, never images.
            os.link(partial, archive)
            partial.unlink()
            work.rename(final)
            final.chmod(0o755)
            with checksum.open('x') as stream:
                stream.write(archive_sha + '  ' + archive.name + '\n')
            print(json.dumps({'directory': str(final), 'zip': str(archive), 'sha256': archive_sha,
                              'bytes': archive.stat().st_size, 'manifest_sha256': pin,
                              'phone_accessed': False}, indent=2))
            return final, archive
        except BaseException:
            # Keep incomplete local artifacts for diagnosis; never publish them
            # under a new version without rerunning all checks.
            print('Incomplete build retained at: ' + str(work), file=sys.stderr)
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', default='v1')
    parser.add_argument('--output-dir', type=Path, default=PROJECT / 'dist')
    args = parser.parse_args(argv)
    os.umask(0o077)
    build_bundle(args.output_dir, args.release)


if __name__ == '__main__':
    try:
        main()
    except (flashkit.SafetyError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print('BUNDLE BUILD STOPPED: ' + str(exc), file=sys.stderr)
        sys.exit(2)
