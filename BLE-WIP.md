# WiFi provisioning over BLE — work in progress

> **This branch is not release quality. Do not merge it into `main` and do not
> publish an image built from it.** It works, but it carries a failure mode that
> bricks the boot silently (see "The landmine" below). `main` / release `0.3` is
> the stable thing to flash.

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

**Not solid yet**:

- **Connection reliability.** Connecting works from a phone, but from a Linux PC
  (BlueZ/bleak) it frequently times out during service discovery, and after a
  failed attempt advertising does not restart. Root cause not established.
- The full scan → pick → password → connected flow has been exercised, but not
  repeatedly or in varied conditions.
- Connecting does not show the menu by itself: the firmware never tells Linux
  that a phone attached, so you must send a character first. Wiring
  `BLE_GAP_EVENT_CONNECT` to greet automatically is an obvious improvement.

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

**Check after any firmware change:**

```bash
xtensa-esp32s3-elf-nm build/network_adapter.elf | grep space_for_vectors
# must equal CONFIG_VECTORS_ADDR in devkit_c1_16m_linux.config
```

`CONFIG_KERNEL_LOAD_ADDRESS` is coupled the same way to the `linux` partition
offset (`0x42000000 + offset`).

### What has to happen before this is mergeable

Break that coupling. In order of preference:

1. **Pin `space_for_vectors` to a fixed address** with a linker section, so it
   stops moving.
2. **Have the firmware pass the address to Linux** in a `bp_tag` at boot — the
   mechanism already exists (it is how the kernel command line is passed), so
   the two would self-synchronise.
3. At minimum, a **build-time check** that fails loudly on a mismatch.

Option 2 is the right engineering answer.

## Other things worth knowing

- **Never log from `ble_prov.c`.** Once Linux owns the USB-Serial-JTAG console,
  a `printf` from core 0 blocks forever, which hangs the NimBLE host task and
  kills GAP event processing — the connection then dies during service
  discovery. `ESP_LOG*` are compiled out anyway (`LOG_MAXIMUM_LEVEL=1`), which
  is why they were harmless before.
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
