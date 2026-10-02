# Install with DKMS

[← README](../README.md) · [Kernel setup](kernel.md) · [Manual build/sign](installation.md) · [Removal](#remove-and-restore-stock-uvm)

This follows fan-control's **source registration → DKMS build/sign → install →
load/verify** workflow. It targets Ubuntu/DGX OS with DKMS 3.x (interfaces reviewed
against 3.0.11 and the fleet's 3.4.3). Installing this package is the persistent
opt-in: its UVM module defaults to packing eligible tables. There is no global
modprobe option and no new boot service. CUDA clients load UVM normally.

**Supported combination:** Linux aarch64, `7.0.0-1019-nvidia-64k`, NVIDIA
`580.178.04`, source package `580.178.04-0ubuntu0.24.04.1`, and the matching
precompiled NVIDIA kernel-module package. Other kernels, including the 4 KiB
fallback, are excluded. `AUTOINSTALL=yes` supports this exact combination;
future kernel/driver versions require an updated, validated compatibility pin.

DKMS packages only `nvidia-uvm`. The build also compiles RM to resolve its symbols,
but DKMS does not install that RM output. The packaged NVIDIA RM, modeset, DRM
and peermem remain authoritative. A separate NVIDIA DKMS package is not supported
alongside this replacement: two DKMS packages must not own the same UVM module.

## 1. Prepare the host

Complete [kernel and package setup](kernel.md) through the preboot checks.
Run `./scripts/check` in this checkout. The host must have the pinned headers,
NVIDIA source and precompiled modules, Python 3, GCC 13 and the other listed
build tools. Then check:

```sh
sudo apt-get --no-remove install dkms openssl mokutil
dkms --version
dkms status
modinfo -k 7.0.0-1019-nvidia-64k -F filename nvidia_uvm
modinfo -k 7.0.0-1019-nvidia-64k -F version nvidia
```

Before first installation, UVM should resolve to the packaged file under
`kernel/nvidia-580-open/`, not a manual override or another DKMS package. Remove any [persistent manual installation](manual.md#remove), restore stock,
and unload any temporarily loaded module in a maintenance window.
Building does not need a reboot or GPU access. Installing changes future module
loads and initramfs, so install/remove only with GPU clients stopped.

## 2. Configure DKMS signing

Use the [existing-key or enrollment instructions](installation.md#3-sign-for-secure-boot)
if needed. DKMS signs the module itself; do not run the manual `sign-file` step
on DKMS output. A certificate must be enrolled on every target machine.

Inspect existing settings before changing them:

```sh
sudo grep -H -E '^[[:space:]]*(mok_signing_key|mok_certificate)=' \
  /etc/dkms/framework.conf /etc/dkms/framework.conf.d/*.conf
```

Absent files or no matches can be normal. If fan-control already uses an
explicit enrolled key, retain that setup and verify the configured certificate
with `sudo mokutil --test-key /actual/path/to/MOK.der`. These are system-wide
settings shared by DKMS modules, not settings private to memory-saver.

For a new signing setup, keep the key in a persistent root-owned directory. Set
`DGX_MOK_DIR` to the already-created and enrolled pair from the signing guide:

```sh
sudo install -d -m 0700 /root/.local/share/dgx-spark-memory-saver/keys
sudo install -m 0600 "$DGX_MOK_DIR/MOK.priv" \
  /root/.local/share/dgx-spark-memory-saver/keys/MOK.priv
sudo install -m 0644 "$DGX_MOK_DIR/MOK.der" \
  /root/.local/share/dgx-spark-memory-saver/keys/MOK.der
sudo mokutil --test-key /root/.local/share/dgx-spark-memory-saver/keys/MOK.der
sudoedit /etc/dkms/framework.conf
```

Set these entries, preserving unrelated settings and checking that no drop-in
overrides them:

```sh
mok_signing_key="/root/.local/share/dgx-spark-memory-saver/keys/MOK.priv"
mok_certificate="/root/.local/share/dgx-spark-memory-saver/keys/MOK.der"
```

Do not replace an existing signing identity merely to use these example paths.
Verify the actual key/certificate paths printed by DKMS during the build.
On systems intentionally running without signature enforcement, enrollment is
not required; this project does not disable Secure Boot.

## 3. Register only the build inputs

Version `0.4.0` is the DKMS package version, independent of NVIDIA's module
version. These commands retain the production R580 package setup; the same build
helper selects R610 when that reviewed profile is installed. Read its
[conditional requirements](driver-610.md) before using R610. From the checkout root:

```bash
(
  set -euo pipefail
  destination=/usr/src/dgx-spark-memory-saver-0.4.0
  test ! -e "$destination"
  sudo install -d "$destination/scripts" "$destination/patches" "$destination/packaging"
  sudo install -m 0644 dkms.conf compatibility.json provenance.json provenance-610.json "$destination/"
  sudo install -m 0755 scripts/driver-build scripts/refresh-initramfs "$destination/scripts/"
  sudo install -m 0644 scripts/driver_build.py "$destination/scripts/"
  sudo install -m 0644 patches/0001-pack-user-leaf-tables.patch \
    patches/0002-pack-user-leaf-tables-610.patch "$destination/patches/"
  sudo install -m 0644 packaging/enable-packing.patch "$destination/packaging/"
)
sudo dkms add -m dgx-spark-memory-saver -v 0.4.0
```

This copies no keys, binaries, results, `.work` directory or NVIDIA source tree.
The build reads the package-managed NVIDIA source, verifies its fingerprints,
and patches an isolated copy inside DKMS's build directory.

## 4. Build and install

```sh
sudo dkms build -m dgx-spark-memory-saver -v 0.4.0 -k 7.0.0-1019-nvidia-64k
sudo dkms install -m dgx-spark-memory-saver -v 0.4.0 -k 7.0.0-1019-nvidia-64k
dkms status -m dgx-spark-memory-saver
modinfo -k 7.0.0-1019-nvidia-64k -F filename nvidia_uvm
modinfo -k 7.0.0-1019-nvidia-64k -F version nvidia_uvm
modinfo -k 7.0.0-1019-nvidia-64k -F vermagic nvidia_uvm
modinfo -k 7.0.0-1019-nvidia-64k -F signer nvidia_uvm
modinfo -k 7.0.0-1019-nvidia-64k -p nvidia_uvm
```

Expect `installed`, an `updates/dkms/nvidia-uvm.ko` path (possibly compressed),
NVIDIA version `580.178.04`, matching kernel vermagic, the intended signer and
`uvm_pack_sysmem_leaf_tables` among the parameters. The kernel and source
fingerprints are checked during build; the pre-install hook rechecks them and
the packaged RM/UVM and the actual cached DKMS artifact even when DKMS reuses
an earlier binary. A cached R580 artifact cannot be installed beside R610.
The kernel exclusion is generated from the shared compatibility table.

Do not use `--force` to bypass a failed pre-install check. NVIDIA's version
string is preserved, but the patched source version differs; DKMS supports that
replacement. A version refusal needs inspection, not an automatic override.

Install/remove hooks run `depmod` before updating the existing target initramfs.
DKMS versions differ in how they surface post-hook failures: inspect hook output
and require the following explicit refresh to succeed before loading/rebooting:

```sh
sudo depmod 7.0.0-1019-nvidia-64k
sudo update-initramfs -u -k 7.0.0-1019-nvidia-64k
```

On newer DKMS, the original module is archived with its path for restoration;
older Ubuntu DKMS leaves the packaged file in place beneath the override. Keep
the DKMS state directory intact. Do not manually delete its `original_module`
backup or copy over packaged files.

## 5. Load and verify

Use `./scripts/status` or `./scripts/status --json` from the checkout for a
read-only overview of installed and loaded state.

Boot the candidate kernel using [the one-shot procedure](kernel.md#6-boot-once-into-64-kib)
if necessary, then complete its swap, CPU governor and network checks. With GPU
clients stopped, verify that `sudo fuser /dev/nvidia-uvm` reports no users.
On the candidate kernel:

```sh
uname -r
getconf PAGESIZE
sudo modprobe -r nvidia_uvm
sudo modprobe nvidia_uvm
cat /sys/module/nvidia_uvm/parameters/uvm_pack_sysmem_leaf_tables
cat /sys/module/nvidia_uvm/srcversion
```

Require the target kernel, 65,536-byte pages and packing value `Y`. Both DKMS
and persistent manual installation default to `Y`; the temporary
`build.sh` load uses an explicit `=1`.
The allocator's hardware predicates remain unchanged; parameter presence alone
does not prove that packing actually occurred. Run the [hardware validation](usage.md#validate)
and memory checks before production use. On a cluster, check every rank before
restarting distributed serving.

For diagnosis on this patched module, loading with
`sudo modprobe nvidia_uvm uvm_pack_sysmem_leaf_tables=0` disables packing until
it is next reloaded. Do not put the custom parameter in a global modprobe file:
the stock module does not recognize it.

## Updates

To migrate from `0.1.0`, `0.2.0` or the experimental `0.3.0`, remove that exact
registration using its recorded version,
verify stock restoration, and then register `0.4.0`. Do not overwrite the old
registered source or delete DKMS backup directories.

`git pull` updates the checkout, not `/usr/src` or DKMS's registered source.
For a new project version, remove the old registration as below, then copy and
register the new version using its `dkms.conf`. Do not overwrite registered
source while its module is installed. For a changed checkout retaining `0.4.0`,
remove that registration and its source directory before copying it afresh.

**Remove memory-saver before upgrading NVIDIA packages.** Build exclusions and
pre-install checks prevent new mismatched installations; they cannot unload or
remove a previously installed override merely because a later driver upgrade
changes RM. Never leave this UVM override shadowing a newer NVIDIA driver.
Restore the packaged driver, perform the upgrade, and use stock until that new
combination is supported. DKMS skips other kernels rather than promising
compatibility with an untested version. Preserve the 4 KiB fallback.

## Remove and restore stock UVM

This removes **memory-saver**, restores the packaged UVM driver and refreshes
its initramfs. It leaves the installed kernels, swap files, boot default and
shared signing keys alone. Returning to 4 KiB or removing the optional kernel setup is
[separate](maintenance.md#return-to-the-stock-kernel).

### 1. Identify the installed version and running kernel

```sh
uname -r
dkms status -m dgx-spark-memory-saver
```

The commands below remove version `0.4.0`. If status reports a different
version, use that exact version in the removal and source-cleanup commands.
Stop here if DKMS reports a broken registration: preserve its source and
`original_module` backup while repairing the registration. Do not delete those
directories as a substitute for `dkms remove`.

### 2. Unload the candidate kernel's UVM module

In a maintenance window, stop all GPU clients and their automatic restarts.
On the candidate kernel, confirm `sudo fuser /dev/nvidia-uvm` reports no users,
then unload UVM if present:

```sh
if [ "$(uname -r)" = 7.0.0-1019-nvidia-64k ] && [ -d /sys/module/nvidia_uvm ]; then
  sudo modprobe -r nvidia_uvm
fi
```

**If unload fails, stop.** Do not force-unload an in-use module or proceed as if
it had stopped. If you already booted the stock 4 KiB kernel, its UVM module
need not be unloaded to remove the candidate kernel's on-disk override.

### 3. Remove DKMS registration and refresh the candidate's boot image

```bash
(
  set -e
  sudo dkms remove -m dgx-spark-memory-saver -v 0.4.0 --all
  sudo depmod 7.0.0-1019-nvidia-64k
  sudo update-initramfs -u -k 7.0.0-1019-nvidia-64k
)
```

Require all three commands to succeed before continuing. The explicit refresh
also catches hook failures that some DKMS versions do not propagate. Keep the
candidate kernel installed until this removal finishes. Rebooting alone does
not remove an installed DKMS override.

### 4. Verify the on-disk driver has returned to stock

```sh
dkms status -m dgx-spark-memory-saver
modinfo -k 7.0.0-1019-nvidia-64k -F filename nvidia_uvm
modinfo -k 7.0.0-1019-nvidia-64k -F version nvidia_uvm
modinfo -k 7.0.0-1019-nvidia-64k -p nvidia_uvm
```

Require:

- No remaining memory-saver registration in DKMS status.
- The UVM path under `kernel/nvidia-580-open/`, not `updates/dkms/`.
- NVIDIA version `580.178.04`.
- No `uvm_pack_sysmem_leaf_tables` parameter in the parameter list.

If DKMS removal succeeded but the packaged file was not restored, repair the
exact precompiled package before loading anything:

```bash
(
  set -e
  sudo env NEEDRESTART_MODE=l apt-get --no-remove --reinstall install \
    linux-modules-nvidia-580-open-7.0.0-1019-nvidia-64k=7.0.0-1019.19~24.04.2+1
  sudo depmod 7.0.0-1019-nvidia-64k
  sudo update-initramfs -u -k 7.0.0-1019-nvidia-64k
)
```

Repeat the identity checks. If the override is still selected, stop and resolve
that ownership problem; reinstalling a package does not necessarily remove a
separate higher-priority override.

### 5. Verify the loaded driver before resuming work

Load stock UVM for the **running** kernel, which may be either the retained
4 KiB kernel or the candidate 64 KiB kernel:

```sh
sudo modprobe nvidia_uvm
cat /sys/module/nvidia_uvm/srcversion
modinfo -F srcversion nvidia_uvm
test ! -e /sys/module/nvidia_uvm/parameters/uvm_pack_sysmem_leaf_tables
nvidia-smi
```

The two source versions must match, the parameter-absence check must succeed,
and NVIDIA should report a healthy driver. These distinguish the loaded module
from the file on disk. Run your CUDA/serving correctness check before resuming
use; `nvidia-smi` alone does not exercise UVM. For a distributed service, verify
every rank before restarting them together.

### 6. Remove the registered source, optionally

Only after DKMS status is clear and stock restoration is verified:

```sh
sudo rm -rf -- /usr/src/dgx-spark-memory-saver-0.4.0
```

The ordinary checkout and its `.work` build directory can then be removed too,
after saving any results you need. Keep shared signing keys, enrolled
certificates and DKMS signing settings if fan-control or other modules use
them. No memory-saver service or global modprobe configuration was installed,
so there is none to disable or delete.

## Validation boundary

The allocator patches retain their recorded GPU validation. Version 0.4.0
packaging has hardware-free orchestration tests and exact packaged-source patch
checks for R580 and R610; its own on-device install/remove cycle has not been run.
The hardware lifecycle evidence below belongs to version 0.2.0. DKMS adds a separate
two-line source change (comment and default value), build orchestration, signing
through DKMS, and install/remove hooks. The repository tests exercise rejection
of mismatched packages/headers/source, conflicting module ownership, isolated
builds, cleanup and default patch application without hardware access.

An [isolated DKMS 3.4.3 add/build/sign check](validation.md#isolated-dkms-build-on-dgx1)
passed on dgx1 using private state/source trees and a disposable, unenrolled key.
The status command also passed on the live stock host. A subsequent
[coordinated lifecycle test on dgx3](validation.md#installation-and-removal-on-dgx3)
passed real system DKMS installation, Secure Boot, CUDA checks, removal and
reboot into the restored stock module. It used the already-enrolled fleet key
and previously installed kernel prerequisites; it did not repeat firmware key
enrollment or test a new kernel/driver version. See the
[upstream DKMS implementation](https://github.com/dkms-project/dkms/blob/v3.4.3/dkms.in)
for signing, module backup and hook behavior.
