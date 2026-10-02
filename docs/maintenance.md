# Updates and removal

[← README](../README.md) · [Build](installation.md) · [Temporary trial](trial.md)

## Return to the packaged driver

The [temporary trial](trial.md#roll-back) loads a module directly from the build
directory. It does not replace files in `/lib/modules`, update initramfs or
register with DKMS. Stop GPU clients, unload the trial module and reload stock
UVM using that procedure. Confirm all ranks agree before restarting distributed
serving. Removing the checkout alone does not unload a running module.

Once stock UVM is restored, the ignored `.work` build directory or the entire
checkout can be removed. Keep locally enrolled signing keys if other modules
use them; removing this project does not require changing Secure Boot.

## Update the project

Restore stock UVM between trials, then update the checkout and run
`./scripts/check`. Preserve any evidence needed from the previous build outside
the build directory before removing that directory and building again. A new
file on disk does not replace a module already loaded in memory.

Record the commit, unsigned and signed module hashes, source version, kernel,
driver and opt-in parameter for each trial. The historical hashes identify the
original artifacts; path-sensitive builds may produce different hashes.

## Kernel and driver updates

The build deliberately pins a tested package and kernel. Updating either needs
a source review, a build against matching headers, and renewed correctness and
memory measurements. Do not bypass the source checks or copy a module built
for a different kernel. Use the packaged driver while a new combination is
unverified.

Persistent installation and automatic rebuilds are not implemented. They would
need matching NVIDIA RM/UVM versions, signing, conditional activation only on
the compatible kernel, and a working stock fallback. In particular, a global
`uvm_pack_sysmem_leaf_tables` option breaks stock modules that lack the parameter.
