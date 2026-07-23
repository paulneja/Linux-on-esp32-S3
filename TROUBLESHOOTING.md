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
which wedged the firmware so the STA could no longer scan. The SoftAP is gone as
of 0.3, so this should not happen; if it does, it is worth an issue.

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
