#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ $(uname -s) != Linux || $(uname -m) != aarch64 ]]; then
    echo "Build requires Linux aarch64 and the pinned NVIDIA source/header packages." >&2
    exit 1
fi
source_dir=/usr/src/nvidia-580.178.04
build_dir="$root/.work/nvidia-580.178.04-uvm-pool"
target_kernel=7.0.0-1019-nvidia-64k
[[ $(dpkg-query -W -f='${Version}' nvidia-kernel-source-580-open) == 580.178.04-0ubuntu0.24.04.1 ]]
[[ ! -e "$build_dir" ]]
(cd "$source_dir" && sha256sum -c <<'SUMS'
61dcbb1826e6104452d82d319b5b8c810e328e6a606f619e0efaa273d162bdea  nvidia-uvm/uvm_mmu.c
9676e8dd2e3ce37390fdac6a8dd18d728d23e81ce4f47f7978971928ec9ba419  nvidia-uvm/uvm_mmu.h
SUMS
)
mkdir -p "$build_dir"
cp -a "$source_dir/." "$build_dir/"
patch -d "$build_dir" -p1 --fuzz=0 < "$root/patches/0001-pack-user-leaf-tables.patch"
make -C "$build_dir" -j4 CC=gcc-13 NV_KERNEL_MODULES='nvidia nvidia-uvm' KERNEL_UNAME="$target_kernel" SYSSRC="/lib/modules/$target_kernel/build" modules
sha256sum "$build_dir/nvidia-uvm.ko"
modinfo "$build_dir/nvidia-uvm.ko" | sed -n '/^version:/p;/^vermagic:/p;/^parm:/p'
