# NVIDIA 610.57.04 port

The shared builder selects the R610 profile for Ubuntu source package
`nvidia-kernel-source-610-open=610.57.04-0ubuntu0.24.04.3` and the existing
`7.0.0-1019-nvidia-64k` kernel. The profile remains conditional and is not the production choice.

## Hardware qualification, 2026-10-02

Stock Ubuntu R610 failed a 4.5 GiB transfer on all three Sparks with Xid 31 /
FAULT_PTE. Removing this patch and rebooting dgx3 with stock UVM reproduced the
failure; unlimited memlock did not cure it either. This matches the ARM64
64 KiB DMA-submap alignment problem in
[NVIDIA issue 1269](https://github.com/NVIDIA/open-gpu-kernel-modules/issues/1269).
Installing this UVM port alone does not correct the RM defect.

A separate, signed experimental RM alignment correction passed 3,584 small
allocation/readback operations, the 4.5 GiB transfer, BF16 matmul, CUDA graph
replay, and 60 readback probes around 15 boundaries in a 64 GiB allocation on
each node. R610's default system memory pools retained freed memory after the
large test and prevented vLLM's free-memory preflight. With
`NVreg_EnableSystemMemoryPools=0`, the same tests returned memory to the host,
and the three-rank service passed its 5/5 quality screen and decode/prefill
benchmarks. These observations qualify this particular combination, not stock
R610 or every supported CUDA workload. Long-context capacity was not requalified.

The RM correction, host configuration, exact identities, failed controls and
native benchmark reports are owned by the
[deployment experiment](https://github.com/christopherowen/spark3-vllm-ds41f/tree/main/experiments/2026-10-02-driver-cuda-refresh).
They remain outside this repository's UVM-only installation and DKMS hooks.
The released R580/0.2.0 implementation remains the production choice.

## Port and installation mechanics

`patches/0002-pack-user-leaf-tables-610.patch` rebases the original allocator
onto R610. Only surrounding context changes: the aperture comments and the
`mmu_mode_hal()` signature. Allocation, per-tree ownership, coherent-DMA gate,
tracker wait before reuse, zeroing, unmapping and accounting are preserved.
R610 still allocates a full CPU page for these small tables without the patch.
The original patch and results remain unchanged; `provenance.json` retains
the original source manifest and `provenance-610.json` pins the R610 source hashes.

Before changing packages, stop GPU clients and remove the 0.2.0 DKMS
registration. Keep exact R580 packages available for restoration. Install both
Ubuntu precompiled-module metapackages
`linux-modules-nvidia-610-open-nvidia-hwe-24.04` and
`linux-modules-nvidia-610-open-nvidia-64k-hwe-24.04` at
`7.0.0-1019.19~24.04.2+1`, plus `nvidia-driver-610-open` and the source package
at `610.57.04-0ubuntu0.24.04.3`. The metapackages provide the NVIDIA DKMS
dependency without registering NVIDIA's separate DKMS build. Simulate the
transaction first and retain firmware needed by the previous driver.

Use the shared [DKMS registration and build commands](dkms.md), package version
0.4.0. The builder selects the R610 manifest from the target kernel's installed
RM version and reports its conditional qualification. It does not install an RM
correction, change system-pool settings or claim that stock R610 is safe.

Before a driver change, remove the exact registered memory-saver version while
GPU clients are stopped. Its removal hook restores stock UVM and refreshes the
initramfs. Restore/install the matching driver packages, then rebuild the shared
package for that driver; do not reuse a cached UVM from another NVIDIA release.
Never load an R580 UVM beside R610 RM. The 0.3.0 branch and deployment experiment
retain the original R610 hardware-test identity.
