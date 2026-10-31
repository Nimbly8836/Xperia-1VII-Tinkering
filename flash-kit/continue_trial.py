#!/usr/bin/env python3
"""Continue one recent session that stopped at read-only probe, without rebooting.

Never resume a partial write or fabricate a fresh baseline. By default the
original battery reading must be <=600s old. Explicit --accept-recorded-battery
accepts an older reading as historical, not as a verified current charge.
Actual writes still require the full interactive confirmation.
"""
import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import flashkit
import trial


def battery_arguments(baseline, serial, accept_recorded_battery=False):
    if not accept_recorded_battery:
        return trial.battery_arguments(baseline, serial)
    level = baseline.get('battery_percent')
    observed_at = baseline.get('battery_observed_at')
    observed_monotonic = baseline.get('battery_observed_monotonic')
    matches = baseline.get('baseline_matches')
    if (type(matches) is not bool or not matches or baseline.get('serial') != serial
            or type(level) is not int or not 60 <= level <= 100
            or type(observed_at) is not int or not 0 < observed_at <= trial.time.time()
            or type(observed_monotonic) not in (int, float)
            or not 0 < observed_monotonic <= trial.time.monotonic()):
        raise flashkit.SafetyError('Recorded battery evidence is missing, invalid or belongs to another device')
    return ['--android-battery', str(level), '--battery-observed-at', str(observed_at),
            '--accept-recorded-battery']


def checked_session(name, serial, accept_recorded_battery=False):
    trial.validate_serial(serial)
    if not re.fullmatch(r'fs72-trial-live-[A-Za-z0-9_-]+', name):
        raise flashkit.SafetyError('Expected the original live session directory name, not an arbitrary path')
    session = Path(tempfile.gettempdir()) / name
    info = session.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise flashkit.SafetyError('Session must be a private directory owned by this user')
    for filename in ['baseline.json', 'result.json', 'input-manifest.json', 'probe.log']:
        file_info = (session / filename).lstat()
        if not stat.S_ISREG(file_info.st_mode) or file_info.st_uid != os.getuid() or file_info.st_size > 1024 * 1024:
            raise flashkit.SafetyError('Invalid session evidence file')
    for filename in ['authorization.json', 'native.log', '.continue.lock', 'continue-probe.log']:
        if os.path.lexists(session / filename):
            raise flashkit.SafetyError('Session already authorized, used or continued; no retry after a possible write')
    images = session / 'images'
    image_info = images.lstat()
    if not stat.S_ISDIR(image_info.st_mode) or image_info.st_uid != os.getuid():
        raise flashkit.SafetyError('Invalid original image directory')
    result = flashkit.read_json(session / 'result.json')
    if result != {'mode': 'blocked_at_read_only_probe', 'phone_write_requested': False, 'exit_code': 1}:
        raise flashkit.SafetyError('Only the known read-only probe failure is resumable')
    log = (session / 'probe.log').read_text()
    commands = [line.removeprefix('TRIAL_COMMAND ') for line in log.splitlines() if line.startswith('TRIAL_COMMAND ')]
    if ('TRIAL_STOPPED completed_images=0 possible_device_write=no simulated_mutation=no;' not in log
            or any(not (c.startswith('getvar:') or c == 'Get-root-key-hash') for c in commands)):
        raise flashkit.SafetyError('Probe log does not establish a read-only stop')
    baseline = flashkit.read_json(session / 'baseline.json')
    if not isinstance(baseline, dict) or baseline.get('observed') != trial.TRIAL_BASELINE:
        raise flashkit.SafetyError('Original Android identity does not match')
    battery_arguments(baseline, serial, accept_recorded_battery)
    return session, baseline


