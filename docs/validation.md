# Validation: 2026-10-02

The evidence predates extraction into this repository. Patch, GPU tests and JSON
reports were copied unchanged from the pinned experiment in `provenance.json`.
Repository extraction did not run another GPU trial or change serving.

## Environment

Three DGX Sparks (GB10), tensor parallelism 3, DeepSeek V4.1 Flash on the r5o
vLLM/B12X image. Kernel pair: `7.0.0-1019-nvidia` and
`7.0.0-1019-nvidia-64k`; NVIDIA 580.178.04. The model, precision, 2.2 GiB/rank KV
budget, graph sizes and pinned draft-verification cost tables were unchanged.
The tested 64 KiB host profile also disables THP and sets the free-memory reserve
to 45,166 KiB. Results compare those host profiles; they do not isolate CPU page
size from every other host control.

The trial module was temporarily loaded with packing and release assertions
on. Only UVM was replaced. It was signed with an existing enrolled key. All three
nodes loaded source identity `2A94659FBB6D360FF27D9A9`; the original signed artifact
hash and source package identity are in the [trial record](../results/2026-10-02/trial-results.json).
No module binary or signing key is included here.

## Correctness and memory

- Stock and patched UVM both passed 3,584 direct CUDA allocations over four
  threads, with hole reuse and full-buffer readback.
- Patched UVM passed a 4.5 GiB pinned transfer, BF16 matmul and CUDA graph replay.
- The three-rank model loaded and passed all five serving quality cases.
- No serving request failures, swap growth, thermal slowdown, UVM assertions or
  GPU faults were observed during the candidate screen.
- A normal reboot restored stock 4 KiB UVM on all three nodes. Production r5o
  was restored and its live configuration check passed.

UVM backing on the profiled node:

| Configuration | GiB |
|---|---:|
| Stock 4 KiB | 0.20325 |
| Stock 64 KiB | 3.25201 |
| Packed 64 KiB | 0.21771 |

The patch recovered **3.03430 GiB versus stock 64 KiB**. The serving cgroup's
kernel aggregate independently fell from about 3.389 to 0.3464 GiB. Trace hashes
are preserved in the trial record; full raw host captures are not bundled here.
Disabling PyTorch expandable segments had failed to recover the memory and was
not retained. NVIDIA RM allocations were nearly equal across the stock arms;
the extra memory was predominantly UVM table backing.

## Final matched comparison

The authoritative speed comparison is
[stock 4 KiB repeat](../results/2026-10-02/bench-4k-repeat.json) versus
[packed 64 KiB](../results/2026-10-02/bench-64k-pool.json). Both use the dgx1 client,
identical workload options, quality warmup and source-text inputs. There are five
decode samples per point and three prefill samples per length. No profiler was
active during timing. The candidate had previously run standalone CUDA smoke;
do not interpret startup times as controlled measurements.

| Measure | Stock 4 KiB | Packed 64 KiB |
|---|---:|---:|
| Prose, one stream, tokens/s | 51.87 | 53.85 |
| Prose, eight streams, tokens/s | 170.30 | 167.53 |
| Code, one stream, tokens/s | 63.81 | 62.98 |
| Code, eight streams, tokens/s | 191.82 | 189.98 |
| Prose, one-stream step, ms | 41.05 | 41.55 |
| Code, one-stream step, ms | 45.68 | 45.91 |
| Prose, one-stream TTFT, ms | 202 | 198 |
| Code, one-stream TTFT, ms | 213 | 215 |
| Nominal 32K prefill, tokens/s | 3,812.3 | 3,808.7 |
| Nominal 64K prefill, tokens/s | 3,820.9 | 3,817.2 |
| Minimum available memory, rank 0, GiB | 6.69 | 8.55 |
| Minimum available memory, rank 1, GiB | 7.77 | 9.56 |
| Minimum available memory, rank 2, GiB | 7.77 | 9.55 |

Eight-stream TPS is aggregate throughput. Decode used reasoning-on prose/code
cases at temperature zero. This production arm is not deterministic; acceptance
and generated outputs vary. A single stream's step timing is less sensitive to
that variation than TPS. Request-level confidence intervals at eight streams
are not forty independent boots.

Actual prefill token counts match in both reports:

