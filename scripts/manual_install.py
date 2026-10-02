# SPDX-License-Identifier: MIT
"""Persistent manual UVM installation. Never stop services or load/unload modules."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import driver_build as driver
import signing

KERNEL = driver.KERNEL
STATE = Path('/var/lib/dgx-spark-memory-saver')
RECEIPT = STATE / ('manual-' + KERNEL + '.json')
DESTINATION = Path('/lib/modules') / KERNEL / 'updates/dgx-spark-memory-saver/nvidia-uvm.ko'
SYS_MODULES = Path('/sys/module')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_receipt(receipt):
    descriptor, name = tempfile.mkstemp(prefix='.receipt-', dir=STATE)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            os.fchmod(stream.fileno(), 0o644)
            json.dump(receipt, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, RECEIPT)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def locked():
    driver.require(os.geteuid() == 0, 'Installation/removal requires root; status does not.')
    driver.require(not STATE.is_symlink(), 'Refusing symlinked installation state directory.')
    STATE.mkdir(parents=True, exist_ok=True, mode=0o755)
    with (STATE / 'manual.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def require_unloaded():
    driver.require(driver.output('uname', '-s') == 'Linux' and driver.output('uname', '-m') == 'aarch64',
                   'Manual installation/removal requires Linux aarch64.')
    if driver.output('uname', '-r') == KERNEL:
        driver.require(not (SYS_MODULES / 'nvidia_uvm').exists(),
                       'Stop GPU clients and unload nvidia_uvm before changing its installation.')


def validate_artifact(module, version, allow_unsigned=False):
    receipt = json.loads((module.parent / 'build.json').read_text())
    driver.require(receipt.get('schema') == 1 and receipt.get('kernel') == KERNEL and
                   receipt.get('driver') == version and receipt.get('default_on') is True,
                   'A persistent build for the pinned kernel/driver is required.')
    driver.require(receipt.get('module_sha256') == digest(module),
                   'Module changed after build/signing; rebuild instead of editing the receipt.')
    driver.require(driver.output('modinfo', '-F', 'version', str(module)) == version,
                   'Module driver version does not match.')
    driver.require(driver.output('modinfo', '-F', 'vermagic', str(module)).split()[0] == KERNEL,
                   'Module kernel vermagic does not match.')
    state = driver.output('mokutil', '--sb-state').splitlines()
    enabled = 'SecureBoot enabled' in state
    driver.require(enabled or 'SecureBoot disabled' in state, 'Cannot determine Secure Boot state.')
    if not receipt.get('signed'):
        driver.require(allow_unsigned and not enabled,
                       'Use a signed build, or --unsigned only with Secure Boot disabled.')
    else:
        cert = module.parent / 'signing-certificate.der'
        driver.require(digest(cert) == receipt.get('certificate_sha256'), 'Signing certificate changed.')
        signer = driver.output('modinfo', '-F', 'signer', str(module))
        driver.require(bool(signer) and signer == receipt.get('signer'), 'Module signer does not match receipt.')
        if enabled:
            signing.require_enrolled(cert)
    return receipt


def install(module, allow_unsigned=False):
    require_unloaded()
    driver.require(not RECEIPT.exists() and not RECEIPT.is_symlink(),
                   'A manual installation receipt exists; remove that installation first.')
    driver.require(not DESTINATION.exists() and not DESTINATION.is_symlink(),
                   'Destination exists without this installation; refusing to overwrite it.')
    dkms = driver.output('dkms', 'status')
    driver.require(not any(line.startswith('dgx-spark-memory-saver/') for line in dkms.splitlines()),
                   'Remove the memory-saver DKMS registration before manual installation.')
    profile = driver.check_install(KERNEL, Path('/lib/modules') / KERNEL / 'build')
    driver.require((driver.BOOT / ('initrd.img-' + KERNEL)).is_file(),
                   'Target initramfs is missing; complete kernel setup first.')
    receipt = validate_artifact(module, profile['driver'], allow_unsigned)
    receipt.update(state='installing', method='manual', package_version=driver.PACKAGE_VERSION,
                   destination=str(DESTINATION))
    # Journal first: removal can recover even if copying or initramfs refresh fails.
    save_receipt(receipt)
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.memory-saver-', dir=DESTINATION.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(module.read_bytes())
            os.fchmod(stream.fileno(), 0o644)
            stream.flush()
            os.fsync(stream.fileno())
        driver.require(digest(Path(name)) == receipt['module_sha256'],
                       'Build artifact changed while staging; nothing installed.')
        os.link(name, DESTINATION)  # no overwrite, even if a competing writer appeared
    finally:
        Path(name).unlink(missing_ok=True)
    # No cached module index or initramfs may retain the previous selection.
    if (driver.BOOT / ('initrd.img-' + KERNEL)).exists():
        driver.refresh_initramfs(KERNEL)
    else:
        driver.run('depmod', KERNEL)
    selected = Path(driver.output('modinfo', '-k', KERNEL, '-F', 'filename', 'nvidia_uvm'))
    driver.require(selected.resolve() == DESTINATION.resolve(),
                   'Installed file is not selected. Run remove-manual to restore stock.')
    receipt['state'] = 'installed'
    save_receipt(receipt)
    print(f'Installed {DESTINATION}; not loaded. Run ./scripts/status before loading.')


def remove():
    require_unloaded()
    driver.require(RECEIPT.is_file() and not RECEIPT.is_symlink(), 'No manual installation receipt found.')
    receipt = json.loads(RECEIPT.read_text())
    driver.require(receipt.get('kernel') == KERNEL and receipt.get('method') == 'manual' and
                   receipt.get('destination') == str(DESTINATION), 'Invalid manual installation receipt.')
    if DESTINATION.exists() or DESTINATION.is_symlink():
        driver.require(not DESTINATION.is_symlink() and digest(DESTINATION) == receipt.get('module_sha256'),
                       'Installed file changed; refusing to delete an unrecognized module.')
    receipt['state'] = 'removing'
    save_receipt(receipt)
    DESTINATION.unlink(missing_ok=True)
    if (driver.BOOT / ('initrd.img-' + KERNEL)).exists():
        driver.refresh_initramfs(KERNEL)
    else:
        driver.run('depmod', KERNEL)
    selected = Path(driver.output('modinfo', '-k', KERNEL, '-F', 'filename', 'nvidia_uvm'))
    version = driver.output('modinfo', '-k', KERNEL, '-F', 'version', 'nvidia')
    stock = driver.stock_module(KERNEL, version)
    driver.check_module(stock, KERNEL, version)
    driver.require(selected.resolve() == stock.resolve(),
                   'Stock UVM is not selected. Repair the packaged driver, then rerun remove-manual.')
    driver.require('uvm_pack_sysmem_leaf_tables:' not in driver.output('modinfo', '-p', str(selected)),
                   'Selected module still exposes the packing parameter.')
    RECEIPT.unlink()
    print('Manual override removed and stock UVM selected; not loaded.')


def main(action):
    global KERNEL, RECEIPT, DESTINATION
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", default=driver.KERNEL)
    if action == 'install':
        parser.add_argument('--module', type=Path, default=driver.WORK / 'nvidia-uvm.ko')
        parser.add_argument('--unsigned', action='store_true', help='Allow unsigned build only with Secure Boot disabled')
    args = parser.parse_args()
    try:
        driver.kernel_profile(args.kernel)
        KERNEL = args.kernel
        RECEIPT = STATE / ('manual-' + KERNEL + '.json')
        DESTINATION = Path('/lib/modules') / KERNEL / 'updates/dgx-spark-memory-saver/nvidia-uvm.ko'
        with locked():
            if action == 'install':
                install(args.module, args.unsigned)
            else:
                remove()
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError, IndexError) as error:
        print(f'memory-saver: {error}', file=sys.stderr)
        if RECEIPT.exists():
            print('Installation receipt retained. Resolve the error and use remove-manual for recovery.', file=sys.stderr)
        return 1
    return 0
