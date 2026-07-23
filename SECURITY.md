# Security

This is a research project: a general-purpose Linux running on a microcontroller
that was never designed to host one. It is meant for a workbench and a trusted
home LAN. **Do not put a board running this image on an untrusted network, or
anywhere the network it joins matters.**

Nothing below is a bug report. These are deliberate trade-offs, listed so the
choice to accept them is yours and not a surprise.

## What the shipped image exposes

| | |
|---|---|
| **Root password** | `changeme123`, the same on every flashed board |
| **Telnet** | on by default, **unencrypted** — password and session in clear text |
| **SSH** | off by default (`ssh-server on` enables it); slow on this hardware |
| **Bluetooth LE** | advertises as `Esp32-Linux`, **no pairing, no PIN** |
| **Secure boot / flash encryption** | not used; flash can be read and rewritten over USB |

The password is deliberately an obvious `changeme` rather than a plausible-looking
one, so there is no chance of mistaking it for a real secret. Change it with
`passwd` before the board is on any network you care about.

### The Bluetooth link is unauthenticated

Anyone within BLE range can connect and reach the WiFi provisioning dialog. It
is not a root shell — it only scans and joins networks — but that is enough to
**move your board onto a network of their choosing**, and to list the SSIDs the
board can see.

There is no pairing because the point of the feature is joining a network with
no PC and no cable, and the dialog has to work before any credentials exist. If
that trade is wrong for you, delete `/etc/init.d/S46blewifi` and reboot; the
rest of the system is unaffected.

## Past incidents

**Any open WiFi network, joined automatically.** Buildroot's `wpa_supplicant`
package installs its own `/etc/wpa_supplicant.conf` containing a network block
with no `ssid` and `key_mgmt=NONE`, which matches *any* unencrypted network. A
board built from this repo joined a carrier hotspot on its own, unprompted.

The released images never carried the file, but only by accident — it had been
deleted by hand from an incremental build tree, and nothing here reproduced
that. Fixed by removing it in a post-build script, plus a check in
`make-images.sh`, whose previous check looked only for a `psk=` line and so
missed it entirely: **an open-network block contains no credentials at all,
which is exactly what makes it dangerous.**

If you built from source before that fix, check the board:

```sh
cat /etc/wpa_supplicant.conf     # a network block with no ssid is the bad one
```

## Reporting something

Open a GitHub issue. There is no private disclosure channel — this is a
single-maintainer hobby project, and pretending otherwise would be worse than
saying so. If a finding genuinely should not be public first, open an issue
asking for a contact and leave the details out of it.

No support commitment, no fix timeline, no backports. The reproducibility
caveats and the list of past build defects are in
[DEVELOPMENT.md](DEVELOPMENT.md).
