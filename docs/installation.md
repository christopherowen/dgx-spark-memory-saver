# Install prerequisites, build and sign

[← README](../README.md) · [Kernel setup](kernel.md) · [Temporary trial](trial.md) · [Updates and removal](maintenance.md)

The order is: **get this project → install the kernel and tools → build and sign
UVM → boot the candidate kernel once → load, validate and roll back**.

## 1. Get the source and install prerequisites

On the Spark, get the checkout and run the hardware-free checks:

```sh
sudo apt-get update
sudo env NEEDRESTART_MODE=l apt-get --no-remove install git python3
git clone https://github.com/christopherowen/dgx-spark-memory-saver.git
cd dgx-spark-memory-saver
./scripts/check
```

Use [the complete kernel setup guide](kernel.md) to preserve the stock boot
entry, install the exact packages and prepare compatible swap. Its package
list includes:

| Requirement | Tested package or tool |
| --- | --- |
| 64 KiB kernel and modules | `linux-image-7.0.0-1019-nvidia-64k`, `linux-modules-7.0.0-1019-nvidia-64k` |
| Matching headers | `linux-headers-7.0.0-1019-nvidia-64k` |
| CPU governor tools | `linux-tools-7.0.0-1019-nvidia-64k` |
| Packaged NVIDIA modules | `linux-modules-nvidia-580-open-7.0.0-1019-nvidia-64k` |
| NVIDIA source | `nvidia-kernel-source-580-open=580.178.04-0ubuntu0.24.04.1` |
| Compiler and build tools | `build-essential`, `gcc-13`, `patch`, `coreutils` |
| Inspection and boot support | `kmod`, `dkms`, `initramfs-tools`, `util-linux`, `psmisc` |
| Signing | `openssl`, `mokutil` |

Exact kernel-package versions and installation commands are in that guide.
Already-prepared machines should verify those identities instead of repeating
host preparation. CUDA development packages, PyTorch and bpftrace are **not**
needed to compile this kernel module.

## 2. Build the patched UVM module

From the checkout root as your ordinary user:

```sh
./scripts/build.sh
```

The script verifies the source package version and SHA-256 of both patched
files, copies the source into `.work/nvidia-580.178.04-uvm-pool`, applies the
patch without fuzz, and builds against the pinned headers. It refuses to reuse
an existing build directory. The resulting module is
`.work/nvidia-580.178.04-uvm-pool/nvidia-uvm.ko`.

The build does not install, sign or load modules, alter boot defaults, or update
initramfs. It also builds RM to resolve module symbols; only UVM was replaced in
the trial. Keep the packaged RM module rather than replacing it with that build
output. Record the printed unsigned module hash before signing.

## 3. Sign for Secure Boot

Check `mokutil --sb-state`. With Secure Boot enforced, the replacement module
must be signed by an enrolled key. The trial kept Secure Boot enabled. These
steps follow [Ubuntu's module signing and MOK model](https://documentation.ubuntu.com/security/security-features/platform-protections/secure-boot/).

### Reuse an existing enrolled key

If you already use an enrolled key for the fan controller or another module,
reuse it. Set the directory containing `MOK.priv` and `MOK.der`:

```sh
# Replace this with the actual directory containing your existing key pair.
export DGX_MOK_DIR="/absolute/path/to/your/keys"
sudo mokutil --test-key "$DGX_MOK_DIR/MOK.der"
```

Require confirmation that the certificate is enrolled. A generated certificate
or pending import is insufficient. Keep the private key outside this checkout.
If the key is root-owned, use `sudo` for signing rather than making it readable
to other users.

### Create and enroll a key if you do not have one

This creates a fresh local pair, refusing to overwrite existing files:

```bash
export DGX_MOK_DIR="$HOME/.local/share/dgx-spark-memory-saver/keys"
(
  set -euo pipefail
  umask 077
  mkdir -p "$DGX_MOK_DIR"
  chmod 700 "$DGX_MOK_DIR"
  test ! -e "$DGX_MOK_DIR/MOK.priv"
  test ! -e "$DGX_MOK_DIR/MOK.der"
  openssl req -new -x509 -newkey rsa:3072 -nodes -days 3650 \
    -subj '/CN=DGX Spark local module signing/' \
    -addext 'extendedKeyUsage=codeSigning' \
    -keyout "$DGX_MOK_DIR/MOK.priv" -outform DER -out "$DGX_MOK_DIR/MOK.der"
  chmod 600 "$DGX_MOK_DIR/MOK.priv"
)
sudo mokutil --import "$DGX_MOK_DIR/MOK.der"
```

Choose a temporary enrollment password. During a planned reboot into the stock
kernel, use the firmware MOK console: **Enroll MOK → Continue → Yes**, enter
the password, and reboot. This needs console access; SSH does not complete it.
After reconnecting, set `DGX_MOK_DIR` again and run
`sudo mokutil --test-key "$DGX_MOK_DIR/MOK.der"`. Verify enrollment before
arming the 64 KiB trial boot. Enroll the signing certificate on every machine
where you intend to load a module signed with that key; distribute the public
certificate, not the private key.

### Sign the built module

From the checkout root with `DGX_MOK_DIR` set to the verified enrolled pair:

```sh
sudo /lib/modules/7.0.0-1019-nvidia-64k/build/scripts/sign-file sha256 \
  "$DGX_MOK_DIR/MOK.priv" "$DGX_MOK_DIR/MOK.der" \
  .work/nvidia-580.178.04-uvm-pool/nvidia-uvm.ko
modinfo -F signer .work/nvidia-580.178.04-uvm-pool/nvidia-uvm.ko
modinfo -F vermagic .work/nvidia-580.178.04-uvm-pool/nvidia-uvm.ko
sha256sum .work/nvidia-580.178.04-uvm-pool/nvidia-uvm.ko
```

Record the signed hash too. The vermagic must match the candidate kernel and
the signer your enrolled certificate. On a machine intentionally running
without signature enforcement, signing may be skipped; this project does not
require disabling Secure Boot.

## 4. Boot and validate

Continue at [the one-shot kernel boot](kernel.md#6-boot-once-into-64-kib), then
[load and verify the replacement UVM module](trial.md#load-and-verify).
Copying or signing a module does not activate it. There is no persistent UVM
installer or DKMS registration in this project.

For the GPU tests, use an existing compatible CUDA/PyTorch environment: the
recorded test used PyTorch `2.13.0+cu130` in the serving image. Its exact image
identity is in the result files. Both test programs require PyTorch and access
to the host driver; a full CUDA toolkit is not required by the Python programs.
Changing the PyTorch environment is a new test condition and should be recorded.

`bpftrace` is optional and only needed for the allocation-attribution diagnostic.
Install it with `sudo apt-get --no-remove install bpftrace` if performing that
trace. Follow [the trace limits](trial.md#trace-separately-from-timing); do not
run instrumentation during throughput measurements.
