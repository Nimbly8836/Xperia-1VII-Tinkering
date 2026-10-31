#!/usr/bin/env python3
"""Offline candidate preparation and optional read-only ADB preflight.

This revision cannot flash. The execute subcommand always refuses, regardless
of files, flags, or edited manifests. No flashing executable is invoked.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

KIT = Path(__file__).resolve().parent
PROJECT = KIT.parent
SOURCE = PROJECT / 'firmware-downloads/packages/fs54-eu-71.1.A.2.265/APP-SW_PDX256_GLOBALEEA-A4_USER_71.1.A.2.265_X-FLASH-ALL-B083_COM.zip'
SOURCE_SHA256 = 'd272727231a31b22402c4564f387ebd91b9958e5ba8485f8925ea2cb9d813465'
CANDIDATE = KIT / 'candidate-fs54-eu-71.1.A.2.265-NOT-APPROVED'
SUFFIX = '_X-FLASH-ALL-B083.sin'
CANDIDATE_PARTITIONS = (
    'bluetooth', 'boot', 'dsp', 'dtbo', 'featenabler', 'init_boot', 'modem',
    'pvmfw', 'recovery', 'spuservice', 'super', 'vbmeta', 'vbmeta_system', 'vendor_boot',
)
PRESERVED_PARTITIONS = ('appslog', 'diag', 'metadata', 'misc', 'modemst1', 'modemst2', 'persist', 'userdata')
EXCLUDED_CONTROL_FILES = {
    'auto-boot.ta', 'osv-restriction.ta', 'reset-kernel-cmd-debug.ta',
    'reset-retail-demo-active-sts.ta', 'boot.zip', 'partition.zip',
}
REFERENCE_FILES = {'odm.map', 'update.xml', 'securitypatchlevel.dat'}
EXPECTED_MEMBERS = ({p + SUFFIX for p in CANDIDATE_PARTITIONS + PRESERVED_PARTITIONS}
                    | EXCLUDED_CONTROL_FILES | REFERENCE_FILES)
POLICY = {
    'goal': 'dual_physical_sim_preserved_and_esim_switchable',
    'data_policy': 'no_intentional_wipe_residual_failure_risk_accepted',
    'authorization': 'preparation_only',
    'flash_allowed': False,
    'sony_signature_verified': False,
}
BLOCKERS = (
    '本机 physical+eSIM 组合能力及有效开关尚未验证；只读查询未取得能力值。',
    '尚未批准能保留双实体卡切换能力的签名镜像/基带配置组合。',
    '原机 HK .248 恢复材料及非擦除恢复条件尚未完成审核。',
    '实际刷写工具、隐式 TA/槽位操作及最终写入清单尚未批准。',
    '用户只授权准备；本版本没有手机写入实现，也没有 force/解锁开关。',
)
README_TEXT = '''NOT APPROVED FOR FLASHING / 禁止直接刷写

This directory is an offline review candidate, not a Newflasher firmware folder.
No flasher, TA, userdata, metadata, persist, modemst, partition or boot-delivery
files are included. Kernel boot SIN is distinct from bootloader delivery.
The 14 collected images are NOT an approved write list.

Do NOT copy Newflasher into this directory or images/ and run it. A partial
folder may fail after some writes, and tool-internal TA operations are not
controlled merely by excluding files. Do not add files or rename partitions.
Use flashkit.py verify to recheck this candidate against its pinned source ZIP.
The execute command in this revision is permanently blocked.
'''
BASELINE = {
    'ro.product.model': 'XQ-FS72',
    'ro.build.display.id': '71.1.A.2.248 release-keys',
    'ro.boot.hardware.sku': 'c001526',
    'ro.boot.flash.locked': '1',
    'ro.boot.verifiedbootstate': 'green',
    'persist.radio.multisim.config': 'dsds',
}
RESERVE_BYTES = 3 * 1024**3
CHUNK_BYTES = 4 * 1024**2
BLOCKED_EXIT = 78


class SafetyError(Exception):
    """Stop rather than make an unreviewed assumption."""


def sha256_stream(stream):
    digest = hashlib.sha256()
    count = 0
    for block in iter(lambda: stream.read(CHUNK_BYTES), b''):
        digest.update(block)
        count += len(block)
    return digest.hexdigest(), count


def sha256_file(path):
    with path.open('rb') as stream:
        return sha256_stream(stream)[0]


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise SafetyError(f'Invalid JSON: {path.name}') from exc


def classify(name):
    if name in {p + SUFFIX for p in CANDIDATE_PARTITIONS}:
        return 'candidate_only_not_approved'
    if name in {p + SUFFIX for p in PRESERVED_PARTITIONS}:
        return 'preserve_do_not_stage'
    if name in EXCLUDED_CONTROL_FILES:
        return 'control_or_identity_excluded'
    if name in REFERENCE_FILES:
        return 'reference_only_not_staged'
    raise SafetyError(f'Unreviewed source member: {name}')


def file_signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def assert_source_stable(source, handle, initial):
    try:
        current = os.fstat(handle.fileno())
        named = source.lstat()
    except OSError as exc:
        raise SafetyError('Source disappeared or became unreadable during operation') from exc
    if not stat.S_ISREG(named.st_mode) or file_signature(current) != initial or file_signature(named) != initial:
        raise SafetyError('Source was replaced or modified during operation')


@contextlib.contextmanager
def source_snapshot(source, expected_sha):
    # Hash and ZIP reads use the same no-follow descriptor. Metadata and path
    # identity are checked before/after use, including in-place modifications.
    try:
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise SafetyError('Cannot open the original source ZIP without following links') from exc
    with os.fdopen(descriptor, 'rb') as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise SafetyError('Source is not a regular file')
        initial = file_signature(info)
        assert_source_stable(source, handle, initial)
        digest, _ = sha256_stream(handle)
        if digest != expected_sha:
            raise SafetyError('Source SHA-256 mismatch; refusing this version or modified archive')
        assert_source_stable(source, handle, initial)
        handle.seek(0)
        with zipfile.ZipFile(handle) as archive:
            yield archive
        assert_source_stable(source, handle, initial)


def audit_archive(archive, source_name, expected_sha):
    entries = archive.infolist()
    names = [entry.filename for entry in entries]
    if len(names) != len(set(names)) or set(names) != EXPECTED_MEMBERS:
        raise SafetyError('Source member set differs from the reviewed 31-file package')
    result = []
    for entry in entries:
        if entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16) or Path(entry.filename).name != entry.filename or '\\' in entry.filename:
            raise SafetyError('Unsafe ZIP member type or path')
        result.append({'name': entry.filename, 'bytes': entry.file_size,
                       'role': classify(entry.filename)})
    return {'source_name': source_name, 'source_sha256': expected_sha,
            'target': 'XQ-FS54_Customized_EU_UK_71.1.A.2.265',
            'policy': dict(POLICY), 'members': result,
            'candidate_bytes': sum(e['bytes'] for e in result if e['role'] == 'candidate_only_not_approved')}


def audit_source(source=SOURCE, expected_sha=SOURCE_SHA256):
    with source_snapshot(source, expected_sha) as archive:
        result = audit_archive(archive, source.name, expected_sha)
    return result


def inspect_sin(path, partition):
    """Check container target names only; do NOT claim signature verification."""
    if path.is_symlink() or not path.is_file():
        raise SafetyError('SIN must be a regular file')
    payloads = []
    size = path.stat().st_size
    with tarfile.open(path, mode='r:') as archive:
        members = archive.getmembers()
        if len(members) < 2 or len(members) > 512:
            raise SafetyError('Unexpected SIN member count')
        for index, member in enumerate(members):
            expected = f'{partition}.cms' if index == 0 else f'{partition}.{index-1:03d}'
            if member.name != expected or not member.isfile() or member.issparse() or member.size <= 0:
                raise SafetyError(f'SIN internal target/type mismatch for {partition}')
            if member.offset_data + member.size > size:
                raise SafetyError('SIN member exceeds file bounds')
            if index == 0 and member.size > 1024**2:
                raise SafetyError('Unexpected CMS size')
            payloads.append({'name': member.name, 'bytes': member.size})
    return payloads


def prepare(source=SOURCE, destination=CANDIDATE, expected_sha=SOURCE_SHA256):
    if destination.exists() or destination.is_symlink():
        raise SafetyError('Destination already exists; verify it, do not overwrite or merge')
    work = None
    try:
        with source_snapshot(source, expected_sha) as archive:
            audit = audit_archive(archive, source.name, expected_sha)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(destination.parent).free < audit['candidate_bytes'] + RESERVE_BYTES:
                raise SafetyError('Insufficient disk space with 3 GiB reserve; no automatic cleanup')
            work = Path(tempfile.mkdtemp(prefix='.' + destination.name + '.building-', dir=destination.parent))
            images = work / 'images'
            images.mkdir()
            manifest = {'schema': 1, 'policy': dict(POLICY), 'source_sha256': expected_sha,
                        'source_name': source.name, 'target': audit['target'], 'images': [],
                        'blockers': list(BLOCKERS)}
            for partition in CANDIDATE_PARTITIONS:
                name = partition + SUFFIX
                target = images / name
                digest = hashlib.sha256()
                count = 0
                with archive.open(name) as src, target.open('xb') as dst:
                    for block in iter(lambda: src.read(CHUNK_BYTES), b''):
                        if shutil.disk_usage(work).free < RESERVE_BYTES + len(block):
                            raise SafetyError('Disk reserve reached; no completed package published')
                        dst.write(block)
                        digest.update(block)
                        count += len(block)
                if count != archive.getinfo(name).file_size:
                    raise SafetyError('Extracted size mismatch')
                members = inspect_sin(target, partition)
                manifest['images'].append({'partition': partition, 'name': name, 'bytes': count,
                                           'sha256': digest.hexdigest(), 'sin_members': members,
                                           'decision': 'candidate_only_not_approved'})
                target.chmod(0o400)
                print(f'PREPARED FOR REVIEW: {name} ({count} bytes)', flush=True)
            (work / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
            (work / 'NOT_APPROVED.txt').write_text(README_TEXT)
        # Publish only after the source descriptor/path stability guard passes.
        if destination.exists() or destination.is_symlink():
            raise SafetyError('Destination appeared during preparation; refusing replacement')
        work.rename(destination)
    except BaseException:
        if work is not None:
            print(f'INCOMPLETE REVIEW BUILD RETAINED: {work}', file=sys.stderr)
        raise
    return manifest


def verify(source=SOURCE, destination=CANDIDATE, expected_sha=SOURCE_SHA256):
    if destination.is_symlink() or not destination.is_dir():
        raise SafetyError('Candidate directory is missing or is a symlink')
    expected_files = {'manifest.json', 'NOT_APPROVED.txt'} | {'images/' + p + SUFFIX for p in CANDIDATE_PARTITIONS}
    actual_files = set()
    for path in destination.rglob('*'):
        if path.is_symlink():
            raise SafetyError('Symlinks are not allowed in candidate')
        relative = str(path.relative_to(destination))
        if path.is_dir():
            if relative != 'images':
                raise SafetyError('Unexpected directory in candidate')
        elif path.is_file():
            actual_files.add(relative)
        else:
            raise SafetyError('Unexpected filesystem object in candidate')
    if actual_files != expected_files:
        raise SafetyError('Candidate contains missing or unexpected files; no flasher/TA/control additions allowed')
    manifest = read_json(destination / 'manifest.json')
    if not isinstance(manifest, dict):
        raise SafetyError('Candidate manifest must be a JSON object')
    if type(manifest.get('schema')) is not int or manifest.get('schema') != 1 or manifest.get('policy') != POLICY or manifest.get('source_sha256') != expected_sha or manifest.get('source_name') != source.name or manifest.get('blockers') != list(BLOCKERS):
        raise SafetyError('Candidate policy/source metadata mismatch')
    if (destination / 'NOT_APPROVED.txt').read_text() != README_TEXT:
        raise SafetyError('Candidate warning marker was changed')
    records = manifest.get('images')
    if not isinstance(records, list) or any(not isinstance(r, dict) or not isinstance(r.get('partition'), str) for r in records):
        raise SafetyError('Candidate images must be a list of partition records')
    if len(records) != len(CANDIDATE_PARTITIONS) or {r['partition'] for r in records} != set(CANDIDATE_PARTITIONS):
        raise SafetyError('Candidate image manifest is incomplete or duplicated')
    by_partition = {r['partition']: r for r in records}
    with source_snapshot(source, expected_sha) as archive:
        audit = audit_archive(archive, source.name, expected_sha)
        if manifest.get('target') != audit['target']:
            raise SafetyError('Candidate target mismatch')
        for partition in CANDIDATE_PARTITIONS:
            name = partition + SUFFIX
            path = destination / 'images' / name
            entry = by_partition[partition]
            with archive.open(name) as original:
                original_sha, size = sha256_stream(original)
            if entry.get('name') != name or entry.get('decision') != 'candidate_only_not_approved' or entry.get('bytes') != size or path.stat().st_size != size or entry.get('sha256') != original_sha or sha256_file(path) != original_sha:
                raise SafetyError(f'Candidate differs from pinned original: {name}')
            if entry.get('sin_members') != inspect_sin(path, partition):
                raise SafetyError('SIN internal target report mismatch')
    return {'candidate_integrity_verified': True, 'images': len(records), 'flash_allowed': False,
            'goal_verified': False, 'candidate_bytes': audit['candidate_bytes'], 'blockers': list(BLOCKERS)}


def adb_read(serial, arguments):
    if not re.fullmatch(r'[A-Za-z0-9._:-]+', serial):
        raise SafetyError('Invalid explicit device serial')
    approved = [['getprop', key] for key in BASELINE] + [['dumpsys', 'battery']]
    if arguments not in approved:
        raise SafetyError('ADB command is not on the fixed read-only allowlist')
    try:
        process = subprocess.run(['adb', '-s', serial, 'shell', *arguments], capture_output=True,
                                 text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SafetyError('Read-only ADB query unavailable or timed out; no retry') from exc
    if process.returncode:
        raise SafetyError('Read-only ADB query failed; no retries or privilege escalation')
    return process.stdout.strip()


def preflight(serial, expected=None):
    expected = BASELINE if expected is None else expected
    if not isinstance(expected, dict) or set(expected) != set(BASELINE) or any(not isinstance(v, str) for v in expected.values()):
        raise SafetyError('Unreviewed baseline property set')
    observed = {key: adb_read(serial, ['getprop', key]) for key in BASELINE}
    mismatches = [key for key, value in expected.items() if observed[key] != value]
    battery = adb_read(serial, ['dumpsys', 'battery'])
    levels = re.findall(r'^\s*level:\s*(\d+)\s*$', battery, re.MULTILINE)
    if len(levels) != 1:
        raise SafetyError('Battery level is not unambiguous')
    try:
        level = int(levels[0])
    except ValueError as exc:
        raise SafetyError('Invalid battery level') from exc
    baseline_ok = not mismatches and 60 <= level <= 100
    return {'baseline_matches': baseline_ok, 'observed': observed, 'mismatched_properties': mismatches,
            'battery_percent': level, 'flash_allowed': False,
            'capability_verified': False, 'blockers': list(BLOCKERS)}


def refuse_execution():
    print('BLOCKED: 本版本不执行手机写入；未运行任何刷写器。')
    for reason in BLOCKERS:
        print('- ' + reason)
    return BLOCKED_EXIT


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ['audit', 'prepare', 'verify', 'status', 'execute']:
        commands.add_parser(command)
    readonly = commands.add_parser('preflight', help='Explicit optional read-only ADB baseline only')
    readonly.add_argument('--serial', required=True)
    args = parser.parse_args(argv)
    os.umask(0o077)
    if args.command in {'status', 'execute'}:
        return refuse_execution()
    if args.command == 'preflight':
        result = preflight(args.serial)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result['baseline_matches'] else 2
    if args.command == 'audit':
        result = audit_source()
    elif args.command == 'verify':
        result = verify()
    else:
        with (KIT / '.prepare.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            prepare()
        result = verify()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (SafetyError, OSError, ValueError, tarfile.TarError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
        print(f'STOPPED WITHOUT PHONE WRITES: {exc}', file=sys.stderr)
        sys.exit(2)
