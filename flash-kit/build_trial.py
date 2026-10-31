#!/usr/bin/env python3
"""Build the experimental macOS/Linux preserve-data trial, without USB access."""
import hashlib
import json
import os
import platform
import shlex
import subprocess
from pathlib import Path

import flashkit

ROOT = Path(__file__).resolve().parent
UPSTREAM_SHA = '79804a4df5a35e507a96df827083ca3eac3f70d068223ca2a70246f4ad2f9e17'
UPSTREAM = ROOT / 'upstream/newflasher-59f12e4.c.txt'
BUILD = ROOT / 'build'
# Images are applied to A (where slotted), with shared super and other shared
# targets. Boot-critical payloads and AVB metadata follow system/radio payloads.
ORDER = ('bluetooth', 'dsp', 'featenabler', 'modem', 'pvmfw', 'spuservice',
         'super', 'dtbo', 'vendor_boot', 'init_boot', 'boot', 'recovery', 'vbmeta_system', 'vbmeta')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Pinned source transformation anchor is not unique')
    return text.replace(old, new, 1)


def compose(upstream, policy, main):
    # Exclude the original XML/TA handling, directory flasher and upstream main.
    marker = '/* track the current level in the xml tree */'
    if upstream.count(marker) != 1:
        raise RuntimeError('Unexpected upstream boundary')
    prefix = upstream.split(marker, 1)[0]
    prefix = replace_once(prefix, '#define ENABLE_DEBUG 1',
                          'static bool trial_simulation = false;\n'
                          'static bool trial_last_reply_is_data = false;\n'
                          'static bool trial_last_reply_is_battery_unsupported = false;\n'
                          'static unsigned long trial_mock_transfer(int ep, char *bytes, unsigned long size);\n\n'
                          '#define ENABLE_DEBUG 1')
    mac = '#ifdef __APPLE__\n\nstatic unsigned long transfer_bulk_async(HANDLE dev, int ep, char *bytes, unsigned long size, int timeout, int exact)\n{'
    prefix = replace_once(prefix, mac, mac + '\n\tif (trial_simulation) return trial_mock_transfer(ep, bytes, size);')
    # Never resend an outbound USB transfer after a PIPE error; the outcome of
    # a partially sent chunk must be treated as unknown, not retried blindly.
    start = prefix.index(mac)
    end = prefix.index('////////////////////////////////////////////////////////////////', start)
    transfer = prefix[start:end]
    retry = '} while ((res == LIBUSB_ERROR_PIPE) && (try < 3));'
    if transfer.count(retry) != 2:
        raise RuntimeError('Unexpected USB retry structure')
    index = transfer.rfind(retry)
    transfer = transfer[:index] + transfer[index:].replace(retry, '} while (0); /* outbound: fail, do not resend */', 1)
    # A failed outbound transfer is ambiguous: do not even clear its halt.
    out_start = transfer.index('\t\t\tif (res == LIBUSB_ERROR_PIPE)', transfer.index('if (ep == EP_OUT)'))
    out_end = transfer.index('\n\t\t\ttry++;', out_start)
    transfer = transfer[:out_start] + transfer[out_end:]
    prefix = prefix[:start] + transfer + prefix[end:]
    prefix = replace_once(prefix,
        'if (trial_simulation) return trial_mock_transfer(ep, bytes, size);',
        'if (trial_simulation) return trial_mock_transfer(ep, bytes, size);\n'
        '\tif (size > INT_MAX || (ep != EP_IN && ep != EP_OUT)) return 0;')
    # Select the same reviewed libusb backend on both hosts. Never spoof
    # __APPLE__: the policy/main still need the real OS for crypto and stat.
    prefix = replace_once(prefix, '#include "version.h"',
                          '#define TRIAL_LIBUSB_BACKEND 1\n#include "version.h"')
    prefix = replace_once(prefix, '#if !defined(_WIN32) && !defined(__APPLE__)',
                          '#if !defined(_WIN32) && !defined(TRIAL_LIBUSB_BACKEND)')
    if prefix.count('#ifdef __APPLE__') != 3:
        raise RuntimeError('Unexpected upstream platform selector count')
    prefix = prefix.replace('#ifdef __APPLE__', '#ifdef TRIAL_LIBUSB_BACKEND')
    prefix = replace_once(prefix,
        'ret_len = transfer_bulk_async(dev, ep, bytes, size, timeout, exact);',
        'ret_len = transfer_bulk_async(dev, ep, bytes, size, timeout, exact);\n'
        '\ttrial_last_reply_is_data = ret_len >= 4 && ret_len <= size && '\
        '((ret_len == 12) || (ret_len == 13 && bytes[12] == 0)) && !memcmp(bytes, "DATA", 4);\n'
        '\ttrial_last_reply_is_battery_unsupported = ret_len <= size && '
        '((ret_len == 25) || (ret_len == 26 && bytes[25] == 0)) && '
        '!memcmp(bytes, "FAILBattery not supported", 25);')
    process_start = prefix.index('static int process_sins(')
    before, process = prefix[:process_start], prefix[process_start:]
    xml_start = process.index('#ifdef _WIN32\n\tsnprintf(buff, sizeof(buff), "%s\\\\update.xml"')
    xml_end = process.index('\n\tmemset(buff, 0, sizeof(buff));', xml_start)
    process = process[:xml_start] + '\n/* Trial does not consult XML skip rules; every pinned image must transfer. */\n' + process[xml_end:]
    if 'check_in_updatexml' in process or 'file_found_in_updatexml' in process:
        raise RuntimeError('Unexpected remaining XML skip path')
    data_check = 'if (strlen(tmp_reply) != 12)'
    if process.count(data_check) != 2:
        raise RuntimeError('Unexpected DATA handshake sites')
    process = process.replace(data_check, 'if (!trial_last_reply_is_data || strlen(tmp_reply) != 12 || memcmp(tmp_reply, "DATA", 4) != 0)')
    process = replace_once(process, 'if (memcmp(tmp_reply, "yes", 3) == 0)',
        'if (!trial_slot_answer_ok(flashfile, tmp_reply)) { printf("TRIAL_SLOT_REPLY_REJECTED\\n"); return 0; }\n'
        '\t\t\t\t\t\tif (strcmp(tmp_reply, "yes") == 0)')
    command_call = 'transfer_bulk_async(dev, EP_OUT, command, strlen(command), USB_TIMEOUT, 1)'
    if process.count(command_call) != 6:
        raise RuntimeError('Unexpected SIN command send sites')
    process = process.replace(command_call, 'trial_send_command(dev, command)')
    if process.count('transfer_bulk_async(dev, EP_OUT') != 2:
        raise RuntimeError('Unreviewed raw output sites in SIN transport')
    process = replace_once(process,
        'printf(" - Failed write\\n");\n\t\t\t\t\tfclose(f);\n\t\t\t\t\tf = NULL;',
        'printf(" - Failed local temporary write\\n");\n\t\t\t\t\tfclose(f);\n\t\t\t\t\tf = NULL;\n\t\t\t\t\treturn 0;')
    process = replace_once(process,
        'if (f != NULL) {\n\t\t\tfclose(f);\n\t\t\tf = NULL;\n\t\t}',
        'if (f != NULL) {\n\t\t\tint close_result = fclose(f);\n\t\t\tf = NULL;\n\t\t\tif (close_result != 0) return 0;\n\t\t}')
    return before + '\n' + policy + '\n' + process + '\n' + main


