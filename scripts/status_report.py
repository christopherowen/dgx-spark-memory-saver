# SPDX-License-Identifier: MIT
"""Read-only installed/loaded UVM inspection. Does not initialize CUDA."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import driver_build as driver

SYS_MODULES = Path('/sys/module')
RECEIPT = Path('/var/lib/dgx-spark-memory-saver') / ('manual-' + driver.KERNEL + '.json')


def read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return None


def probe(*args):
    try:
        result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.stdout.strip() if result.returncode == 0 else None
    except OSError:
        return None


def module_info(kernel):
    if not kernel:
        return None
    values = {field: probe('modinfo', '-k', kernel, '-F', field, 'nvidia_uvm')
              for field in ('filename', 'version', 'srcversion', 'signer')}
    parameters = probe('modinfo', '-k', kernel, '-p', 'nvidia_uvm')
    values['packing_parameter'] = None if parameters is None else 'uvm_pack_sysmem_leaf_tables:' in parameters
    return values


def collect(target_kernel=driver.KERNEL):
    kernel = probe('uname', '-r')
    result = {'kernel': kernel, 'page_size': probe('getconf', 'PAGESIZE'),
              'rm_version': read(SYS_MODULES / 'nvidia/version'),
              'uvm_loaded': (SYS_MODULES / 'nvidia_uvm').is_dir(),
              'loaded_srcversion': read(SYS_MODULES / 'nvidia_uvm/srcversion'),
              'packing': read(SYS_MODULES / 'nvidia_uvm/parameters/uvm_pack_sysmem_leaf_tables'),
              'current_disk': module_info(kernel), 'target_disk': module_info(target_kernel),
              'target_kernel': target_kernel,
              'target_rm_version': probe('modinfo', '-k', target_kernel, '-F', 'version', 'nvidia'),
              'secure_boot': probe('mokutil', '--sb-state'), 'manual_install': None,
              'dkms': None, 'issues': [], 'unknowns': []}
    if target_kernel not in driver.REGISTRY['kernels']:
        result['unknowns'].append('Target kernel has no reviewed compatibility profile.')
    dkms = probe('dkms', 'status')
    if dkms is not None:
        result['dkms'] = [line for line in dkms.splitlines() if line.startswith('dgx-spark-memory-saver/')]
    else:
        result['unknowns'].append('DKMS status unavailable.')
    receipt_path = RECEIPT if target_kernel == driver.KERNEL else RECEIPT.parent / ('manual-' + target_kernel + '.json')
    if receipt_path.exists():
        try:
            result['manual_install'] = json.loads(receipt_path.read_text())
        except (OSError, ValueError):
            result['unknowns'].append('Manual installation receipt unreadable.')
    evaluate(result)
    return result


def supported(version, kernel):
    entry = driver.REGISTRY['drivers'].get(version, {})
    return kernel in entry.get('kernels', []) and kernel in driver.REGISTRY['kernels']


def evaluate(result):
    issues, unknowns = result['issues'], result['unknowns']
    current = result['current_disk'] or {}
    entry = (driver.REGISTRY['drivers'].get(result.get('rm_version'), {})
             if supported(result.get('rm_version'), result.get('kernel')) else {})
    result['qualification'] = entry.get('qualification', 'unreviewed')
    result['caveat'] = entry.get('caveat')
    if not result['kernel'] or not result['page_size']:
        unknowns.append('Running kernel or page size unavailable.')
    if result['uvm_loaded']:
        if not result['loaded_srcversion'] or not current.get('srcversion'):
            unknowns.append('Cannot compare loaded and on-disk UVM identities.')
        elif result['loaded_srcversion'] != current['srcversion']:
            issues.append('Loaded UVM differs from the file selected for the next load.')
    if result['packing'] is not None:
        if not supported(result['rm_version'], result['kernel']) or result['page_size'] != '65536':
            issues.append('Patched UVM is loaded outside the supported kernel/driver/page-size combination.')
    if current.get('packing_parameter'):
        if not supported(current.get('version'), result['kernel']):
            issues.append('Patched UVM is selected on an unsupported running kernel.')
        if result['rm_version'] and result['rm_version'] != current.get('version'):
            issues.append('Selected UVM version differs from loaded NVIDIA RM.')
    target = result['target_disk'] or {}
    if target.get('packing_parameter'):
        if not result.get('target_rm_version'):
            unknowns.append('Cannot determine the target kernel NVIDIA RM version.')
        elif result['target_rm_version'] != target.get('version') or not supported(target.get('version'), result.get('target_kernel', driver.KERNEL)):
            issues.append('Target kernel has a patched UVM/RM version mismatch.')
    if result['uvm_loaded'] and current.get('packing_parameter') and result['packing'] is None and result['loaded_srcversion'] == current.get('srcversion'):
        unknowns.append('Loaded patched module parameter is unreadable.')
    manual = result['manual_install']
    if manual:
        if manual.get('state') != 'installed':
            issues.append('Manual installation is incomplete; use remove-manual to recover.')
        if result['dkms']:
            issues.append('Both manual and DKMS registrations are present.')
        if not target.get('filename'):
            unknowns.append('Cannot determine the manual installation module selection.')
        if target.get('filename') and Path(target['filename']).resolve() != Path(manual.get('destination', '')).resolve():
            issues.append('Manual receipt does not match the selected target module.')
    result['state'] = ('needs-attention' if issues else 'unverified' if unknowns else
                       'packing-enabled' if result['packing'] in ('Y', '1') else
                       'packing-disabled' if result['packing'] is not None else
                       'stock-loaded' if result['uvm_loaded'] else 'uvm-not-loaded')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--kernel', default=driver.KERNEL, help='Target kernel to inspect on disk')
    args = parser.parse_args()
    if probe('uname', '-s') != 'Linux':
        print('memory-saver: status requires Linux; no changes made.', file=sys.stderr)
        return 2
    result = collect(args.kernel)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print('State:', result['state'])
        print('Driver qualification:', result['qualification'])
        if result['caveat']:
            print('Compatibility note:', result['caveat'])
        print('Kernel:', result['kernel'], '| CPU page bytes:', result['page_size'])
        print('Loaded RM:', result['rm_version'], '| UVM:', result['loaded_srcversion'])
        print('Packing parameter:', result['packing'] or 'absent')
        print('Current disk UVM:', (result['current_disk'] or {}).get('filename'))
        print('64 KiB disk UVM:', (result['target_disk'] or {}).get('filename'))
        print('DKMS:', result['dkms'])
        print('Manual:', (result['manual_install'] or {}).get('state', 'not registered'))
        for item in result['issues'] + result['unknowns']:
            print('-', item)
        print('Parameter state does not measure memory saved or prove an allocation used packing.')
    return 1 if result['issues'] else 2 if result['unknowns'] else 0
