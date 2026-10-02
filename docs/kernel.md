# Install and verify the 64 KiB kernel

[← README](../README.md) · [Build and sign UVM](installation.md) · [Rollback](maintenance.md)

These instructions reproduce the **tested DGX OS / Ubuntu 24.04 aarch64 package
combination**. They are for an existing Spark with working NVIDIA 580.178.04
userspace and the stock `7.0.0-1019-nvidia` kernel. They are not a general driver
upgrade recipe. CPU base page size is a kernel build choice, not a GRUB flag.

Do this in a maintenance window, with GPU workloads stopped and console access
available. For distributed serving, prepare and validate every node before
restarting the ranks together. Do not let an inference service automatically
start before the driver and memory checks are complete.

## 1. Inspect the current system and available packages

Use Bash for the command blocks and keep the same shell until reboot:

```bash
uname -m
uname -r
getconf PAGESIZE
cat /sys/module/nvidia/version
nvidia-smi
mokutil --sb-state
findmnt /
df -h / /boot
sudo grub-editenv list

target_kernel=7.0.0-1019-nvidia-64k
stock_kernel=7.0.0-1019-nvidia
kernel_package_version=7.0.0-1019.19~24.04.2
nvidia_source_version=580.178.04-0ubuntu0.24.04.1
sudo apt-get update
apt-cache policy "linux-image-$target_kernel" "linux-modules-$target_kernel" \
  "linux-headers-$target_kernel" "linux-tools-$target_kernel" \
  "linux-modules-nvidia-580-open-$target_kernel" nvidia-kernel-source-580-open
```

Require `aarch64`, the stock kernel above, `4096`, and driver `580.178.04`.
Resolve any pending `next_entry`, `prev_entry` or `initrdfail` override before
continuing. Empty values are normal. Retain enough disk space for both kernels,
the driver build and, if used, the separate 16 GiB swap file below.

Use the machine's configured DGX OS/Ubuntu repositories. If the exact versions
are unavailable, stop here: do not substitute a newer package, add an unverified
repository or download a random kernel. A new version needs a compatibility
review. The NVIDIA module package version is the kernel version **plus `+1`**;
the source package has a separate NVIDIA version.

## 2. Preserve the working boot entry before installing

Installing a newer kernel can change which entry GRUB chooses. This pins the
known-working kernel and saves the previous settings. It deliberately refuses
to overwrite an earlier preparation. If already prepared, inspect that state
instead of rerunning this block.

```bash
(
  set -euo pipefail
  test "$(uname -r)" = "$stock_kernel"
  test "$(getconf PAGESIZE)" = 4096
  boot_backup=/var/lib/dgx-spark-memory-saver/preparation
  boot_pin=/etc/default/grub.d/zz-dgx-spark-memory-saver.cfg
  test ! -e "$boot_backup"
  test ! -e "$boot_pin"
  root_uuid=$(findmnt -n -o UUID /)
  test -n "$root_uuid"
  stock_entry="gnulinux-advanced-$root_uuid>gnulinux-$stock_kernel-advanced-$root_uuid"
  sudo grep -F "'gnulinux-$stock_kernel-advanced-$root_uuid'" /boot/grub/grub.cfg
  sudo mkdir -p "$boot_backup"
  sudo cp -a /etc/default/grub /etc/default/grub.d /etc/fstab /boot/grub/grub.cfg "$boot_backup/"
  sudo grub-editenv list | sudo tee "$boot_backup/grubenv.before"
  printf 'GRUB_DEFAULT="%s"\n' "$stock_entry" | sudo tee "$boot_pin"
  sudo update-grub
  sudo grub-script-check /boot/grub/grub.cfg
  sudo grep -F "set default=\"$stock_entry\"" /boot/grub/grub.cfg
)
```

This uses the submenu identifiers generated on the tested Ubuntu installation.
If the entry or final default check fails, inspect the actual GRUB entries and
resolve the mismatch before installing or rebooting. Do not guess menu numbers.

## 3. Install the exact packages and build tools

First review the simulated transaction. It must preserve the working driver
and stock kernel; unexpected driver changes or removals need resolving first.

