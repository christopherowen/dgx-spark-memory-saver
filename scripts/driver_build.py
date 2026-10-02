#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Profile-selected manual/DKMS builds and read-only compatibility checks."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / 'compatibility.json').read_text())
KERNEL = REGISTRY['default_kernel']
PACKAGE_VERSION = REGISTRY['package_version']
WORK = ROOT / '.work' / 'uvm'
BOOT = Path('/boot')


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def output(*args):
    return run(*args, stdout=subprocess.PIPE).stdout.strip()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def repository_file(name):
    path = (ROOT / name).resolve()
    require(not Path(name).is_absolute() and path.is_relative_to(ROOT.resolve()),
            'Compatibility input must remain inside the repository.')
    return path


def kernel_profile(kernel):
    require(kernel in REGISTRY['kernels'], f'Unsupported kernel: {kernel}; add a reviewed compatibility entry.')
    return REGISTRY['kernels'][kernel]


def driver_profile(version, kernel):
    kernel_profile(kernel)
    require(version in REGISTRY['drivers'],
            f'Unsupported NVIDIA {version}; no reviewed source profile. See docs/compatibility.md.')
    entry = REGISTRY['drivers'][version]
    require(kernel in entry['kernels'], f'NVIDIA {version} has no profile for {kernel}.')
    manifest = json.loads(repository_file(entry['manifest']).read_text())
    require(manifest['upstream']['tag'] == version, 'Profile and source manifest disagree.')
    return dict(entry, driver=version, upstream=manifest['upstream'])


def module_package(kernel, version):
    require(re.fullmatch(r'[0-9]+(?:\.[0-9]+)+', version) is not None, 'Invalid NVIDIA module version.')
    return f'linux-modules-nvidia-{version.split(".")[0]}-open-{kernel}'


def selected_profile(kernel):
    kernel_profile(kernel)
    return driver_profile(output('modinfo', '-k', kernel, '-F', 'version', 'nvidia'), kernel)


def check_environment(kernel, headers):
    require(output('uname', '-s') == 'Linux' and output('uname', '-m') == 'aarch64',
            'Build requires Linux aarch64.')
    kernel_profile(kernel)
    require((headers / 'include/config/kernel.release').read_text().strip() == kernel,
            'Headers do not match the requested kernel.')
    require('CONFIG_ARM64_64K_PAGES=y' in
            (headers / 'include/config/auto.conf').read_text().splitlines(),
            'Headers must be configured for 64 KiB ARM64 pages.')
    profile = selected_profile(kernel)
    upstream = profile['upstream']
    for package, version in [(upstream['package'], upstream['package_version']),
                             (module_package(kernel, profile['driver']), profile['kernels'][kernel]['module_package_version'])]:
        require(output('dpkg-query', '-W', '-f=${db:Status-Status} ${Version}', package)
                == 'installed ' + version, f'Install the pinned package {package}={version}.')
    source = Path(upstream['source_root'])
    for name, digest in upstream['file_sha256'].items():
        require(hashlib.sha256((source / name).read_bytes()).hexdigest() == digest,
                f'Packaged NVIDIA source changed: {name}.')
    require(hashlib.sha256(repository_file(profile['patch']).read_bytes()).hexdigest() == profile['patch_sha256'],
            'Allocator patch differs from its reviewed profile.')
    if profile.get('caveat'):
        print('Compatibility note: ' + profile['caveat'], file=sys.stderr)
    return profile


def stock_module(kernel, version):
    paths = output('dpkg-query', '-L', module_package(kernel, version)).splitlines()
    stock = [Path(p) for p in paths
             if p.endswith(('/nvidia-uvm.ko', '/nvidia-uvm.ko.zst', '/nvidia-uvm.ko.xz'))]
    require(len(stock) == 1 and stock[0].is_file(), 'Cannot identify the packaged stock UVM file.')
    return stock[0]


def check_module(module, kernel, version):
    require(output('modinfo', '-F', 'version', str(module)) == version,
            'UVM artifact driver version differs from the selected RM; rebuild for this driver.')
    require(output('modinfo', '-F', 'vermagic', str(module)).split()[0] == kernel,
            'UVM artifact belongs to another kernel.')


