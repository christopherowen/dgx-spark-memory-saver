# Status, loading and validation

[← README](../README.md) · [Manual installation](manual.md) · [DKMS](dkms.md) · [Removal](maintenance.md)

## Read-only status

From the checkout, without sudo:

```sh
./scripts/status
./scripts/status --json
```

This reports the running kernel/page size, loaded NVIDIA RM/UVM identities,
packing parameter, selected UVM files for the running and supported kernels,
Secure Boot, DKMS registration and manual installation receipt. It uses sysfs
and read-only inspection commands; it does not initialize CUDA, allocate GPU
memory, load modules or repair anything.

| Result | Meaning |
| --- | --- |
| `packing-enabled` | Compatible loaded module has its packing parameter enabled |
| `packing-disabled` | Patched module is loaded with the parameter disabled |
| `stock-loaded` | Loaded module has no packing parameter and matches disk |
| `uvm-not-loaded` | No UVM module is currently loaded |
| `needs-attention` | Known mismatch, conflicting installation or incomplete operation |
| `unverified` | A required identity or registration could not be inspected |

Exit status is 0 for consistent inspected state, 1 for a detected problem, and
2 for incomplete inspection or an unsupported inspection platform. A status of
`packing-enabled` is not a memory-savings measurement and does not establish
that every allocation meets the packing predicates. JSON preserves both raw
fields and findings for automation. Suggested responses are in
[troubleshooting](troubleshooting.md).

## Load and verify

After completing either persistent installation, coordinate a maintenance
window and stop GPU clients before replacing a loaded module. Follow the
load steps in the [manual guide](manual.md#load-and-verify) or
[DKMS guide](dkms.md#5-load-and-verify), then run `./scripts/status`.
All ranks of distributed serving must use matching kernel/driver/module state.
Run the validation below before serving. Installation and removal never stop
workloads or load/unload UVM automatically.

## Temporary loading without installation

This optional path uses the historical default-off build and explicit `=1`.
It lasts until unload or reboot. It assumes **neither** persistent manual nor
DKMS memory-saver installation is present. Use their removal guides otherwise.
Retain a known-working stock kernel and recovery access.

### Build and identity

Run `scripts/build.sh` as an ordinary user. It requires the pinned source package
and staged 64 KiB headers, but does not require the candidate kernel to be running
while compiling. Before loading, verify the running kernel, module and source:

```sh
uname -r
getconf PAGESIZE
cat /sys/module/nvidia/version
modinfo .work/nvidia-580.178.04-uvm-pool/nvidia-uvm.ko
sha256sum .work/nvidia-580.178.04-uvm-pool/nvidia-uvm.ko
```

The load target must be `7.0.0-1019-nvidia-64k` with 65,536-byte pages and the
matching NVIDIA 580.178.04 driver. Historical binary hashes in the result file
identify the tested artifacts; a new build may have a different binary hash.

Secure Boot requires signing the module with a locally held, enrolled key using
the target headers' `scripts/sign-file`. Keep keys outside this repository. The
original trial used an existing enrolled key and left Secure Boot enabled.
For this temporary build only, sign the output directly after selecting your
enrolled `DGX_MOK_DIR`:

```sh
sudo /lib/modules/7.0.0-1019-nvidia-64k/build/scripts/sign-file sha256 \
  "$DGX_MOK_DIR/MOK.priv" "$DGX_MOK_DIR/MOK.der" \
  .work/nvidia-580.178.04-uvm-pool/nvidia-uvm.ko
```

A signature is a loading requirement, not proof of correctness. The combined
`build-sign` helper instead produces the persistent default-on build.

### Load the temporary module

With all GPU clients stopped, confirm that `/dev/nvidia-uvm` has no users. Load
only the built UVM module; keep the packaged RM, modeset and DRM modules.

```sh
sudo fuser /dev/nvidia-uvm
# Proceed only when this reports no users.
sudo modprobe -r nvidia_uvm
sudo insmod .work/nvidia-580.178.04-uvm-pool/nvidia-uvm.ko \
  uvm_pack_sysmem_leaf_tables=1 \
  uvm_release_asserts=1 \
  uvm_release_asserts_set_global_error=1
cat /sys/module/nvidia_uvm/parameters/uvm_pack_sysmem_leaf_tables
cat /sys/module/nvidia_uvm/srcversion
```

Expected packing value: `Y`. Record the signed file hash, loaded source identity,
parameters and kernel on every node. The original trial's identities are in
[trial-results.json](../results/2026-10-02/trial-results.json).
If loading fails, restore the packaged module with `sudo modprobe nvidia_uvm`
before running any CUDA work. Do not bypass signature or version checks.

## Validate

Use an isolated CUDA/PyTorch environment bounded to 20 GiB, with serving stopped.
The original trial used PyTorch `2.13.0+cu130` in its existing serving image.
Both programs allocate GPU memory and synchronize:

```sh
python3 tests/allocation_stress.py
python3 tests/cuda_smoke.py
```

The first test uses direct CUDA driver allocations after establishing a primary
context. Four threads allocate, free and reuse holes, verifying complete buffers.
The second crosses the 4 GiB boundary with a 4.5 GiB pinned transfer in each
direction, then checks BF16 matrix multiplication and CUDA graph replay.

Inspect the kernel log for UVM assertions, Xids and allocation errors. Verify
cleanup after clients exit. Then check the actual model, distributed operations,
quality and memory headroom before timing. A successful test must also establish
that packing ran: the parameter alone does not prove its hardware predicates
matched. The original trial confirmed the large UVM allocation reduction.

## Trace separately from timing

`tools/kernel-charges.bt` requires root, bpftrace and the exact Linux/NVIDIA
symbols used by the trial. Pass the actual CPU page size as argument 1. It is a
diagnostic probe, not a general memory accountant; socket and pipe uncharges are
not completely covered. It exposes replaced-page records rather than silently
double counting them. Check replacements, order mismatches and probe errors
before interpreting any attribution. The recorded corrected trial had no UVM
replacement records.

The original trace was bounded to 768 MiB, no swap and 480 seconds, with
`BPFTRACE_MAX_MAP_KEYS=131072`. Attach before model startup; stop gracefully with
SIGINT and wait for it to exit before benchmarking. Instrumented work is not a
valid throughput measurement.

## Roll back

After stopping GPU clients, unload the manually loaded UVM and reload the packaged module:

```sh
sudo modprobe -r nvidia_uvm
sudo modprobe nvidia_uvm
```

This works because the manual procedure never installs over packaged modules or changes
modprobe configuration. A normal reboot also returns to the configured stock
boot path; the recorded fleet retained 4 KiB as its normal default.
Verify that the custom parameter is absent and that all nodes agree before
restoring distributed serving.

Persistent installation is available through [manual installation](manual.md)
or [DKMS](dkms.md). Their installed overrides have separate removal procedures;
this temporary-load rollback does not uninstall either one. A global modprobe
parameter would break stock UVM versions that do not recognize it. No production
promotion is implied by adding the DKMS packaging.
