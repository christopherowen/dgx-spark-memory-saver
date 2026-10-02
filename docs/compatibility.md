# Driver compatibility

One builder, signing flow, manual installer, DKMS package and status command
serve all reviewed profiles in [compatibility.json](../compatibility.json).
Selection uses the on-disk NVIDIA RM for the requested kernel, so a running
4 KiB kernel can prepare a different, installed 64 KiB target. A directory name,
the running driver's release, or the mere presence of newer source is not the
selection authority.

| NVIDIA version | Source package revision | Kernel | Qualification |
| --- | --- | --- | --- |
| 580.178.04 | 580.178.04-0ubuntu0.24.04.1 | 7.0.0-1019-nvidia-64k | Allocator and 0.2.0 lifecycle validated on the fleet; production choice |
| 610.57.04 | 610.57.04-0ubuntu0.24.04.3 | 7.0.0-1019-nvidia-64k | Conditional: bounded GPU and serving checks with a separate RM correction and system pools disabled; stock R610 failed |

Version 0.4.0 generalizes the packaging. It retains both allocator patches
unchanged; their added and removed C code is identical. Differences are source
context only. R610's conditional status is reported by both the compatibility
check and status command, and stored with the build receipt. These tools do not
install or verify its separate RM correction; see [the R610 evidence](driver-610.md).

```sh
./scripts/driver-build profiles        # list reviewed profiles; works off-host
./scripts/driver-build check           # verify this host's target; no build/write
./scripts/status --json               # loaded/disk identity and qualification
```

Build, build-sign, manual install/remove and status accept `--kernel RELEASE`.
Only registered kernels are accepted for build/install. Headers must match that
release and enable ARM64 64 KiB pages. Exact source and precompiled-module package
versions, patched-file hashes, patch hash, module driver version and vermagic are
checked. Unknown releases stop with a compatibility error. DKMS generates its
kernel exclusion from the same table and checks the actual cached binary before
installing, including compressed artifacts.

Build artifacts now have the stable path `.work/uvm/`. The build receipt records
the selected driver, target kernel, source identity, patch, qualification and
artifact hash. Existing work must be explicitly cleaned before another build.
Installing registers only UVM, even though NVIDIA's build also produces RM to
resolve symbols. No allocator implementation is duplicated in Python or DKMS.

## Add a release

1. Record the exact NVIDIA source package and stock module package. Add a source
   manifest with hashes for both patched files. Keep historical manifests intact.
2. Review the allocator interfaces, coherent-DMA predicate, per-tree ownership,
   tracking/wait before reuse, zeroing, unmapping and accounting. Reuse an existing
   patch when it applies with zero fuzz and preserves those invariants. If its
   context changed, add a context-only variant and check its code edits against
   the original. Patch applicability alone does not establish compatibility.
3. Add the driver entry and its per-kernel module package pin. For a new kernel,
   add the kernel/compiler entry and the reviewed driver/kernel pairing. DKMS
   exclusion and target selection update from this data; no Python release
   constants or second build script are needed.
4. Run packaging tests, apply to the exact source, compile against the actual
   target headers, and check module identity/signing. In a coordinated maintenance
   window, exercise installation, allocation readback, large transfers, graph
   replay, serving, removal and reboot. Record known external driver requirements.
5. Set qualification from the evidence and bump the project package version for
   a release. Preserve old registered DKMS source until it has been removed.

## Driver upgrades and removal

Remove the installed override before replacing NVIDIA packages. DKMS does not
automatically remove an old UVM when an unrelated RM package changes on the same
kernel. Its cached-artifact check prevents installing a mismatched binary, but
does not make unattended driver replacement safe. Rebuild for the new selected
profile after the package transition. Keep signing and module loading explicit.

Manual removal uses the installed receipt to identify its own override and then
verifies stock UVM against the currently installed RM. It does not require the
old source package to remain installed. Unknown or changed override files remain
protected from deletion. See [manual removal](manual.md#remove) and
[DKMS removal](dkms.md#remove-and-restore-stock-uvm).

## Validation of this packaging change

Hardware-free tests cover both selection paths, unchanged source, source/patch
drift, stale cached binaries, headers, ownership conflicts, signing, recovery
and status. The actual R580 and R610 source files were read from dgx1, checked
against their manifests and patched with zero fuzz; both default-on patches
applied, and the allocator code edits match exactly. The
[source-check receipt](../results/2026-10-02-packaging-profiles/source-check.json)
records the resulting hashes. This change has not been installed or loaded on
the fleet; the existing R580/0.2.0 production installation is unchanged.
