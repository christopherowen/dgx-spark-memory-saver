# Contributing

Keep changes small and include the exact GPU, kernel, CPU page size, NVIDIA
driver package and source identity in reports. This repository follows the
focused driver, documentation and hardware-free check layout used by
[dgx-spark-fan-control](https://github.com/christopherowen/dgx-spark-fan-control).

Run `./scripts/check` before submitting (Python 3.10+, OpenSSL and patch). These checks must remain usable without
CUDA, root access or a Spark. Do not import the hardware test programs from a
discovered unit test: importing them can initialize CUDA and allocate memory.

Allocator changes require a build against the pinned source, an explanation of
DMA mapping, ownership, synchronization and accounting, and a recorded hardware
result or an explicit statement that hardware validation is outstanding. Follow
the [validation procedure](docs/usage.md) in a coordinated exclusive window.

Keep measurements under `results/` immutable. New measurements belong in a new
directory with their own environment and workload identities. If the patch or
test programs change, update their provenance to distinguish new development
from the byte-identical historical extraction. Do not present old measurements
as validation of changed code.

Build only in an isolated source copy. The normal build and check commands must
not install or load modules, enroll keys, change boot settings or modify the
packaged NVIDIA source. Kernel or driver upgrades need explicit review and new
validation. Keep the DKMS kernel exclusion in sync with the manifest and
retain the pre-install checks for cached binaries. Only UVM may be registered;
never install the RM build output. Bump `PACKAGE_VERSION` for released packaging
changes and keep installation/removal documentation aligned. Test DKMS
installation and restoration in an exclusive window before claiming on-device
acceptance.

Do not commit signing keys, module binaries, credentials or private machine logs.
Preserve NVIDIA's MIT notices and the repository's licensing when editing the
patch. Keep production orchestration in the deployment repository.

Manual installation/removal tests must use temporary state/module/sysfs paths
and mocked host commands. Key-generation tests use disposable keys and never
enroll them. Status remains read-only and must distinguish missing evidence
from a healthy state. Preserve recovery receipts when a mutation fails.
