#!/usr/bin/env python3
"""Read-only preparation for FS54 .265 -> .35. No upgrade/write entry exists here."""
import argparse
import json
import os
import re
import subprocess
import sys
import time

import bundle_runtime
import flashkit
import trial

BASELINE = dict(trial.TRIAL_BASELINE, **{'ro.product.model': 'XQ-FS54'})
SOURCE_VBMETA_DIGEST = '6fc0e861da50bbc338dbe5a00afb5a1147ee8d2092db397c80a58348c28a3c3a'
READS = {'Get-root-key-hash', 'Read-TA:2:2127', 'Read-TA:2:2301'} | {
    'getvar:' + name for name in ('product', 'serialno', 'version-bootloader', 'secure',
        'Default-security', 'slot-count', 'current-slot', 'max-download-size', 'Sector-size',
        'Battery', 'snapshot-update-status')
} | {'getvar:has-slot:' + name for name in (*flashkit.CANDIDATE_PARTITIONS, 'bootloader')}


def android_baseline(serial):
    trial.validate_serial(serial)
    observed_at = time.time_ns() // 1_000_000_000
    monotonic = time.monotonic()
    baseline = flashkit.preflight(serial, expected=BASELINE)
    if not baseline['baseline_matches']:
        raise flashkit.SafetyError('Phone must match the FS54 .265 / HK hardware baseline with battery >=60%; no USB probe started')
    result = subprocess.run(['adb', '-s', serial, 'shell', 'getprop', 'ro.boot.vbmeta.digest'],
                            capture_output=True, text=True, timeout=20)
    digest = result.stdout.strip().lower()
    if result.returncode or not re.fullmatch('[a-f0-9]{64}', digest) or digest != SOURCE_VBMETA_DIGEST:
        raise flashkit.SafetyError('Current verified-boot digest does not match the audited .265 source')
    baseline.pop('blockers', None)
    baseline.update(serial=serial, battery_observed_at=observed_at,
                    battery_observed_monotonic=monotonic, vbmeta_digest=digest)
    trial.battery_arguments(baseline, serial)
    return baseline


def summarize(code, text):
    commands = [line.removeprefix('TRIAL_COMMAND ') for line in text.splitlines() if line.startswith('TRIAL_COMMAND ')]
    if not commands or any(command not in READS for command in commands):
        raise flashkit.SafetyError('Native log is missing the fixed read-only command sequence')
    matches = {str(unit): f'UPGRADE_BOOT_CONFIG_MATCH Read-TA:2:{unit}=yes' in text for unit in (2127, 2301)}
    slots = re.findall(r'^TRIAL_DEVICE has-slot:bootloader=(yes|no)$', text, re.MULTILINE)
    slot = slots[0] if len(slots) == 1 else None
    complete = (code == 0 and 'UPGRADE_READONLY_PROBE_OK_NO_WRITES' in text
                and all(matches.values()) and slot is not None)
    return {'read_only_probe_complete': complete, 'exit_code': code,
            'boot_config_matches_reference': matches,
            'bootloader_has_slot': slot,
            'phone_write_requested': False, 'flash_allowed': False,
            'note': 'This is inspection evidence, not an implemented or validated .35 upgrade.'}


def probe_from_baseline(baseline, session):
    serial = baseline.get('serial')
    if not isinstance(serial, str):
        raise flashkit.SafetyError('Missing explicit device identity')
    trial.validate_serial(serial)
    if baseline.get('observed') != BASELINE or baseline.get('vbmeta_digest') != SOURCE_VBMETA_DIGEST:
        raise flashkit.SafetyError('Baseline does not establish the audited source system')
    trial.checked_build()
    arguments = ['--upgrade-probe', serial, *trial.battery_arguments(baseline, serial)]
    code = trial.native(arguments, session, session / 'native.log')
    report = summarize(code, (session / 'native.log').read_text())
    (session / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def run(serial=None):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise flashkit.SafetyError('Use an interactive terminal for the Android-to-Flash-mode handoff')
    trial.checked_build()
    serial = bundle_runtime.select_device(serial)
    baseline = android_baseline(serial)
    session = trial.new_session('upgrade-readonly')
    (session / 'baseline.json').write_text(json.dumps(baseline, indent=2) + '\n')
    print('READ-ONLY preparation: bootloader, slot support and two boot-config units only.')
    print('No flashing, TA writes, erases, slot changes or reboot commands will be sent.')
    print('Shut down normally, then hold Volume Down while connecting USB to enter Sony Flash mode.')
    print('The fresh battery handoff expires after 10 minutes. Private session:', session)
    input('Press Enter after entering Flash mode, or Ctrl+C to cancel: ')
    report = probe_from_baseline(baseline, session)
    print(json.dumps(report, indent=2))
    print('Inspection finished; no upgrade started. You may disconnect USB and boot Android normally.')
    return 0 if report['read_only_probe_complete'] else 2


def simulate():
    trial.checked_build()
    session = trial.new_session('upgrade-readonly-simulation')
    code = trial.native(['--upgrade-probe-simulate'], session, session / 'native.log')
    report = summarize(code, (session / 'native.log').read_text())
    report['simulation_only'] = True
    (session / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['read_only_probe_complete'] else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='mode', required=True)
    commands.add_parser('simulate', help='No ADB or USB; synthetic probe responses only')
    live = commands.add_parser('run', help='Read Android, ask for manual Flash mode, then read only')
    live.add_argument('--serial')
    args = parser.parse_args(argv)
    os.umask(0o077)
    return simulate() if args.mode == 'simulate' else run(args.serial)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (flashkit.SafetyError, OSError, ValueError, subprocess.SubprocessError, KeyboardInterrupt, EOFError) as exc:
        message = str(exc) if isinstance(exc, flashkit.SafetyError) else type(exc).__name__
        print('READ-ONLY PREPARATION STOPPED: ' + message, file=sys.stderr)
        sys.exit(2)
