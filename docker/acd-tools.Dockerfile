FROM ubuntu:24.04

ARG FREEROUTING_VERSION=2.1.0
ARG FREEROUTING_SHA256=2c07d58f75dac03782664081e7a58b41c25400d871a9fcf166a2ea6fe60d5def
ARG UV_VERSION=0.7.12

ENV DEBIAN_FRONTEND=noninteractive
ENV UV_SYSTEM_PYTHON=1

COPY docker/freerouting /usr/local/bin/freerouting

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates \
        curl \
        git \
        software-properties-common \
        openjdk-21-jre-headless \
        ngspice \
        python3.12 \
        python3.12-venv \
    && add-apt-repository ppa:kicad/kicad-9.0-releases \
    && apt-get update \
    && apt-get install --no-install-recommends -y kicad \
    && kicad-cli --version | grep -E '^9\.' \
    && curl --fail --location --silent --show-error \
        --output /opt/freerouting.jar \
        "https://github.com/freerouting/freerouting/releases/download/v${FREEROUTING_VERSION}/freerouting-${FREEROUTING_VERSION}.jar" \
    && echo "${FREEROUTING_SHA256}  /opt/freerouting.jar" | sha256sum --check \
    && chmod 0755 /usr/local/bin/freerouting \
    && freerouting --version 2>&1 || test $? -eq 1 \
    && ngspice --version \
    && git --version \
    && curl --fail --location --silent --show-error \
        --output /tmp/uv.tar.gz \
        "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz" \
    && tar -xzf /tmp/uv.tar.gz -C /tmp \
    && install -m 0755 "/tmp/uv-x86_64-unknown-linux-gnu/uv" /usr/local/bin/uv \
    && rm -rf /tmp/uv.tar.gz /tmp/uv-x86_64-unknown-linux-gnu \
    && apt-get purge -y --auto-remove curl software-properties-common \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/usr/local/bin:${PATH}"
WORKDIR /workspace
