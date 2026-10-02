# Manual installation and removal

[← README](../README.md) · [Prerequisites and signing](installation.md) · [Status and usage](usage.md) · [DKMS alternative](dkms.md)

This route installs a signed UVM override persistently for the pinned 64 KiB
kernel. It survives reboot but does not rebuild automatically. Choose this
route **or DKMS**, not both. Neither installer changes the kernel boot default
or loads a module. CUDA clients load the selected UVM normally.

## Build and sign

Complete the [kernel setup](kernel.md) and [key enrollment](installation.md).
From the checkout as the key's owner:

```sh
./scripts/build-sign
```

Set `DGX_MOK_DIR` if using an existing signing key. The helper verifies key mode
0600, key/certificate agreement, expiry and enrollment before compiling. It
builds in an isolated source copy, enables packing by default, signs UVM and
records the exact artifact hash in `.work/nvidia-580.178.04-uvm-pool/build.json`.
The public certificate is copied alongside the module; the private key is not.
An existing build directory must first be removed with
`./scripts/driver-build clean` after preserving any needed results.

For a host intentionally running without Secure Boot enforcement, the unsigned
alternative is `./scripts/driver-build build-install`. Installation then requires
`--unsigned` and independently verifies that Secure Boot is disabled. The ordinary
`./scripts/build.sh` produces the historical default-off temporary build, which
the persistent installer deliberately rejects.

## Install

In a maintenance window, stop GPU clients and automatic restarts. If running
the candidate kernel, unload UVM first after verifying it has no users:

```sh
sudo fuser /dev/nvidia-uvm
# Continue only when it reports no users.
sudo modprobe -r nvidia_uvm
sudo ./scripts/install-manual
./scripts/status
```

If currently running the stock 4 KiB kernel, unloading its UVM is unnecessary;
the installation changes only the candidate kernel. An unsigned installation
uses `sudo ./scripts/install-manual --unsigned` after the unsigned build above.

The installer checks source/package/header/driver identity, the build receipt,
module hash and Secure Boot requirements. It refuses another override or a
memory-saver DKMS registration. It writes only:

- `/lib/modules/7.0.0-1019-nvidia-64k/updates/dgx-spark-memory-saver/nvidia-uvm.ko`;
- its installation receipt and lock under `/var/lib/dgx-spark-memory-saver/`;
- the target module index and existing target initramfs.

The packaged module remains at its original path. No global modprobe option,
private key, boot service or GRUB change is installed. Keep this checkout for
removal. A durable receipt is written before module installation, so an
interrupted installation can be recovered with the removal command.

## Load and verify

Boot the candidate kernel with [the one-shot procedure](kernel.md#6-boot-once-into-64-kib)
if necessary. With GPU clients still stopped:

```sh
sudo modprobe nvidia_uvm
./scripts/status
```

Expect matching loaded/on-disk identities, the supported kernel and driver,
and `packing-enabled`. This means the parameter is enabled; it does not prove
that any particular allocation used packing or measure memory saved. Complete
[CUDA and serving validation](usage.md#validate) before resuming production.

## Remove

Stop GPU clients. On the candidate kernel, unload UVM before removal:

```sh
sudo modprobe -r nvidia_uvm
sudo ./scripts/remove-manual
./scripts/status
sudo modprobe nvidia_uvm
./scripts/status
```

On the stock 4 KiB kernel, its UVM does not need unloading to remove the
candidate's on-disk override. **Stop if unload fails; never force-unload it.**

Removal verifies the installed file against the receipt before deleting it,
updates the target module index/initramfs, and verifies that the packaged UVM
is selected and lacks the packing parameter. Only then is the receipt removed.
It never deletes an unrecognized replacement file, loads a module or stops a
service. After loading stock, require matching loaded/on-disk identities and
absence of the packing parameter. Test CUDA/serving before resuming use.

If removal or initramfs refresh fails, the receipt remains for recovery. Fix the
reported problem and rerun `remove-manual`; it can finish even if the override
was already deleted. If the packaged file itself is missing, use the exact
package repair command in [stock restoration](dkms.md#4-verify-the-on-disk-driver-has-returned-to-stock),
then rerun removal. Do not edit receipt hashes or delete its state to suppress
an ownership error.

Removing the override leaves kernels, swap, boot defaults, signing keys and
certificates intact. After successful removal, the checkout and build directory
may be deleted. The empty lock/state directory is harmless. A reboot alone
does not uninstall a persistent manual override.

## Updates and migration

Remove the old manual installation before building/installing a replacement or
registering DKMS. Conversely, remove the DKMS registration and verify stock UVM
before installing manually. Remove this override **before NVIDIA driver updates**;
a cached UVM binary does not become compatible when RM changes. Other kernel
versions remain unsupported until explicitly reviewed and validated.
