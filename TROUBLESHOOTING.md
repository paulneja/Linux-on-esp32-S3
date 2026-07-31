# Troubleshooting

Symptoms seen on real hardware, with what actually caused them. Most were found
the slow way, so the diagnostic step is included rather than just the fix.

## Boot

### Boot stops after `mmc_spi`, no panic, no further output

The next line in a healthy boot is `esp32s3-rsa: selftest 512-bit PASS`. If it
never appears, the kernel is spinning in the RSA driver's opening wait:

```c
while (readl(rsa + RSA_QUERY_CLEAN) != 1)
        cpu_relax();
```

That loop has **no timeout**. It waits for the RSA block to be clocked, and the
driver never clocks it on purpose — the SYSTEM clock registers are shared with
the firmware's AES/SHA, so the firmware hands the block over instead, with
`periph_module_enable(PERIPH_RSA_MODULE)` in `app_main.c`.

So a kernel paired with a firmware that lacks that call hangs here, silently.
Fixed in the firmware patch; if you hit it, your firmware is older than your
kernel. Rebuild both from the same checkout.

### Boot stops right at `Run /sbin/init`, having printed everything else

`CONFIG_VECTORS_ADDR` in the kernel config does not match `space_for_vectors` in
the firmware ELF. Linux writes its exception vectors over firmware memory and
dies the instant it executes userspace.

The address is chosen by the firmware's linker, so it **moves whenever the
firmware's size changes**. `make-images.sh` now detects this, realigns the
kernel config and rebuilds — it should not reach you. If you build by hand,
compare them yourself:

```sh
xtensa-esp32s3-elf-nm network_adapter.elf | grep space_for_vectors
grep CONFIG_VECTORS_ADDR .../devkit_c1_16m_linux.config
```

### Guru Meditation boot loop, before Linux prints anything

`CONFIG_KERNEL_LOAD_ADDRESS` must equal `0x42000000 +` the `linux` partition
offset. Moving a partition without updating it produces exactly this.

### `jffs2: Name CRC failed on node at 0x...`

One line during boot, and then everything works normally. A directory entry on
`/etc` or `/home` was written only half way; jffs2 notices during the scan it
does at mount, discards that entry and carries on. The scan exists for exactly
this — it is the filesystem repairing itself, not reporting a fault.

Which of the two partitions it is: the offset is relative to the start of the
partition, so compare it against `cat /proc/mtd`. Anything past `etc`'s
`0x70000` can only be `home`.

Nothing important can be lost this way. The base system is a read-only cramfs
and cannot be touched; what goes missing is whatever that one entry named,
under `/etc` or `/home`. In the case seen here, an empty directory.

It comes from a write cut short — a flash interrupted part way through, or the
power going while something was being saved. Clear it for good by erasing
first:

```sh
./flash.sh --erase
```

Verified: present after an interrupted flash, gone after a full erase and
rewrite of the same image.

## After boot

### The prompt is `~` but you are in `/root`, and writes fail

`/root` is on the read-only cramfs. Root's home should be `/home/root`, on the
writable jffs2 partition. If it is not, `setup-home.sh` did not run — check that
it is listed in `BR2_ROOTFS_POST_BUILD_SCRIPT` in the defconfig.

```sh
grep ^root: /etc/passwd     # should end in /home/root
```

### The board joined a WiFi network you never configured

