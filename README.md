# DGX Spark Memory Saver

**Recover memory lost to GPU page tables on a 64 KiB DGX Spark kernel.**

**Experimental, opt-in driver patch.** Tested on GB10 with NVIDIA 580.178.04 and
Ubuntu kernel `7.0.0-1019-nvidia-64k`. The three-node serving trial recovered
**1.78–1.86 GiB of usable memory per node compared with stock 4 KiB Linux**.
It did **not** demonstrate a substantial TPS or TTFT improvement.

This patches NVIDIA's `nvidia-uvm` kernel module. It does not modify Linux's
page size, vLLM, model weights, arithmetic or serving configuration.

## Start here

| I want to… | Guide |
| --- | --- |
| See how much memory it saves | [Measurements and limitations](docs/validation.md) |
| Install the 64 KiB kernel and prerequisites | [Kernel packages, swap and boot checks](docs/kernel.md) |
| Install manually with Secure Boot | [Prerequisites and signing](docs/installation.md), [manual installation](docs/manual.md) |
| Install it persistently with DKMS | [DKMS, signing, activation and removal](docs/dkms.md) |
| Check what is installed and loaded | [Read-only status and verification](docs/usage.md) |
| Uninstall the DKMS patch | [Remove and verify stock UVM](docs/dkms.md#remove-and-restore-stock-uvm) |
| Remove the manual installation | [Manual removal](docs/manual.md#remove) |
| Return to 4 KiB or handle updates | [Updates and removal](docs/maintenance.md) |
| Understand the allocation change | [Design and lifetime rules](docs/design.md) |

## Why it helps

UVM allocates a whole CPU page for each small GPU page table. On a 64 KiB kernel,
a 256-byte leaf table therefore occupies 64 KiB. Our loaded-model trace found
about 3.25 GiB in this backing storage.

The patch gives each eligible table a separate 4 KiB slot in a shared 64 KiB
page, allowing sixteen tables per page. In the profiled node, backing storage
fell to 0.218 GiB: **3.03 GiB recovered versus the stock 64 KiB driver**.
The smaller 1.78–1.86 GiB figure above is the net gain over the 4 KiB system,
including other host-memory differences.

Root tables and other allocation sizes retain their original allocation.
[Design and lifetime rules](docs/design.md) explain the scope and synchronization.

## Activation and rollback

Choose [manual installation](docs/manual.md) or [DKMS installation](docs/dkms.md).
Both are persistent and enable packing by default; installation is the opt-in.
The manual route has build/sign/install/remove helpers. DKMS package `0.2.0`
manages its own builds and signing. Both install only UVM, check the pinned
kernel/driver combination, and refresh the target initramfs. They do not load
modules, stop services or change the boot default.

```sh
./scripts/status            # read-only: installed and loaded state
./scripts/status --json     # the same findings in machine-readable form
```

The allocator also requires coherent DMA, an integrated GPU without separate
VRAM, a user page tree and a 256-byte request. Other cases retain the stock
allocator. No global modprobe parameter is installed. Remove the override before
NVIDIA upgrades. The historical default-off `build.sh` remains available for
[temporary loading without installation](docs/usage.md#temporary-loading-without-installation).

## Validation

The original trial passed concurrent allocation/reuse with full-buffer readback,
a 4.5 GiB pinned transfer, BF16 matmul, CUDA graph replay, model loading and all
five serving quality checks on three Sparks. Benchmarks used the same client,
prompts and pinned speculative-verification costs for the final comparison.
No request failures, swap growth or thermal slowdown were observed.

Version `0.2.0` also passed an isolated DKMS build/sign on dgx1 and live
read-only status inspection. Persistent installation/removal and reboot with
these new helpers still require on-device acceptance; they have not been
performed on the serving cluster.

See [measurements and limitations](docs/validation.md), the unchanged
[benchmark reports](results/2026-10-02/), and [test programs](tests/).
These are bounded tests, not a long production soak or evidence of determinism.
Page-table bugs can corrupt GPU memory; build success alone is not validation.

## Compatibility

Validated on NVIDIA DGX Spark (GB10, Linux aarch64), NVIDIA open driver
`580.178.04-0ubuntu0.24.04.1`, and Ubuntu kernel `7.0.0-1019-nvidia-64k`.
The build verifies the exact source package and both patched source files.
Other kernel and driver versions have not been validated. The [kernel setup guide](docs/kernel.md) installs the tested distribution
packages. The driver build script does not build or install Linux itself.

This is an independent experimental project, unaffiliated with NVIDIA.

## Development

```sh
./scripts/check
```

These hardware-free checks use Python 3.10+, OpenSSL and patch. They verify the recorded artifact hashes, Python and shell
syntax, patch parsing, signing helpers, installation recovery, read-only status, DKMS guards and local
documentation links.
GitHub Actions runs the same command. They never import the CUDA test programs or access a GPU.
Compilation on the target and the [hardware validation](docs/usage.md) are separate.
See [contributing](CONTRIBUTING.md) for the evidence required when changing the
allocator.

## Provenance and scope

This is the development home for the patch originally tested in
[spark3-vllm-ds41f](https://github.com/christopherowen/spark3-vllm-ds41f/tree/0e3b624e55e350ca621b336f8b88626f60dec9da/experiments/2026-10-02-kernel-64k/uvm-pool).
That repository retains its historical experiment snapshot.
[provenance.json](provenance.json) records the source identity and copied-file
hashes. The extracted patch and GPU tests are byte-identical to the tested
versions. The shared build helper verifies the same pins; both persistent builds
apply a separate [default-on packaging patch](packaging/enable-packing.patch).

No upstream submission or production promotion has been made. Driver/kernel
updates require a new compatibility review. No signing keys or driver binaries
are distributed. Original additions are MIT-licensed; NVIDIA notices are
retained in [NOTICE](NOTICE) and [LICENSES](LICENSES/).
