# NVIDIA 610.57.04 port

This unpromoted branch builds package 0.3.0 for Ubuntu source package
`nvidia-kernel-source-610-open=610.57.04-0ubuntu0.24.04.3` and the existing
`7.0.0-1019-nvidia-64k` kernel. Hardware validation is pending.

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
