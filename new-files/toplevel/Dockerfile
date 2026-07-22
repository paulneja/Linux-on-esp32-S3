# Reproducible build environment for Linux-on-ESP32-S3 (native Xtensa).
#
# Debian 12 is deliberate: it matches what jcmvbkbc's own README targets, and
# its GCC (12.x) and CMake are old enough not to trip the "host tools too new"
# failures a rolling-release distro hits (GMP's configure breaking under GCC
# 15+'s C23 default; old CMakeLists.txt rejected by CMake >= 3.31). None of the
# host workarounds a bleeding-edge host needs apply here.
#
# Build it from the root of this repo:
#     docker build -f new-files/toplevel/Dockerfile -t linux-on-esp32s3 .
#     docker run --rm -v $(pwd)/build-output:/work/esp32-linux-build/build \
#         linux-on-esp32s3
#
# The compile takes hours: it builds a crosstool-NG toolchain, then buildroot,
# the kernel and the firmware. Results land in the mounted build/ directory.
FROM debian:12

RUN apt-get update && apt-get install -y --no-install-recommends \
    autoconf automake bash bc bison build-essential cmake flex gawk git \
    gperf help2man libncurses-dev libtool libtool-bin libusb-1.0-0 \
    python3 python3-venv rsync texinfo unzip wget ca-certificates patch \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work

# This project's delta: the patches and the files copied into the upstream
# trees. apply-local-changes.sh picks these up via ./local-changes.
COPY patches       /work/local-changes/patches
COPY new-files     /work/local-changes/new-files

# The upstream build driver. It is not vendored here — it is jcmvbkbc's, and
# patch 00 adds the host-tool workarounds and, crucially, the two calls to
# apply-local-changes.sh that make a clean build reproduce *this* project
# rather than the upstream one.
RUN git clone https://github.com/jcmvbkbc/esp32-linux-build /work/esp32-linux-build \
    && cd /work/esp32-linux-build \
    && patch -p1 < /work/local-changes/patches/00-esp32-linux-build.patch

# The pieces that live next to the build driver: the applier itself, and the
# 16MB/8MB-PSRAM board profile (upstream only ships the 8MB one).
RUN cp /work/local-changes/new-files/toplevel/apply-local-changes.sh \
       /work/local-changes/new-files/toplevel/devkit-c1-16m.conf \
       /work/esp32-linux-build/ \
    && ln -s /work/local-changes /work/esp32-linux-build/local-changes

WORKDIR /work/esp32-linux-build

# crosstool-NG refuses to run as root, so build as an unprivileged user.
RUN useradd -m builder && chown -R builder:builder /work
USER builder

# `-c <profile>.conf` selects the board profile; the default matches this
# project's hardware (16MB flash / 8MB PSRAM). Override at run time, e.g.:
#     docker run ... linux-on-esp32s3 -c devkit-c1-8m.conf
ENTRYPOINT ["./rebuild-esp32s3-linux-wifi.sh"]
CMD ["-c", "devkit-c1-16m.conf"]
