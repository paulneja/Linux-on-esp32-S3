# Changelog

Releases carry one flashable `.bin` for a 16 MB / 8 MB-PSRAM ESP32-S3. Full
notes and the binaries are on the
[releases page](https://github.com/paulneja/Linux-on-esp32-S3/releases).

## Unreleased — the memory the board was reserving and never using

Measured on the developer board with the new kernel, against the same board
before it: `MemAvailable` at idle went from 860 kB to 3484 kB, the worst point
during the Bash benchmark from 248 kB to 2404 kB, and `init` starts at 1.71 s
instead of 4.23 s. `tainted` 0, no OOM, panic, BUG or Oops.

### Security

- **The four dropbear private host keys no longer ship in the image.** They
  come from buildroot's board directory, where they are tracked in a public
  repository, and they were landing in `rootfs.cramfs` at mode 0644 and in
  `etc.jffs2`. Every board built from this project answered SSH with the same
  key, downloadable by anyone. inetd already runs dropbear with `-R`, which
  writes a key per board into the writable `/etc` on the first connection.
  `package-final.py` now refuses to package an image that carries them.
- The WiFi configuration is written under `umask 077` instead of at 0644 with
  the passphrase in it until a later `chmod`, and the SSID and password are
  rejected if they contain a quote, a backslash or a newline. That path is
  reachable with no authentication at all from the BLE provisioning dialog.
- DHCP-supplied resolvers go into `resolv.conf` ahead of 1.1.1.1 and 8.8.8.8,
  which had been written first, so every lookup went to a public resolver
  before the network's own and LAN names never resolved.
- `/var/log` points at `/run/log` rather than the 1777 `/tmp`, where syslogd
  created world-readable authentication records.
- `ble-wifi-setup` reads through `/run` instead of a predictable name in
  `/tmp`, times out instead of parking mid-dialog forever, and parses the scan
  list by tabs, so an SSID with two spaces or a `*` survives.
- The kernel drops `no_hash_pointers`, `/dev/mem` and `TIOCSTI`, and restricts
  `dmesg`.
- The WiFi driver no longer advertises WEP40, WEP104, TKIP and SMS4, and no
  longer dumps 1600 bytes of hex to the console for any packet with one header
  byte set — remotely triggerable, about two seconds of UART each.

### Memory

- `SLUB_TINY`, the allocator variant written for machines under 16 MiB. Slab
  went from 3692 kB to 1700 kB.
- `INET_TABLE_PERTURB_ORDER=8`: the source-port randomisation table was
  262144 bytes at boot, sized for a host making thousands of outbound
  connections.
- jffs2 stops reserving the zlib deflate workspace, which `CMODE_NONE` means
  is never entered. NOMMU has no vmalloc area — `mm/nommu.c` makes `vmalloc`
  a `kmalloc` — so it was an order-7 allocation: a contiguous 512 KiB block,
  which is the one thing a fork here cannot find.
- `LOG_BUF_SHIFT` 17 to 15, `LEGACY_PTYS` off, and `TICK_CPU_ACCOUNTING`
  instead of `VIRT_CPU_ACCOUNTING_GEN`, which pulls in a debugging option that
  adds work to every syscall return.
- tmpfs cannot be capped on this kernel, and the fstab now says why instead
  of pretending: `SHMEM` depends on MMU, so what answers to tmpfs is the
  tiny-shmem stub over ramfs, whose only mount option is `mode`. A `size=`
  is rejected and the filesystem is not mounted at all. Keep large files on
  `/home`.

### Fork

The backend gave every process its own page set, including the resident one,
whose set is dead weight: its data is in the region itself. Exchanging the
resident page with the incoming shadow page leaves the outgoing process's data
in the set the incoming one vacated, so N processes need N-1 sets and the
resident owner holds none. Two loads and two stores per word is what the
save-then-restore pair of memcpy already cost, so the traffic per context
switch is unchanged.

Measured with `programbench`, peak system-wide backup during each run:

| program | before | after |
|---|---:|---:|
| socat, a plain fork and exec | 296 kB | 144 kB |
| micropython | 512 kB | 384 kB |
| dash | 560 kB | 420 kB |
| bash | 892 kB | 800 kB |

The halving is exact for a single fork of one region, which is what socat
does and what the arithmetic predicts. A shell benchmark keeps several
processes alive at once, where N-1 against N is a smaller proportion, so the
improvement there is 10 to 25 per cent. `fork-test` passes 5/5 static and
5/5 dynamic on the board.

Copy-on-write is not possible on this chip, and the reason is now written
down rather than remembered: the TRM's section 15.6 says an unpermitted write
*fails* and raises an asynchronous interrupt. There is no restartable fault to
copy a page and retry the store from.

`bank_access()` keeps interrupts disabled for one page instead of for a length
that comes from userspace — reading `/proc/PID/mem` of a banked process could
ask for a single 512 KiB memcpy with interrupts off. The ceiling on banked
private memory is a module parameter now; it also bounds how long a switch
runs with interrupts disabled.

### The WiFi driver

- A use after free on the interface creation error path: `esp_wdev` is
  `netdev_priv(ndev)` and was written after `free_netdev()`, with
  `adapter->priv[]` left pointing at it. That path is taken when a command to
  core 0 times out, which is when the firmware is slow at boot.
- The receive path copied a fixed 1600 bytes from an allocation the firmware
  sizes to the packet — 12 bytes for a short command response — reading past
  the end of the other core's heap. Its length check also added the header to
  a `u16` before comparing, so a declared length near 65535 passed.
- A command node handed out without an skb was never returned to the free
  queue, and every caller checks for the skb and gives up, so twenty
  allocation failures emptied the pool permanently and WiFi stayed dead until
  reboot. Two more leaks on the association and response paths.
- Transmit completion ran only when a receive in the same batch succeeded, so
  one failure with the write ring full could leave the queue stopped.
- `prepare_command_request()` rejects an oversized payload instead of reaching
  `skb_over_panic()`; the node then fits the transport maximum and drops from
  the kmalloc-4096 slab to kmalloc-2048.
- A `synchronize_rcu()` before every command, with no RCU readers to wait for.
- `esp_alloc_skb()` reserved headroom only when the slab returned an unaligned
  pointer, so transmit was allocating a second skb and copying every frame.

Twelve WiFi scans on the board with no node pool exhaustion; five networks
found.

### Core 0

- Both watchdogs are enabled. Nothing watched the WiFi and BLE core: if it
  deadlocked, Linux kept running with permanently dead networking and no way
  to reset it. Two traps, both found by building and reading the generated
  config: `CONFIG_INT_WDT`, the deprecated alias, sits 650 lines further down
  and silently turned the interrupt watchdog back off, and
  `ESP_INT_WDT_CHECK_CPU1` defaults to on, under which core 0 feeds the
  watchdog only after core 1's FreeRTOS tick sets a flag — core 1 runs Linux,
  so the chip would have reset itself every 1.6 s.
- `send_task` slept a whole tick when its queues were empty, adding up to
  10 ms to any packet arriving into an idle queue. The enqueue sites signal a
  semaphore instead.
- `SPIRAM_MEMTEST` no longer walks 8 MiB on every power-on.
- Enabling the watchdogs moves the firmware's `space_for_vectors` by a page,
  and the kernel is linked against that address, so `CONFIG_VECTORS_ADDR`
  moves with it. Flashing one without the other gives a core 0
  `StoreProhibited` panic and a reset loop; `package-final.py` compares them.
  The measured table is in the sdkconfig and in `build/verification/`.

### Flash

About 1.4 MB reclaimed from a rootfs partition that had 48 KB free: iptables
(788657 bytes, for a firewall that ships empty and that a post-build script
already renamed out of the boot sequence, whose plugins match on things this
kernel does not build), lua (223683 bytes, for one CGI now written in sh and
awk), the duplicate MicroPython and the untested payloads under
`/usr/share/mmu` (468 KB), the gpio tools that duplicate `espctl`, and four
libraries no ELF in the image lists as `NEEDED`. The kernel itself is 320 KB
smaller. One trade was tried and reverted: compressing busybox's help text
saves 45 KB of flash but makes every `--help` allocate about 450 KB of RAM
for bunzip2, in one contiguous block — `nc --help` went from 76 KB private to
584 KB on the board.

### Behaviour

- **The shell fallback only triggers on a real fork failure.** It switched to
  dash and replayed the last command on any non-zero exit status, so `grep`
  finding nothing, a failed `test`, or a command that wrote half a file and
  died were all retried. Bash returns 126 when it cannot fork. It also asks
  before replaying now, keeps its state per process rather than in one shared
  path, and no longer writes a preference to jffs2 at the moment memory ran
  out.
- Starting dash without `-l` meant dash users read no `/etc/profile` at all —
  no PATH, no EDITOR, no umask — which the low-memory switch then made
  permanent.
- `ssh-server` and `web-server` send SIGHUP to inetd instead of killing and
  relaunching it without `-f`, which left the pidfile naming a dead process,
  so stopping inetd stopped working and a later start bound a second one.
  `ssh-server` also had no root check and reported success after failing.
- `wifi --help` printed the script's own source.
- The board keeps a clock across reboots and sends a hostname with its DHCP
  request. Without the first, every boot started in 1970 and TLS failed until
  NTP answered; without the second the router listed the board unnamed.
- udhcpc logs to syslog. On NOMMU it re-execs into the background and sets
  `logmode` to none, so nothing it reported reached `/var/log/network.log`,
  which the README tells you to read.
- `kernel.default_stack_size` is 32 KiB. On NOMMU the stack is one allocation
  with no guard page, and curl, wpa_supplicant, dropbear, nano and iw all have
  a zero `PT_GNU_STACK` and land on it; the manifest records which do.

### Build

- `package-final.py` checks the kernel's link address against the linux
  partition offset, cross-checks `partition-table.bin` against the CSV, and
  refuses an image carrying dropbear keys.
- `flash.sh --backup DIR` reads `/etc` and `/home` off the board, which
  `build/README.md` told you to do without providing a way.
- `run.sh --recover` used esptool 5 spellings that the pinned 4.8.1 rejects.
- Host checks run on every push, over every tracked shell script rather than a
  list, with a bashism check on the scripts busybox runs and guards against a
  patch carrying a binary hunk or a file that `new-files/` also ships.

## 0.7 — fork, Bash and a userspace that fits (2026-09-08)

- Native NOMMU fork with private software banks, last-owner backup recovery,
  memory counters and quiet-by-default tracing. Not COW or a full MMU;
  UP-only, no multithreaded fork, 512 KiB private-memory limit per fork.
- Bash for user logins; BusyBox remains `/bin/sh` for services. Fixed hush
  login-profile recursion and reduced Bash's initial PID-cache allocation.
- Dash, GNU Make, MicroPython with fork/IPC, socat and nc under normal names.
- Editable `/home/www`, private user homes, `su`/`passwd`, dtach sessions,
  persistent per-user cron and working `@reboot`. No SQLite, sudo or doas.
- Process compatibility tests, `programbench`, memory-aware `jobq`, selectable
  image profiles and checked removal of ELF debug/section metadata.
- Removed nonessential source comments while preserving licenses and
  functional directives/configuration/patch-matching data.
- Added a clean, pinned-source container pipeline producing a complete
  16 MiB image and checksums.
- Ship the factory `/home` formatted instead of erased, fixing the observed
  first-boot stall at `mkdir`. The clean image from `ee9e06d` passed 26/26
  hardware checks; its exact hash and scope are recorded under `build/verification/`.
- Check flashing inputs, sizes and partition layout before any erase; preserve
  paths with spaces and document which modes overwrite `/etc` and `/home`.
- Restore `flash.sh --help` and add host-only regression tests with a simulated
  flasher. Distinguish functional clean-build validation from bit-identical builds.
- Two independent builds of the same commit differ only in `/etc/shadow`, from
  Buildroot's random password salt; everything else matches byte for byte.
- Keep booting when `/home` is slow: `S06home-users` waits a bounded 45 seconds
  for `home-init` and continues, and `web-server migrate` no longer writes to
  `/etc` on every boot. A board whose `/home` needed reclaim previously stopped
  reaching the login prompt.
- Retry the ESP-IDF tool download and stop the build when it still fails. A
  transient `504` from GitHub used to be ignored, and the run carried on until
  the firmware stage died with an unrelated looking mesage.
- Boot to a login prompt in about 14 seconds from reset. Init no longer blocks
  on `/home` and writes less to flash while starting, and the validated run
  completed boot and all 27 tests with no OOM kill in `dmesg`.
- Stop the DHCP client and protect the console shell before running the board
  suite. Its script forks on every retry, and on an idle image with ~1.3 MiB
  free that was enough for the OOM killer to take the console shell out from
  under the cron test.
- Retry a benchmark whose measured program is killed by the OOM killer, up to
  three times, printing each retry. Measuring Bash leaves under 100 KiB free,
  so a DHCP lease event forking its script there was enough to kill it and
  abort the whole benchmark step. A non-kill failure still fails immediately.
- Stream the build to the terminal instead of hiding it in a log, state its
  cost before starting, and report elapsed time; `-q` restores the quiet form.
- Add `./run.sh`, a menu-driven driver for the whole path: environment checks,
  clean build, checksums, flashing, the board suite, a two-build reproducibility
  comparison and a factory restore. Every step is also a flag, so it runs
  unattended. It finds an interpreter with pyserial, avoids reusing an output
  directory, and offers to close a console holding the serial port.
- Take an image directory with `./flash.sh --images DIR`, so the same checked
  flasher serves the committed 0.6 release and a freshly built artifacts
  directory. `--parts --erase` writes a factory `home.jffs2` when the directory
  has one and otherwise leaves `/home` erased, which the board formats on its
  first write. `images/` keeps the 0.7 release, matching its own combined
  image byte for byte.
- Known limitation of the platform, not fixed here: once jffs2 has to reclaim
  and erase used blocks, write throughput collapses. The published 0.6 kernel
  behaves the same way, so this is not new in this branch.

The entries below describe earlier releases and retain their original limits.

## 0.6 — the clock sets itself, the web page stays on (2026-07-31)

**Two things that had to be redone after every single boot no longer do.** The
clock now comes from the network instead of starting at 1 Jan 1970, which is
what made every HTTPS request fail; and the status page has a switch that
survives a restart. Neither needed new machinery — both are one small script
hung off something the board already did.

Verified twice over. On a **fully erased board**, not an incremental reflash:
erase, write the combined image, join WiFi from nothing, and the clock sets
itself and HTTPS works with nothing typed by hand. And rebuilt from this
repository alone by GitHub Actions in Docker, where all seven images come out
at exactly the size of the ones committed here and the two that carry nothing
of the machine that built them are byte-identical.

### The clock sets itself

The board has no RTC, so it powered on in 1970 and *every* HTTPS request failed
until someone typed `date -s` by hand. It now asks NTP.

- `CONFIG_NTPD=y` in the busybox config (client only — a board that has just
  learnt the time has no business serving it). This is the only new code on the
  image: `rootfs.cramfs` grows by one 16 KB block, 6,832,128 → 6,848,512 bytes,
  leaving 992 KB free in the partition.
- The sync runs from a **udhcpc hook**, `/usr/share/udhcpc/default.script.d/50-set-clock`,
  not an init script. udhcpc calls its hooks after the address, the default
  route and `resolv.conf` are all in place, which is the first moment an NTP
  query can succeed; an init script would have to sit in a loop waiting for
  exactly that.
- It runs in the background — udhcpc waits for the script and `ifup` waits for
  udhcpc, and since 0.5 the boot deliberately does not wait for `ifup`. It
  cannot linger either: `ntpd -q` arms a 10 s alarm at startup (50 s once some
  peer has replied) and kills itself when it fires.
- Three peers: `pool.ntp.org`, plus Cloudflare's and Google's time servers as
  **IP literals**, so a network where DNS is broken but UDP 123 works still
  gets the time. Cloudflare is listed only as an address — with the name there
  too, both resolve to the same host and ntpd drops one as a duplicate peer.
- On `bound` it always syncs; on `renew` only if the clock is still unset. A
  lease renewal on a board that already knows the year is not a reason to go
  ask again.
- What it did lands in `/var/log/network.log`, next to what `ifup` did.

### `web-server on|off|status`

The status page needed `httpd -h /www -p 80` typed again after every reboot.
Now it has the same helper `ssh-server` has, and for the same reasons.

- The switch is a line in `/etc/inetd.conf`, on the writable `/etc` partition,
  so it survives a reboot. inetd starts httpd only when someone actually
  connects: enabled-but-unvisited costs no process and no RAM, which matters
  more here than the per-request spawn does.
- **Off by default**, unchanged. An unauthenticated HTTP port is not something
  to hand out unasked.
- The service field is the port number, not `http`: busybox inetd takes either,
  but `/etc/services` calls port 80 `www` with `http` only as an alias.
- Verified end to end with busybox inetd + `httpd -i` before it went near the
  board, CGI included.

### `flash.sh --parts` wrote three of the six pieces to the wrong place

The offsets were typed into the script and had drifted from the partition
table: `/etc` landed inside the firmware partition and the kernel 128K below
where the bootloader looks for it. esptool reports success and the board never
boots. `--parts` is the road less travelled — the combined image is the
documented path and `make-images.sh` builds it by reading the same table — so
nothing caught it.

Rather than correct the numbers and leave the next drift to chance, the script
now reads them out of `partition_table.esp32s3.16m8r`, the same CSV
`make-images.sh` generates `partition-table.bin` from. Change the table and
both follow. Verified by moving two partitions in the CSV and watching the
offsets move with them, with the script untouched.

Only `0x0` (bootloader) and `0x8000` (the partition table itself) stay
constants, because they cannot come from a table that has not been found yet.

### CI checks the build against the images here, not just that it builds

A green run used to mean "it compiled and packaged". It never compared the
result with what this repository ships, which is the one thing a build from a
clean checkout is worth running for.

- The packaging job keeps a copy of the committed images before
  `make-images.sh` overwrites them, and prints a table — to the log and to the
  run summary — of size and byte equality for each.
- It reports rather than fails. Byte-identical is not the expected outcome for
  most of them: the kernel embeds the `user@host` that built it, so a Docker
  build and a native one differ in length there and every pointer table after
  it shifts. `bootloader.bin` and `partition-table.bin` carry no such thing and
  must match exactly; if those two ever differ the summary says so outright.
- Caught while testing that step: iterating over `images/*.bin` silently skips
  `rootfs.cramfs`, `xipImage` and `etc.jffs2` — three of the four that can
  actually differ. It walks both directories by name now.
- `include-hidden-files` on the raw build artifact. A build tree is mostly
  dotfiles, and v4 quietly stopped including them, so repackaging a downloaded
  artifact was not the same as repackaging the tree it came from.
- A concurrency group, the artifact actions moved to their current majors after
  checking every input the workflow uses still exists, and `make-images.sh`
  now says *"there is no toolchain here"* instead of failing obscurely when the
  vector address moves in a packaging job that has no compiler.

The first run of it, on this release: seven of seven sizes equal, two
byte-identical, the vector address in agreement, and no WiFi credentials baked
into the image.

### Also

- **TROUBLESHOOTING**: `jffs2: Name CRC failed on node at 0x...`, which is a
  directory entry written only half way — jffs2 spots it at mount, discards it
  and carries on. Seen here after a flash that was interrupted part way; a full
  erase cleared it. Includes how to tell which of the two writable partitions
  it is, and why nothing important can be lost that way.
- **TROUBLESHOOTING**: `sh: bad number`, printed by hush after almost every
  command substitution in an interactive shell — including `$(echo hi)`, which
  runs no external program. It is hush re-executing busybox because a NOMMU
  system cannot fork. Values are always correct and scripts are unaffected.
- **SECURITY**: the NTP queries as their own trade-off. Unsolicited outbound
  traffic to three third parties, unauthenticated, and whoever can intercept it
  decides whether an expired certificate looks valid to this board.

## 0.5 — SoftAP gone, faster boot, reproducible (2026-07-26)

**A new binary.** The SoftAP is removed from both the driver and the firmware,
the cold boot is down from 14.6 s to 11.0 s, and the whole thing has been
rebuilt from a clean clone of this repo and booted again.

### Build reproducibility

A build made from a clean clone did not reproduce the released image; these are
the defects that stood in the way, all found on hardware.

- The Docker image was missing `cpio`, which buildroot checks for *after*
  crosstool-NG has compiled the entire toolchain — hours in, at the most
  expensive point.
- `03-buildroot-tracked-changes.patch` carried a compiled binary `git apply`
  cannot reconstruct, so it was rejected in full on every fresh clone — and the
  failure was read as "already applied" and ignored. Builds reported success
  while producing images with no `/etc/fstab`, `inetd.conf` or `S05home`.
- The firmware patch had drifted behind the tree the images were built from: it
  was missing the RSA handover (without which **the kernel hangs at boot with no
  output**), the entire BLE link, and a vendored ESP-IDF change. Regenerated
  from that tree and verified byte for byte.
- The defconfig had drifted too: `setup-home.sh` was not being run, so root
  landed in `/root` on the read-only cramfs. And buildroot's own default
  `wpa_supplicant.conf` was reaching the image, making a clean build join any
  open WiFi network by itself.

A full from-scratch build in Docker now runs to completion and the result boots
on hardware.

Since confirmed the harder way: a clean clone of this repo, built end to end
and flashed, boots and joins WiFi. Five of the six images come out at exactly
the size of the ones committed here and `etc.jffs2` within 4 bytes, but only
`bootloader.bin` and `partition-table.bin` are byte-identical. That clone was
built in Docker and these images natively, which is most of the difference:
the kernel carries the build `user@host` in its version string, and a
different length there shifts every pointer table after it. See DEVELOPMENT.md
for the full accounting.

### SoftAP removed for real

0.3 disabled the SoftAP; the code stayed behind, unreachable. It is now gone
from both sides, and the binaries change accordingly.

- Kernel: `01-kernel-esp32ng-ap-support.patch` is deleted. The esp32-ng driver
  is pristine upstream plus the BLE pipe — no `.start_ap`/`.stop_ap`, no
  `cmd_ap_start`/`cmd_ap_stop`, no `CMD_AP_*`/`EVENT_AP_*` codes, no
  `ap_iface`/`esp_ap_password` module parameters, `ESP_MAX_INTERFACE` back to 1.
  This is a no-op for the STA: the removed refactor threaded `priv->if_type`
  through 19 call sites, and on a STA-only build that value is always
  `ESP_STA_IF` — exactly the constant upstream hardcodes.
- Firmware: `cmd.c` is byte-identical to upstream again. WiFi start-up returns
  to upstream's model (event loop and `esp_wifi_start()` inside
  `process_init_interface()`, behind the `!sta_init_flag` guard) rather than
  starting once at boot, which was only ever done so the AP beacon would carry
  its RSN element.
