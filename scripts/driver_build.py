#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pinned manual/DKMS build, install validation and initramfs refresh hooks."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.work' / 'nvidia-610.57.04-uvm-pool'
MANIFEST = json.loads((ROOT / 'provenance.json').read_text())
SOURCE = Path(MANIFEST['upstream']['source_root'])
KERNEL = MANIFEST['tested_kernel']
DRIVER = MANIFEST['upstream']['tag']
MODULE_PACKAGE = 'linux-modules-nvidia-610-open-' + KERNEL
MODULE_PACKAGE_VERSION = '7.0.0-1019.19~24.04.2+1'
BOOT = Path('/boot')


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def output(*args):
    return run(*args, stdout=subprocess.PIPE).stdout.strip()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def check_environment(kernel, headers):
    require(output('uname', '-s') == 'Linux' and output('uname', '-m') == 'aarch64',
            'Build requires Linux aarch64.')
    require(kernel == KERNEL, f'Only {KERNEL} is supported; refusing {kernel}.')
    require((headers / 'include/config/kernel.release').read_text().strip() == kernel,
            'Headers do not match the requested kernel.')
    require('CONFIG_ARM64_64K_PAGES=y' in
            (headers / 'include/config/auto.conf').read_text().splitlines(),
            'Headers must be configured for 64 KiB ARM64 pages.')
    upstream = MANIFEST['upstream']
    for package, version in [(upstream['package'], upstream['package_version']),
                             (MODULE_PACKAGE, MODULE_PACKAGE_VERSION)]:
        require(output('dpkg-query', '-W', '-f=${db:Status-Status} ${Version}', package)
                == 'installed ' + version, f'Install the pinned package {package}={version}.')
    for name, digest in upstream['file_sha256'].items():
        require(hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == digest,
                f'Packaged NVIDIA source changed: {name}.')
    require(output('modinfo', '-k', kernel, '-F', 'version', 'nvidia') == DRIVER,
            'Packaged NVIDIA RM version does not match UVM source.')


def check_install(kernel, headers):
    # Recheck even when DKMS reuses a previously built binary after a host update.
    check_environment(kernel, headers)
    status = output('dkms', 'status')
    require(not any(line.startswith('nvidia/') or line.startswith('nvidia-')
                    for line in status.splitlines()),
            'An NVIDIA DKMS package is registered. Use the precompiled NVIDIA package route.')
    paths = output('dpkg-query', '-L', MODULE_PACKAGE).splitlines()
    stock = [Path(p) for p in paths
             if p.endswith(('/nvidia-uvm.ko', '/nvidia-uvm.ko.zst', '/nvidia-uvm.ko.xz'))]
    require(len(stock) == 1 and stock[0].is_file(), 'Cannot identify the packaged stock UVM file.')
    require(output('modinfo', '-F', 'version', str(stock[0])) == DRIVER,
            'Stock UVM version does not match the pinned driver.')
    selected = Path(output('modinfo', '-k', kernel, '-F', 'filename', 'nvidia_uvm'))
    require(selected.resolve() == stock[0].resolve(),
            'Another UVM override is selected. Remove it and restore stock before installation.')
    require(output('modinfo', '-F', 'vermagic', str(stock[0])).split()[0] == kernel,
            'Stock UVM belongs to another kernel.')


def clean():
    require(not WORK.parent.is_symlink() and not WORK.is_symlink(),
            'Refusing a symlink at the build workspace.')
    if WORK.exists():
        shutil.rmtree(WORK)


def build(kernel, headers, dkms=False):
    check_environment(kernel, headers)
    require(not WORK.parent.is_symlink() and not WORK.exists() and not WORK.is_symlink(),
            'Build workspace exists or is a symlink; clean it before rebuilding.')
    WORK.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SOURCE, WORK, symlinks=True)
    run('patch', '-d', str(WORK), '-p1', '--fuzz=0', '--batch', '-i',
        str(ROOT / 'patches/0002-pack-user-leaf-tables-610.patch'))
    if dkms:
        # Installing this package is the persistent opt-in; stock modules get no
        # global modprobe option. Allocator predicates and a =0 override remain.
        run('patch', '-d', str(WORK), '-p1', '--fuzz=0', '--batch', '-i',
            str(ROOT / 'packaging/enable-packing.patch'))
    run('make', '-C', str(WORK), '-j4', 'CC=gcc-13',
        'NV_KERNEL_MODULES=nvidia nvidia-uvm', 'KERNEL_UNAME=' + kernel,
        'SYSSRC=' + str(headers), 'modules')
    module = WORK / 'nvidia-uvm.ko'
    require(module.is_file(), 'Build did not produce nvidia-uvm.ko.')
    require(output('modinfo', '-F', 'version', str(module)) == DRIVER,
            'Built UVM has an unexpected driver version.')
    require(output('modinfo', '-F', 'vermagic', str(module)).split()[0] == kernel,
            'Built UVM has an unexpected kernel vermagic.')
    digest = hashlib.sha256(module.read_bytes()).hexdigest()
    receipt = {'schema': 1, 'kernel': kernel, 'driver': DRIVER, 'default_on': dkms,
               'module_sha256': digest, 'signed': False}
    (WORK / 'build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(digest, module)
    print('Built only; signing, installation and loading are separate.')


def refresh_initramfs(kernel):
    require(kernel == KERNEL, f'Refusing initramfs update for unsupported kernel: {kernel}')
    if (BOOT / ('initrd.img-' + kernel)).exists():
        # DKMS hooks precede its final depmod. Refresh the index before the image.
        run('depmod', kernel)
        run('update-initramfs', '-u', '-k', kernel)
    else:
        print(f'No initramfs for {kernel} (possibly being removed); no archive created.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build-manual', 'build-install', 'build-dkms', 'check-install', 'clean', 'refresh-initramfs'])
    parser.add_argument('--kernel', default=KERNEL)
    parser.add_argument('--headers', type=Path)
    args = parser.parse_args()
    headers = args.headers or Path('/lib/modules') / args.kernel / 'build'
    try:
        if args.action == 'clean':
            clean()
        elif args.action == 'refresh-initramfs':
            refresh_initramfs(args.kernel)
        elif args.action == 'check-install':
            check_install(args.kernel, headers)
        else:
            build(args.kernel, headers, dkms=args.action in ('build-dkms', 'build-install'))
    except (RuntimeError, OSError, subprocess.CalledProcessError, IndexError) as error:
        print(f'memory-saver: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
