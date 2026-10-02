# NVIDIA 610.57.04 port

This unpromoted branch builds package 0.3.0 for Ubuntu source package
`nvidia-kernel-source-610-open=610.57.04-0ubuntu0.24.04.3` and the existing
`7.0.0-1019-nvidia-64k` kernel. It remains unpromoted.

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
The original patch and results remain unchanged; `provenance-580.json` retains
the previous source manifest and `provenance.json` pins the new source hashes.

Before changing packages, stop GPU clients and remove the 0.2.0 DKMS
registration. Keep exact R580 packages available for restoration. Install both
Ubuntu precompiled-module metapackages
`linux-modules-nvidia-610-open-nvidia-hwe-24.04` and
`linux-modules-nvidia-610-open-nvidia-64k-hwe-24.04` at
`7.0.0-1019.19~24.04.2+1`, plus `nvidia-driver-610-open` and the source package
at `610.57.04-0ubuntu0.24.04.3`. The metapackages provide the NVIDIA DKMS
dependency without registering NVIDIA's separate DKMS build. Simulate the
transaction first and retain firmware needed by the previous driver.

Copy this clean pinned checkout to `/usr/src/dgx-spark-memory-saver-0.3.0`,
excluding `.git` and `.work`. Run `sudo dkms add -m dgx-spark-memory-saver -v
0.3.0`, then `sudo dkms build -m dgx-spark-memory-saver -v 0.3.0 -k
7.0.0-1019-nvidia-64k` and the corresponding `dkms install`. Use the already
enrolled fleet signing key. Confirm signed R610 RM/UVM, reboot, and verify
`./scripts/status --json` before allocation and serving tests.

Remove with `sudo dkms remove -m dgx-spark-memory-saver -v 0.3.0 --all`
while GPU clients are stopped. The hook restores stock R610 UVM and refreshes
initramfs. To restore R580, remove this registration first, reinstall the
recorded R580 packages, reinstall the pinned 0.2.0 source/registration, and
reboot before starting serving. Never load an R580 UVM beside R610 RM.