def continue_trial(name, serial, accept_recorded_battery=False):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise flashkit.SafetyError('Continuation requires your local interactive terminal')
    receipt = trial.checked_build()
    session, baseline = checked_session(name, serial, accept_recorded_battery)
    # Exclusive, permanent claim: never continue the same session twice.
    with (session / '.continue.lock').open('x') as claim:
        claim.write('one continuation attempt; never retry a possible write\n')
    print('接续刚才尚未写入的会话；不重新开机、不重复复制固件。', flush=True)
    age = (trial.time.time() - baseline['battery_observed_at']) / 60
    print(f"原Android电量：{baseline['battery_percent']}%；读取于约{age:.1f}分钟前。", flush=True)
    if accept_recorded_battery:
        print('你已明确接受使用该历史读数；当前电量未实时核实。原读数和时间不会改写。', flush=True)
    else:
        print('未接受历史电量时，仍要求原读取时间不超过10分钟。', flush=True)
    print('先只读检查当前Flash模式；不会自动确认或开始刷写。', flush=True)
    probe_log = session / 'continue-probe.log'
    code = trial.native(['--probe', serial, *battery_arguments(baseline, serial, accept_recorded_battery)], session, probe_log)
    if code or 'TRIAL_PROBE_OK_NO_WRITES' not in probe_log.read_text():
        print('只读检查仍未通过，未开始写入。日志：', probe_log)
        return code or 2
    print('即将试刷FS54 .265的14个固定镜像：仅A槽及共享super；不主动清数据。')
    print('仍不保证开机、数据恢复或双实体卡/eSIM功能；失败不自动重试或重启。')
    if input('确认实际写入，请完整输入 ' + trial.PHRASE + '\n> ').strip() != trial.PHRASE:
        print('已取消，未写入。')
        return 2
    trial.checked_build()
    arguments = battery_arguments(baseline, serial, accept_recorded_battery)
    with (session / 'authorization.json').open('x') as output:
        json.dump({'typed_confirmation': trial.PHRASE, 'functional_goal': flashkit.POLICY['goal'],
                   'data_risk_accepted': True, 'continued_read_only_failure': True,
                   'recorded_battery_accepted': accept_recorded_battery,
                   'battery_percent': baseline['battery_percent'],
                   'battery_observed_at': baseline['battery_observed_at'],
                   'build_binary_sha256': receipt['binary_sha256']}, output, indent=2)
    code = trial.native(['--flash', serial, trial.PHRASE, *arguments], session / 'images', session / 'native.log')
    text = (session / 'native.log').read_text()
    complete = code == 0 and 'TRIAL_COMPLETE_NO_REBOOT_FUNCTIONAL_RESULT_NOT_VERIFIED' in text
    (session / 'result.json').write_text(json.dumps({'mode': 'live_trial', 'exit_code': code,
        'images_completed': text.count('TRIAL_IMAGE_COMPLETE '), 'write_sequence_complete': complete,
        'functional_goal_verified': False, 'automatic_reboot': False,
        'source_zip_sha256': flashkit.SOURCE_SHA256, 'binary_sha256': receipt['binary_sha256']}, indent=2) + '\n')
    print('日志：', session)
    if not complete:
        print('未报告完整成功，可能部分写入。不要重试/切槽/重启/清数据，保留日志。')
        return code or 2
    print('写入序列完成，未自动重启；不代表eSIM/双卡验收通过。')
    print('程序退出后再断开USB并正常开机；若出现清数据提示，不要确认。')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', required=True, help='Original fs72-trial-live-* directory name')
    parser.add_argument('--serial', required=True)
    parser.add_argument('--accept-recorded-battery', action='store_true',
                        help='Explicitly accept the original historical battery reading, without pretending it is fresh')
    args = parser.parse_args()
    os.umask(0o077)
    return continue_trial(args.session, args.serial, args.accept_recorded_battery)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (flashkit.SafetyError, OSError, ValueError, subprocess.SubprocessError, KeyboardInterrupt) as exc:
        print('STOPPED: ' + str(exc), file=sys.stderr)
        sys.exit(2)
