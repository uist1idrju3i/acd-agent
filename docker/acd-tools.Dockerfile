FROM ubuntu:26.04

ARG FREEROUTING_VERSION=2.3.0
ARG FREEROUTING_SHA256=3cf18d608437740bc497db6b8ef5888e2e60a08de0def20691d1bad0c0e0ee24
ARG UV_VERSION=0.12.3
ARG UV_SHA256=600cf9a742aca00d292673b16b5acffaa7b8c269a364ad0c2e79498dcb1fe101

ENV DEBIAN_FRONTEND=noninteractive
ENV UV_SYSTEM_PYTHON=1

COPY docker/freerouting /usr/local/bin/freerouting

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates \
        curl \
        git \
        software-properties-common \
        openjdk-25-jre-headless \
        ngspice \
        python3.14 \
        python3.14-venv \
    && add-apt-repository ppa:kicad/kicad-10.0-releases \
    && apt-get update \
    && apt-get install --no-install-recommends -y \
        kicad \
        kicad-footprints \
        kicad-libraries \
        kicad-symbols \
    && kicad-cli --version | grep -E '^10\.' \
    && curl --fail --location --silent --show-error \
        --output /opt/freerouting.jar \
        "https://github.com/freerouting/freerouting/releases/download/v${FREEROUTING_VERSION}/freerouting-${FREEROUTING_VERSION}.jar" \
    && echo "${FREEROUTING_SHA256}  /opt/freerouting.jar" | sha256sum --check \
    && chmod 0755 /usr/local/bin/freerouting \
    && freerouting --version 2>&1 || test $? -eq 1 \
    && ngspice --version \
    && git --version \
    && python3.14 --version | grep -E '^Python 3\.14\.' \
    && curl --fail --location --silent --show-error \
        --output /tmp/uv.tar.gz \
        "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz" \
    && echo "${UV_SHA256}  /tmp/uv.tar.gz" | sha256sum --check \
    && tar -xzf /tmp/uv.tar.gz -C /tmp \
    && install -m 0755 "/tmp/uv-x86_64-unknown-linux-gnu/uv" /usr/local/bin/uv \
    && rm -rf /tmp/uv.tar.gz /tmp/uv-x86_64-unknown-linux-gnu \
    && apt-get purge -y --auto-remove curl software-properties-common \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/usr/local/bin:${PATH}"
WORKDIR /workspace