def check_install(kernel, headers, module_dir=None):
    # A driver update can leave a cached DKMS binary for this same kernel.
    profile = check_environment(kernel, headers)
    status = output('dkms', 'status')
    require(not any(line.startswith('nvidia/') or line.startswith('nvidia-')
                    for line in status.splitlines()),
            'An NVIDIA DKMS package is registered. Use the precompiled NVIDIA package route.')
    stock = stock_module(kernel, profile['driver'])
    check_module(stock, kernel, profile['driver'])
    selected = Path(output('modinfo', '-k', kernel, '-F', 'filename', 'nvidia_uvm'))
    require(selected.resolve() == stock.resolve(),
            'Another UVM override is selected. Remove it and restore stock before installation.')
    if module_dir is not None:
        artifacts = [module_dir / ('nvidia-uvm.ko' + suffix) for suffix in ('', '.zst', '.xz', '.gz')]
        artifacts = [path for path in artifacts if path.is_file()]
        require(len(artifacts) == 1, 'Cannot identify the cached DKMS UVM artifact.')
        check_module(artifacts[0], kernel, profile['driver'])
        require('uvm_pack_sysmem_leaf_tables:' in output('modinfo', '-p', str(artifacts[0])),
                'Cached DKMS artifact is not the memory-saver module.')
    return profile


def clean():
    require(not WORK.parent.is_symlink() and not WORK.is_symlink(),
            'Refusing a symlink at the build workspace.')
    if WORK.exists():
        shutil.rmtree(WORK)


def build(kernel, headers, dkms=False):
    profile = check_environment(kernel, headers)
    require(not WORK.parent.is_symlink() and not WORK.exists() and not WORK.is_symlink(),
            'Build workspace exists or is a symlink; clean it before rebuilding.')
    WORK.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(Path(profile['upstream']['source_root']), WORK, symlinks=True)
    run('patch', '-d', str(WORK), '-p1', '--fuzz=0', '--batch', '-i',
        str(repository_file(profile['patch'])))
    if dkms:
        run('patch', '-d', str(WORK), '-p1', '--fuzz=0', '--batch', '-i',
            str(ROOT / 'packaging/enable-packing.patch'))
    run('make', '-C', str(WORK), '-j4', 'CC=' + kernel_profile(kernel)['compiler'],
        'NV_KERNEL_MODULES=nvidia nvidia-uvm', 'KERNEL_UNAME=' + kernel,
        'SYSSRC=' + str(headers), 'modules')
    module = WORK / 'nvidia-uvm.ko'
    require(module.is_file(), 'Build did not produce nvidia-uvm.ko.')
    check_module(module, kernel, profile['driver'])
    digest = hashlib.sha256(module.read_bytes()).hexdigest()
    receipt = {'schema': 1, 'kernel': kernel, 'driver': profile['driver'], 'default_on': dkms,
               'module_sha256': digest, 'signed': False, 'profile': profile,
               'package_version': PACKAGE_VERSION}
    (WORK / 'build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(digest, module)
    print('Built only; signing, installation and loading are separate.')


def refresh_initramfs(kernel):
    kernel_profile(kernel)
    if (BOOT / ('initrd.img-' + kernel)).exists():
        run('depmod', kernel)
        run('update-initramfs', '-u', '-k', kernel)
    else:
        print(f'No initramfs for {kernel} (possibly being removed); no archive created.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['profiles', 'check', 'build-manual', 'build-install', 'build-dkms', 'check-install', 'clean', 'refresh-initramfs'])
    parser.add_argument('--kernel', default=KERNEL)
    parser.add_argument('--headers', type=Path)
    parser.add_argument('--dkms-module-dir', type=Path)
    args = parser.parse_args()
    headers = args.headers or Path('/lib/modules') / args.kernel / 'build'
    try:
        if args.action == 'profiles':
            print(json.dumps(REGISTRY, indent=2))
        elif args.action == 'check':
            print(json.dumps(check_environment(args.kernel, headers), indent=2))
        elif args.action == 'clean':
            clean()
        elif args.action == 'refresh-initramfs':
            refresh_initramfs(args.kernel)
        elif args.action == 'check-install':
            check_install(args.kernel, headers, args.dkms_module_dir)
        else:
            build(args.kernel, headers, dkms=args.action in ('build-dkms', 'build-install'))
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError, IndexError, KeyError) as error:
        print(f'memory-saver: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