See [SECURITY.md](SECURITY.md#past-incidents). Check for a network block with no
`ssid` in `/etc/wpa_supplicant.conf`; that matches any open network. Delete the
file and reboot.

### `Command[4] timed out` / `cmd_scan_request ... ret: -22`

A scan request the firmware did not answer. Occasional ones while the firmware
is busy are survivable — `wpa_supplicant` retries and eventually associates.

Continuous ones that never recover used to mean the SoftAP had been brought up,
which wedged the firmware so the STA could no longer scan. The SoftAP was
disabled in 0.3 and the code removed from both the driver and the firmware
afterwards, so this should not happen; if it does, it is worth an issue.

### `curl: (60) peer certificate could not be verified` on every HTTPS site

The clock, not the CA bundle. **The board has no RTC, so it powers on at 1 Jan
1970, every time.** Every certificate's `notBefore` is decades in the future
from there, so verification fails — for *all* sites, which is what tells this
apart from a root that is genuinely missing from the trimmed bundle.

Check first:

```sh
date                                       # 1970 means NTP has not run
grep clock /var/log/network.log            # what it tried, and when
```

The clock is set over NTP from a udhcpc hook, so it needs a DHCP lease *and*
working internet. If it is still 1970:

- **No internet, only a LAN.** Nothing to ask. Set it by hand.
- **UDP 123 filtered.** Some networks block it. Set it by hand.
- **DNS broken.** Two of the three peers are IP literals precisely so this does
  not matter, but if outbound UDP is blocked too, the same applies.

```sh
date -s "2026-07-31 03:30:00"
curl -sI https://github.com | head -1      # HTTP/1.1 200 OK
```

Verified on hardware: with the clock at 1970 github, google and example.com all
fail; with it set, all three succeed. Nothing persists the date across a power
cycle — the board asks again on each join.

`echo $CURL_CA_BUNDLE` should print
`/usr/share/ca-certificates/ca-bundle.crt` (set by `/etc/profile.d/curl-ca.sh`,
so it is only in *login* shells). If that is empty, you are in a non-login
shell, and that is a different failure with the same message.

### The status page does not answer

It is **off by default**, and being off looks exactly like being unreachable.
Check and turn it on:

```sh
web-server status
web-server on
```

That setting lives in `/etc/inetd.conf` on the writable `/etc` partition, so it
survives a reboot — but *not* a reflash, which rewrites that partition.

If `web-server status` says enabled and the page still does not load, inetd is
the thing to look at (`ps | grep inetd`); `web-server on` restarts it as part of
its job, so running it again is a reasonable first move.

### `sh: bad number` after almost every command

Harmless, and not your script. On the **interactive** shell every command
substitution prints it — one to three times, unpredictably — while producing
the right value:

```sh
A=$(echo hi); echo "A=[$A]"
sh: bad number
sh: bad number
sh: bad number
A=[hi]
```

`$(echo hi)` runs no external program at all, so this is hush itself: on a
NOMMU system it cannot fork, and re-executes busybox to run a subshell. The
message comes out of that path.

It is confined to shells whose stderr is a terminal. Scripts are unaffected —
the boot log and `/var/log/network.log` are clean, and the substituted values
are always correct. Ignore it. If it bothers you, redirect: `cmd 2>/dev/null`.

## Bluetooth

### The board does not appear in a BLE scan

- **Wait ~30 s after power-on.** The BLE stack advertises long before Linux has
  finished booting, and that window is unreliable — core 0 is busy bringing up
  WiFi. This is a known limitation, not a fault.
- Make sure the app scans in **BLE** mode. The ESP32-S3 has no Bluetooth
  Classic, so a Classic-only scan can never find it.
- A phone that has already bonded may not show it in a fresh scan; look under
  paired devices instead.
- Some BLE terminal apps keep a stale connection after disconnecting. Force-quit
  the app, or toggle Bluetooth, before blaming the board.

### Connected, but nothing happens

The dialog does not greet you on connect. **Send any character** and the menu
appears. If it still does not, check the daemon is alive:

```sh
ls -l /dev/esp-ble          # must exist, or the firmware has no BLE
ps | grep ble-wifi-setup
```

`/dev/esp-ble` allows a single reader; a second one gets `-EBUSY`.

## Build

Build failures have their own issue template, which asks for what is actually
needed to diagnose one. See also the incidents list in
[DEVELOPMENT.md](DEVELOPMENT.md) — every entry there was a build that reported
success and produced something wrong.
