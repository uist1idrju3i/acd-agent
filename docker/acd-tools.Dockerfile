FROM ubuntu:26.04

ARG FREEROUTING_VERSION=2.3.0
ARG FREEROUTING_SHA256=3cf18d608437740bc497db6b8ef5888e2e60a08de0def20691d1bad0c0e0ee24
ARG UV_VERSION=0.12.5
ARG UV_SHA256=68a509da24b06b4223a1c0175fb5eb5bc79342b76cbeff0cfe51ac3f5b17b6b2
ARG QEMU_ESP_TAG=esp-develop-9.2.2-20260417
ARG QEMU_ESP_ARCHIVE=qemu-riscv32-softmmu-esp_develop_9.2.2_20260417-x86_64-linux-gnu.tar.xz
ARG QEMU_ESP_SHA256=547f03e04701a92cbb699f7f7d015adc1f5b5ef93cbb94c0dd9b7107e2d84e77
ARG ESP_IDF_VERSION=v6.0.2
ARG ESP_IDF_PYTHON_VERSION=3.12

ENV DEBIAN_FRONTEND=noninteractive
ENV UV_SYSTEM_PYTHON=1
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python
ENV ACD_HOME=/opt/acd
ENV IDF_PATH=/opt/esp-idf
ENV IDF_TOOLS_PATH=/opt/esp-idf-tools
ENV IDF_PYTHON_ENV_PATH=/opt/esp-idf-tools/python_env/acd_idf_env
ENV CCACHE_DIR=/opt/ccache
ENV IDF_CCACHE_ENABLE=1
# Keep runtime bytecode caches out of the bundled source tree: writes inside
# ${ACD_HOME}/src invalidate the editable install and make uv rebuild the
# package, which would require network access at run time.
ENV PYTHONPYCACHEPREFIX=/tmp/acd-pycache

COPY docker/freerouting /usr/local/bin/freerouting

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates \
        curl \
        git \
        software-properties-common \
        openjdk-26-jre-headless \
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
        libcairo2 \
        fonts-dejavu-core \
        fonts-noto-cjk \
        ccache \
        xz-utils \
        libslirp0 \
        libsdl2-2.0-0 \
        libusb-1.0-0 \
    && kicad-cli --version | grep -E '^10\.' \
    && ldconfig -p | grep -q 'libcairo\.so\.2' \
    && ldconfig -p | grep -q 'libslirp\.so\.0' \
    && ldconfig -p | grep -q 'libSDL2-2\.0\.so\.0' \
    && ldconfig -p | grep -q 'libusb-1\.0\.so\.0' \
    && fc-list | grep -qi 'Noto Sans CJK' \
    && ccache --version \
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
    && rm -rf /var/lib/apt/lists/*

# Espressif QEMU for the firmware lane virtual run (pinned release archive).
RUN curl --fail --location --silent --show-error \
        --output /tmp/qemu-esp.tar.xz \
        "https://github.com/espressif/qemu/releases/download/${QEMU_ESP_TAG}/${QEMU_ESP_ARCHIVE}" \
    && echo "${QEMU_ESP_SHA256}  /tmp/qemu-esp.tar.xz" | sha256sum --check \
    && mkdir -p /opt/qemu-esp \
    && tar -xJf /tmp/qemu-esp.tar.xz -C /opt/qemu-esp --strip-components=1 \
    && rm -f /tmp/qemu-esp.tar.xz \
    && ln -s /opt/qemu-esp/bin/qemu-system-riscv32 /usr/local/bin/qemu-system-riscv32 \
    && qemu-system-riscv32 --version | grep -E 'QEMU emulator version 9\.2\.2'

# ESP-IDF toolchain for the esp32c3 target. The ESP-IDF Python environment uses a
# pinned interpreter provisioned by uv so it stays independent from the system
# Python used by ACD itself.
RUN git clone --depth 1 --branch "${ESP_IDF_VERSION}" --recursive \
        https://github.com/espressif/esp-idf.git "${IDF_PATH}" \
    && uv python install "${ESP_IDF_PYTHON_VERSION}" \
    && IDF_PYTHON="$(uv python find "${ESP_IDF_PYTHON_VERSION}")" \
    && "${IDF_PYTHON}" "${IDF_PATH}/tools/idf_tools.py" install --targets=esp32c3 \
    && mkdir -p "${IDF_PYTHON_ENV_PATH}" \
    && "${IDF_PYTHON}" "${IDF_PATH}/tools/idf_tools.py" install-python-env \
    && test -x "${IDF_PYTHON_ENV_PATH}/bin/python" \
    && bash -c '. "${IDF_PATH}/export.sh" >/dev/null 2>&1 && idf.py --version' \
        | grep -E "^ESP-IDF v6\.0\.2" \
    && rm -rf "${IDF_TOOLS_PATH}/dist" /root/.cache/pip

# ACD source, pipeline scripts and fixtures, so that authoritative runs need no
# repository clone inside the container.
COPY pyproject.toml uv.lock README.md AGENTS.md LICENSE ${ACD_HOME}/
COPY src ${ACD_HOME}/src
COPY scripts ${ACD_HOME}/scripts
COPY fixtures ${ACD_HOME}/fixtures
COPY profiles ${ACD_HOME}/profiles
COPY assets ${ACD_HOME}/assets
COPY evidence ${ACD_HOME}/evidence
COPY plugins ${ACD_HOME}/plugins
COPY docker/image-digests.json ${ACD_HOME}/docker/image-digests.json
COPY vendor/software-agent-sdk ${ACD_HOME}/vendor/software-agent-sdk

# Prebaked Python environment: the locked dependency set is resolved at build
# time so container runs neither resolve nor download dependencies.
RUN cd "${ACD_HOME}" \
    && uv sync --frozen --compile-bytecode \
    && uv run --frozen python -c "import acd, build123d, cairosvg; print(acd.__name__)" \
    && uv run --frozen python scripts/print_locked_image.py --entry acd-tools >/dev/null \
    && apt-get purge -y --auto-remove software-properties-common

# Warm the shared PEP 723 environment and prove that the pinned Skill path is
# reusable without network access. A metadata check verifies that every
# acd-importing script uses the same block.
RUN cd "${ACD_HOME}" \
    && python3.14 scripts/verify_skill_package_ref.py --metadata-only \
    && uv run --script scripts/probe_pinned_acd_graph.py --fixture fixtures/golden-design-1 \
    && uv run --offline --script scripts/probe_pinned_acd_graph.py \
        --fixture fixtures/golden-design-1

ENV PATH="/usr/local/bin:${PATH}"
ENV UV_FROZEN=1
WORKDIR /workspace
