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
| Build the patched driver | [Source, requirements and build](docs/installation.md) |
| Try it and verify it is working | [Temporary trial and Secure Boot](docs/trial.md) |
| Return to the stock driver or handle updates | [Updates and removal](docs/maintenance.md) |
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

The patch is disabled by default. Its opt-in parameter is
`uvm_pack_sysmem_leaf_tables=1`. The path also requires 64 KiB CPU pages, coherent
DMA, a real integrated GPU with no separate VRAM, a user page tree, and a
256-byte table request. Other cases use the stock allocator.

[The trial procedure](docs/trial.md) describes the temporary module load,
Secure Boot requirements, checks and rollback. This repository provides no
persistent installer. In particular, do not set the new parameter globally:
the stock 4 KiB UVM module does not recognize it.

## Validation

The original trial passed concurrent allocation/reuse with full-buffer readback,
a 4.5 GiB pinned transfer, BF16 matmul, CUDA graph replay, model loading and all
five serving quality checks on three Sparks. Benchmarks used the same client,
prompts and pinned speculative-verification costs for the final comparison.
No request failures, swap growth or thermal slowdown were observed.

See [measurements and limitations](docs/validation.md), the unchanged
[benchmark reports](results/2026-10-02/), and [test programs](tests/).
These are bounded tests, not a long production soak or evidence of determinism.
Page-table bugs can corrupt GPU memory; build success alone is not validation.

## Compatibility

Validated on NVIDIA DGX Spark (GB10, Linux aarch64), NVIDIA open driver
`580.178.04-0ubuntu0.24.04.1`, and Ubuntu kernel `7.0.0-1019-nvidia-64k`.
The build verifies the exact source package and both patched source files.
Other kernel and driver versions have not been validated. A 64 KiB kernel must
already be available; this project does not build or install Linux itself.

This is an independent experimental project, unaffiliated with NVIDIA.

## Development

```sh
./scripts/check
```

These hardware-free checks verify the recorded artifact hashes, Python and shell
syntax, patch parsing and local documentation links. GitHub Actions runs the
same command. They never import the CUDA test programs or access a GPU.
Compilation on the target and the [hardware trial](docs/trial.md) are separate.
See [contributing](CONTRIBUTING.md) for the evidence required when changing the
allocator.

## Provenance and scope

This is the development home for the patch originally tested in
[spark3-vllm-ds41f](https://github.com/christopherowen/spark3-vllm-ds41f/tree/0e3b624e55e350ca621b336f8b88626f60dec9da/experiments/2026-10-02-kernel-64k/uvm-pool).
That repository retains its historical experiment snapshot.
[provenance.json](provenance.json) records the source identity and copied-file
hashes. The extracted patch and GPU tests are byte-identical to the tested
versions; the build script's repository paths have been adapted.

No upstream submission or production promotion has been made. Driver/kernel
updates require a new compatibility review. No signing keys or driver binaries
are distributed. Original additions are MIT-licensed; NVIDIA notices are
retained in [NOTICE](NOTICE) and [LICENSES](LICENSES/).
