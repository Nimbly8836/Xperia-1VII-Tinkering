#!/usr/bin/env python3
"""Build the fixed experimental .265 -> .35/V40 writer. Never access USB."""
import hashlib
import json
import os
import platform
import subprocess
import sys

import build_trial
import flashkit
import prepare_upgrade
import trial
import upgrade_trial


def build():
    if platform.system() not in {'Darwin', 'Linux'}:
        raise flashkit.SafetyError('Build on macOS or Linux')
    if not prepare_upgrade.DESTINATION.exists():
        prepare_upgrade.prepare()
    original = prepare_upgrade.verify()
    images = upgrade_trial.normalized_images(original)
    if [item['partition'] for item in images] != list(build_trial.ORDER) + ['bootloader']:
        raise flashkit.SafetyError('Upgrade order must be the fixed 14 images, then bootloader')
    build = upgrade_trial.BUILD
    build.mkdir(exist_ok=True)
    raw = upgrade_trial.unwrap_bootloader(prepare_upgrade.DESTINATION / 'images' / prepare_upgrade.BOOTLOADER)
    if upgrade_trial.RAW_BOOT.exists():
        if upgrade_trial.RAW_BOOT.is_symlink() or flashkit.sha256_file(upgrade_trial.RAW_BOOT) != upgrade_trial.RAW_BOOT_SHA256:
            raise flashkit.SafetyError('Existing unwrapped bootloader differs; do not overwrite unknown data')
    else:
        with upgrade_trial.RAW_BOOT.open('xb') as output:
            output.write(raw)
        upgrade_trial.RAW_BOOT.chmod(0o400)
    header = ['struct trial_image { const char *partition; const char *name; const char *sha256; unsigned long long bytes; };',
              '#define TRIAL_IMAGE_COUNT 15', '#define TRIAL_MAX_MEMBER 104857600UL',
              '#define TRIAL_UPGRADE_WRITER 1', '#define TRIAL_CONFIRMATION ' + json.dumps(trial.UPGRADE_PHRASE),
              'static const struct trial_image trial_images[TRIAL_IMAGE_COUNT] = {']
    for item in images:
        header.append('    {' + ','.join([json.dumps(item['partition']), json.dumps(item['name']),
                                         json.dumps(item['sha256']), str(item['bytes']) + 'ULL']) + '},')
    header.append('};\n')
    (build / 'trial_images.h').write_text('\n'.join(header))
    (build / 'version.h').write_text('#define VERSION 61\n')
    upstream = build_trial.UPSTREAM.read_bytes()
    if build_trial.UPSTREAM.is_symlink() or hashlib.sha256(upstream).hexdigest() != build_trial.UPSTREAM_SHA:
        raise flashkit.SafetyError('Pinned upstream changed')
    source = build_trial.compose(upstream.decode(), (build_trial.ROOT / 'trial_policy.c.in').read_text(),
                                (build_trial.ROOT / 'trial_main.c.in').read_text())
    generated = build / 'upgrade-writer.c'
    generated.write_text(source)
    command = build_trial.compiler_command(platform.system(), generated, upgrade_trial.BINARY, build)
    subprocess.run(command, check=True)
    upgrade_trial.BINARY.chmod(0o700)
    subprocess.run([str(upgrade_trial.BINARY), '--self-test'], check=True)
    (build / 'compile_commands.json').write_text(json.dumps([{'directory': str(build_trial.ROOT),
        'file': str(generated), 'arguments': command}], indent=2) + '\n')
    receipt = {'trial_plan': 'upgrade-35', 'host_system': platform.system(), 'host_machine': platform.machine(),
               'source_zip_sha256': prepare_upgrade.RELEASE['sha256'], 'confirmation': trial.UPGRADE_PHRASE,
               'input_sha256': {name: flashkit.sha256_file(build_trial.ROOT / name) for name in sorted(upgrade_trial.INPUTS)},
               'generated_sha256': flashkit.sha256_file(generated), 'binary_sha256': flashkit.sha256_file(upgrade_trial.BINARY),
               'images': images, 'original_gzip_bootloader_sha256': prepare_upgrade.BOOTLOADER_SHA256,
               'unwrapped_tar_sha256': upgrade_trial.RAW_BOOT_SHA256,
               'boot_config_writes': False, 'gpt_writes': False, 'automatic_reboot': False,
               'native_guard_self_test': True, 'phone_accessed_during_build': False,
               'real_upgrade_tested': False}
    upgrade_trial.RECEIPT.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    try:
        os.umask(0o077)
        build()
    except (flashkit.SafetyError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print('UPGRADE BUILD STOPPED: ' + str(exc), file=sys.stderr)
        sys.exit(2)
