# SPDX-License-Identifier: MIT
"""Signing uses disposable local keys; all host operations use isolated fixtures."""
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import driver_build as driver
import signing
import manual_install as manual
import status_report as status
VERSION = "580.178.04"
MODULE_PACKAGE = driver.module_package(driver.KERNEL, VERSION)


class SigningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.tmp.name) / 'keys'
        signing.generate(cls.directory)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_real_key_generation_pair_permissions_and_module_signing_oid(self):
        private, cert = self.directory / 'MOK.priv', self.directory / 'MOK.der'
        signing.check_pair(private, cert)
        self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o600)
        text = signing.command('openssl', 'x509', '-inform', 'DER', '-in', str(cert), '-text', '-noout').stdout.decode()
        self.assertIn('1.3.6.1.4.1.2312.16.1.2', text)
        self.assertIn('CA:FALSE', text)

    def test_generation_never_overwrites_existing_pair(self):
        before = (self.directory / 'MOK.priv').read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'overwrite'):
            signing.generate(self.directory)
        self.assertEqual((self.directory / 'MOK.priv').read_bytes(), before)

    def test_insecure_key_mode_rejected_before_build(self):
        private = self.directory / 'MOK.priv'
        private.chmod(0o644)
        try:
            with patch.object(driver, 'build') as build, self.assertRaisesRegex(RuntimeError, '0600'):
                signing.build_sign(self.directory)
            build.assert_not_called()
        finally:
            private.chmod(0o600)

    def test_key_certificate_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = Path(tmp)
            signing.generate(other)
            with self.assertRaisesRegex(RuntimeError, 'do not match'):
                signing.check_pair(self.directory / 'MOK.priv', other / 'MOK.der')

    def test_enrollment_requires_exact_positive_text_including_exit_one(self):
        cert = self.directory / 'MOK.der'
        for code, text, accepted in [(1, f'{cert} is already enrolled\n', True),
                                     (0, f'{cert} is not enrolled\n', False),
                                     (0, '', False)]:
            with self.subTest(code=code, text=text), patch.object(signing.subprocess, 'run',
                    return_value=subprocess.CompletedProcess([], code, stdout=text)):
                if accepted:
                    signing.require_enrolled(cert)
                else:
                    with self.assertRaises(RuntimeError):
                        signing.require_enrolled(cert)

    def test_build_sign_records_signed_artifact_and_public_certificate(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / 'work'
            work.mkdir()
            headers = Path(tmp) / 'headers'
            (headers / 'scripts').mkdir(parents=True)
            (headers / 'scripts/sign-file').touch()
            def build(*args, **kwargs):
                (work / 'nvidia-uvm.ko').write_bytes(b'unsigned')
                (work / 'build.json').write_text(json.dumps({'signed': False}))
            def sign(*args):
                (work / 'nvidia-uvm.ko').write_bytes(b'signed')
            with patch.object(driver, 'WORK', work), patch.object(driver, 'build', side_effect=build) as builder, \
                    patch.object(signing, 'require_enrolled') as enrolled, patch.object(driver, 'run', side_effect=sign), \
                    patch.object(driver, 'output', return_value='Local test signer'):
                signing.build_sign(self.directory, headers)
                builder.assert_called_once_with(driver.KERNEL, headers, dkms=True)
                enrolled.assert_called_once()
            receipt = json.loads((work / 'build.json').read_text())
            self.assertTrue(receipt['signed'])
            self.assertEqual(receipt['module_sha256'], hashlib.sha256(b'signed').hexdigest())
            self.assertEqual(receipt['certificate_sha256'], manual.digest(work / 'signing-certificate.der'))



class ManualTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state = root / 'state'
        self.state.mkdir()
        self.receipt = self.state / 'manual.json'
        self.destination = root / 'lib/modules/updates/memory-saver/nvidia-uvm.ko'
        self.sys = root / 'sys'
        self.sys.mkdir()
        self.boot = root / 'boot'
        self.boot.mkdir()
        (self.boot / ('initrd.img-' + driver.KERNEL)).touch()
        self.module = root / 'build/nvidia-uvm.ko'
        self.module.parent.mkdir()
        self.module.write_bytes(b'fixture module')
        self.stock = root / 'stock/nvidia-uvm.ko'
        self.stock.parent.mkdir()
        self.stock.write_bytes(b'packaged module')
        self.metadata = {'schema': 1, 'kernel': driver.KERNEL, 'driver': VERSION,
                         'default_on': True, 'signed': False,
                         'module_sha256': manual.digest(self.module)}
        self.write_metadata()
        for obj, name, value in [(manual, 'STATE', self.state), (manual, 'RECEIPT', self.receipt),
                                  (manual, 'DESTINATION', self.destination), (manual, 'SYS_MODULES', self.sys),
                                  (driver, 'BOOT', self.boot)]:
            guard = patch.object(obj, name, value)
            guard.start()
            self.addCleanup(guard.stop)
        self.overrides = {}
        for name, value in [('output', self.output), ('check_install', None),
                             ('refresh_initramfs', None), ('run', None)]:
            guard = patch.object(driver, name, side_effect=value) if value else patch.object(driver, name)
            mock = guard.start()
            setattr(self, 'mock_' + name, mock)
            self.addCleanup(guard.stop)
        self.mock_check_install.return_value = {'driver': VERSION}

    def write_metadata(self):
        (self.module.parent / 'build.json').write_text(json.dumps(self.metadata))

    def output(self, *args):
        if args in self.overrides:
            return self.overrides[args]
        defaults = {('uname', '-s'): 'Linux', ('uname', '-m'): 'aarch64',
                    ('uname', '-r'): driver.KERNEL, ('dkms', 'status'): '',
                    ('mokutil', '--sb-state'): 'SecureBoot disabled',
                    ('modinfo', '-F', 'version', str(self.module)): VERSION,
                    ('modinfo', '-k', driver.KERNEL, '-F', 'version', 'nvidia'): VERSION,
                    ('modinfo', '-F', 'version', str(self.stock)): VERSION,
                    ('modinfo', '-F', 'vermagic', str(self.stock)): driver.KERNEL + ' SMP',
                    ('modinfo', '-F', 'vermagic', str(self.module)): driver.KERNEL + ' SMP',
                    ('dpkg-query', '-L', MODULE_PACKAGE): str(self.stock),
                    ('modinfo', '-p', str(self.stock)): 'stock_option: description'}
        if args == ('modinfo', '-k', driver.KERNEL, '-F', 'filename', 'nvidia_uvm'):
            return str(self.destination if self.destination.exists() else self.stock)
        return defaults[args]

    def test_full_install_remove_preserves_stock_and_clears_receipt(self):
        original = self.stock.read_bytes()
        manual.install(self.module, allow_unsigned=True)
        self.assertEqual(self.destination.read_bytes(), self.module.read_bytes())
        self.assertEqual(json.loads(self.receipt.read_text())['state'], 'installed')
        self.assertEqual(stat.S_IMODE(self.receipt.stat().st_mode), 0o644)
        manual.remove()
        self.assertFalse(self.destination.exists())
        self.assertFalse(self.receipt.exists())
        self.assertEqual(self.stock.read_bytes(), original)
        self.assertEqual(self.mock_refresh_initramfs.call_count, 2)
        self.mock_run.assert_not_called()  # no module load/unload or service commands

    def test_active_module_blocks_install_without_writes(self):
        (self.sys / 'nvidia_uvm').mkdir()
        with self.assertRaisesRegex(RuntimeError, 'unload'):
            manual.install(self.module, True)
        self.assertFalse(self.receipt.exists())
        self.assertFalse(self.destination.exists())

    def test_dkms_registration_blocks_manual_install(self):
        self.overrides[('dkms', 'status')] = 'dgx-spark-memory-saver/0.2.0: added'
        with self.assertRaisesRegex(RuntimeError, 'DKMS'):
            manual.install(self.module, True)
        self.assertFalse(self.receipt.exists())

    def test_unsigned_module_is_rejected_when_secure_boot_enabled(self):
        self.overrides[('mokutil', '--sb-state')] = 'SecureBoot enabled'
        with self.assertRaisesRegex(RuntimeError, 'signed build'):
            manual.install(self.module, True)
        self.assertFalse(self.receipt.exists())

    def test_secure_boot_signed_install_requires_matching_enrolled_certificate(self):
        certificate = self.module.parent / 'signing-certificate.der'
        certificate.write_bytes(b'public test certificate')
        self.metadata.update(signed=True, signer='Test', certificate_sha256=manual.digest(certificate))
        self.write_metadata()
        self.overrides[('mokutil', '--sb-state')] = 'SecureBoot enabled'
        self.overrides[('modinfo', '-F', 'signer', str(self.module))] = 'Test'
        with patch.object(signing, 'require_enrolled', side_effect=RuntimeError('not enrolled')):
            with self.assertRaisesRegex(RuntimeError, 'not enrolled'):
                manual.install(self.module)
        self.assertFalse(self.receipt.exists())
        with patch.object(signing, 'require_enrolled') as check:
            manual.install(self.module)
            check.assert_called_once_with(certificate)


    def test_changed_artifact_and_default_off_builds_rejected(self):
        self.module.write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError, 'changed after'):
            manual.install(self.module, True)
        self.metadata['module_sha256'] = manual.digest(self.module)
        self.metadata['default_on'] = False
        self.write_metadata()
        with self.assertRaisesRegex(RuntimeError, 'persistent build'):
            manual.install(self.module, True)
        self.assertFalse(self.receipt.exists())

    def test_removal_refuses_file_replaced_by_someone_else(self):
        manual.install(self.module, True)
        self.destination.write_bytes(b'some other module')
        with self.assertRaisesRegex(RuntimeError, 'unrecognized module'):
            manual.remove()
        self.assertEqual(self.destination.read_bytes(), b'some other module')
        self.assertTrue(self.receipt.exists())

    def test_removal_can_restore_current_driver_after_package_change(self):
        manual.install(self.module, True)
        # Recovery must not depend on retaining the original source package or
        # on a new driver already having a reviewed memory-saver profile.
        replacement = '999.1.0'
        self.overrides[('modinfo', '-k', driver.KERNEL, '-F', 'version', 'nvidia')] = replacement
        self.overrides[('dpkg-query', '-L', driver.module_package(driver.KERNEL, replacement))] = str(self.stock)
        self.overrides[('modinfo', '-F', 'version', str(self.stock))] = replacement
        manual.remove()
        self.assertFalse(self.destination.exists())
        self.assertFalse(self.receipt.exists())

    def test_failed_refresh_is_recoverable_through_remove(self):
        self.mock_refresh_initramfs.side_effect = subprocess.CalledProcessError(1, 'update-initramfs')
        with self.assertRaises(subprocess.CalledProcessError):
            manual.install(self.module, True)
        self.assertEqual(json.loads(self.receipt.read_text())['state'], 'installing')
        self.mock_refresh_initramfs.side_effect = None
        manual.remove()
        self.assertFalse(self.receipt.exists())
        self.assertFalse(self.destination.exists())

    def test_failed_removal_keeps_receipt_for_retry(self):
        manual.install(self.module, True)
        self.mock_refresh_initramfs.side_effect = subprocess.CalledProcessError(1, 'update-initramfs')
        with self.assertRaises(subprocess.CalledProcessError):
            manual.remove()
        self.assertFalse(self.destination.exists())
        self.assertEqual(json.loads(self.receipt.read_text())['state'], 'removing')
        self.mock_refresh_initramfs.side_effect = None
        manual.remove()
        self.assertFalse(self.receipt.exists())


