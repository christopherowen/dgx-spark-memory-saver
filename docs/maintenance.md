# Updates and removal

[← README](../README.md) · [Installation](installation.md) · [Status](usage.md)

## Return to the packaged driver

Use the procedure corresponding to the installation method:

| Method | Removal |
| --- | --- |
| Persistent manual | [Unload, `remove-manual`, verify stock and reload](manual.md#remove) |
| DKMS | [Unload, remove DKMS registration, verify stock and reload](dkms.md#remove-and-restore-stock-uvm) |
| Temporary explicit load | [Unload and reload the packaged module](usage.md#roll-back) |

Removing the checkout or rebooting does not uninstall a persistent override.
Removal leaves kernels, swap, boot defaults and shared signing keys untouched.
Verify all ranks before restarting distributed serving. Preserve the checkout
and any incomplete-operation receipt until recovery has finished.

## Return to the stock kernel

After a one-shot 64 KiB boot, stop GPU clients and reboot normally. The explicit
stock GRUB default remains in place and the one-shot candidate selection has
been consumed. A temporary module load is not carried across reboot. Persistent overrides
remain installed for the 64 KiB kernel until removed separately.
Confirm:

```sh
uname -r
getconf PAGESIZE
cat /sys/module/nvidia/version
nvidia-smi
systemctl --failed
swapon --show
```

Expect `7.0.0-1019-nvidia`, `4096` and NVIDIA `580.178.04`. If you followed the
manual `noauto` swap procedure, run `sudo swapon /swap.img` when the original
file is not already active. Do not activate `/swap-64k.img` on this kernel.
Restore the original swap entry's options in `/etc/fstab` and remove the
64 KiB `/swap-64k.img` entry, using the saved
`/var/lib/dgx-spark-memory-saver/preparation/fstab` as a reference. Preserve
unrelated edits made since the backup. Run `sudo systemctl daemon-reload`.

The temporary THP and free-memory settings disappear at reboot unless another
service applies them. Verify the original policy and all nodes' agreement
before resuming serving. A host already using a page-aware swap/policy service
should return through its existing procedure instead of duplicating it.

The kernel packages may remain installed. Keep the explicit stock GRUB pin
while they do: removing the pin can make the newer candidate the default again.
Removing kernels or restoring an older GRUB policy is a separate maintenance
operation; inspect the generated default before rebooting. Never remove the
running or known-working fallback kernel. The GRUB backups are under the same
preparation directory. A normal reboot is not recovery from a hung host; use
the console to select the known-working entry if needed.

## Update the project

Remove the existing persistent installation using its route above, then update
the checkout and run
`./scripts/check`. Preserve any evidence needed from the previous build outside
the build directory before removing that directory and building again. A new
file on disk does not replace a module already loaded in memory.

Record the commit, unsigned and signed module hashes, source version, kernel,
driver and opt-in parameter for each build and load. The historical hashes identify the
original artifacts; path-sensitive builds may produce different hashes.

## Kernel and driver updates

The build deliberately pins a tested package and kernel. Updating either needs
a source review, a build against matching headers, and renewed correctness and
memory measurements. Do not bypass the source checks or copy a module built
for a different kernel. Use the packaged driver while a new combination is
unverified.

Both installation methods select reviewed combinations from
[compatibility.json](../compatibility.json). Adding a version is described in
[the compatibility guide](compatibility.md). DKMS build
exclusions skip unvalidated kernels. Remove either override before
NVIDIA driver updates: checks on new builds do not remove a previously installed
binary after RM changes. Installing through DKMS does not change the stock GRUB
default or install a global modprobe parameter.
