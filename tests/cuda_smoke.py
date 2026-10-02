"""Bounded compatibility check; run in a 20 GiB container with serving stopped."""
import json
import time
import torch

t0 = time.monotonic()
MiB = 1024 * 1024
# Cross the 4 GiB boundary in one allocation and one host-to-device mapping.
n = 4608 * MiB
host = torch.empty(n, dtype=torch.uint8, pin_memory=True)
host.fill_(37)
device = torch.empty(n, dtype=torch.uint8, device="cuda")
device.copy_(host, non_blocking=True)
torch.cuda.synchronize()
for offset in (0, 2048 * MiB, 4096 * MiB - MiB, 4096 * MiB, n - MiB):
    chunk = device[offset:offset+MiB].cpu()
    assert bool(torch.all(chunk == 37)), offset
device.fill_(91)
host.copy_(device, non_blocking=True)
torch.cuda.synchronize()
assert int(host.min()) == int(host.max()) == 91
del host, device
torch.cuda.empty_cache()
# Exercise cuBLAS and CUDA graphs after the large-copy path.
x = torch.ones((512, 512), dtype=torch.bfloat16, device="cuda")
y = x @ x
torch.cuda.synchronize()
stream = torch.cuda.Stream()
with torch.cuda.stream(stream):
    for _ in range(3):
        y = x @ x
stream.synchronize()
graph = torch.cuda.CUDAGraph()
with torch.cuda.graph(graph):
    y = x @ x
graph.replay()
torch.cuda.synchronize()
assert bool(torch.all(y == 512))
print(json.dumps({"passed": True, "large_copy_bytes": n, "seconds": time.monotonic()-t0,
                  "device": torch.cuda.get_device_name(), "torch": torch.__version__}))