```bash
sudo apt-get --simulate --no-remove --no-install-recommends install \
  "linux-image-$target_kernel=$kernel_package_version" \
  "linux-modules-$target_kernel=$kernel_package_version" \
  "linux-headers-$target_kernel=$kernel_package_version" \
  "linux-tools-$target_kernel=$kernel_package_version" \
  "linux-modules-nvidia-580-open-$target_kernel=$kernel_package_version+1" \
  "nvidia-kernel-source-580-open=$nvidia_source_version" \
  git build-essential gcc-13 patch coreutils kmod python3 openssl mokutil \
  dkms initramfs-tools util-linux psmisc
```

Then install the reviewed transaction. `needrestart` listing mode avoids its
service restarts; this is still a host package operation in the maintenance
window. It does not reboot the machine.

```bash
sudo env NEEDRESTART_MODE=l apt-get --no-remove --no-install-recommends install \
  "linux-image-$target_kernel=$kernel_package_version" \
  "linux-modules-$target_kernel=$kernel_package_version" \
  "linux-headers-$target_kernel=$kernel_package_version" \
  "linux-tools-$target_kernel=$kernel_package_version" \
  "linux-modules-nvidia-580-open-$target_kernel=$kernel_package_version+1" \
  "nvidia-kernel-source-580-open=$nvidia_source_version" \
  git build-essential gcc-13 patch coreutils kmod python3 openssl mokutil \
  dkms initramfs-tools util-linux psmisc
sudo dkms autoinstall -k "$target_kernel"
sudo depmod "$target_kernel"
sudo update-initramfs -u -k "$target_kernel"
sudo update-grub
```

