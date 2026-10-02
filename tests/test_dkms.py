# SPDX-License-Identifier: MIT
"""Exercise real build orchestration with isolated source and command doubles.

No root access, CUDA import, module installation or GPU access.
"""
import copy
import hashlib
import importlib.machinery
import importlib.util
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('driver_build', str(ROOT / 'scripts/driver_build.py'))
spec = importlib.util.spec_from_loader(loader.name, loader)
driver = importlib.util.module_from_spec(spec)
loader.exec_module(driver)
VERSION = '580.178.04'
MODULE_PACKAGE = driver.module_package(driver.KERNEL, VERSION)
MODULE_PACKAGE_VERSION = driver.REGISTRY['drivers'][VERSION]['kernels'][driver.KERNEL]['module_package_version']


class BuildChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.source = root / 'packaged-source'
        self.source.mkdir()
        self.profile = copy.deepcopy(driver.driver_profile(VERSION, driver.KERNEL))
        manifest = self.profile
        self.profile['upstream']['source_root'] = str(self.source)
        for name in manifest['upstream']['file_sha256']:
            path = self.source / name
            path.parent.mkdir(exist_ok=True)
            path.write_text('untouched source ' + name)
            manifest['upstream']['file_sha256'][name] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.headers = root / 'headers'
        (self.headers / 'include/config').mkdir(parents=True)
        (self.headers / 'include/config/kernel.release').write_text(driver.KERNEL + '\n')
        (self.headers / 'include/config/auto.conf').write_text('CONFIG_ARM64_64K_PAGES=y\n')
        self.work = root / '.work/build'
        self.stock = root / 'packaged-modules/nvidia-uvm.ko'
        self.stock.parent.mkdir()
        self.stock.write_text('stock module')
        for name, value in [('WORK', self.work)]:
            guard = patch.object(driver, name, value)
            guard.start()
            self.addCleanup(guard.stop)
        self.real_profile = driver.driver_profile
        guard = patch.object(driver, 'driver_profile', side_effect=lambda version, kernel: self.profile if version == self.profile['driver'] else self.real_profile(version, kernel))
        guard.start()
        self.addCleanup(guard.stop)
        self.overrides = {}
        self.calls = []
        guard = patch.object(driver, 'run', self.command)
        guard.start()
        self.addCleanup(guard.stop)

    def command(self, *args, **kwargs):
        self.calls.append(args)
        version = self.profile['driver']
        package = driver.module_package(driver.KERNEL, version)
        defaults = {
            ('uname', '-s'): 'Linux', ('uname', '-m'): 'aarch64',
            ('dkms', 'status'): 'dgx-spark-fan-control/0.1.3: installed',
            ('dpkg-query', '-L', package): str(self.stock),
            ('modinfo', '-k', driver.KERNEL, '-F', 'version', 'nvidia'): version,
            ('modinfo', '-k', driver.KERNEL, '-F', 'filename', 'nvidia_uvm'): str(self.stock),
        }
        for package, version in [(self.profile['upstream']['package'], self.profile['upstream']['package_version']),
                                 (package, MODULE_PACKAGE_VERSION)]:
            defaults[('dpkg-query', '-W', '-f=${db:Status-Status} ${Version}', package)] = 'installed ' + version
        for module in [self.stock, self.work / 'nvidia-uvm.ko']:
            defaults[('modinfo', '-F', 'version', str(module))] = self.profile['driver']
            defaults[('modinfo', '-F', 'vermagic', str(module))] = driver.KERNEL + ' SMP modversions aarch64'
        if args in self.overrides:
            return subprocess.CompletedProcess(args, 0, self.overrides[args])
        if args in defaults:
            return subprocess.CompletedProcess(args, 0, defaults[args])
        if args[0] == 'patch':
            # Simulate a source edit only in the isolated copy.
            target = Path(args[2]) / 'nvidia-uvm/uvm_mmu.c'
            target.write_text(target.read_text() + '\npatched')
            return subprocess.CompletedProcess(args, 0, '')
        if args[0] == 'make':
            (Path(args[2]) / 'nvidia-uvm.ko').write_text('built module')
            return subprocess.CompletedProcess(args, 0, '')
        raise AssertionError('Unexpected external command: ' + repr(args))

    def assert_not_built(self):
        self.assertFalse(any(c[0] in ('patch', 'make') for c in self.calls))
        self.assertFalse(self.work.exists())

    def test_manual_and_dkms_builds_preserve_packaged_source(self):
        before = {p: p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        for dkms in [False, True]:
            self.calls.clear()
            driver.build(driver.KERNEL, self.headers, dkms=dkms)
            applied = [Path(c[-1]).name for c in self.calls if c[0] == 'patch']
            self.assertEqual(applied, ['0001-pack-user-leaf-tables.patch'] +
                             (['enable-packing.patch'] if dkms else []))
            self.assertEqual(before, {p: p.read_bytes() for p in before})
            driver.clean()
        self.assertFalse(self.work.exists())

    def test_wrong_platform_is_rejected(self):
        self.overrides[('uname', '-m')] = 'x86_64'
        with self.assertRaisesRegex(RuntimeError, 'aarch64'):
            driver.build(driver.KERNEL, self.headers, dkms=True)
        self.assert_not_built()

    def test_other_kernels_are_rejected(self):
        for kernel in ['7.0.0-1019-nvidia', '7.0.0-1020-nvidia-64k']:
            with self.assertRaisesRegex(RuntimeError, 'Unsupported kernel'):
                driver.build(kernel, self.headers, dkms=True)
        self.assert_not_built()

    def test_header_release_and_page_configuration_are_checked(self):
        release = self.headers / 'include/config/kernel.release'
        release.write_text('another-kernel')
        with self.assertRaisesRegex(RuntimeError, 'Headers do not match'):
            driver.build(driver.KERNEL, self.headers)
        release.write_text(driver.KERNEL)
        (self.headers / 'include/config/auto.conf').write_text('CONFIG_ARM64_4K_PAGES=y\n')
        with self.assertRaisesRegex(RuntimeError, '64 KiB'):
            driver.build(driver.KERNEL, self.headers)
        self.assert_not_built()

    def test_changed_source_is_rejected(self):
        (self.source / 'nvidia-uvm/uvm_mmu.h').write_text('changed upstream')
        with self.assertRaisesRegex(RuntimeError, 'source changed'):
            driver.build(driver.KERNEL, self.headers)
        self.assert_not_built()

    def test_cached_install_rechecks_driver_and_packages(self):
        key = ('modinfo', '-k', driver.KERNEL, '-F', 'version', 'nvidia')
        self.overrides[key] = 'another-driver'
        with self.assertRaisesRegex(RuntimeError, 'Unsupported NVIDIA'):
            driver.check_install(driver.KERNEL, self.headers)
        self.overrides.clear()
        self.overrides[('dpkg-query', '-W', '-f=${db:Status-Status} ${Version}', MODULE_PACKAGE)] = 'installed newer'
        with self.assertRaisesRegex(RuntimeError, 'pinned package'):
            driver.check_install(driver.KERNEL, self.headers)
        self.assert_not_built()

    def test_install_requires_intact_stock_module_and_no_other_override(self):
        driver.check_install(driver.KERNEL, self.headers)
        key = ('modinfo', '-k', driver.KERNEL, '-F', 'filename', 'nvidia_uvm')
        self.overrides[key] = '/some/other/nvidia-uvm.ko'
        with self.assertRaisesRegex(RuntimeError, 'override'):
            driver.check_install(driver.KERNEL, self.headers)
        self.overrides.clear()
        self.stock.unlink()
        with self.assertRaisesRegex(RuntimeError, 'stock UVM'):
            driver.check_install(driver.KERNEL, self.headers)

    def test_competing_nvidia_dkms_is_rejected(self):
        self.overrides[('dkms', 'status')] = 'nvidia/610.57.04, kernel, aarch64: installed'
        with self.assertRaisesRegex(RuntimeError, 'NVIDIA DKMS'):
            driver.check_install(driver.KERNEL, self.headers)

    def test_workspace_reuse_and_symlink_cleanup_are_rejected(self):
        self.work.mkdir(parents=True)
        marker = self.work / 'keep'
        marker.touch()
        with self.assertRaisesRegex(RuntimeError, 'workspace exists'):
            driver.build(driver.KERNEL, self.headers)
        self.assertTrue(marker.exists())
        driver.clean()
        self.work.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            driver.clean()
        self.assertTrue(self.source.is_dir())

    def test_second_driver_selects_its_patch_and_receipt(self):
        original = self.profile
        self.profile = copy.deepcopy(self.real_profile('610.57.04', driver.KERNEL))
        self.profile['upstream']['source_root'] = str(self.source)
        self.profile['upstream']['file_sha256'] = original['upstream']['file_sha256']
        driver.build(driver.KERNEL, self.headers, dkms=True)
        self.assertEqual([Path(c[-1]).name for c in self.calls if c[0] == 'patch'],
                         ['0002-pack-user-leaf-tables-610.patch', 'enable-packing.patch'])
        import json
        receipt = json.loads((self.work / 'build.json').read_text())
        self.assertEqual(receipt['driver'], '610.57.04')
        self.assertEqual(receipt['profile']['qualification'], 'conditional')

    def test_cached_dkms_artifact_must_match_current_driver(self):
        cache = Path(self.tmp.name) / 'dkms-cache'
        cache.mkdir()
        module = cache / 'nvidia-uvm.ko.zst'
        module.write_bytes(b'cached')
        version_key = ('modinfo', '-F', 'version', str(module))
        self.overrides[version_key] = '610.57.04'
        with self.assertRaisesRegex(RuntimeError, 'artifact driver version'):
            driver.check_install(driver.KERNEL, self.headers, cache)
        self.overrides[version_key] = VERSION
        self.overrides[('modinfo', '-F', 'vermagic', str(module))] = driver.KERNEL + ' SMP'
        self.overrides[('modinfo', '-p', str(module))] = 'uvm_pack_sysmem_leaf_tables: packing'
        driver.check_install(driver.KERNEL, self.headers, cache)
        self.overrides[('modinfo', '-p', str(module))] = 'stock'
        with self.assertRaisesRegex(RuntimeError, 'not the memory-saver'):
            driver.check_install(driver.KERNEL, self.headers, cache)
        module.unlink()
        with self.assertRaisesRegex(RuntimeError, 'cached DKMS'):
            driver.check_install(driver.KERNEL, self.headers, cache)

    def test_unreviewed_patch_is_rejected_before_build(self):
        self.profile['patch_sha256'] = 'not-the-reviewed-patch'
        with self.assertRaisesRegex(RuntimeError, 'Allocator patch differs'):
            driver.build(driver.KERNEL, self.headers)
        self.assert_not_built()


class PackagingChecks(unittest.TestCase):
    def test_initramfs_refresh_order_missing_image_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(driver, 'BOOT', Path(tmp)), patch.object(driver, 'run') as command:
            driver.refresh_initramfs(driver.KERNEL)
            command.assert_not_called()
            (Path(tmp) / ('initrd.img-' + driver.KERNEL)).touch()
            driver.refresh_initramfs(driver.KERNEL)
            self.assertEqual([call.args for call in command.call_args_list],
                             [('depmod', driver.KERNEL), ('update-initramfs', '-u', '-k', driver.KERNEL)])
            command.reset_mock()
            command.side_effect = subprocess.CalledProcessError(1, 'depmod')
            with self.assertRaises(subprocess.CalledProcessError):
                driver.refresh_initramfs(driver.KERNEL)
            command.assert_called_once_with('depmod', driver.KERNEL)


    def test_dkms_registers_only_uvm_with_exact_kernel_and_arch(self):
        shell = '''kernelver=7.0.0-1019-nvidia-64k
kernel_source_dir=/lib/modules/$kernelver/build
dkms_tree=/isolated/dkms
arch=aarch64
source ./dkms.conf
printf '%s\\n' "$PACKAGE_NAME" "$PACKAGE_VERSION" "${#BUILT_MODULE_NAME[@]}" "${BUILT_MODULE_NAME[0]}" "$AUTOINSTALL" "$BUILD_EXCLUSIVE_KERNEL" "$BUILD_EXCLUSIVE_ARCH" "$PRE_INSTALL" "$POST_INSTALL" "$POST_REMOVE"
'''
        values = subprocess.check_output(['bash', '-c', shell], cwd=ROOT, text=True).splitlines()
        self.assertEqual(values[:5], ['dgx-spark-memory-saver', '0.4.0', '1', 'nvidia-uvm', 'yes'])
        self.assertIn('/isolated/dkms/dgx-spark-memory-saver/0.4.0/' + driver.KERNEL + '/aarch64/module', values[7])
        self.assertEqual(values[1], driver.PACKAGE_VERSION)
        self.assertRegex(driver.KERNEL, values[5])
        self.assertIsNone(re.fullmatch(values[5], '7.0.0-1019-nvidia'))
        self.assertIsNone(re.fullmatch(values[5], '7.0.0-1020-nvidia-64k'))
        self.assertRegex('aarch64', values[6])
        self.assertIsNone(re.fullmatch(values[6], 'x86_64'))
        for command in values[7:]:
            self.assertTrue((ROOT / command.split()[0]).is_file())
            self.assertIn(driver.KERNEL, command)

    def test_dkms_default_patch_applies_to_historical_patch_content(self):
        # Extract the introduced parameter block from the immutable experiment
        # patch; applying the packaging patch must change just the default/comment.
        additions = '\n'.join(line[1:] for line in
                              (ROOT / 'patches/0001-pack-user-leaf-tables.patch').read_text().splitlines()
                              if line.startswith(('+', ' ')) and not line.startswith('+++')) + '\n'
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'nvidia-uvm/uvm_mmu.c'
            source.parent.mkdir()
            source.write_text(additions)
            subprocess.run(['patch', '-d', tmp, '-p1', '--fuzz=0', '--batch', '-i',
                            str(ROOT / 'packaging/enable-packing.patch')], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            expected = additions.replace('Disabled by default and inert on 4 KiB.',
                                         'Installation opts in; inert on 4 KiB.').replace(
                'static bool uvm_pack_sysmem_leaf_tables;', 'static bool uvm_pack_sysmem_leaf_tables = true;')
            self.assertEqual(source.read_text(), expected)

    def test_initramfs_hook_refuses_other_kernels_before_commands(self):
        result = subprocess.run(['bash', str(ROOT / 'scripts/refresh-initramfs'), 'wrong-kernel'],
                                text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unsupported kernel', result.stderr)


if __name__ == '__main__':
    unittest.main()