- The vendored ESP-IDF needs no patch now, so `06-idf-hostap-sta-join.patch`
  is gone; `hostap_sta_join` is `static` again.
- One entry of that `wpa_funcs` block had to go back: `wpa_sta_set_ap_rsnxe`
  sits among the AP callbacks but belongs to the supplicant —
  `wpa_sm_set_ap_rsnxe` lives in `rsn_supp/wpa.c` and records the RSNXE the
  *access point* advertised. `initialise_wifi()` memsets `wpa_cb` and re-fills
  it, so anything `esp_supplicant_init()` had set is lost unless restored by
  hand. With it NULL the blob logs `wifi:null wpa_sta_ap_set_rsnxe` on every
  association: WPA2-PSK still associates and routes, but the message lands on
  the serial console mid-command, and WPA3/SAE-H2E does need the callback.
  Caught on hardware after the removal, not by review.
- The firmware is also **built** without SoftAP:
  `CONFIG_ESP_WIFI_SOFTAP_SUPPORT=n` keeps the SDK's own AP machinery
  (`esp_hostap.c`, the `ap/` authenticator sources, the WiFi lib's SoftAP init)
  out of the image. ESP-IDF supports this directly — with the option off it
  compiles an empty `net80211_softap_funcs_init()` over the weak symbol in the
  closed WiFi lib. `network_adapter.bin` drops from 721,632 to 686,992 bytes,
  and the fixed 768K `factory` partition goes from 8% to 13% free — headroom
  the BLE stack had nearly used up.
- Rootfs: `/etc/udhcpd.conf` (a DHCP server for the AP's clients) and the
  busybox `udhcpd` applet are gone. `udhcpc`, the client the STA needs, stays.
- Two build-system defects found on the way: `apply-local-changes.sh` copied
  `new-files/board/` with `rsync` and no `--delete`, so a deleted kernel patch
  would linger in the buildroot tree and keep being applied; and the reference
  copy in `kernel-driver-esp32-ng/` was stale — it shipped `esp_ble_prov.c`
  while its `Makefile` did not build it.

Verified on hardware: RSA self-tests pass, `espsta0` is the only netdev, and a
WiFi scan returns results — the operation the SoftAP used to wedge.

### Boot time: 14.6 s → 11.0 s to a login prompt

Measured from the first serial byte after reset, repeatable to 0.01 s over
several cold boots. All of it came out of userspace (8.4 s → 4.8 s); the kernel
and firmware phases are unchanged at 6.2 s.

- **`S40network` no longer blocks the boot** (~2.2 s). `ifup -a` moves to the
  background: nothing later in the boot needs the network — inetd binds
  regardless of link state and the BLE link talks over `/dev/esp-ble` — and the
  interface finishes coming up behind the login prompt. It was pure waiting:
  `/etc/network/interfaces` declares `espsta0` as `inet dhcp` with
  wpa_supplicant in a *post-up* hook, so udhcpc starts before the radio has
  even associated. Its output goes to `/var/log/network.log` instead of landing
  on top of the prompt; `/etc/init.d/S40network start-fg` runs it in the
  foreground by hand.
- **`S02sysctl` replaced** (~1.4 s). Buildroot's generic version scans five
  directories with `find`, pipes through `xargs` and `readlink`, and builds a
  two-stage `logger` pipeline — about ten process spawns to apply the single
  line this board has. On XIP cramfs with a NOMMU libc that is not free.
- **cron removed** (~0.8 s). Nothing on the board used it, there are no
  crontabs, and its own stop path was broken (`no /usr/sbin/crond found`).
  `CONFIG_CROND=n` also stops buildroot from installing `S50crond`.
- **iptables no longer starts at boot** (~0.6 s), while staying installed. It
  had nothing to restore — the SoftAP's NAT is gone — so `trim-target.sh` drops
  the `S35` prefix: `rcS` only runs `/etc/init.d/S??*`, and
  `/etc/init.d/iptables start` still works by hand.

One thing this did *not* touch: 2.48 s of the kernel's 4.2 s goes into a single
gap around `of_fixed_clk_driver_init`, where the console hands over from
earlycon to `ttyS0`. It is not initcall time (all 170 initcalls together come
to 0.87 s), and `initcall_debug` cannot be used to look at it — it hangs the
board at exactly that point, mid-character. Still unexplained.

## 0.4 — WiFi setup over Bluetooth (2026-07-22)

Join the board to WiFi **from a phone, with no PC and no cable**. It advertises
over BLE as `Esp32-Linux`; connect with any BLE serial terminal, send a
character, pick a network from the list. The ESP32-S3 has no Bluetooth Classic,
so this is the Nordic UART Service over BLE.

Wait about 30 seconds after power-on before connecting — the BLE stack comes up
long before Linux has finished booting, and that window is unreliable.

- NimBLE peripheral on core 0 as a byte pipe to Linux (`/dev/esp-ble`); the
  dialog runs through the existing `wifi` command, so the driver state cannot
  desynchronise.
- The kernel's vector address is now kept in sync with the firmware
  automatically, instead of being a hand-maintained constant that silently
  killed the boot when the firmware changed size.

## 0.3 — SoftAP removed, nano, interactive wifi (2026-07-18)

- **SoftAP removed; STA only.** The closed WiFi blob beaconed as WEP, and
  bringing the AP up wedged the firmware so the STA could no longer scan. The
  board now joins networks rather than hosting them, which also makes scanning
  reliable.
- **nano** replaces the busybox `vi` applet; `vi` is a symlink to it.
- **Interactive `wifi`.** Scan, list numbered, pick one — open networks connect
  straight away, secured ones prompt. 0.2's README promised `wifi connect`
  before the command existed; now it does.
- **One full-flash image.** Flashing it alone rewrites the whole 16 MB chip.

## 0.2 — native Xtensa Linux (2026-07-17)

**Linux runs natively on the ESP32-S3.** 0.1 ran Linux on a RISC-V emulator
hosted on the chip; this replaces it with a real Linux 6.11 kernel compiled for
Xtensa, executing on the chip's own cores. No interpreter in the middle.

Verified on a fully erased board: boots to a login prompt, the RSA accelerator
passes its self-tests, the rootfs mounts from flash, telnet comes up, and the
board reaches the internet.

## 0.1 (2026-07-13)

First release: Linux on a RISC-V emulator hosted on the ESP32-S3. Superseded by
0.2, which is better in every respect; kept for the history.
