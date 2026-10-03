# Scope

This repository owns an NVIDIA UVM patch, its build instructions,
standalone tests and evidence. It does not manage the serving cluster.

- Preserve pinned source/package/kernel identities and existing result files.
- Keep GPU arithmetic and unrelated driver paths outside this patch's scope.
- Preserve the `uvm_pack_sysmem_leaf_tables` gate, DMA mapping/accounting,
  per-tree ownership, and wait before slot reuse. Document any change to these
  invariants.
- The temporary `build.sh` defaults packing off; persistent manual and DKMS
  installation enable it through the separate default-on packaging patch.
- Keep the allocator patch's code and line numbering, and recorded results,
  immutable. Comments may be revised in place at the same line count; update
  `patch_sha256`, the provenance `sha256`, and keep `code_sha256` unchanged.
- DKMS supports only combinations registered in compatibility.json. Preserve
  source/package pins and qualification status per profile; do not use a
  wildcard version or patch success alone as evidence of compatibility.
- Build in an ignored copy of the source; never edit packaged driver sources.
- Do not install/load modules, reboot machines or run GPU tests without explicit
  authorization and coordination with the machine's current owner.
- Do not commit keys, module binaries or ignored machine-local files.
- Distinguish local packaging checks from GPU validation. Extraction into this
  repository does not constitute another hardware validation run.
- Record unsuccessful runs and confounds alongside successful results.
