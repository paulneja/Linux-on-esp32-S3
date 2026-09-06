
FROM debian:12

RUN apt-get update && apt-get install -y --no-install-recommends \
    autoconf automake bash bc bison build-essential bzip2 cmake cpio file \
    flex gawk git gperf help2man libncurses-dev libtool libtool-bin \
    libusb-1.0-0 python3 python3-venv rsync texinfo unzip wget \
    ca-certificates patch \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work

COPY patches       /work/local-changes/patches
COPY new-files     /work/local-changes/new-files

RUN git clone https://github.com/jcmvbkbc/esp32-linux-build /work/esp32-linux-build \
    && cd /work/esp32-linux-build \
    && patch -p1 < /work/local-changes/patches/00-esp32-linux-build.patch

RUN cp /work/local-changes/new-files/toplevel/apply-local-changes.sh \
       /work/local-changes/new-files/toplevel/devkit-c1-16m.conf \
       /work/esp32-linux-build/ \
    && ln -s /work/local-changes /work/esp32-linux-build/local-changes

WORKDIR /work/esp32-linux-build

RUN useradd -m builder && chown -R builder:builder /work
USER builder

ENTRYPOINT ["./rebuild-esp32s3-linux-wifi.sh"]
CMD ["-c", "devkit-c1-16m.conf"]