class StatusTests(unittest.TestCase):
    def snapshot(self):
        return {'kernel': driver.KERNEL, 'page_size': '65536', 'rm_version': VERSION,
                'uvm_loaded': True, 'loaded_srcversion': 'abc', 'packing': 'Y',
                'current_disk': {'srcversion': 'abc', 'packing_parameter': True, 'version': VERSION},
                'target_disk': {'packing_parameter': True, 'version': VERSION},
                'target_rm_version': VERSION, 'dkms': [], 'manual_install': None,
                'issues': [], 'unknowns': []}

    def test_healthy_parameter_state_without_savings_claim(self):
        data = self.snapshot()
        status.evaluate(data)
        self.assertEqual(data['state'], 'packing-enabled')
        self.assertNotIn('memory_saved', data)

    def test_second_driver_is_reported_as_conditional(self):
        data = self.snapshot()
        data['rm_version'] = data['target_rm_version'] = '610.57.04'
        data['current_disk']['version'] = data['target_disk']['version'] = '610.57.04'
        status.evaluate(data)
        self.assertEqual(data['state'], 'packing-enabled')
        self.assertEqual(data['qualification'], 'conditional')
        self.assertIn('RM alignment', data['caveat'])

    def test_loaded_disk_mismatch_and_driver_drift(self):
        for field, value in [('loaded_srcversion', 'other'), ('rm_version', 'new-driver'),
                             ('target_rm_version', 'new-driver')]:
            with self.subTest(field=field):
                data = self.snapshot()
                data[field] = value
                status.evaluate(data)
                self.assertEqual(data['state'], 'needs-attention')

    def test_unreadable_identity_is_unknown_not_success(self):
        data = self.snapshot()
        data['loaded_srcversion'] = None
        status.evaluate(data)
        self.assertEqual(data['state'], 'unverified')

    def test_incomplete_install_and_dual_registration(self):
        data = self.snapshot()
        data['manual_install'] = {'state': 'installing'}
        data['dkms'] = ['dgx-spark-memory-saver/0.2.0: installed']
        status.evaluate(data)
        self.assertEqual(data['state'], 'needs-attention')
        self.assertEqual(len(data['issues']), 2)

    def test_collect_uses_only_read_only_commands(self):
        commands = []
        def probe(*args):
            commands.append(args)
            if args == ('uname', '-r'):
                return driver.KERNEL
            if args == ('getconf', 'PAGESIZE'):
                return '65536'
            return ''
        with tempfile.TemporaryDirectory() as tmp, patch.object(status, 'SYS_MODULES', Path(tmp)), \
                patch.object(status, 'RECEIPT', Path(tmp) / 'absent'), patch.object(status, 'probe', side_effect=probe):
            status.collect()
        self.assertTrue(all(c[0] in ('uname', 'getconf', 'modinfo', 'mokutil', 'dkms') for c in commands))
        self.assertTrue(all(c[0] != 'dkms' or c[1:] == ('status',) for c in commands))


if __name__ == '__main__':
    unittest.main()
