# Paperboard ED097TC2 console

Target: SVERIO Paperboard v1, ESP32-S3 N16R8 and ED097TC2 (1200 × 825).
The display configuration uses VCOM -1.5 V and a 5 MHz pixel clock.

## Architecture

Linux runs on core 1; the ESP-IDF service and display renderer stay on core 0.
A root-only `/dev/epd` misc device sends terminal bytes through the shared-memory
transport. `epd-shell` relays a PTY to the serial terminal and display. Root logins
on /dev/console or /dev/ttyS0 enter the relay automatically. Other terminals and
noninteractive invocations use the regular shell. Create /etc/paperboard-no-mirror
to disable automatic mirroring on future logins.

The display is a 75 × 34 ASCII terminal with cursor movement, scrolling, inverse
text and basic escape sequences. It is not a complete VT100 implementation and
does not mirror early boot messages. It uses text states instead of allocating a
large framebuffer in the PSRAM owned by Linux.

V3 prepares up to 48 changed scanlines in the 64-slot internal ring before each
LCD transfer. Unchanged rows drive neutral pixels directly from the ISR. Larger
changes are divided into batches, each completing all stock DU phases. This
removes concurrent row preparation from the transfer at the cost of additional
scans. Healthy power-good statuses are silent; errors remain visible.

The local epdiy copy includes the single-core renderer, procedural line input,
queue allocation/publication fixes and internal-memory raster/font support.
Its license is retained in epdiy/LICENSE. A draw error stops updates until reboot.

## Build and test

On a Linux build host with Docker, from a clean committed checkout:

    JOBS=8 bash build/reproduce.sh

Use `main` for the display build or `paperboard-headless` for the display-disabled
build. Use a fresh build directory when switching branches; do not reuse completed
stage markers from another variant. Build output includes a merged 16 MiB image
and a manifest with checksums and kernel/firmware vector compatibility checks.

Host tests (Clang, Python 3, ASan and UBSan):

    bash paperboard/tests/run.sh

## Verification

Paperboard V3 was built and reported working on the user's Paperboard after V1/V2
had line queue underruns during Linux activity. Parser, queue, and login-wrapper
host tests passed. Headless V1 was built; the ELF flag and final rootfs were
verified to disable display initialization and automatic mirroring, respectively.
Headless hardware boot and USB flashing via the web installer remain unverified.

Headless retains the linked renderer to preserve the tested kernel memory layout,
but returns before display GPIO/I2C setup, power sequencing or task allocation.
/dev/epd remains available for ABI compatibility and discards writes in that build.

Factory images include public default credentials root / changeme123. Change the
password with passwd. Wi-Fi configuration is performed using the wifi command
from a serial shell, not Improv provisioning in the web installer.
