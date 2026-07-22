# WiFi provisioning over BLE — work in progress

> **Status: working end to end on hardware.** A phone joined the board to a
> WiFi network over BLE — scan, pick, password, DHCP address — with no PC and no
> serial cable. The silent-brick failure mode that made this dangerous is fixed:
> `make-images.sh` now refuses to package a mismatched image (see "The
> landmine"). What is not yet characterised is how *reliably* it connects.

## What this is for

Joining the board to a WiFi network when you are away from a PC and have no
serial cable. The board advertises over Bluetooth LE as **`Esp32-Linux`**; you
connect from a phone with any BLE serial app, send any character, and get:

```
=== Linux on ESP32-S3 - WiFi setup ===
Scanning, please wait...

  1) -50  lock  HomeNetwork
  2) -72  open  SomeOpenAP

Send the number of the network:
```

Pick a number; open networks connect straight away, secured ones ask for the
password; it reports the IP it got.

The ESP32-S3 has **no Bluetooth Classic**, so SPP is not available. This uses
the Nordic UART Service (NUS) over BLE, which phone serial apps speak
(Serial Bluetooth Terminal in *BLE* mode, nRF Connect, LightBlue).

## How it is put together

```
phone (BLE serial app)
  └─ BLE / NUS ─> core 0: NimBLE peripheral  (main/ble_prov.c)
                    └─ byte pipe, if_type ESP_BLE_PROV_IF over the shmem IPC
                         └─ core 1 Linux: /dev/esp-ble  (drivers/.../esp_ble_prov.c)
                              └─ ble-wifi-setup daemon runs the dialog
```

The firmware side is deliberately a **dumb pipe**. The dialog runs on the Linux
side and calls the existing `wifi` command, because Linux owns the WiFi
connection — having the firmware join a network on its own would desynchronise
the driver state.

esp-hosted's `slave_bt.c` HCI passthrough is *not* used: it hands the controller
to the Linux host for BlueZ, which cannot run on this NOMMU/8MB target.

## Status

**Works** (verified on hardware): Linux boots with the BLE firmware; the board
advertises as `Esp32-Linux`; a phone connects and the GATT service is
discovered; `/dev/esp-ble` is created; the daemon starts; the dialog was
exercised from a phone.

**Verified on hardware**: the whole chain delivers. Text typed on a phone
arrives on `/dev/esp-ble`, the daemon answers with the network list, and
selecting one and entering the password brings the STA up and reports the DHCP
address.

**Not characterised yet**:

- **Connection reliability.** It connects and completes the dialog from a
  phone. From a Linux host (BlueZ/bleak) a 6-cycle stress run produced 0
  complete dialogs — but the same board served a phone correctly throughout, so
  that result says more about the test host's Bluetooth than about the firmware.
  How often a phone fails to connect has not been measured.
- Connecting does not show the menu by itself: the firmware never tells Linux
  that a phone attached, so you must send a character first. Wiring
  `BLE_GAP_EVENT_CONNECT` to greet automatically is an obvious improvement.

**The BLE link is ready before Linux is — wait ~30 s after power-on before
connecting.** The firmware starts advertising as soon as its BLE stack syncs,
well before the kernel has finished booting. Connecting in that window is
unreliable: the phone finds the board but the connection hangs, because core 0
is still bringing up WiFi and the NimBLE host task cannot answer service
discovery in time. After ~30 s everything works consistently.

The dialog side of the race is handled: it waits for `espsta0` and retries the
scan instead of answering "No networks found" when it is simply early.

Gating advertising on a readiness signal from Linux was tried and reverted: the
board then never advertised at all (the marker did not arrive, cause not
established), which is a far worse failure than asking the user to wait. If
retried, it must fall back to advertising anyway after a timeout so it cannot
end up silent.

Three firmware defects were fixed while chasing the reliability question. None
of them was the reason the dialog appeared not to work — that turned out to be
the test host — but each was real:

- The GATT write callback ran `xQueueSend` with `portMAX_DELAY`. That callback
  executes in the NimBLE host task, so a full queue would hang the entire BLE
  stack. It now drops the byte after 50 ms instead.
- Advertising is re-armed by a periodic callout rather than relying solely on
  `BLE_GAP_EVENT_DISCONNECT`, so a connection that fails midway cannot leave
  the peripheral silent.
- Connection parameters are relaxed on connect (30-50 ms interval, 4 s
  supervision timeout), since this core also runs WiFi and the IPC to Linux.

## The landmine (read this before changing anything)

The firmware reserves the 4 KB buffer that Linux uses for its exception vectors:

```c
/* main/linux_boot.c */
static char IRAM_ATTR space_for_vectors[4096] __attribute__((aligned(4096)));
```

**The linker chooses that address, and it moves when the firmware's size or
layout changes.** The kernel has it hard-coded:

```
CONFIG_VECTORS_ADDR=0x4037f000      # board/espressif/esp32s3/devkit_c1_16m_linux.config
```

Right now they match because they were aligned by hand. If they ever diverge,
Linux writes its exception vectors into firmware memory and **dies the moment it
executes userspace — with no panic, no message, nothing on the console.** The
kernel boots perfectly and then goes silent at `Run /sbin/init`. This cost a
long debugging session to find.

Adding NimBLE grew the firmware by ~117 KB and moved the buffer from
`0x4037c000` to `0x4037f000`, which is exactly how it was discovered.

### This is now caught at build time

`make-images.sh` reads the address out of the firmware ELF and compares it to
the kernel config. On a mismatch it refuses to package and prints the exact
line to change:

```
!! MISMATCH: firmware reserves 0x4037f000, kernel expects 0x4037c000
!! An image built like this boots the kernel fine and then dies
!! silently at /sbin/init, with nothing on the console.
!! Fix: set CONFIG_VECTORS_ADDR=0x4037f000 in
!!   new-files/board/espressif/esp32s3/devkit_c1_16m_linux.config
error: refusing to package an image that will not boot
```

So the failure is now loud and self-explanatory instead of a silent brick, and
a broken image cannot be shipped by accident. To check by hand:

```bash
xtensa-esp32s3-elf-nm build/network_adapter.elf | grep space_for_vectors
```

`CONFIG_KERNEL_LOAD_ADDRESS` is coupled the same way to the `linux` partition
offset (`0x42000000 + offset`), and is not yet checked automatically.

### Still worth doing

The check makes the coupling safe, not absent. Removing it entirely would mean
either pinning `space_for_vectors` to a fixed address with a linker section, or
having the firmware pass the address to Linux in a `bp_tag` at boot (the
mechanism already exists — it is how the kernel command line is passed). The
second is the right engineering answer, but neither is required to ship safely
now that a mismatch cannot slip through.

## Other things worth knowing

- **Never log from `ble_prov.c`.** Once Linux owns the USB-Serial-JTAG console,
  a `printf` from core 0 blocks forever, which hangs the NimBLE host task and
  kills GAP event processing — the connection then dies during service
  discovery. `ESP_LOG*` are compiled out anyway (`LOG_MAXIMUM_LEVEL=1`), which
  is why they were harmless before.
- **`/dev/esp-ble` takes a single reader.** The daemon holds it open for its
  whole lifetime. To watch the raw pipe for debugging, stop the daemon first
  (`killall ble-wifi-setup`), or the second reader just gets `EBUSY`:

  ```sh
  killall ble-wifi-setup
  cat /dev/esp-ble &        # now type on the phone; characters appear here
  /etc/init.d/S46blewifi start   # remember to put it back
  ```
- **The daemon avoids forking.** 8MB and no swap; `wifi scan` alone spawns
  iw+awk+sort+awk. An earlier version that read the pipe with `dd | tr` in a
  loop kept those alive across the scan and got OOM-killed. It now opens the
  device once on fd 3 and uses only shell builtins.
- **Partition layout moved** to make room for the bigger firmware:
  `factory` 640K→768K, `linux` 4.5M→4M at `0x140000`, `rootfs` at `0x540000`,
  `home` 3328K. `etc` stays 448K — 320K (5 erase blocks) is jffs2's bare minimum
  and was briefly suspected of the boot hang before the real cause was found.

## Building it

`images/` on this branch is deliberately **not** updated: it still holds the
stable `0.3` binaries from `main`, so nothing here can be flashed by accident.
Build from source (see DEVELOPMENT.md), then `./make-images.sh`, and mind the
landmine check above before flashing.

## Files

| Path | What |
|---|---|
| `patches/05-firmware-ble-provisioning.patch` | NimBLE NUS peripheral + the pipe, on core 0 |
| `new-files/board/.../patches/linux/03-kernel-ble-prov.patch` | `/dev/esp-ble` misc device + driver hooks |
| `new-files/board/.../rootfs_overlay/usr/sbin/ble-wifi-setup` | the provisioning dialog |
| `new-files/board/.../rootfs_overlay/etc/init.d/S46blewifi` | starts it at boot |
| `kernel-driver-esp32-ng/esp_ble_prov.c` | readable copy of the kernel driver |
