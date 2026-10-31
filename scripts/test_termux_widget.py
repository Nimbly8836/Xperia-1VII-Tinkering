"""Inspect shortcut commands and check Bash syntax; never execute a shortcut."""
import shlex
import subprocess
import unittest
from pathlib import Path

import switch_sim

ROOT = Path(__file__).with_name('termux-widget')
SCRIPTS = {'enable-esim.sh': 'esim', 'enable-dual-sim.sh': 'physical'}


class TermuxWidgetTests(unittest.TestCase):
    def test_shortcuts_use_english_names_and_messages(self):
        for name in SCRIPTS:
            with self.subTest(script=name):
                text = (ROOT / name).read_text()
                self.assertTrue(name.isascii())
                self.assertTrue(text.isascii())
                self.assertTrue(text.startswith('#!/data/data/com.termux/files/usr/bin/bash\n'))

    def test_broadcast_matches_the_existing_adb_command(self):
        for name, mode in SCRIPTS.items():
            with self.subTest(script=name):
                lines = (ROOT / name).read_text().splitlines()
                requests = [line for line in lines if line.startswith('RISH_APPLICATION_ID=')]
                self.assertEqual(len(requests), 1)
                request = shlex.split(requests[0])
                self.assertEqual(request[:5], [
                    'RISH_APPLICATION_ID=com.termux', 'RISH_PRESERVE_ENV=0',
                    '/system/bin/sh', '$HOME/.local/share/xperia-rish/rish', '-c'])
                self.assertEqual(len(request), 6)
                expected = switch_sim.broadcast_command('TEST', mode)[4:]
                expected[0] = '/system/bin/am'
                self.assertEqual(shlex.split(request[5]), expected)

    def test_exit_status_is_saved_before_print_and_pause(self):
        for name in SCRIPTS:
            with self.subTest(script=name):
                lines = (ROOT / name).read_text().splitlines()
                index = next(i for i, line in enumerate(lines) if line.startswith('RISH_APPLICATION_ID='))
                self.assertEqual(lines[index + 1], 'result=$?')
                self.assertTrue(lines[index + 2].startswith('printf '))
                self.assertTrue(lines[index + 3].startswith('read -r -p '))
                self.assertEqual(lines[index + 4], 'exit "$result"')
                self.assertEqual(index + 5, len(lines))

    def test_bash_syntax_without_executing_scripts(self):
        for name in SCRIPTS:
            with self.subTest(script=name):
                result = subprocess.run(['bash', '-n', str(ROOT / name)], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
