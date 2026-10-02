# Design

The base is the Ubuntu source package for NVIDIA 580.178.04. Its
`phys_mem_allocate_sysmem()` uses `alloc_pages(flags, get_order(size))` and maps
the allocation through `uvm_gpu_map_cpu_pages()`. A sub-page request therefore
consumes one complete CPU page. The tested GPU uses 256-byte leaf tables.

The patch retains that allocator as `phys_mem_allocate_sysmem_full_page()`.
Eligible user leaf allocations receive 4 KiB slots from 64 KiB backing pages.
The slot size deliberately leaves additional packing potential unused: this
experiment recovers the large 64 KiB regression with sixteen independent,
4 KiB-aligned slots. It does not pack roots or change the GPU data-page size.

## Ownership and synchronization

Each page tree owns a list of backing pages with available slots. A backing page
contains the original physical allocation, a slot bitmap and a list entry.
An allocation records its backing-page pointer and GPU address including its
slot offset. Full pages leave the available list; freeing a slot makes them
available again. The final free removes the backing page and releases it.

The pool's leaf spinlock protects only bitmap/list updates. Allocation, DMA
mapping, tracker waits and physical frees occur outside that lock. New pages
are obtained through the existing allocator, preserving its memory-cgroup
context, DMA translation, physical-TLB invalidation and mapping accounting.

The existing tree tracker wait happens before clearing a slot's ownership bit.
Reused slots are zeroed. The path requires coherent DMA and slots do not share
CPU cache lines. Existing CPU mapping uses the physical address's page offset,
so a table maps to its own slot. Final teardown unmaps the original whole-page
DMA address and frees the backing page, rather than unmapping a suballocation.

## Guarded scope

All of these must hold:

- `uvm_pack_sysmem_leaf_tables=1` (read-only module parameter).
- CPU page size is exactly 65,536 bytes.
- The request is exactly 256 bytes in a user page tree.
- There is a real PCI device, marked as an integrated GPU with no separate VRAM.
- The device uses coherent DMA.

The historical/manual patch defaults the parameter off. The separate DKMS
packaging patch defaults it on: installation is the persistent opt-in. No
allocator condition or synchronization changes between the two builds.

The tested hardware is GB10. The predicates are not a compatibility claim for
other integrated GPUs. Unsupported cases retain the original allocator.

No upstream submission has been made. The long-term preference is an upstream
allocator fix; this repository records a narrow tested candidate for review.
