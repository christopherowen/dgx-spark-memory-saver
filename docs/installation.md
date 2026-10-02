# Build the driver

[← README](../README.md) · [Temporary trial](trial.md) · [Updates and removal](maintenance.md)

Use Linux aarch64 with these inputs already installed:

- `nvidia-kernel-source-580-open=580.178.04-0ubuntu0.24.04.1`
- Headers for `7.0.0-1019-nvidia-64k`
- GCC 13, make, patch, coreutils and kmod

```sh
git clone https://github.com/christopherowen/dgx-spark-memory-saver.git
cd dgx-spark-memory-saver
./scripts/build.sh
```

The script verifies the source package version and SHA-256 of both patched
files, copies the source into `.work/nvidia-580.178.04-uvm-pool`, applies the
patch without fuzz, and builds against the pinned headers. It refuses to reuse
an existing build directory. The resulting module is
`.work/nvidia-580.178.04-uvm-pool/nvidia-uvm.ko`.

The build does not install, sign or load modules, alter boot defaults, or update
initramfs. It also builds RM to resolve module symbols; only UVM was replaced in
the trial. Do not replace the packaged RM module with that build output.
