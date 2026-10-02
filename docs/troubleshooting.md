# Troubleshooting

[← README](../README.md) · [Status](usage.md#read-only-status) · [Removal](maintenance.md)

Run `./scripts/status` first. It never fixes state automatically. Keep serving
stopped while resolving an installation/load problem; verify every rank before
resuming a distributed service.

| Finding | Meaning and next step |
| --- | --- |
| Loaded UVM differs from disk | A module was installed/removed after UVM loaded, or a temporary module is active. In a maintenance window, unload and reload the intended module, then recheck. |
| Patched UVM/RM version mismatch | Remove the override before proceeding with the driver upgrade. Restore matching packaged modules. Do not force a mismatched UVM to load. |
| Both manual and DKMS registration | Choose one installation route. Use the owning route's removal procedure before installing the other. |
| Manual operation incomplete | The receipt survived a failed/interrupted install or removal. Resolve the reported error and rerun `remove-manual`; do not delete the receipt. |
| Installed file changed | The manual remover cannot establish ownership. Inspect who replaced it. Do not alter its stored hash to make removal accept it. |
| `unverified` | Inspect the listed missing tool, permissions or identity. Lack of evidence is not a successful verification. |
| Packing parameter absent | Stock UVM is loaded, or the patch is not selected for this kernel. Inspect current/target paths and registration. |
| Packing enabled, no expected savings | The parameter enables eligibility checks; it does not prove allocations used the packing path. Reproduce the workload and measure memory separately. |

## Build or signing errors

The source package, source file hashes, kernel release and 64 KiB header
configuration must match the pins. Do not bypass a failed identity check. Use
`./scripts/driver-build clean` to discard only the isolated build after saving
needed logs; it never cleans `/usr/src/nvidia-*`.

`build-sign` requires an enrolled matching key pair and private-key mode 0600.
An enrollment request needs its firmware-console step before it is usable.
Reuse the existing fan-control key through `DGX_MOK_DIR` if appropriate. A
root-owned key should be used as its owner, not made readable to other users.
An unknown Secure Boot state blocks manual installation rather than guessing.

## Initramfs refresh failed

Neither installer should be considered complete until its target initramfs is
refreshed. For manual installation, retain the receipt and use `remove-manual`
to return to stock after resolving disk-space or tool errors. DKMS documents an
explicit refresh because some versions do not propagate post-hook failures.
Do not reboot into a partially updated candidate just to see whether it works.

## Module in use

Stop the CUDA clients and their automatic restart mechanisms, then inspect
`sudo fuser /dev/nvidia-uvm`. Unload only once there are no users. The helper
will not stop workloads or force-unload modules. When booted on the stock 4 KiB
kernel, its UVM does not need unloading to remove an override installed only
for the 64 KiB kernel.

## Return to stock

Follow [manual removal](manual.md#remove) or [DKMS removal](dkms.md#remove-and-restore-stock-uvm).
Both include verification and recovery. Keep the known-working stock kernel
and shared signing keys. Boot-default or swap changes made during kernel setup
are separate from driver removal.
