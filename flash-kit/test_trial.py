import contextlib
import hashlib
import importlib.util
import io
import json
import re
import signal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_trial
import flashkit

# Load this standalone script explicitly, not an unrelated installed 'trial'.
_spec = importlib.util.spec_from_file_location('fs72_trial_under_test', Path(__file__).with_name('trial.py'))
if _spec is None or _spec.loader is None:
    raise RuntimeError('Cannot load the trial script under test')
trial = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(trial)


class FakeProcess:
    def __init__(self, stream=None, code=0):
        self.stdout = stream if stream is not None else io.BytesIO(b'TRIAL_SIMULATION_COMPLETE_NO_USB\n')
        self.code = code
        self.returncode = None
        self.signals = []
        self.waited = False

    def poll(self):
        return self.returncode

    def wait(self):
        self.waited = True
        self.returncode = self.code
        return self.code

    def send_signal(self, value):
        self.signals.append(value)


class InterruptedStream(io.BytesIO):
    interrupted = False

    def readline(self, *args):
        if not self.interrupted:
            self.interrupted = True
            raise KeyboardInterrupt
        return super().readline(*args)


class TrialTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='trial-unit-tests-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        guard = patch.object(trial.subprocess, 'Popen', side_effect=AssertionError('No real process/USB in unit tests'))
        guard.start()
        self.addCleanup(guard.stop)
        read_guard = patch.object(flashkit, 'adb_read', side_effect=AssertionError('No real ADB in unit tests'))
        read_guard.start()
        self.addCleanup(read_guard.stop)

    def test_trial_baseline_requires_265(self):
        self.assertEqual(trial.TRIAL_BASELINE['ro.build.display.id'], '71.1.A.2.265 release-keys')
        self.assertEqual(flashkit.BASELINE['ro.build.display.id'], '71.1.A.2.248 release-keys')
        def fake_read(serial, command):
            return 'level: 100' if command == ['dumpsys', 'battery'] else trial.TRIAL_BASELINE[command[1]]
        with patch.object(flashkit, 'adb_read', side_effect=fake_read):
            self.assertTrue(flashkit.preflight('TEST', expected=trial.TRIAL_BASELINE)['baseline_matches'])
            self.assertFalse(flashkit.preflight('TEST')['baseline_matches'])

    def test_baseline_cannot_add_other_getters(self):
        expected = dict(trial.TRIAL_BASELINE, **{'ro.serialno': 'not permitted'})
        with self.assertRaises(flashkit.SafetyError):
            flashkit.preflight('TEST', expected=expected)

    def test_noninteractive_run_stops_before_work(self):
        with patch.object(trial.sys.stdin, 'isatty', return_value=False), patch.object(trial, 'checked_build', side_effect=AssertionError('must not reach build')), self.assertRaises(flashkit.SafetyError):
            trial.run('TEST')

    def test_invalid_serial(self):
        for value in ['a;reboot', 'a\nb', '', 'a/b', 'x' * 101]:
            with self.assertRaises(flashkit.SafetyError):
                trial.validate_serial(value)

    def test_native_normal_waits(self):
        process = FakeProcess()
        with patch.object(trial.subprocess, 'Popen', return_value=process) as start, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(trial.native(['--simulate'], self.root, self.root / 'run.log'), 0)
        self.assertTrue(process.waited)
        self.assertEqual(process.signals, [])
        self.assertTrue(start.call_args.kwargs['start_new_session'])

    def test_interrupt_requests_boundary_stop_and_waits(self):
        process = FakeProcess(InterruptedStream(b'TRIAL_STOPPED\n'))
        with patch.object(trial.subprocess, 'Popen', return_value=process), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(trial.native(['--simulate'], self.root, self.root / 'run.log'), 2)
        self.assertTrue(process.waited)
        self.assertIn(signal.SIGUSR1, process.signals)

    def test_log_failure_does_not_orphan_child_or_report_success(self):
        class BadOutput(io.StringIO):
            def write(self, value):
                raise OSError('fake disk failure')
        class BadLog:
            def open(self, mode):
                return BadOutput()
        process = FakeProcess()
        with patch.object(trial.subprocess, 'Popen', return_value=process), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(trial.native(['--simulate'], self.root, BadLog()), 2)
        self.assertTrue(process.waited)
        self.assertIn(signal.SIGUSR1, process.signals)

    def test_simulation_faults_are_mutually_exclusive(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            trial.main(['simulate', '--fail-at', '2', '--fault', 'data-fail-prefix'])

    def test_sony_query_names_match_independent_upstream(self):
        upstream = build_trial.UPSTREAM.read_text()
        policy = (trial.ROOT / 'trial_policy.c.in').read_text()
        self.assertIn('"Get-root-key-hash"', upstream)
        self.assertIn('"Get-root-key-hash"', policy)
        self.assertNotIn('trial_get(device,"root-key-hash"', policy)
        for key in re.findall(r'trial_get\(device,\s*"([^"]+)"', policy):
            if key != 'snapshot-update-status':
                self.assertIn('"getvar:' + key + '"', upstream, key)

    def test_build_transform_removes_skip_and_routes_commands(self):
        source = build_trial.UPSTREAM.read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(), build_trial.UPSTREAM_SHA)
        transformed = build_trial.compose(source.decode(), (trial.ROOT / 'trial_policy.c.in').read_text(),
                                          (trial.ROOT / 'trial_main.c.in').read_text())
        process = transformed.split('static int process_sins(', 1)[1].split('/* Experimental macOS/Linux', 1)[0]
        self.assertNotIn('update.xml', process)
        self.assertNotIn('check_in_updatexml', process)
        self.assertEqual(process.count('trial_send_command(dev, command)'), 6)
        self.assertEqual(process.count('transfer_bulk_async(dev, EP_OUT'), 2)
        self.assertEqual(process.count('!trial_last_reply_is_data'), 2)
        self.assertIn('trial_slot_answer_ok(flashfile, tmp_reply)', process)
        self.assertNotIn('int main(int argc, char *argv[])', transformed)
        self.assertNotIn('proced_ta_file(', transformed)
        self.assertIn('#define TRIAL_LIBUSB_BACKEND 1', transformed)
        self.assertEqual(transformed.count('#ifdef TRIAL_LIBUSB_BACKEND'), 3)
        self.assertNotIn('libusb_clear_halt(dev, endpoint_out)', transformed)
        self.assertIn('/* outbound: fail, do not resend */', transformed)

    def test_battery_handoff_requires_fresh_same_device_reading(self):
        baseline = {'baseline_matches': True, 'serial': 'TEST', 'battery_percent': 100,
                    'battery_observed_at': 1700000000, 'battery_observed_monotonic': 100.0}
        with patch.object(trial.time, 'time', return_value=1700000001), patch.object(trial.time, 'monotonic', return_value=101.0):
            self.assertEqual(trial.battery_arguments(baseline, 'TEST'),
                             ['--android-battery', '100', '--battery-observed-at', '1700000000'])
            for changes in [{'serial': 'WRONG'}, {'baseline_matches': False},
                            {'battery_percent': 59}, {'battery_percent': 101}, {'battery_percent': True},
                            {'battery_observed_at': 1699999000}, {'battery_observed_at': 1700000100},
                            {'battery_observed_monotonic': -1000.0}, {'battery_observed_monotonic': 200.0}]:
                with self.subTest(changes=changes), self.assertRaises(flashkit.SafetyError):
                    trial.battery_arguments(dict(baseline, **changes), 'TEST')
            with self.assertRaises(flashkit.SafetyError):
                trial.battery_arguments({}, 'TEST')

    def test_expiry_while_waiting_for_flashmode_never_starts_probe(self):
        with self.assertRaises(flashkit.SafetyError):
            self.run_fixture(clock=[100.0, 701.0])
        self.assertFalse((self.root / 'probe.log').exists())
        self.assertFalse((self.root / 'native.log').exists())

    def test_expiry_while_confirming_never_starts_flash(self):
        with self.assertRaises(flashkit.SafetyError):
            self.run_fixture(clock=[100.0, 101.0, 701.0])
        self.assertTrue((self.root / 'probe.log').exists())
        self.assertFalse((self.root / 'native.log').exists())

    def run_fixture(self, probe_ok=True, confirmed=True, live_code=0, clock=None):
        class Tty(io.StringIO):
            def isatty(self):
                return True
        calls = []
        def fake_native(arguments, cwd, log):
            self.assertEqual(arguments[-4:], ['--android-battery', '100', '--battery-observed-at', '1700000000'])
            arguments = arguments[:-4]
            calls.append(arguments)
            if arguments[0] == '--probe':
                log.write_text('TRIAL_PROBE_OK_NO_WRITES' if probe_ok else 'TRIAL_REQUIRED_READ_FAILED snapshot-update-status')
                return 0 if probe_ok else 1
            self.assertEqual(arguments, ['--flash', 'TEST', trial.PHRASE])
            log.write_text('TRIAL_COMPLETE_NO_REBOOT_FUNCTIONAL_RESULT_NOT_VERIFIED' if live_code == 0 else 'TRIAL_STOPPED')
            return live_code
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(Tty()))
            stack.enter_context(patch.object(trial.sys, 'stdin', Tty()))
            stack.enter_context(patch.object(trial, 'checked_build', return_value={'binary_sha256': 'fixture'}))
            stack.enter_context(patch.object(trial, 'new_session', return_value=self.root))
            stack.enter_context(patch.object(trial, 'snapshot_images', return_value=self.root / 'images'))
            stack.enter_context(patch.object(trial.time, 'time', return_value=1700000000))
            stack.enter_context(patch.object(trial.time, 'time_ns', return_value=1700000000_000000000))
            stack.enter_context(patch.object(trial.time, 'monotonic', side_effect=clock or [100.0, 101.0, 102.0]))
            stack.enter_context(patch.object(flashkit, 'preflight', return_value={'baseline_matches': True, 'battery_percent': 100, 'blockers': []}))
            stack.enter_context(patch.object(trial, 'native', side_effect=fake_native))
            stack.enter_context(patch('builtins.input', side_effect=['', trial.PHRASE if confirmed else 'NO']))
            code = trial.run('TEST')
        return code, calls

    def test_failed_read_only_probe_never_reaches_flash(self):
        code, calls = self.run_fixture(probe_ok=False)
        self.assertNotEqual(code, 0)
        self.assertEqual(calls, [['--probe', 'TEST']])
        self.assertFalse((self.root / 'authorization.json').exists())

    def test_user_cancel_after_probe_never_reaches_flash(self):
        code, calls = self.run_fixture(confirmed=False)
        self.assertNotEqual(code, 0)
        self.assertEqual(calls, [['--probe', 'TEST']])

    def test_confirmed_run_reaches_one_mock_write_not_a_retry(self):
        code, calls = self.run_fixture(live_code=1)
        self.assertNotEqual(code, 0)
        self.assertEqual(calls, [['--probe', 'TEST'], ['--flash', 'TEST', trial.PHRASE]])
        result = json.loads((self.root / 'result.json').read_text())
        self.assertFalse(result['write_sequence_complete'])
        self.assertFalse(result['functional_goal_verified'])

    def test_transfer_success_is_not_functional_success(self):
        code, calls = self.run_fixture()
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 2)
        result = json.loads((self.root / 'result.json').read_text())
        self.assertTrue(result['write_sequence_complete'])
        self.assertFalse(result['functional_goal_verified'])

    def test_build_receipt_rejects_changed_wrapper(self):
        for relative in trial.INPUTS:
            p = self.root / relative
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('fixture:' + relative)
        binary = self.root / 'build/native'
        binary.write_text('not executable test data')
        generated = self.root / 'build/trial-writer.c'
        generated.write_text('fixture')
        receipt = {'source_zip_sha256': flashkit.SOURCE_SHA256,
                   'host_system': trial.platform.system(), 'host_machine': trial.platform.machine(),
                   'input_sha256': {s: trial.digest(self.root / s) for s in trial.INPUTS},
                   'binary_sha256': trial.digest(binary), 'generated_sha256': trial.digest(generated)}
        rpath = self.root / 'build/receipt.json'
        rpath.write_text(json.dumps(receipt))
        with patch.object(trial, 'ROOT', self.root), patch.object(trial, 'BINARY', binary), patch.object(trial, 'RECEIPT', rpath):
            trial.checked_build()
            with patch.object(trial.platform, 'system', return_value='OtherOS'), self.assertRaises(flashkit.SafetyError):
                trial.checked_build()
            with patch.object(trial.platform, 'machine', return_value='OtherCPU'), self.assertRaises(flashkit.SafetyError):
                trial.checked_build()
            (self.root / 'trial.py').write_text('changed')
            with self.assertRaises(flashkit.SafetyError):
                trial.checked_build()


if __name__ == '__main__':
    unittest.main()
