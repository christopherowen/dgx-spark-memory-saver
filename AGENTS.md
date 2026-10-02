# Scope

This repository owns an experimental NVIDIA UVM patch, its build instructions,
standalone tests and evidence. It does not manage the serving cluster.

- Preserve pinned source/package/kernel identities and existing result files.
- Keep GPU arithmetic and unrelated driver paths outside this patch's scope.
- Preserve the opt-in gate, DMA mapping/accounting, per-tree ownership, and wait
  before slot reuse. Document any change to these invariants.
- The manual build defaults packing off; DKMS installation opts in through the
  separate default-on packaging patch. Keep the allocator patch and recorded
  results immutable. DKMS supports only the pinned kernel/driver combination.
- Build in an ignored copy of the source; never edit packaged driver sources.
- Do not install/load modules, reboot machines or run GPU tests without explicit
  authorization and coordination with the machine's current owner.
- Do not commit keys, module binaries or ignored machine-local files.
- Distinguish local packaging checks from GPU validation. Extraction into this
  repository does not constitute another hardware validation run.
- Record unsuccessful runs and confounds alongside successful results.
