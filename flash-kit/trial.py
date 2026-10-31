#!/usr/bin/env python3
"""Experimental FS72 HK .265 -> FS54 EU .265 preserve-data trial.

run: real writes only after normal-Android baseline, typed confirmation and
manual Flash-mode entry. simulate: no USB. probe: Flash-mode reads only.
No Root, unlock, factory reset, automatic retry or automatic reboot.
"""
import argparse
import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import flashkit

ROOT = Path(__file__).resolve().parent
BINARY = ROOT / 'build/fs72-preserve-trial'
RECEIPT = ROOT / 'build/build-receipt.json'
PHRASE = 'FS72_TO_FS54_265_A_KEEP_DATA_TRIAL'
TRIAL_BASELINE = dict(flashkit.BASELINE, **{'ro.build.display.id': '71.1.A.2.265 release-keys'})
INPUTS = {'upstream/newflasher-59f12e4.c.txt', 'build_trial.py', 'trial_policy.c.in',
          'trial_main.c.in', 'flashkit.py', 'trial.py', 'build/trial_images.h'}


def digest(path):
    return flashkit.sha256_file(path)


def checked_build():
    receipt = flashkit.read_json(RECEIPT)
    if not isinstance(receipt, dict) or receipt.get('source_zip_sha256') != flashkit.SOURCE_SHA256:
        raise flashkit.SafetyError('Build receipt does not match fixed firmware')
    hashes = receipt.get('input_sha256')
    if not isinstance(hashes, dict) or set(hashes) != INPUTS:
        raise flashkit.SafetyError('Build input set mismatch')
    for relative, wanted in hashes.items():
        path = ROOT / relative
        if path.is_symlink() or not path.is_file() or digest(path) != wanted:
            raise flashkit.SafetyError('Native source/build inputs changed; rebuild and retest first')
    generated = ROOT / 'build/trial-writer.c'
    if generated.is_symlink() or not generated.is_file() or digest(generated) != receipt.get('generated_sha256'):
        raise flashkit.SafetyError('Generated native source changed')
    if BINARY.is_symlink() or not BINARY.is_file() or digest(BINARY) != receipt.get('binary_sha256'):
        raise flashkit.SafetyError('Native executable hash mismatch')
    return receipt


def new_session(mode):
    path = Path(tempfile.mkdtemp(prefix='fs72-trial-' + mode + '-'))
    path.chmod(0o700)
    return path


