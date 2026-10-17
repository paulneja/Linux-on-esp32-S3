# 8 MB boards: generic-n8 and xiao-n8

The 8 MB targets are built from a copy of the N16 tree with a patch series on
top. The N16 sources are not changed for them. `run.sh` exports `HEAD` into
`target-builds/<target>/`, applies `targets-patches/<target>/series` there and
builds that copy.

| Target       | Board                                         | Series                        |
| ------------ | --------------------------------------------- | ----------------------------- |
| `generic-n8` | ESP32-S3 N8R8 (8 MB flash, 8 MB octal PSRAM)  | `targets-patches/generic-n8/` |
| `xiao-n8`    | Seeed XIAO ESP32S3 and XIAO ESP32S3 Sense     | `targets-patches/xiao-n8/`    |
| `xiao-n8-sd` | XIAO ESP32S3 Sense with `/home` on the SD     | `targets-patches/xiao-n8-sd/` |

`xiao-n8` is `generic-n8` plus one patch that turns on the login on the chip's
own USB port, since the XIAO has no UART adapter. Its other patches are
symlinks to the `generic-n8` ones. `xiao-n8-sd` adds one more on top of that.

## Choosing one

`./run.sh` asks which board it is for the first time and keeps the answer in
`.target`. Option 10 in the menu changes it, and `--target n16|generic-n8|xiao-n8`
picks one for a single run.

## Flash layout

| Partition | Offset     | Size       |
| --------- | ---------- | ---------- |
| factory   | `0x010000` | 768 KiB    |
| etc       | `0x0d0000` | 320 KiB    |
| linux     | `0x120000` | 2432 KiB   |
| rootfs    | `0x380000` | 4224 KiB   |
| home      | `0x7a0000` | 384 KiB    |

The firmware jumps to `0x42000000` plus the offset of `linux`, and the kernel
runs in place from there, so `CONFIG_KERNEL_LOAD_ADDRESS` has to follow the
partition: `0x42120000` here, `0x42140000` on N16. Moving `linux` without it
gives a board that never starts Linux.

## xiao-n8-sd

The Sense's expansion board has a microSD slot on SPI: CS on GPIO21, SCK on
GPIO7, MISO on GPIO8, MOSI on GPIO9. This target turns on SPI, MMC over SPI,
the block layer and ext2 in the kernel, and mounts the card's first partition
as `/home`. The card has to be formatted as ext2 first, on a PC:

```sh
sudo mkfs.ext2 -L home /dev/sdX1
```

Without a card `/home` is not mounted and the login has no home directory.
The kernel grows, so `linux` takes 2688 KiB and `/home` on flash shrinks to a
64 KiB stub the tools still expect:

| Partition | Offset     | Size       |
| --------- | ---------- | ---------- |
| etc       | `0x0d0000` | 320 KiB    |
| linux     | `0x120000` | 2688 KiB   |
| rootfs    | `0x3c0000` | 4288 KiB   |
| home      | `0x7f0000` | 64 KiB     |

## What is left out

Everything the N16 image has, except:

- Bash, GNU Make, MicroPython (the Linux build; `mmu-run`'s payload stays) and nano.
  `/bin/sh` is BusyBox and Dash is there for sessions. BusyBox `vi` replaces nano.
- ncurses and terminfo, which only Bash and nano used.
- 54 BusyBox applets nothing on the board calls: bzip2/lzma/xz/lzop, i2c tools,
  virtual consoles and fonts, swap, runit, dnsd, tftp, hexedit, bc/dc and others.
- In wpa_supplicant, 802.11r/ac/ax, TDLS, PKCS#12 and the IPv6 control socket.
  WPA2-PSK and open networks are what `wifi` sets up.
- In libcurl, cookies, proxies and the protocols other than HTTP(S), FTP and MQTT.

SSH, Telnet, the web page, curl with HTTPS, socat, cron and dtach sessions are
all in. The board test binaries stay too, because the suite checks fork() with
them.

The build also skips compiling Bash, Make and the Linux MicroPython for these
targets.

## Keeping the series working

Each patch covers one area: build, packaging, flashing, tests, configuration,
BusyBox and wpa_supplicant. When a change to the N16 tree touches a file in one
of them, CI's patch check fails on that push; regenerate the affected patch
against the new `HEAD` and check that the whole series still applies to a fresh
export.
