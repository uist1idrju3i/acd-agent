"""Deterministic ESP-IDF firmware project projection.

The design graph is the only source of pin assignments: they are projected
into a generated header (``acd_pins.h``) that the static application code
consumes. Generated files contain no timestamps so byte-identical reruns
yield identical hashes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from fw_graph import FirmwareLane, FirmwareSettings

_SEPARATOR_PATTERN = re.compile(r"[^a-z0-9]+")
_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

# Net roles the Golden Design #1 firmware needs, keyed by graph net node id.
_REQUIRED_NETS = (
    "net.led",
    "net.i2c_sda",
    "net.i2c_scl",
    "net.uart_tx",
    "net.uart_rx",
    "net.boot",
    "net.usb_dn",
    "net.usb_dp",
)

SHT40_I2C_ADDRESS = 0x44
LED_BLINK_PERIOD_MS = 1000
LOG_PERIOD_MS = 2000


class FirmwareProjectionError(ValueError):
    """Raised when the firmware project cannot be projected (fail-closed)."""


def _validate_boot_log_message(value: object) -> str:
    if not isinstance(value, str):
        raise FirmwareProjectionError("boot_log_message must be a string")
    if (
        not value
        or value.count("%s") != 1
        or any(character in value for character in ('"', "\\", "\r", "\n"))
        or any(
            character == "%"
            and value[index : index + 2] != "%s"
            for index, character in enumerate(value)
        )
    ):
        raise FirmwareProjectionError(
            "boot_log_message must be a C string literal template with exactly "
            "one %s and no quotes, backslashes, newlines, or other percent directives"
        )
    return value


@dataclass(frozen=True)
class FirmwareProject:
    name: str
    root: Path
    pins_header: Path
    main_source: Path

    @property
    def app_binary(self) -> Path:
        return self.root / "build" / f"{self.name}.bin"


def firmware_project_name(graph_id: str) -> str:
    """Return the ESP-IDF project name derived from a design graph id."""
    return f"{log_tag(graph_id)}_fw"


def log_tag(graph_id: str) -> str:
    """Return the firmware log tag derived from a design graph id."""
    slug = _SEPARATOR_PATTERN.sub("_", graph_id.strip().lower()).strip("_")
    tag = f"acd_{slug}"
    if not slug or not _IDENTIFIER_PATTERN.fullmatch(tag):
        raise FirmwareProjectionError(
            f"graph_id does not yield a firmware project name: {graph_id!r}"
        )
    return tag


def _macro_name(net_id: str) -> str:
    return "ACD_PIN_" + net_id.removeprefix("net.").upper()


def render_pins_header(
    lane: FirmwareLane, target_revision: str, settings: FirmwareSettings
) -> str:
    lines = [
        "/* Generated from the design graph. Do not edit: the graph is canonical. */",
        "#pragma once",
        "",
        f'#define ACD_TARGET_REVISION "{target_revision}"',
        "",
    ]
    for net_id in _REQUIRED_NETS:
        try:
            gpio = lane.gpio_for_net(net_id)
        except Exception as exc:
            raise FirmwareProjectionError(str(exc)) from exc
        lines.append(f"#define {_macro_name(net_id)} {gpio}")
    lines += [
        "",
        f"#define ACD_SHT40_I2C_ADDRESS 0x{SHT40_I2C_ADDRESS:02x}",
        f"#define ACD_LED_BLINK_PERIOD_MS {settings.led_blink_period_ms}",
        f"#define ACD_LOG_PERIOD_MS {settings.log_period_ms}",
        "",
    ]
    return "\n".join(lines)


# The C template is written verbatim except for these named placeholders.
_LOG_TAG_PLACEHOLDER = "__ACD_LOG_TAG__"
_BOOT_LOG_MESSAGE_PLACEHOLDER = "__ACD_BOOT_LOG_MESSAGE__"

_main_c_prefix = """\
/* Golden Design #1 firmware: 1 Hz LED blink + SHT40 temperature/humidity log.
 * Pin assignments come exclusively from the generated acd_pins.h projection.
 */
#include <stdio.h>

#include "acd_pins.h"
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "__ACD_LOG_TAG__";

static i2c_master_dev_handle_t s_sht40;