def snapshot_images(session):
    # Recheck against the pinned original, not just an editable local manifest.
    flashkit.verify()
    manifest = flashkit.read_json(flashkit.CANDIDATE / 'manifest.json')
    images = session / 'images'
    images.mkdir(mode=0o700)
    for entry in manifest['images']:
        original = flashkit.CANDIDATE / 'images' / entry['name']
        target = images / entry['name']
        # APFS clone is a separate inode/COW snapshot; do not use hard links.
        subprocess.run(['/bin/cp', '-c', str(original), str(target)], check=True)
        if target.is_symlink() or target.stat().st_ino == original.stat().st_ino or target.stat().st_size != entry['bytes'] or digest(target) != entry['sha256']:
            raise flashkit.SafetyError('Snapshot mismatch; no native operation started')
        target.chmod(0o400)
    (session / 'input-manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    return images


def native(arguments, cwd, log):
    # No arbitrary host timeout/automatic retry. Cancellation asks the native
    # driver to stop at an image boundary, and we drain/wait rather than orphan it.
    with log.open('w') as output:
        process = subprocess.Popen([str(BINARY), *arguments], cwd=cwd, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        errors = []
        log_ok = True
        console_ok = True

        def request_stop(reason):
            errors.append(reason)
            if process.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    process.send_signal(signal.SIGUSR1)
            with contextlib.suppress(OSError):
                print('请求在安全边界停止；已发出的写入不能撤销：' + reason, file=sys.stderr, flush=True)

        try:
            if process.stdout is None:
                raise flashkit.SafetyError('Missing native output stream')
            while True:
                try:
                    raw_line = process.stdout.readline()
                except KeyboardInterrupt:
                    request_stop('用户中断')
                    continue
                except OSError:
                    request_stop('原生输出管道读取失败')
                    process.stdout.close()
                    break
                if not raw_line:
                    break
                line = raw_line.decode('utf-8', errors='replace')
                if log_ok:
                    try:
                        output.write(line)
                        output.flush()
                    except OSError:
                        log_ok = False
                        request_stop('日志写入失败')
                if console_ok:
                    try:
                        print(line, end='', flush=True)
                    except OSError:
                        console_ok = False
                        request_stop('终端输出失败')
            while True:
                try:
                    code = process.wait()
                    break
                except KeyboardInterrupt:
                    request_stop('用户中断')
            return 2 if errors else code
        finally:
            if process.poll() is None:
                request_stop('主控异常')
                if process.stdout is not None:
                    process.stdout.close()
                process.wait()


def simulate(fail_at=None, fault=None):
    receipt = checked_build()
    session = new_session('simulation')
    print('SIMULATION ONLY: no USB or phone access. Session:', session, flush=True)
    images = snapshot_images(session)
    arguments = ['--simulate']
    if fail_at is not None and fault is not None:
        raise flashkit.SafetyError('Choose one simulation fault at a time')
    if fail_at is not None:
        if not 1 <= fail_at <= 10000:
            raise flashkit.SafetyError('Invalid simulation failure point')
        arguments.extend(['--fail-at', str(fail_at)])
    if fault is not None:
        if fault not in {'data-fail-prefix', 'data-okay-prefix', 'super-slot-failure', 'snapshot-merging'}:
            raise flashkit.SafetyError('Unknown simulation fault')
        arguments.extend(['--fault', fault])
    code = native(arguments, images, session / 'native.log')
    text = (session / 'native.log').read_text()
    complete = 'TRIAL_SIMULATION_COMPLETE_NO_USB' in text and code == 0
    commands = [s.removeprefix('TRIAL_COMMAND ') for s in text.splitlines() if s.startswith('TRIAL_COMMAND ')]
    report = {'mode': 'simulation', 'usb_used': False, 'exit_code': code, 'complete': complete,
              'images_completed': text.count('TRIAL_IMAGE_COMPLETE '), 'commands': commands,
              'failure_injection': fail_at, 'protocol_fault': fault,
              'simulated_raw_bytes': re.findall(r'TRIAL_SIMULATED_RAW_BYTES=(\d+)', text),
              'build_binary_sha256': receipt['binary_sha256']}
    (session / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print('SIMULATION_RESULT:', session / 'result.json')
    return code


def validate_serial(serial):
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', serial):
        raise flashkit.SafetyError('Invalid explicit USB serial')


def probe(serial):
    validate_serial(serial)
    checked_build()
    session = new_session('probe')
    print('FLASH-MODE READ-ONLY PROBE. No download/erase/flash/TA write. Session:', session)
    code = native(['--probe', serial], session, session / 'native.log')
    (session / 'result.json').write_text(json.dumps({'mode': 'read_only_probe', 'exit_code': code,
                                                   'phone_write_requested': False}, indent=2) + '\n')
    return code


def battery_arguments(baseline, serial):
    level = baseline.get('battery_percent')
    observed_at = baseline.get('battery_observed_at')
    observed_monotonic = baseline.get('battery_observed_monotonic')
    matches = baseline.get('baseline_matches')
    if (type(matches) is not bool or not matches or baseline.get('serial') != serial
            or type(level) is not int or not 60 <= level <= 100
            or type(observed_at) is not int or type(observed_monotonic) not in (int, float)
            or not 0 <= time.time() - observed_at <= 600
            or not 0 <= time.monotonic() - observed_monotonic <= 600):
        raise flashkit.SafetyError('Battery baseline missing, mismatched or older than 10 minutes; restart from Android, no cached baseline reuse')
    return ['--android-battery', str(level), '--battery-observed-at', str(observed_at)]


def run(serial):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise flashkit.SafetyError('Real writes require an interactive local terminal; no noninteractive confirmation bypass')
    validate_serial(serial)
    receipt = checked_build()
    print('正在核验固定源包并创建只读 APFS 快照；此阶段不写手机。', flush=True)
    session = new_session('live')
    images = snapshot_images(session)
    print('读取正常开机手机的基线；现在请保持 Android 开机、USB 调试已授权。', flush=True)
    observed_at, observed_monotonic = time.time_ns() // 1_000_000_000, time.monotonic()
    baseline = flashkit.preflight(serial, expected=TRIAL_BASELINE)
    baseline.update(serial=serial, battery_observed_at=observed_at,
                    battery_observed_monotonic=observed_monotonic)
    baseline.pop('blockers', None)  # Legacy preparation gates are not trial authorization.
    (session / 'baseline.json').write_text(json.dumps(baseline, indent=2, ensure_ascii=False) + '\n')
    if not baseline['baseline_matches']:
        raise flashkit.SafetyError('Android baseline must be stock HK FS72 .265 with sufficient battery; no writes started')
    print('''
实际试刷，不是模拟：XQ-FS72 HK .265 -> XQ-FS54 EU/UK .265。
功能能力留到刷后验收，双实体卡/eSIM切换及恢复成功均不保证。
会写14个固定系统/无线固件镜像：有槽的只写A，共享super按源包更新。
全部写入成功并同步后才设置启动槽A。共享super意味着B不是回滚快照。
不直接写userdata/metadata/persist/modemst1/2/misc，不写GPT、不改SPC/CustomerID。
共享super会更新内部逻辑分区元数据；写前必须读到OTA快照状态none，否则停止。
保留现有bootloader，且Flash模式必须报告匹配的商业根哈希和V36 bootloader。
必要状态、槽位/身份不匹配时拒绝；电量至少60%。仅Battery明确不支持时，
可使用同一台手机本次运行中10分钟内的Android电量；其余错误不回退。
唯一允许的TA写入是会话状态unit 2:10100的1/0，不是身份/密钥TA。
已有单台刷机成功、数据保留及内置eSIM联网反馈；不保证本次或其他设备成功。
这是本项目基于Newflasher传输代码的实验性受限入口，仍须逐项验收。
不自动重启、不自动恢复出厂、不Root、不解锁、不在失败后自动重试。
尚无已验证的原HK恢复包/失败无损回退保证。应先自行备份重要数据。
接受残余风险不代表数据必能恢复，也不保证第二实体卡一定可切回。
''')
    print('''
现在正常关机。按住音量减，再连接USB，进入Sony Flash模式（不是蓝色Fastboot）。
程序以USB 0fce:b00b和手机序列号为准；只允许连接一台Flash模式Sony设备。
不要运行其他刷机工具。进入后按回车，随后不要拔线或中断。
''')
    input('进入 Flash 模式后按回车进行只读设备检查；此步不写分区或TA。')
    checked_build()
    probe_dir = session / 'probe'
    probe_dir.mkdir(mode=0o700)
    probe_code = native(['--probe', serial, *battery_arguments(baseline, serial)], probe_dir, session / 'probe.log')
    if probe_code != 0 or 'TRIAL_PROBE_OK_NO_WRITES' not in (session / 'probe.log').read_text():
        (session / 'result.json').write_text(json.dumps({'mode': 'blocked_at_read_only_probe',
            'phone_write_requested': False, 'exit_code': probe_code}, indent=2) + '\n')
        print('只读检查未通过，尚未开始写入。可断开USB正常开机；不要绕过检查。日志：', session)
        return probe_code or 2
    if input('只读检查通过。确认上述实际写入范围，请完整输入 ' + PHRASE + '\n> ').strip() != PHRASE:
        print('已取消，未执行手机写入。')
        return 2
    (session / 'authorization.json').write_text(json.dumps({'typed_confirmation': PHRASE,
        'functional_goal': flashkit.POLICY['goal'], 'data_risk_accepted': True,
        'runtime_capability_prevalidation_waived_for_trial': True,
        'build_binary_sha256': receipt['binary_sha256']}, indent=2) + '\n')
    checked_build()
    code = native(['--flash', serial, PHRASE, *battery_arguments(baseline, serial)], images, session / 'native.log')
    text = (session / 'native.log').read_text()
    complete = code == 0 and 'TRIAL_COMPLETE_NO_REBOOT_FUNCTIONAL_RESULT_NOT_VERIFIED' in text
    report = {'mode': 'live_trial', 'exit_code': code, 'images_completed': text.count('TRIAL_IMAGE_COMPLETE '),
              'write_sequence_complete': complete, 'functional_goal_verified': False,
              'automatic_reboot': False, 'source_zip_sha256': flashkit.SOURCE_SHA256,
              'binary_sha256': receipt['binary_sha256']}
    (session / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PRIVATE SESSION LOG:', session)
    if not complete:
        print('未报告完整成功。可能已部分写入：保留日志，不自动重试/切槽/重启/清数据。')
        return code or 2
    print('写入序列完成，未自动重启；这不是eSIM/双实体卡验收通过。')
    print('关闭本程序后再断开USB并正常开机；若出现清数据/恢复出厂提示，不要确认。')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='mode', required=True)
    simulation = commands.add_parser('simulate')
    faults = simulation.add_mutually_exclusive_group()
    faults.add_argument('--fail-at', type=int)
    faults.add_argument('--fault', choices=['data-fail-prefix', 'data-okay-prefix', 'super-slot-failure', 'snapshot-merging'])
    for name in ['probe', 'run']:
        sub = commands.add_parser(name)
        sub.add_argument('--serial', required=True)
    args = parser.parse_args(argv)
    os.umask(0o077)
    if args.mode == 'simulate':
        return simulate(args.fail_at, args.fault)
    if args.mode == 'probe':
        return probe(args.serial)
    return run(args.serial)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (flashkit.SafetyError, OSError, ValueError, subprocess.SubprocessError, KeyboardInterrupt) as exc:
        print('STOPPED: ' + str(exc), file=sys.stderr)
        sys.exit(2)
