#!/usr/bin/env python3
"""Download the reviewed Sony chunk manifests to PC only; never touch a phone.

Default is plan-only. Payload GETs use ax with TLS verification and HTTP failure
checks. ZIP archives are not extracted. Local SHA-256 is an inventory checksum,
not a Sony signature/authenticity verification.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlsplit
import zipfile

BASE = Path(__file__).resolve().parent
META = BASE / 'metadata'
PACKAGES = BASE / 'packages'
RESERVE = 3 * 1024**3
VERSION = '71.1.A.2.265'
EXPECTED = {
    'fs72-sea': ('XQ-FS72', 'XQ-FS72_Customized_SEA'),
    'fs54-eu': ('XQ-FS54', 'XQ-FS54_Customized_EU_UK'),
}


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(4 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()


def atomic_json(path, value):
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w') as f:
        json.dump(value, f, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)


def parse_json(text):
    try:
        return json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ValueError('Invalid JSON metadata; refusing to continue') from exc


def parse_xml(text):
    # Run with .venv/bin/python; system Python packages are unchanged.
    from defusedxml import ElementTree

    return ElementTree.fromstring(text, forbid_dtd=True, forbid_entities=True, forbid_external=True)


def load_plan():
    plan = parse_json((META / 'selection.json').read_text())
    if plan['version'] != VERSION or len(plan['packages']) != 2:
        raise ValueError('Unexpected plan version or package count')
    result = []
    seen = set()
    for package in plan['packages']:
        key = package['key']
        if key in seen or key not in EXPECTED:
            raise ValueError('Unexpected or duplicate package')
        seen.add(key)
        if (package['model'], package['customization']) != EXPECTED[key] or package['version'] != VERSION:
            raise ValueError('Unexpected model/customization/version')
        kinds = set()
        for item in package['files']:
            name = item['name']
            if Path(name).name != name or '\\' in name or not name.endswith('.zip'):
                raise ValueError('Unsafe output filename')
            kind = item['kind']
            if kind not in {'APP_SW', 'CUSTOMER_ID', 'E_LABEL'} or kind in kinds:
                raise ValueError('Unexpected or duplicate resource type')
            kinds.add(kind)
            meta_name = item['chunks_metadata']
            if Path(meta_name).name != meta_name or '\\' in meta_name:
                raise ValueError('Unsafe metadata filename')
            meta_path = META / meta_name
            raw = meta_path.read_bytes()
            text = raw.decode('utf-8-sig')
            if len(raw) > 1000000 or '\x00' in text or '<!DOCTYPE' in text.upper():
                raise ValueError('Oversized XML, alternate encoding or DTD is not allowed')
            root = parse_xml(text)
            if root.tag != 'file-chunks':
                raise ValueError('Unexpected chunk manifest')
            chunks = []
            for node in root:
                if node.tag != 'file-chunk':
                    raise ValueError('Unexpected chunk element')
                size_text = node.findtext('size')
                link = node.find('link')
                if size_text is None or link is None:
                    raise ValueError('Chunk is missing size or link')
                try:
                    number = int(node.attrib['number'])
                    size = int(size_text)
                except (ValueError, KeyError) as exc:
                    raise ValueError('Invalid chunk number or size') from exc
                url = link.attrib['href']
                u = urlsplit(url)
                if u.scheme != 'https' or u.hostname != 'app.swup.update.sony.net' or u.port not in (None, 443) or u.username or u.password or not u.path.startswith('/filestorage/'):
                    raise ValueError('Unapproved payload URL')
                if number != len(chunks) or not 0 < size <= 128 * 1024**2:
                    raise ValueError('Invalid chunk order or size')
                chunks.append({'size': size, 'url': url})
            if not chunks or sum(c['size'] for c in chunks) != item['size']:
                raise ValueError('Manifest size mismatch')
            result.append({**item, 'key': key, 'chunks': chunks,
                           'manifest_sha256': hashlib.sha256(raw).hexdigest()})
        if kinds != {'APP_SW', 'CUSTOMER_ID', 'E_LABEL'}:
            raise ValueError('Incomplete package resources')
    return result


def download(item):
    directory = PACKAGES / f"{item['key']}-{VERSION}"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / item['name']
    receipt = target.with_name(target.name + '.verified.json')
    if target.exists():
        if not receipt.exists():
            raise ValueError(f'Existing file without completion receipt: {target.name}')
        previous = parse_json(receipt.read_text())
        if target.stat().st_size != item['size'] or previous['manifest_sha256'] != item['manifest_sha256'] or sha256(target) != previous['sha256']:
            raise ValueError('Existing completed file does not match manifest/receipt')
        print('VERIFIED EXISTING', target.name, flush=True)
        return
    part = target.with_name(target.name + '.partial')
    journal = target.with_name(target.name + '.progress.json')
    chunk_file = target.with_name(target.name + '.chunk.partial')
    state = {'manifest_sha256': item['manifest_sha256'], 'completed': []}
    if journal.exists():
        state = parse_json(journal.read_text())
        if state['manifest_sha256'] != item['manifest_sha256']:
            raise ValueError('Manifest changed; refusing resume')
    completed = state['completed']
    if len(completed) > len(item['chunks']):
        raise ValueError('Invalid progress record')
    committed = sum(c['size'] for c in item['chunks'][:len(completed)])
    if part.exists():
        if part.stat().st_size < committed:
            raise ValueError('Partial file shorter than committed progress')
        with part.open('r+b') as f:
            for expected, record in zip(item['chunks'], completed, strict=False):
                data = f.read(expected['size'])
                if hashlib.sha256(data).hexdigest() != record['sha256']:
                    raise ValueError('Previously downloaded chunk is corrupted')
            # Discard only our own uncommitted trailing bytes after interruption.
            f.truncate(committed)
    elif committed:
        raise ValueError('Partial file missing')
    for number in range(len(completed), len(item['chunks'])):
        chunk = item['chunks'][number]
        if shutil.disk_usage(BASE).free < RESERVE + 2 * chunk['size']:
            raise RuntimeError('Disk reserve reached; paused without deleting completed data')
        print(f"GET {item['key']} {item['kind']} chunk {number+1}/{len(item['chunks'])}", flush=True)
        cmd = ['ax', chunk['url'], '-f', '-m', '180', '--max-bytes', str(chunk['size']), '-o', str(chunk_file)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode:
            raise RuntimeError(f'Payload request failed at chunk {number+1}; rerun to resume')
        result = parse_json(proc.stdout)
        final_url = urlsplit(result['url'])
        if result.get('status') != 200 or final_url.scheme != 'https' or final_url.hostname != 'app.swup.update.sony.net' or not final_url.path.startswith('/filestorage/'):
            raise ValueError('Unexpected payload response origin/status')
        if not chunk_file.exists() or chunk_file.stat().st_size != chunk['size']:
            raise ValueError('Downloaded chunk size mismatch')
        digest = sha256(chunk_file)
        with part.open('ab') as dst, chunk_file.open('rb') as src:
            shutil.copyfileobj(src, dst, 4 * 1024**2)
            dst.flush()
            os.fsync(dst.fileno())
        completed.append({'sha256': digest})
        atomic_json(journal, state)
        chunk_file.unlink()  # Only this script's temporary, already appended chunk.
    if part.stat().st_size != item['size']:
        raise ValueError('Completed archive length mismatch')
    print('CHECK ZIP CRC', item['name'], flush=True)
    with zipfile.ZipFile(part) as z:
        bad = z.testzip()
        if bad is not None:
            raise ValueError(f'Archive CRC failure: {bad}')
        members = [{'name': x.filename, 'size': x.file_size, 'compressed_size': x.compress_size} for x in z.infolist()]
    checksum = sha256(part)
    record = {'name': item['name'], 'bytes': item['size'], 'sha256': checksum,
              'manifest_sha256': item['manifest_sha256'], 'zip_crc_ok': True,
              'source_host': 'app.swup.update.sony.net', 'purpose': 'OFFLINE_ANALYSIS_ONLY',
              'sony_signature_verified': False, 'members': members}
    atomic_json(receipt, record)
    part.replace(target)
    print('COMPLETE', target.name, checksum, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true', help='Download reviewed ZIPs to this computer only')
    args = parser.parse_args()
    os.umask(0o077)
    items = load_plan()
    total = sum(x['size'] for x in items)
    print(f'PLAN: {len(items)} ZIPs; {total} bytes ({total/1024**3:.3f} GiB); version={VERSION}', flush=True)
    for item in items:
        print(item['key'], item['name'], item['size'], flush=True)
    if not args.download:
        return
    PACKAGES.mkdir(exist_ok=True)
    import fcntl
    with (BASE / '.download.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        remaining = sum(x['size'] for x in items if not (PACKAGES/f"{x['key']}-{VERSION}"/x['name']).exists())
        # Conservatively budget full remaining ZIPs even when a partial exists.
        if shutil.disk_usage(BASE).free < remaining + RESERVE + 128 * 1024**2:
            raise RuntimeError('Insufficient disk for remaining archives plus reserve')
        for item in items:
            download(item)
    print('ALL DOWNLOADS VERIFIED; no archives extracted; no phone operations', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'STOPPED: {exc}', file=sys.stderr, flush=True)
        sys.exit(1)