`linux-tools` is needed by the Spark's CPU governor service; omitting it caused
an actual failure in the first trial. `psmisc` provides `fuser` for the UVM load
checks. `dkms autoinstall` rebuilds modules **already registered on your host**;
it includes this project only after you have separately registered it through
[the memory-saver DKMS setup](dkms.md). If you use
[dgx-spark-fan-control](https://github.com/christopherowen/dgx-spark-fan-control),
verify its DKMS build and enrolled signing certificate for the new kernel too.
Resolve failed DKMS builds before proceeding.

```bash
dpkg-query -W "linux-image-$target_kernel" "linux-modules-$target_kernel" \
  "linux-headers-$target_kernel" "linux-tools-$target_kernel" \
  "linux-modules-nvidia-580-open-$target_kernel" nvidia-kernel-source-580-open
grep -x 'CONFIG_ARM64_64K_PAGES=y' "/boot/config-$target_kernel"
test -s "/boot/vmlinuz-$target_kernel"
lsinitramfs "/boot/initrd.img-$target_kernel" | less
modinfo -k "$target_kernel" -F version nvidia
modinfo -k "$target_kernel" -F vermagic nvidia_uvm
modinfo -k "$target_kernel" -F signer nvidia_uvm
modinfo -k "$target_kernel" -F vermagic mlx5_core
modinfo -k "$target_kernel" -F vermagic mlx5_ib
dkms status
sudo grub-script-check /boot/grub/grub.cfg
```

Require driver `580.178.04`, target-kernel vermagic, the target modules in the
initramfs, and signed modules under Secure Boot. Check every extra module your
machine depends on, including the fan controller if installed. The current
kernel and page size should still be unchanged.

## 4. Prepare swap for both page sizes

A swap header made for 4 KiB pages cannot simply be reused on the 64 KiB kernel.
Keep the original file intact. The tested hosts use an ext4 root filesystem and
`/swap.img`. If your swap layout differs (partition, Btrfs, zram, encrypted swap
or hibernation), adapt the procedure to that layout first.

```bash
swapon --show
findmnt -no FSTYPE /
cat /etc/fstab
```

For the tested layout, create a separate file, refusing to overwrite anything:

```bash
sudo bash -eu <<'ROOT'
file=/swap-64k.img
test ! -e "$file"
umask 077
fallocate -l 16G "$file"
chmod 600 "$file"
mkswap --pagesize 65536 "$file"
ROOT
sudoedit /etc/fstab
```

In `fstab`, change the original `/swap.img` entry to `noauto`, preserving its
other applicable options. Add the following **also with `noauto`**:

```text
/swap-64k.img none swap noauto 0 0
```

Run `sudo systemctl daemon-reload`. Neither edit disables currently active swap;
this guide activates only the matching file manually after each one-shot boot.
Do not run `swapon /swap-64k.img` on the 4 KiB kernel or reformat the original
file. The separate-file approach follows the
[swap page-size requirement](https://man7.org/linux/man-pages/man8/mkswap.8.html).
The deployment's automatic page-aware swap service is not required for this
manual setup; retain it if your operator already manages swap that way.

## 5. Build and sign before rebooting into 64 KiB

Follow [signing and installation](installation.md#4-choose-an-installation-route).
Compilation can happen while still running the stock 4 KiB kernel. If a new
signing key needs enrollment, complete its firmware-console enrollment and
verify it on the stock kernel before booting into 64 KiB.

## 6. Boot once into 64 KiB

Stop GPU workloads and their automatic restart mechanisms using your normal
service controls. Confirm console/recovery access. Select the exact candidate
entry for one boot while retaining the stock normal default. Set these again
if you opened a new shell after key enrollment:

```bash
target_kernel=7.0.0-1019-nvidia-64k
stock_kernel=7.0.0-1019-nvidia
(
  set -euo pipefail
  root_uuid=$(findmnt -n -o UUID /)
  test -n "$root_uuid"
  stock_entry="gnulinux-advanced-$root_uuid>gnulinux-$stock_kernel-advanced-$root_uuid"
  target_entry="gnulinux-advanced-$root_uuid>gnulinux-$target_kernel-advanced-$root_uuid"
  sudo grep -F "set default=\"$stock_entry\"" /boot/grub/grub.cfg
  sudo grep -F "'gnulinux-$target_kernel-advanced-$root_uuid'" /boot/grub/grub.cfg
  sudo grub-reboot "$target_entry"
  sudo grub-editenv list
)
```

Require `next_entry` to match the candidate, then `sudo reboot`. To cancel
before reboot, use `sudo grub-editenv /boot/grub/grubenv unset next_entry`.
A one-shot entry is not a watchdog: a hung host still needs console/power
recovery. Do not make 64 KiB the persistent default before completing the boot and driver checks.

## 7. Verify the boot, then load the patched UVM module

```bash
uname -r
getconf PAGESIZE
cat /sys/module/nvidia/version
nvidia-smi
systemctl --failed
systemctl is-active nv-cpu-governor.service
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
sudo swapon /swap-64k.img
swapon --show
sudo journalctl -k -b -p warning
```

Require `7.0.0-1019-nvidia-64k`, `65536`, driver `580.178.04`, and working
network/fan/CPU governor services. On the tested hosts the CPU governors read
`performance`. Skip manual `swapon` if the correct file is already active.
The package installation initially gives you **stock UVM on a 64 KiB kernel**;
packing is not active until you follow [manual load and verify](usage.md#load-and-verify)
or install and verify the [DKMS build](dkms.md#5-load-and-verify).

### Reproduce the measured memory profile

The published memory result also used THP disabled on 64 KiB and a 45,166 KiB
minimum free-memory reserve, matching the original 4 KiB host's reserve. These
are separate from the patch, and the measurements include their effects.
Inspect and record the original values before applying the same temporary
settings on the tested hardware:

```bash
cat /sys/kernel/mm/transparent_hugepage/enabled
sysctl vm.min_free_kbytes vm.watermark_boost_factor
printf 'never\n' | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
sudo sysctl -w vm.min_free_kbytes=45166
```

The trial also had `vm.watermark_boost_factor=0` on **both** arms. Keep policy
matched and recorded if benchmarking. These commands are transient and do not
install a persistent sysctl policy. A reserve appropriate to this measured host
is not a universal recommendation for other machines or workloads.

Proceed to [driver validation](usage.md#validate). For rollback, follow
[return to the stock kernel](maintenance.md#return-to-the-stock-kernel).
