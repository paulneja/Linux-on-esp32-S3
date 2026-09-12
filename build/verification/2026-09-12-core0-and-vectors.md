# Core 0 firmware, watchdogs, and the vectors address

Local verification on the developer board, 2026-09-12. Kernel and firmware
were built on the host against the pinned esp-idf 5.1.1 and flashed by hand to
their partitions; the rootfs on the board is still the one from
`reproduce.0UaSuK`, so this covers the kernel and firmware only.

## The coupling that bit

Anything that changes how much internal RAM the firmware uses moves its
`space_for_vectors` symbol, and that address is what the kernel is linked
against as `CONFIG_VECTORS_ADDR`. Measured on this tree:

| firmware configuration | space_for_vectors |
|---|---|
| caches 16K/32K, no watchdogs | `0x4037f000` |
| caches 16K/32K, watchdogs on | `0x40380000` (ships) |
| caches 32K/64K, watchdogs on | `0x40384000` |

Flashing a firmware whose address does not match the kernel gives, on the
first boot:

```
vectors ptr = 0x40384000
Guru Meditation Error: Core  0 panic'ed (StoreProhibited)
PC      : 0x4037f002
```

and a reset loop. `build/package-final.py` reads the address out of the
firmware ELF and refuses to package an image where the two disagree, so a full
build cannot ship this combination; flashing partitions by hand can.

The cache increase was reverted for that reason. It is still worth measuring,
but it has to move the kernel's `VECTORS_ADDR` in the same commit.

## What passed with the matched pair

- Boots to a login prompt; `init` starts at 1.75 s.
- Uptime ran from 41.64 s to 91.20 s across a session with no reset, so the
  interrupt watchdog (800 ms) and task watchdog (10 s) are enabled and are
  being fed. `ESP_INT_WDT_CHECK_CPU1` must stay off: core 0 feeds the watchdog
  only after core 1's FreeRTOS tick sets a flag, and core 1 runs Linux.
- `iw dev espsta0 scan` returned 5 networks, and 7 after eleven more scans.
  Twelve scans is twelve trips through the command path with no "No free cmd
  node" in dmesg, which is what the `get_free_cmd_node` leak fix is for.
- `tainted` 0, and no OOM, panic, BUG or Oops in dmesg.
- `MemAvailable` 3572 kB idle.

## Not covered here

The rootfs changes are not on the board: userspace, the flash reclamation and
the CGI rewrite still need a full image build. WiFi was scanned but not
associated, and no traffic was passed.
