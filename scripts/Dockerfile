FROM ubuntu:22.04
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        python3-tk \
        libpython3.10 \
        binutils \
        fonts-cantarell \
        xvfb \
        xauth \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/build \
    && /opt/build/bin/pip install --no-cache-dir pyinstaller==6.22.3
WORKDIR /work
ENTRYPOINT ["/opt/build/bin/python"]
