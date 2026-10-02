# Load, verify and unload the manual build

First complete [kernel and prerequisite setup](kernel.md) and
[build and signing](installation.md). These are operator instructions, not an
automatic installation procedure. Loading with `insmod` lasts until the module
is unloaded or the machine reboots; use DKMS for persistent installation.
These commands assume the manual route, with no memory-saver DKMS override
installed. If using DKMS, follow [DKMS load/removal](dkms.md) instead.
Coordinate an exclusive window and stop all GPU clients before changing UVM.
For distributed serving, every rank must use the same kernel and module.
Retain a known-working stock kernel and a recovery path.

## Build and identity

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
A signature is a loading requirement, not proof of correctness.

## Load and verify

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

Persistent installation is available through [DKMS](dkms.md). Its default-on
build and installed override have their own removal procedure; do not use the
manual rollback to claim a DKMS installation has been removed. A global modprobe
parameter would break stock UVM versions that do not recognize it. No production
promotion is implied by adding the DKMS packaging.
