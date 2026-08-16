"""Deterministic ESP-IDF firmware project projection.

The design graph is the only source of pin assignments: they are projected
into a generated header (``acd_pins.h``) that the static application code
consumes. Generated files contain no timestamps so byte-identical reruns
yield identical hashes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fw_graph import FirmwareLane

FW_PROJECT_NAME = "acd_gd1_fw"

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


@dataclass(frozen=True)
class FirmwareProject:
    root: Path
    pins_header: Path
    main_source: Path


def _macro_name(net_id: str) -> str:
    return "ACD_PIN_" + net_id.removeprefix("net.").upper()


def render_pins_header(lane: FirmwareLane, target_revision: str) -> str:
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
        f"#define ACD_LED_BLINK_PERIOD_MS {LED_BLINK_PERIOD_MS}",
        f"#define ACD_LOG_PERIOD_MS {LOG_PERIOD_MS}",
        "",
    ]
    return "\n".join(lines)


_MAIN_C = """\
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

static const char *TAG = "acd_gd1";

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
    ESP_LOGI(TAG, "ACD GD1 fw boot target_revision=%s", ACD_TARGET_REVISION);
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
    lane: FirmwareLane, target_revision: str, out_dir: Path
) -> FirmwareProject:
    root = out_dir.resolve() / FW_PROJECT_NAME
    main_dir = root / "main"
    main_dir.mkdir(parents=True, exist_ok=True)

    (root / "CMakeLists.txt").write_text(_ROOT_CMAKE.format(name=FW_PROJECT_NAME))
    (root / "sdkconfig.defaults").write_text(_SDKCONFIG_DEFAULTS)
    (main_dir / "CMakeLists.txt").write_text(_MAIN_CMAKE)
    pins_header = main_dir / "acd_pins.h"
    pins_header.write_text(render_pins_header(lane, target_revision))
    main_source = main_dir / "acd_main.c"
    main_source.write_text(_MAIN_C)
    return FirmwareProject(root=root, pins_header=pins_header, main_source=main_source)
