# Real Linux (emulated RISC-V) on an ESP32-S3, reachable over Telnet/WiFi

An **authentic** Linux kernel (RV32IMA with Sv32 MMU + BusyBox/uClibc) runs on a
RISC-V emulator (mini-rv32ima) inside an ESP32-S3, using the PSRAM as system RAM.
You join its WiFi and open a Linux shell over Telnet.

Based on [`Epiczhul/esp32p4-rv32ima`](https://github.com/Epiczhul/esp32p4-rv32ima)
and the [`cnlohr/mini-rv32ima`](https://github.com/cnlohr/mini-rv32ima) core.

> **Status: beta / experimental.** It boots to a shell and reaches the internet
> from the guest by IP via NAT; DNS resolution is still a work in progress.

## Hardware
- ESP32-S3, **8 MB Octal PSRAM (OPI)**, 16 MB flash.
- Serial console over UART0 (on this board, the CH343 → `/dev/ttyACM0`).

## Usage (end user)
1. Power the board.
2. Connect to the WiFi **`esp32-linux`** (password **`linux1234`**).
3. `telnet 192.168.4.1` → Linux shell. Boot ~12 s.

Also over cable: `python tools/capture_boot.py 60` (or any serial terminal at
115200 on `/dev/ttyACM0`). `idf.py monitor` does NOT work here (it requires a TTY).

## Build and flash
Requires ESP-IDF v5.3. First provide your home WiFi (the uplink that gives the
guest internet); this file is gitignored so your password is never committed:
```bash
cp main/wifi_creds.h.example main/wifi_creds.h
# then edit main/wifi_creds.h with your SSID/password
```
Then activate ESP-IDF and flash:
```bash
. "$IDF_PATH/export.sh"       # activate ESP-IDF v5.3 (bash/zsh)
./flash.sh /dev/ttyACM0       # build + flash app + flash kernel Image
```
`flash.sh` also activates ESP-IDF on its own if `idf.py` is not yet on `PATH`
(via `$IDF_PATH/export.sh`), so the manual step above is optional.

> Don't want to build? Grab the prebuilt single-file image from the
> [Releases](../../releases) page and flash it to offset `0x0`.

## How it is put together
- `main/uc-rv32ima.c` — Sv32 loop, SBI and 8250 UART emulation. Runs in a task
  pinned to **Core 1**.
- `main/port-esp.c` — reserves the guest RAM in PSRAM (`heap_caps_malloc`), loads
  the kernel from the `kernel` partition, and handles UART0 I/O.
- `main/net_console.c` — WPA2 WiFi AP + Telnet server (:23) on **Core 0**.
  Two StreamBuffers bridge guest↔socket. The console is mirrored on UART0.
- `main/Image_mmu` — MMU kernel without initramfs, flashed at `0x110000`.
- `main/rootfs.ext4` — persistent virtio-blk root, flashed at `0x710000`.
- `main/s3.dts` — Sv32 DTB, S-mode PLIC, virtio-net and virtio-blk.

## Fine details (custom fixes)
1. **Guest RAM = 7.5 MB.** The firmware requires enough PSRAM, advertises exactly
   `0x780000` bytes and stores the external DTB above the managed range.
2. **Console input.** (a) it is read from UART0 (not the native USB-JTAG). (b) the
   **IIR** register of the emulated 8250 returns `0xC4` (RX data available) when a
   key is pending, otherwise the 8250 driver (irq=0, polling) never reads the byte.
   See `HandleControlLoad` in `uc-rv32ima.c`.

## Known limitations
- Slow (~2 BogoMIPS). The ext4 backend does 4 KB read-modify-erase-write and is
  meant as a prototype, with no wear leveling. One Telnet client at a time.
- DNS resolution from the guest is still being worked on; use IP addresses for now.

## Rebuilding the guest images

```bash
cd ../refs/mini-rv32ima
./build_slim_mmu.sh
./build_slim_rootfs.sh
```

## Tools (`tools/`)
- `patch_dtb.py` — patches the RAM size in the DTB embedded in the Image.
- `capture_boot.py N` — captures N s of serial (resets the board; no TTY needed).
- `interactive_test.py` — boots + sends test commands over serial.
- `telnet_test.py` — test Telnet client against 192.168.4.1.
