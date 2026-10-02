# SPDX-License-Identifier: MIT
"""Local key generation and signed builds. No enrollment, install or module load."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

import driver_build as driver


def key_directory():
    return Path(os.environ.get('DGX_MOK_DIR',
                str(Path.home() / '.local/share/dgx-spark-memory-saver/keys')))


def command(*args):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def check_pair(private, certificate):
    driver.require(stat.S_IMODE(private.stat().st_mode) == 0o600,
                   f'Private key must have mode 0600: {private}')
    public = command('openssl', 'pkey', '-in', str(private), '-pubout', '-outform', 'DER').stdout
    cert_public = command('openssl', 'x509', '-inform', 'DER', '-in', str(certificate),
                          '-pubkey', '-noout').stdout
    der = subprocess.run(['openssl', 'pkey', '-pubin', '-outform', 'DER'], input=cert_public,
                         check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    driver.require(public == der, 'Private key and certificate do not match.')
    command('openssl', 'x509', '-inform', 'DER', '-in', str(certificate), '-checkend', '0', '-noout')


def require_enrolled(certificate):
    # DGX OS mokutil can return 1 even for an enrolled certificate. Require the
    # exact affirmative text under a fixed locale, never a return code alone.
    result = subprocess.run(['mokutil', '--test-key', str(certificate)],
                            env={**os.environ, 'LC_ALL': 'C'}, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    driver.require(f'{certificate} is already enrolled' in result.stdout.splitlines(),
                   f'Certificate is not confirmed enrolled: {certificate}\n{result.stdout.strip()}')


def generate(directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    private, certificate = directory / 'MOK.priv', directory / 'MOK.der'
    driver.require(not private.exists() and not private.is_symlink() and
                   not certificate.exists() and not certificate.is_symlink(),
                   'Refusing to overwrite an existing key or certificate.')
    with tempfile.TemporaryDirectory(prefix='.keygen-', dir=directory) as tmp:
        temp_private, temp_cert = Path(tmp) / 'MOK.priv', Path(tmp) / 'MOK.der'
        command('openssl', 'req', '-new', '-x509', '-newkey', 'rsa:3072', '-nodes',
                '-days', '3650', '-subj', '/CN=DGX Spark local module signing/',
                '-addext', 'basicConstraints=critical,CA:FALSE',
                '-addext', 'subjectKeyIdentifier=hash',
                '-addext', 'extendedKeyUsage=codeSigning,1.3.6.1.4.1.2312.16.1.2',
                '-keyout', str(temp_private), '-outform', 'DER', '-out', str(temp_cert))
        temp_private.chmod(0o600)
        temp_cert.chmod(0o644)
        check_pair(temp_private, temp_cert)
        # link() refuses existing destinations, including a concurrent creator.
        os.link(temp_private, private)
        try:
            os.link(temp_cert, certificate)
        except OSError:
            private.unlink()
            raise
    print(f'Generated {private} and {certificate}; not enrolled.')
    print(command('openssl', 'x509', '-inform', 'DER', '-in', str(certificate),
                  '-noout', '-subject', '-fingerprint', '-sha256').stdout.decode().strip())


def build_sign(directory, headers=None):
    private, certificate = directory / 'MOK.priv', directory / 'MOK.der'
    check_pair(private, certificate)
    require_enrolled(certificate)
    headers = headers or Path('/lib/modules') / driver.KERNEL / 'build'
    sign_file = headers / 'scripts/sign-file'
    driver.require(sign_file.is_file(), f'Missing target signing tool: {sign_file}')
    driver.build(driver.KERNEL, headers, dkms=True)
    module = driver.WORK / 'nvidia-uvm.ko'
    driver.run(str(sign_file), 'sha256', str(private), str(certificate), str(module))
    signer = driver.output('modinfo', '-F', 'signer', str(module))
    driver.require(bool(signer), 'Signing produced no module signer identity.')
    public_copy = driver.WORK / 'signing-certificate.der'
    public_copy.write_bytes(certificate.read_bytes())
    receipt_path = driver.WORK / 'build.json'
    receipt = json.loads(receipt_path.read_text())
    receipt.update(signed=True, signer=signer,
                   certificate_sha256=hashlib.sha256(public_copy.read_bytes()).hexdigest(),
                   module_sha256=hashlib.sha256(module.read_bytes()).hexdigest())
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    print(f'Signed for {driver.KERNEL} by {signer}; not installed or loaded.')


def main(action):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-dir', type=Path, default=key_directory())
    args = parser.parse_args()
    try:
        if action == 'generate':
            generate(args.key_dir)
        else:
            build_sign(args.key_dir)
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'memory-saver: {error}', file=sys.stderr)
        return 1
    return 0
