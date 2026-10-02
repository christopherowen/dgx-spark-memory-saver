"""Direct CUDA allocations: concurrent mapping, hole reuse and full readback.

Run only in a bounded test container with serving stopped. No cached allocator.
Each thread attaches the same primary context and owns disjoint allocations.
"""
import concurrent.futures
import ctypes as C
import json
import random
import time
import torch

lib = C.CDLL('libcuda.so.1')
U = C.c_uint64
P = C.c_void_p

def bind(name, args):
    f = getattr(lib, name)
    f.argtypes = args
    f.restype = C.c_int
    return f

init = bind('cuInit', [C.c_uint])
getctx = bind('cuCtxGetCurrent', [C.POINTER(P)])
setctx = bind('cuCtxSetCurrent', [P])
alloc = bind('cuMemAlloc_v2', [C.POINTER(U), C.c_size_t])
free = bind('cuMemFree_v2', [U])
fill = bind('cuMemsetD8_v2', [U, C.c_ubyte, C.c_size_t])
copy = bind('cuMemcpyDtoH_v2', [P, U, C.c_size_t])
sync = bind('cuCtxSynchronize', [])

def check(rc):
    if rc:
        raise RuntimeError(f'CUDA error {rc}')

check(init(0))
torch.cuda.init()
# Runtime initialization alone can leave the primary context lazily unbound.
context_anchor = torch.empty(1, device='cuda')
ctx = P()
check(getctx(C.byref(ctx)))
assert ctx.value

def worker(index):
    check(setctx(ctx))
    rng = random.Random(index)
    live = {}
    host = C.create_string_buffer(4 * 1024 * 1024)
    count = 0
    def create():
        nonlocal count
        size = rng.choice([65536, 2 * 1024 * 1024, 4 * 1024 * 1024])
        ptr = U()
        check(alloc(C.byref(ptr), size))
        value = (count * 17 + index * 31) % 251 + 1
        live[ptr.value] = (size, value)
        check(fill(ptr, value, size))
        count += 1
    def verify(ptr):
        size, value = live[ptr]
        check(copy(host, U(ptr), size))
        data = C.string_at(host, size)
        assert data == bytes([value]) * size, (index, ptr, size, value)
    try:
        for _ in range(128):
            create()
        for _ in range(12):
            holes = rng.sample(list(live), 64)
            for ptr in holes:
                verify(ptr)
                check(free(U(ptr)))
                del live[ptr]
            for _ in holes:
                create()
            # Verify survivors too: writes to reused mappings must not alias.
            for ptr in live:
                verify(ptr)
        check(sync())
        return count
    finally:
        for ptr in list(live):
            check(free(U(ptr)))
        check(setctx(P()))

start = time.monotonic()
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    counts = list(pool.map(worker, range(4)))
print(json.dumps({'passed': True, 'allocations': sum(counts), 'threads': 4,
                  'rounds': 12, 'full_buffer_readback': True,
                  'seconds': time.monotonic() - start}))