static void sht40_log_once(void)
{
    const uint8_t measure_cmd = 0xFD; /* high-precision measurement */
    uint8_t raw[6] = {0};
    esp_err_t err = i2c_master_transmit(s_sht40, &measure_cmd, 1, 100);
    if (err == ESP_OK) {
        vTaskDelay(pdMS_TO_TICKS(10));
        err = i2c_master_receive(s_sht40, raw, sizeof(raw), 100);
    }
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "SHT40 read failed: %s", esp_err_to_name(err));
        return;
    }
    int t_ticks = (raw[0] << 8) | raw[1];
    int rh_ticks = (raw[3] << 8) | raw[4];
    float temp_c = -45.0f + 175.0f * (float)t_ticks / 65535.0f;
    float rh = -6.0f + 125.0f * (float)rh_ticks / 65535.0f;
    ESP_LOGI(TAG, "SHT40 temp_c=%.2f rh=%.2f", (double)temp_c, (double)rh);
}

void app_main(void)
{
"""
_main_c_boot = _main_c_prefix + (
    f'    ESP_LOGI(TAG, "{_BOOT_LOG_MESSAGE_PLACEHOLDER}", ACD_TARGET_REVISION);\n'
)
_main_c_suffix = """\
    ESP_LOGI(TAG, "pins led=%d sda=%d scl=%d", ACD_PIN_LED, ACD_PIN_I2C_SDA, ACD_PIN_I2C_SCL);

    gpio_config_t led_cfg = {
        .pin_bit_mask = 1ULL << ACD_PIN_LED,
        .mode = GPIO_MODE_OUTPUT,
    };
    ESP_ERROR_CHECK(gpio_config(&led_cfg));

    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = -1,
        .sda_io_num = ACD_PIN_I2C_SDA,
        .scl_io_num = ACD_PIN_I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags = {.enable_internal_pullup = false},
    };
    i2c_master_bus_handle_t bus;
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus));
    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = ACD_SHT40_I2C_ADDRESS,
        .scl_speed_hz = 100000,
    };
    ESP_ERROR_CHECK(i2c_master_bus_add_device(bus, &dev_cfg, &s_sht40));

    int led_state = 0;
    int since_log_ms = ACD_LOG_PERIOD_MS;
    for (;;) {
        led_state = !led_state;
        gpio_set_level(ACD_PIN_LED, led_state);
        ESP_LOGI(TAG, "LED gpio=%d state=%d", ACD_PIN_LED, led_state);
        if (since_log_ms >= ACD_LOG_PERIOD_MS) {
            sht40_log_once();
            since_log_ms = 0;
        }
        vTaskDelay(pdMS_TO_TICKS(ACD_LED_BLINK_PERIOD_MS / 2));
        since_log_ms += ACD_LED_BLINK_PERIOD_MS / 2;
    }
}
"""

_MAIN_C = _main_c_boot + _main_c_suffix

_ROOT_CMAKE = """\
cmake_minimum_required(VERSION 3.16)
include($ENV{{IDF_PATH}}/tools/cmake/project.cmake)
project({name})
"""

_MAIN_CMAKE = """\
idf_component_register(SRCS "acd_main.c" INCLUDE_DIRS ".")
"""

_SDKCONFIG_DEFAULTS = """\
CONFIG_IDF_TARGET="esp32c3"
CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y
"""


def write_firmware_project(
    lane: FirmwareLane,
    target_revision: str,
    out_dir: Path,
    graph_id: str,
    settings: FirmwareSettings | None = None,
) -> FirmwareProject:
    if settings is None:
        settings = FirmwareSettings(
            boot_log_message=f"ACD {graph_id} fw boot target_revision=%s"
        )
    _validate_boot_log_message(settings.boot_log_message)
    name = firmware_project_name(graph_id)
    root = out_dir.resolve() / name
    main_dir = root / "main"
    main_dir.mkdir(parents=True, exist_ok=True)

    (root / "CMakeLists.txt").write_text(_ROOT_CMAKE.format(name=name))
    (root / "sdkconfig.defaults").write_text(_SDKCONFIG_DEFAULTS)
    (main_dir / "CMakeLists.txt").write_text(_MAIN_CMAKE)
    pins_header = main_dir / "acd_pins.h"
    pins_header.write_text(render_pins_header(lane, target_revision, settings))
    main_source = main_dir / "acd_main.c"
    source = _MAIN_C.replace(_LOG_TAG_PLACEHOLDER, log_tag(graph_id))
    if _BOOT_LOG_MESSAGE_PLACEHOLDER not in source:
        raise FirmwareProjectionError(
            "firmware template is missing the boot log message placeholder"
        )
    source = source.replace(
        _BOOT_LOG_MESSAGE_PLACEHOLDER, settings.boot_log_message
    )
    if _BOOT_LOG_MESSAGE_PLACEHOLDER in source:
        raise FirmwareProjectionError(
            "firmware template boot log message placeholder was not replaced"
        )
    main_source.write_text(source)
    return FirmwareProject(
        name=name, root=root, pins_header=pins_header, main_source=main_source
    )
