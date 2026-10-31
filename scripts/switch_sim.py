#!/usr/bin/env python3
"""Preview a SIM-type request; --execute requires interactive confirmation.

Only the observed HK XQ-FS72 hardware / .265 software combination is allowed.
No automatic retries, slot-index guesses, profile deletion, flashing or reboot.
"""
import argparse
import re
import shlex
import subprocess
import sys

ACTION = 'com.android.euicc.service.SIM_TYPE_UPDATE_ACTION'
EXTRA = 'com.android.euicc.service.extra_sim_type'
MODES = {'physical': 0, 'esim': 1}


class SafetyError(Exception):
    """Stop instead of guessing device state or retrying a write."""


def validate_serial(serial):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}', serial):
        raise SafetyError('Invalid ADB serial; use the exact identifier from adb devices.')


def broadcast_command(serial, mode):
    validate_serial(serial)
    return ['adb', '-s', serial, 'shell', 'am', 'broadcast', '--user', '0',
            '--receiver-foreground', '--receiver-permission',
            'android.permission.READ_PRIVILEGED_PHONE_STATE',
            '-a', ACTION, '-p', 'com.qti.phone', '--ei', EXTRA, str(MODES[mode])]


def adb_read(serial, arguments):
    result = subprocess.run(['adb', '-s', serial, 'shell', *arguments],
                            capture_output=True, text=True, timeout=20, check=False)
    if result.returncode:
        raise SafetyError('ADB read failed. Check authorization/connection; no switch sent.')
    return result.stdout.strip()


def preflight(serial):
    props = {key: adb_read(serial, ['getprop', key]) for key in (
        'ro.product.model', 'ro.build.display.id', 'ro.boot.hardware.sku',
        'ro.boot.flash.locked', 'ro.boot.verifiedbootstate',
        'persist.radio.multisim.config')}
    if (props['ro.product.model'] not in {'XQ-FS72', 'XQ-FS54'}
            or props['ro.build.display.id'] != '71.1.A.2.265 release-keys'
            or props['ro.boot.hardware.sku'] != 'c001526'
            or props['ro.boot.flash.locked'] != '1'
            or props['ro.boot.verifiedbootstate'] != 'green'
            or props['persist.radio.multisim.config'] != 'dsds'):
        raise SafetyError('Device differs from the documented HK FS72/.265 baseline; stopped.')
    if not adb_read(serial, ['pm', 'path', 'com.qti.phone']).startswith('package:'):
        raise SafetyError('com.qti.phone is unavailable; stopped.')
    # Properties/package existence are necessary checks, NOT a capability probe.


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=MODES)
    parser.add_argument('--serial', required=True, help='Explicit authorized ADB device')
    parser.add_argument('--execute', action='store_true', help='Read device baseline, then ask before one request')
    args = parser.parse_args(argv)
    command = broadcast_command(args.serial, args.mode)
    print('Request:', shlex.join(command))
    print('Warning: switching interrupts service. The owner reports successful eSIM/dual-physical-SIM round trips on one device.')
    print('This Python wrapper has mock-test coverage; that feedback does not establish a real-device test of this wrapper.')
    print('This cannot verify HAL support or current MEP/slot mapping; inspect those before proceeding.')
    if args.mode == 'physical':
        print('Confirm the current slot/MEP mapping first; one verified device does not establish safety for arbitrary dual-eSIM setups.')
    if not args.execute:
        print('PREVIEW ONLY: no ADB command was executed. Add --execute only after reading README.')
        return 0
    if not sys.stdin.isatty():
        raise SafetyError('Interactive terminal required; no unattended switching.')
    preflight(args.serial)
    phrase = f'SWITCH_TO_{args.mode.upper()}_MAPPING_CHECKED'
    print('No profile is deleted by this script; the other SIM source may become unavailable.')
    print(f'After checking the mapping and accepting the risk, type: {phrase}')
    if input('> ') != phrase:
        raise SafetyError('Confirmation did not match; no switch sent.')
    # Exactly one request, never retry after a timeout or ambiguous response.
    result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    output = result.stdout + '\n' + result.stderr
    if (result.returncode or re.search(r'error|exception|denial|denied|failure', output, re.I)
            or 'Broadcast completed:' not in result.stdout):
        raise SafetyError('Request failed or outcome is unknown. Inspect the phone; do NOT automatically retry.')
    print('Request returned. Broadcast completion is NOT proof of a SIM-type change.')
    print('Check Settings for EID/SIM availability and test service manually. No automatic retry or reboot.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (SafetyError, OSError, subprocess.SubprocessError, EOFError, KeyboardInterrupt) as exc:
        # Do not dump telephony output, serials, EID, ICCID or profile data to logs.
        message = str(exc) if isinstance(exc, SafetyError) else type(exc).__name__
        print(f'STOPPED: {message}. If a request had started, its outcome may be unknown; inspect before retrying.', file=sys.stderr)
        sys.exit(1)
