import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import build_trial


class BuildCommandTests(unittest.TestCase):
    def test_linux_uses_pkg_config_crypto_and_no_apple_sdk(self):
        reply = subprocess.CompletedProcess([], 0, '-lusb-1.0 -lcrypto\n', '')
        with patch.object(build_trial.subprocess, 'run', return_value=reply) as run, patch.dict(os.environ, {'CC': 'gcc'}):
            command = build_trial.compiler_command('Linux', Path('source.c'), Path('binary'), Path('build'))
        run.assert_called_once_with(['pkg-config', '--cflags', '--libs', 'libusb-1.0', 'libcrypto'], check=True, capture_output=True, text=True)
        self.assertEqual(command[0], 'gcc')
        self.assertIn('-D_GNU_SOURCE=1', command)
        self.assertIn('-D_FILE_OFFSET_BITS=64', command)
        self.assertIn('-lcrypto', command)
        self.assertNotIn('-isysroot', command)

    def test_darwin_preserves_sdk_build(self):
        replies = [subprocess.CompletedProcess([], 0, '-lusb-1.0\n', ''), subprocess.CompletedProcess([], 0, '/sdk\n', '')]
        with patch.object(build_trial.subprocess, 'run', side_effect=replies) as run:
            command = build_trial.compiler_command('Darwin', Path('source.c'), Path('binary'), Path('build'))
        self.assertEqual(run.call_count, 2)
        self.assertEqual(command[0], '/usr/bin/clang')
        self.assertIn('-isysroot', command)
        self.assertIn('/sdk', command)
        self.assertNotIn('-lcrypto', command)

    def test_unsupported_host_never_runs_compiler_or_pkg_config(self):
        with patch.object(build_trial.subprocess, 'run') as run, self.assertRaises(RuntimeError):
            build_trial.compiler_command('Windows', Path('source.c'), Path('binary'), Path('build'))
        run.assert_not_called()

    def test_empty_compiler_is_rejected(self):
        reply = subprocess.CompletedProcess([], 0, '-lusb-1.0 -lcrypto\n', '')
        with patch.object(build_trial.subprocess, 'run', return_value=reply), patch.dict(os.environ, {'CC': ''}), self.assertRaises(RuntimeError):
            build_trial.compiler_command('Linux', Path('source.c'), Path('binary'), Path('build'))


if __name__ == '__main__':
    unittest.main()