| Nominal length | Three prompts, tokens |
|---|---|
| 1K | 978 / 881 / 961 |
| 32K | 29,623 / 30,725 / 30,573 |
| 64K | 59,368 / 57,325 / 62,638 |

The net usable-memory gain is **1.78–1.86 GiB per node over 4 KiB**.
There is no substantial demonstrated TPS, TTFT or prefill improvement. This is
a bounded compatibility/performance screen, not a long production soak or a
claim that these savings apply to every workload.

## Retained failures and confounds

The first allocation-test harness did not bind a current CUDA context; it failed
on both stock and patched modules. The recorded version establishes a context
with one small allocation before using driver APIs.

The initial benchmark launch could not create its report directory; it sent no
benchmark requests. Only that directory's ownership was corrected.

Earlier stock screens used a Mac client, while the candidate used dgx1. This
changed network latency and the Python source used for prefill. An apparent 10%
prose TTFT gain from that comparison was rejected. The final dgx1-client control
above resolves that confound. Earlier controls and the failed allocator-setting
experiment remain in the original serving repository's historical experiment.

## DKMS packaging (0.1.0)

The packaging adds a default-on parameter assignment only for DKMS builds.
The original patch and recorded GPU/benchmark files remain unchanged. Both
patches were applied without fuzz to fresh copies of the pinned source: the
result differs from the tested source only in that assignment and its comment.
Hardware-free tests cover build isolation, source/package/header/driver checks,
pre-install ownership checks, kernel exclusions, cleanup and initramfs refresh
ordering. The actual fleet package paths and DKMS 3.4.3 were inspected read-only.

These checks do not establish a DKMS target compilation, signing, installation,
removal or reboot result. Those operations have not been performed on the
Sparks for this packaging release. Follow the [DKMS acceptance procedure](dkms.md)
in a coordinated maintenance window before deployment.

## Installation tools (0.2.0)

Both persistent build routes now use the same default-on packaging patch. The
original allocator patch and historical evidence remain unchanged. The manual
installer records the exact installed artifact and leaves the packaged module
in place. Its remover checks ownership, restores module selection and retains
a recovery receipt after failed refreshes. Neither command loads modules or
controls services. The status command only reads system state.

The hardware-free suite exercises real disposable key generation and certificate
checks, signing orchestration, signed/unsigned installation policy, driver
identity checks, conflicting registrations, changed artifacts, interrupted
installation/removal and read-only status reporting. All host mutations in
those tests are isolated filesystem fixtures or command doubles. Manual and
system DKMS installation, removal and reboot remain unvalidated on the Sparks
until a coordinated deployment window.

### Isolated DKMS build on dgx1

On 2026-10-02, commit `784587863ca06932d32de0378b5d499c4201654a` passed
DKMS 3.4.3 **add/build/sign** for `7.0.0-1019-nvidia-64k`. The test ran as an
unprivileged user with private source, state and install trees. A copy of the
host's DKMS executable redirected `/etc/dkms` references to a private signing
configuration. The actual package recipe, source fingerprints and build helper
were unchanged. A disposable key was generated by the new helper, used by DKMS
for signing, never enrolled and removed with the temporary workspace afterward.

The signed UVM reports driver `580.178.04`, matching target vermagic, source
version `34683B82C2D3339BBD2EEC9` and the intended disposable signer. The unit
finished successfully in 123.2 seconds, with 938.6 MiB reported peak memory and
zero swap under a one-CPU quota, 2 GiB memory limit and low scheduling priority.
The new status command ran on the real host and returned `stock-loaded` with
matching loaded/on-disk identities and no issues or unknowns.

The full [record](../results/2026-10-02-dkms-0.2.0/build.json),
[run output](../results/2026-10-02-dkms-0.2.0/run.log) and
[compiler log](../results/2026-10-02-dkms-0.2.0/make.log) retain artifact/script
hashes and warnings. Warnings included deprecated DKMS `CLEAN`, compiler-name
differences, warnings in unmodified NVIDIA RM code and skipped BTF generation
without `vmlinux`; there were no compilation errors. The RM output was not
installed or distributed.

This closes the actual DKMS compilation/signing and live read-only status
checks. It does not validate system-wide installation, removal, key enrollment
or reboot. No module was loaded, no GPU test ran and no production service was
restarted; the host retained its stock 4 KiB kernel and UVM.