def compiler_command(system, generated, executable, build_dir):
    if system not in {'Darwin', 'Linux'}:
        raise RuntimeError('Supported build hosts: macOS and Linux')
    packages = ['libusb-1.0'] + (['libcrypto'] if system == 'Linux' else [])
    pkg = subprocess.run(['pkg-config', '--cflags', '--libs', *packages], check=True, capture_output=True, text=True)
    if system == 'Darwin':
        sdk = subprocess.run(['xcrun', '--show-sdk-path'], check=True, capture_output=True, text=True).stdout.strip()
        compiler = ['/usr/bin/clang']
        platform_flags = ['-isysroot', sdk]
    else:
        compiler = shlex.split(os.environ.get('CC', 'cc'))
        if not compiler:
            raise RuntimeError('CC cannot be empty')
        platform_flags = ['-D_GNU_SOURCE=1', '-D_FILE_OFFSET_BITS=64']
    return [*compiler, '-std=c11', '-O2', '-DHAS_STDINT_H=1', *platform_flags,
            '-Werror=implicit-function-declaration', '-Wno-unused-function', '-Wno-deprecated-declarations',
            '-I', str(build_dir), str(generated), '-o', str(executable), *shlex.split(pkg.stdout), '-lz', '-lexpat']


def build():
    if platform.system() not in {'Darwin', 'Linux'}:
        raise RuntimeError('Supported build hosts: macOS and Linux')
    if UPSTREAM.is_symlink() or not UPSTREAM.is_file():
        raise RuntimeError('Pinned vendored source is missing or is a symlink')
    upstream_bytes = UPSTREAM.read_bytes()
    if hashlib.sha256(upstream_bytes).hexdigest() != UPSTREAM_SHA:
        raise RuntimeError('Upstream source hash mismatch')
    flashkit.verify()
    manifest = flashkit.read_json(flashkit.CANDIDATE / 'manifest.json')
    images = {record['partition']: record for record in manifest['images']}
    if set(ORDER) != set(flashkit.CANDIDATE_PARTITIONS):
        raise RuntimeError('Unreviewed image set')
    BUILD.mkdir(exist_ok=True)
    header = ['struct trial_image { const char *partition; const char *name; const char *sha256; unsigned long long bytes; };',
              '#define TRIAL_IMAGE_COUNT 14',
              '#define TRIAL_MAX_MEMBER 104857600UL',
              'static const struct trial_image trial_images[TRIAL_IMAGE_COUNT] = {']
    for partition in ORDER:
        record = images[partition]
        header.append('    {' + ','.join([json.dumps(partition), json.dumps(record['name']),
                                          json.dumps(record['sha256']), str(record['bytes']) + 'ULL']) + '},')
    header.append('};\n')
    (BUILD / 'trial_images.h').write_text('\n'.join(header))
    (BUILD / 'version.h').write_text('#define VERSION 61\n')
    policy = (ROOT / 'trial_policy.c.in').read_text()
    main = (ROOT / 'trial_main.c.in').read_text()
    source = compose(upstream_bytes.decode('utf-8'), policy, main)
    generated = BUILD / 'trial-writer.c'
    generated.write_text(source)
    executable = BUILD / 'fs72-preserve-trial'
    command = compiler_command(platform.system(), generated, executable, BUILD)
    subprocess.run(command, check=True)
    executable.chmod(0o700)
    subprocess.run([str(executable), '--self-test'], check=True)
    compile_command = {'directory': str(ROOT), 'file': str(generated), 'arguments': command}
    (BUILD / 'compile_commands.json').write_text(json.dumps([compile_command], indent=2) + '\n')
    inputs = [UPSTREAM, ROOT / 'build_trial.py', ROOT / 'trial_policy.c.in', ROOT / 'trial_main.c.in',
              ROOT / 'flashkit.py', ROOT / 'trial.py', BUILD / 'trial_images.h']
    receipt = {'host_system': platform.system(), 'host_machine': platform.machine(),
               'upstream_commit': '59f12e437d29f0385eb27dcebba5158aa3f97b45',
               'upstream_sha256': UPSTREAM_SHA, 'source_zip_sha256': flashkit.SOURCE_SHA256,
               'input_sha256': {str(p.relative_to(ROOT)): digest(p) for p in inputs},
               'generated_sha256': digest(generated), 'binary_sha256': digest(executable),
               'native_guard_self_test': True, 'usb_used_during_build': False,
               'real_device_flashing_tested': False, 'slot_policy': 'write_A_if_slotted_then_activate_A_after_all_success',
               'allowed_ta_unit': '2:10100 session marker only', 'automatic_reboot': False}
    (BUILD / 'build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    build()
