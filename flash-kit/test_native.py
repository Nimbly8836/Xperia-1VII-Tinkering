"""Opt-in native tests: XPERIA_NATIVE_TESTS=1; no firmware or USB required.

Builds into a disposable directory with fake image metadata, never a production
build receipt. USB init is a fatal stub; bulk transfers are deterministic mocks.
"""
import hashlib
import os
import platform
import subprocess
import tempfile
import unittest
from pathlib import Path

import build_trial

HARNESS = r'''
static int mock_calls=0, mock_halts=0, mock_result=0, mock_length=0;
#define libusb_init forbidden_usb_init
#define libusb_bulk_transfer mock_bulk_transfer
#define libusb_clear_halt mock_clear_halt
#define main trial_program_main
#include "trial-writer.c"
#undef main

int LIBUSB_CALL forbidden_usb_init(libusb_context **context) {
    (void)context; fputs("UNEXPECTED_USB_INIT\n",stderr); abort();
}
int LIBUSB_CALL mock_bulk_transfer(libusb_device_handle *device, unsigned char endpoint,
        unsigned char *data, int length, int *actual, unsigned int timeout) {
    (void)device; (void)endpoint; (void)data; (void)length; (void)timeout;
    mock_calls++; *actual=mock_length; return mock_result;
}
int LIBUSB_CALL mock_clear_halt(libusb_device_handle *device, unsigned char endpoint) {
    (void)device; (void)endpoint; mock_halts++; return 0;
}
#define REQUIRE(value) do { if (!(value)) {fprintf(stderr,"FAILED line %d\n",__LINE__);return 1;} } while(0)

int main(void) {
    char buffer[128]={0}; HANDLE fake=(HANDLE)(uintptr_t)1;
    trial_simulation=false;
    int failures[]={LIBUSB_ERROR_PIPE,LIBUSB_ERROR_TIMEOUT,LIBUSB_ERROR_IO,LIBUSB_SUCCESS};
    for (unsigned i=0;i<sizeof(failures)/sizeof(failures[0]);i++) {
        mock_calls=mock_halts=0;mock_result=failures[i];mock_length=3;
        REQUIRE(transfer_bulk_async(fake,EP_OUT,buffer,4,100,1)==0);
        REQUIRE(mock_calls==1 && mock_halts==0);
    }
    mock_calls=0;mock_result=LIBUSB_SUCCESS;mock_length=4;
    REQUIRE(transfer_bulk_async(fake,EP_OUT,buffer,4,100,1)==4 && mock_calls==1);
    mock_calls=0;
    REQUIRE(transfer_bulk_async(fake,EP_OUT,buffer,(unsigned long)INT_MAX+1,100,1)==0 && mock_calls==0);
    REQUIRE(transfer_bulk_async(fake,99,buffer,4,100,1)==0 && mock_calls==0);

    trial_simulation=true;trial_phase=TRIAL_READ;
    char command[]="getvar:product";
    REQUIRE(transfer_bulk_async(NULL,EP_OUT,command,strlen(command),100,1)==strlen(command));
    REQUIRE(transfer_bulk_async(NULL,EP_IN,buffer,sizeof(buffer),100,0)>0 && mock_calls==0);
    int claimed=0;
    REQUIRE(trial_open_usb(&claimed)==NULL && claimed==-1);

    FILE *sample=tmpfile();REQUIRE(sample!=NULL);
    REQUIRE(fwrite("abc",1,3,sample)==3);rewind(sample);
    REQUIRE(trial_hash_file(sample,"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",3));
    REQUIRE(!trial_hash_file(sample,"0000000000000000000000000000000000000000000000000000000000000000",3));
    rewind(sample);
    REQUIRE(!trial_hash_file(sample,"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",4));
    fclose(sample);
    struct stat before={0},after={0};
    REQUIRE(trial_same_file(&before,&after));
    after.TRIAL_MTIME.tv_nsec=1;REQUIRE(!trial_same_file(&before,&after));
    after=before;after.TRIAL_CTIME.tv_nsec=1;REQUIRE(!trial_same_file(&before,&after));
    REQUIRE(trial_self_test()==0);
    REQUIRE(mock_calls==0);
    puts("NATIVE_PORTABILITY_TESTS_OK_NO_USB");return 0;
}
'''


@unittest.skipUnless(os.environ.get('XPERIA_NATIVE_TESTS') == '1', 'Set XPERIA_NATIVE_TESTS=1 with native build dependencies installed')
class NativeTests(unittest.TestCase):
    def run_native_checks(self, upgrade=False):
        with tempfile.TemporaryDirectory(prefix='native-tests-') as name:
            root = Path(name)
            upstream = build_trial.UPSTREAM.read_bytes()
            self.assertEqual(hashlib.sha256(upstream).hexdigest(), build_trial.UPSTREAM_SHA)
            source = build_trial.compose(upstream.decode(), (build_trial.ROOT / 'trial_policy.c.in').read_text(), (build_trial.ROOT / 'trial_main.c.in').read_text())
            (root / 'trial-writer.c').write_text(source)
            (root / 'version.h').write_text('#define VERSION 61\n')
            order = [*build_trial.ORDER, *(['bootloader'] if upgrade else [])]
            records = ',\n'.join('{"' + p + '","' + p + '.sin","unused-test-only",1}' for p in order)
            (root / 'trial_images.h').write_text(
                'struct trial_image {const char *partition,*name,*sha256;unsigned long long bytes;};\n'
                f'#define TRIAL_IMAGE_COUNT {len(order)}\n#define TRIAL_MAX_MEMBER 104857600UL\n'
                f'#define TRIAL_UPGRADE_WRITER {int(upgrade)}\n'
                f'static const struct trial_image trial_images[{len(order)}]={{' + records + '};\n')
            harness = root / 'harness.c'
            harness.write_text(HARNESS)
            executable = root / 'native-test'
            command = build_trial.compiler_command(platform.system(), harness, executable, root)
            compiled = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('NATIVE_PORTABILITY_TESTS_OK_NO_USB', result.stdout)
            self.assertIn('UPGRADE_READONLY_SELF_TEST_OK_NO_USB', result.stdout)
            self.assertIn('TRIAL_ANDROID_HANDOFF_SELF_TEST_OK_NO_USB', result.stdout)
            self.assertIn('TRIAL_COMMIT_CANCEL_SELF_TEST_OK_NO_USB', result.stdout)
            self.assertNotIn('UNEXPECTED_USB_INIT', result.stderr)

    def test_transport_hash_stat_and_guards_without_usb(self):
        self.run_native_checks()

    def test_upgrade_profile_guards_without_usb(self):
        self.run_native_checks(upgrade=True)


if __name__ == '__main__':
    unittest.main()
