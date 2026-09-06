FROM debian:12@sha256:9344f8b8992482f80cba753f323adeaf17690076c095ccff6cc9536be98185dc
RUN apt-get update && apt-get install -y --no-install-recommends \
    autoconf automake bash bc bison build-essential bzip2 ca-certificates \
    cmake cpio curl file flex gawk git gperf help2man libncurses-dev \
    libtool libtool-bin libusb-1.0-0 ninja-build patch pkg-config python3 \
    python3-serial python3-venv python3-yaml rsync texinfo unzip wget xxd \
    xz-utils zstd \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/flash-tools && /opt/flash-tools/bin/pip install --no-cache-dir esptool==4.8.1
ENV PATH="/opt/flash-tools/bin:$PATH"
ARG BUILDER_UID=1000
ARG BUILDER_GID=1000
RUN groupadd -g "$BUILDER_GID" builder && useradd -m -u "$BUILDER_UID" -g "$BUILDER_GID" builder
USER builder
WORKDIR /work/Linux-on-esp32-S3
ENTRYPOINT ["bash", "build/container-build.sh"]
