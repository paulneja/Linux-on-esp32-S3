# Reproducible build environment for the Linux-on-ESP32-S3 native (Xtensa)
# edition. Debian 12 is used deliberately: it matches what jcmvbkbc's own
# README targets, and its GCC (12.x) and CMake are old enough that they
# don't trip the "too new host tools" failures a bleeding-edge distro hits
# (GMP's configure breaking under GCC 15+'s C23 default; old CMakeLists.txt
# rejected by CMake >= 3.31). Building here needs none of the host-specific
# workarounds documented in PLAN.md for a rolling-release host.
FROM debian:12

RUN apt-get update && apt-get install -y --no-install-recommends \
    autoconf automake bash bc bison build-essential cmake flex gawk git \
    gperf help2man libncurses-dev libtool libtool-bin libusb-1.0-0 \
    python3 python3-venv rsync texinfo unzip wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work

# The actual sources (crosstool-NG, buildroot, esp-hosted, kernel) are
# fetched by rebuild-esp32s3-linux-wifi.sh itself on first run -- this image
# only provides the pinned host toolchain the script needs.
COPY . /work

# `-c <profile>.conf` selects the board profile; default matches this
# project's real hardware (16MB flash / 8MB PSRAM). Override at `docker run`
# time, e.g.: docker run ... linux-on-esp32s3 -c devkit-c1-8m.conf
ENTRYPOINT ["/work/rebuild-esp32s3-linux-wifi.sh"]
CMD ["-c", "devkit-c1-16m.conf"]
