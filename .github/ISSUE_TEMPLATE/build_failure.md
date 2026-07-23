---
name: Build failure
about: A build from source failed, or produced an image that does not work
title: "build: "
labels: build
---

<!--
Every build defect this project has had reported "success" somewhere along the
way, so please do not summarise — paste the output. The questions below are the
ones that actually narrowed the last four down.
-->

## What happened

<!-- One or two sentences. If the build finished but the board misbehaves, say
     what the board does. -->

## How you built it

- **Docker or native**:
- **Host OS** (`uname -a` for native builds):
- **Commit** (`git rev-parse --short HEAD`):
- **Command you ran**:

## Where it stopped

<!-- The last ~50 lines of the build output. If it is a compile error, include
     the first error, not just the last line -- make's last line is usually the
     least useful one. -->

```
```

## If the board boots but misbehaves

Serial log at 115200 baud, from power-on. Anything that captures to a file works
(`cat /dev/ttyACM0 | tee boot.txt` after `stty -F /dev/ttyACM0 115200 raw -echo`,
or `screen`/`picocom` with logging on).

**The single most useful line**: does this appear?

```
esp32s3-rsa: selftest 512-bit PASS
```

If the log stops just before it, the firmware and kernel are out of sync — see
[TROUBLESHOOTING.md](../../TROUBLESHOOTING.md).

```
```

## Checks worth running first

<!-- Not required, but each one has been the answer at least once. -->

- [ ] Clean clone, not a tree with earlier local edits in it
- [ ] `apply-local-changes.sh` printed no error and did not skip a patch
- [ ] `make-images.sh` ran and its size / credential / vector checks passed
- [ ] Flashed the whole image (`./flash.sh --erase`), not selected partitions
