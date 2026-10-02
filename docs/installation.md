# Installation and signing

[← README](../README.md) · [Kernel setup](kernel.md) · [Manual installation](manual.md) · [DKMS](dkms.md)

The order is: **get this project → install prerequisites → enroll a signing key
→ choose manual or DKMS installation → load and verify**.

## 1. Get the source and prerequisites

On the Spark:

```sh
sudo apt-get update
sudo env NEEDRESTART_MODE=l apt-get --no-remove install git python3 openssl patch
git clone https://github.com/christopherowen/dgx-spark-memory-saver.git
cd dgx-spark-memory-saver
./scripts/check
```

Follow [kernel setup](kernel.md) to preserve the stock boot entry, install the
exact packages and prepare compatible swap. Already-prepared machines should
verify their identities instead of repeating preparation.

| Requirement | Tested package or tool |
| --- | --- |
| 64 KiB kernel and modules | `linux-image-7.0.0-1019-nvidia-64k`, `linux-modules-7.0.0-1019-nvidia-64k` |
| Matching headers | `linux-headers-7.0.0-1019-nvidia-64k` |
| CPU governor tools | `linux-tools-7.0.0-1019-nvidia-64k` |
| Packaged NVIDIA modules | `linux-modules-nvidia-580-open-7.0.0-1019-nvidia-64k` |
| NVIDIA source | `nvidia-kernel-source-580-open=580.178.04-0ubuntu0.24.04.1` |
| Compiler and build tools | `build-essential`, `gcc-13`, `patch`, `coreutils` |
| Inspection and boot support | `kmod`, `dkms`, `initramfs-tools`, `util-linux`, `psmisc` |
| Signing and checks | Python 3.10+, `openssl`, `mokutil` |

Exact kernel-package versions and installation commands are in the kernel
guide. CUDA development packages, PyTorch and bpftrace are not needed to compile
this kernel module. Hardware-free tests use disposable local signing keys;
they never enroll them, access a GPU or modify system installation paths.

## 2. Generate or select a signing key

If fan-control already uses an enrolled key, reuse it. Set the directory that
contains its `MOK.priv` and `MOK.der`, for example through your existing
`DGX_MOK_DIR` setting. Do not generate a new key for each build.

For a new pair:

```sh
./scripts/generate-signing-key
```

The default directory is
`$HOME/.local/share/dgx-spark-memory-saver/keys`. An explicit directory can be
selected with `DGX_MOK_DIR` or `--key-dir`. The helper refuses existing files,
verifies that the generated key matches the certificate, and creates a mode
0600 private key. The certificate is marked for module signing. Nothing is
enrolled or installed by this command.

## 3. Sign for Secure Boot

Check `mokutil --sb-state`. The recorded hardware tests kept Secure Boot enabled.
Custom modules need a signature from a certificate enrolled on the target host;
see [Ubuntu's Secure Boot and MOK model](https://documentation.ubuntu.com/security/security-features/platform-protections/secure-boot/).

For a new key, request enrollment:

```sh
export DGX_MOK_DIR="${DGX_MOK_DIR:-$HOME/.local/share/dgx-spark-memory-saver/keys}"
sudo mokutil --import "$DGX_MOK_DIR/MOK.der"
```

Choose a temporary password. During a planned reboot into the stock kernel, use
**Enroll MOK → Continue → Yes** at the firmware console, enter the password,
and complete the reboot. SSH does not complete the firmware step. After
reconnecting, restore `DGX_MOK_DIR` if needed and verify:

```sh
sudo mokutil --test-key "$DGX_MOK_DIR/MOK.der"
```

Require the affirmative enrollment message, not merely an exit code: the DGX OS
version can return 1 even while reporting that the certificate is enrolled.
`build-sign` checks that exact message itself. Certificate enrollment is needed
on every target host; distribute the public certificate, not the private key.

For a root-owned existing key, run the helper as its owner with an explicit
`--key-dir`; do not make the private key readable to other users. DKMS's
persistent signing configuration is described in its own guide.

## 4. Choose an installation route

| Route | Build/sign | Persistence and removal |
| --- | --- | --- |
| [Manual installation](manual.md) | `./scripts/build-sign` | `install-manual` / `remove-manual`; survives reboot |
| [DKMS installation](dkms.md) | DKMS builds and signs with its configured key | DKMS manages registration and removal for the supported combination |

Both persistent builds enable packing by default and preserve the same
allocator predicates. Neither installs a global modprobe option. Both must be
removed before upgrading NVIDIA packages. They cannot coexist on the same
kernel. Installation does not load the module or change boot defaults.

For a temporary explicit load without installation, the historical default-off
build remains available as `./scripts/build.sh`; see
[temporary loading](usage.md#temporary-loading-without-installation).

## Test dependencies

Use an existing compatible CUDA/PyTorch environment for hardware tests. The
recorded test used PyTorch `2.13.0+cu130` in the serving image; its identity is
in the result files. Both test programs require PyTorch and host-driver access,
but no full CUDA toolkit. Record changes to that environment as new conditions.

`bpftrace` is optional, for allocation-attribution diagnostics only. Install it
with `sudo apt-get --no-remove install bpftrace` when needed, and follow
[the trace limits](usage.md#trace-separately-from-timing). Instrumentation must
be stopped before throughput measurements.
