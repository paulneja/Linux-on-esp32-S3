# ESP32 Linux Web Installer

An English static installer for desktop Google Chrome using Web Serial.
Both builds require ESP32-S3 N16R8 (16 MB flash, 8 MB OPI PSRAM).
Headless supports compatible development boards; individual models are not all
verified. The display build requires SVERIO Paperboard v1 + ED097TC2 wiring.

## Run locally

    python3 serve.py

Open http://127.0.0.1:8080 in Google Chrome. Use `--port 8081` if needed.
Do not open index.html through file://. The server binds only to loopback.

## Host

Upload this entire directory to an HTTPS static host. Keep relative paths intact,
including vendor/, firmware/, and both manifest files. No build step, CDN,
analytics or external JavaScript is required. Firmware installation uses
ESP Web Tools 10.4.0 (vendored official npm distribution, Apache-2.0 license).
Documentation: https://esphome.github.io/esp-web-tools/

Both options are FULL installations at offset 0, overwriting all 16 MB including
/etc and /home. They are not the incremental update scripts. Improv detection
is disabled because network setup happens through the Linux serial shell.
The manifest restricts the chip family to ESP32-S3. It does not validate PSRAM.

## First connection

Close the browser serial connection, restart the board and open any serial terminal.
Select your board’s actual serial port, for example COM3 on Windows or
/dev/ttyUSB0 or /dev/ttyACM0 on Linux. Use 115200 baud, 8 data bits, no parity,
1 stop bit (8N1), and no flow control.

Log in as root with password changeme123, then run `wifi`, select a network and
enter its password. This sets up the network for wireless transfers. `passwd`
changes the default login password.

Linux uses UART0 (GPIO43 TX, GPIO44 RX); native USB flashing and the runtime
serial console may require different connections.

## Verification

Firmware SHA-256 values match the previously packaged full builds. Both manifests
point to a single 16 MiB image at offset 0. Local HTTP assets and variant switching
were checked. The installer library loaded with Web Serial support in the preview.
Actual USB flashing from this web page has not been tested on hardware.

Project fork: https://github.com/svermigo/Linux-on-esp32-S3
The corresponding source revisions are:
- Paperboard V3: `9c4a784` (display-enabled build on main).
- Headless V1: `b25c7ad` (display-disabled build on paperboard-headless).

Build instructions and modifications are in this repository. Firmware images
retain their upstream licenses; the ESP Web Tools license is in vendor/.
