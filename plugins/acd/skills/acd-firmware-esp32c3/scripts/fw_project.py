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

from fw_graph import (
    FirmwareCapabilityPlan,
    FirmwareExtractionError,
    FirmwareLane,
    FirmwareSettings,
    validate_boot_log_message,
)

_SEPARATOR_PATTERN = re.compile(r"[^a-z0-9]+")
_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_CAPABILITY_PROVIDERS = frozenset(
    {"firmware_init", "led_blink", "i2c_sensor_init", "i2c_sensor_read", "serial_log"}
)
_DEVICE_PROVIDERS = frozenset({"sht40"})


class FirmwareProjectionError(ValueError):
    """Raised when the firmware project cannot be projected (fail-closed)."""


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
    lane: FirmwareLane,
    target_revision: str,
    settings: FirmwareSettings,
    plan: FirmwareCapabilityPlan,
) -> str:
    lines = [
        "/* Generated from the design graph. Do not edit: the graph is canonical. */",
        "#pragma once",
        "",
        f'#define ACD_TARGET_REVISION "{target_revision}"',
        "",
    ]
    ordered = sorted(
        lane.pins,
        key=lambda pin: (
            plan.pin_role_order.index(pin.role)
            if pin.role in plan.pin_role_order
            else len(plan.pin_role_order),
            pin.net_id,
        ),
    )
    lines.extend(f"#define {_macro_name(pin.net_id)} {pin.gpio}" for pin in ordered)
    devices = {
        (step.device.driver_id, step.device.i2c_address): step.device
        for step in plan.steps
        if step.device is not None
    }
    if devices:
        lines.append("")
        for (_, _), device in sorted(devices.items()):
            lines.append(
                f"#define ACD_{device.driver_id.upper()}_I2C_ADDRESS "
                f"0x{device.i2c_address:02x}"
            )
    capability_ids = {step.capability_id for step in plan.steps}
    if "led_blink" in capability_ids:
        lines.append(f"#define ACD_LED_BLINK_PERIOD_MS {settings.led_blink_period_ms}")
    if "i2c_sensor_read" in capability_ids:
        lines.append(f"#define ACD_LOG_PERIOD_MS {settings.log_period_ms}")
    lines.append("")
    return "\n".join(lines)


def _render_main_source(
    lane: FirmwareLane,
    settings: FirmwareSettings,
    plan: FirmwareCapabilityPlan,
    graph_id: str,
) -> str:
    capability_ids = {step.capability_id for step in plan.steps}
    unsupported = capability_ids - _CAPABILITY_PROVIDERS
    if unsupported:
        raise FirmwareProjectionError(
            "no fragment provider for capabilities: " + ", ".join(sorted(unsupported))
        )
    if "i2c_sensor_read" in capability_ids and "i2c_sensor_init" not in capability_ids:
        raise FirmwareProjectionError(
            "no fragment provider for i2c sensor read without initialization"
        )
    for step in plan.steps:
        if (
            step.capability_id in {"i2c_sensor_init", "i2c_sensor_read"}
            and step.device is not None
            and step.device.driver_id not in _DEVICE_PROVIDERS
        ):
            raise FirmwareProjectionError(
                f"no fragment provider for device driver {step.device.driver_id!r}"
            )
    includes = {"<stdio.h>", '"acd_pins.h"', '"esp_log.h"'}
    if "led_blink" in capability_ids:
        includes.add('"driver/gpio.h"')
    if {"i2c_sensor_init", "i2c_sensor_read"} & capability_ids:
        includes.add('"driver/i2c_master.h"')
    if capability_ids & {"led_blink", "i2c_sensor_init", "i2c_sensor_read"}:
        includes.update({'"freertos/FreeRTOS.h"', '"freertos/task.h"'})
    include_order = {
        "<stdio.h>": 0,
        '"acd_pins.h"': 1,
        '"driver/gpio.h"': 2,
        '"driver/i2c_master.h"': 3,
        '"esp_log.h"': 4,
        '"freertos/FreeRTOS.h"': 5,
        '"freertos/task.h"': 6,
    }
    include_lines = [f"#include {item}" for item in sorted(includes, key=include_order.__getitem__)]
    statics = ['static const char *TAG = "__ACD_LOG_TAG__";']
    init_devices = [
        step.device
        for step in plan.steps
        if step.capability_id == "i2c_sensor_init" and step.device is not None
    ]
    if "i2c_sensor_init" in capability_ids:
        if not init_devices:
            raise FirmwareProjectionError(
                "i2c sensor initialization has no resolved device"
            )
        statics.append(f"static i2c_master_dev_handle_t s_{init_devices[0].driver_id};")
    helpers: list[str] = []
    if "i2c_sensor_read" in capability_ids:
        device = next(
            step.device
            for step in plan.steps
            if step.capability_id == "i2c_sensor_read" and step.device is not None
        )
        device_handle = f"s_{init_devices[0].driver_id}"
        helpers.append(
            f"""static void {device.driver_id}_log_once(void)
{{
    const uint8_t measure_cmd = 0x{device.measurement_command:02X};
    uint8_t raw[6] = {{0}};
    esp_err_t err = i2c_master_transmit({device_handle}, &measure_cmd, 1, 100);
    if (err == ESP_OK) {{
        vTaskDelay(pdMS_TO_TICKS(10));
        err = i2c_master_receive({device_handle}, raw, sizeof(raw), 100);
    }}
    if (err != ESP_OK) {{
        ESP_LOGW(TAG, "{device.driver_id.upper()} read failed: %s", esp_err_to_name(err));
        return;
    }}
    int t_ticks = (raw[0] << 8) | raw[1];
    int rh_ticks = (raw[3] << 8) | raw[4];
    float temp_c = -45.0f + 175.0f * (float)t_ticks / 65535.0f;
    float rh = -6.0f + 125.0f * (float)rh_ticks / 65535.0f;
    ESP_LOGI(TAG, "{device.driver_id.upper()} temp_c=%.2f rh=%.2f", (double)temp_c, (double)rh);
}}"""
        )
    pins_by_role = {pin.role: pin for pin in lane.pins}
    log_pins = [
        pins_by_role[role]
        for role in plan.required_pin_roles
        if role in pins_by_role
    ]
    pin_log = " ".join(f"{pin.role}=%d" for pin in log_pins)
    pin_args = ", ".join(f"ACD_PIN_{pin.role.upper()}" for pin in log_pins)
    initialization: list[str] = []
    for step in plan.steps:
        if step.capability_id == "firmware_init":
            initialization.append(
                f'    ESP_LOGI(TAG, "{settings.boot_log_message}", ACD_TARGET_REVISION);'
            )
            if log_pins:
                initialization.append(f'    ESP_LOGI(TAG, "pins {pin_log}", {pin_args});')
        elif step.capability_id == "led_blink":
            initialization.extend(
                [
                    "    gpio_config_t led_cfg = {",
                    "        .pin_bit_mask = 1ULL << ACD_PIN_LED,",
                    "        .mode = GPIO_MODE_OUTPUT,",
                    "    };",
                    "    ESP_ERROR_CHECK(gpio_config(&led_cfg));",
                ]
            )
        elif step.capability_id == "i2c_sensor_init":
            device = step.device
            if device is None:
                raise FirmwareProjectionError(
                    "i2c sensor initialization has no resolved device"
                )
            initialization.extend(
                [
                    "    i2c_master_bus_config_t bus_cfg = {",
                    "        .i2c_port = -1,",
                    "        .sda_io_num = ACD_PIN_I2C_SDA,",
                    "        .scl_io_num = ACD_PIN_I2C_SCL,",
                    "        .clk_source = I2C_CLK_SRC_DEFAULT,",
                    "        .glitch_ignore_cnt = 7,",
                    "        .flags = {.enable_internal_pullup = false},",
                    "    };",
                    "    i2c_master_bus_handle_t bus;",
                    "    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus));",
                    "    i2c_device_config_t dev_cfg = {",
                    "        .dev_addr_length = I2C_ADDR_BIT_LEN_7,",
                    f"        .device_address = ACD_{device.driver_id.upper()}_I2C_ADDRESS,",
                    "        .scl_speed_hz = 100000,",
                    "    };",
                    "    ESP_ERROR_CHECK(i2c_master_bus_add_device("
                    f"bus, &dev_cfg, &s_{device.driver_id}));",
                ]
            )
    loop: list[str] = []
    if "led_blink" in capability_ids:
        loop.extend(
            [
                "    int led_state = 0;",
                *(
                    ["    int since_log_ms = ACD_LOG_PERIOD_MS;"]
                    if "i2c_sensor_read" in capability_ids
                    else []
                ),
                "    for (;;) {",
                "        led_state = !led_state;",
                "        gpio_set_level(ACD_PIN_LED, led_state);",
                '        ESP_LOGI(TAG, "LED gpio=%d state=%d", ACD_PIN_LED, led_state);',
            ]
        )
        if "i2c_sensor_read" in capability_ids:
            device = next(
                step.device
                for step in plan.steps
                if step.capability_id == "i2c_sensor_read"
                and step.device is not None
            )
            loop.extend(
                [
                    "        if (since_log_ms >= ACD_LOG_PERIOD_MS) {",
                    f"            {device.driver_id}_log_once();",
                    "            since_log_ms = 0;",
                    "        }",
                ]
            )
        loop.extend(
            [
                "        vTaskDelay(pdMS_TO_TICKS(ACD_LED_BLINK_PERIOD_MS / 2));",
            ]
        )
        if "i2c_sensor_read" in capability_ids:
            loop.append("        since_log_ms += ACD_LED_BLINK_PERIOD_MS / 2;")
        loop.append("    }")
    elif "i2c_sensor_read" in capability_ids:
        device = next(
            step.device
            for step in plan.steps
            if step.capability_id == "i2c_sensor_read"
            and step.device is not None
        )
        loop = [
            "    for (;;) {",
            f"        {device.driver_id}_log_once();",
            "        vTaskDelay(pdMS_TO_TICKS(ACD_LOG_PERIOD_MS));",
            "    }",
        ]
    app_body = ["void app_main(void)", "{"]
    app_body.extend(initialization)
    if initialization and loop:
        app_body.append("")
    app_body.extend(loop)
    app_body.append("}")
    section_blocks = [
        "\n".join(
            [
                f"/* Firmware projection for {graph_id}; capabilities are graph declarations. */",
                *include_lines,
            ]
        ),
        "\n".join(statics),
        "\n\n".join(helpers),
        "\n".join(app_body),
    ]
    return (
        "\n\n".join(block for block in section_blocks if block)
        .replace("__ACD_LOG_TAG__", log_tag(graph_id))
        + "\n"
    )


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
    *,
    plan: FirmwareCapabilityPlan,
) -> FirmwareProject:
    if settings is None:
        settings = FirmwareSettings(
            boot_log_message=f"ACD {graph_id} fw boot target_revision=%s"
        )
    try:
        validate_boot_log_message(settings.boot_log_message)
    except FirmwareExtractionError as exc:
        raise FirmwareProjectionError(str(exc)) from exc
    name = firmware_project_name(graph_id)
    root = out_dir.resolve() / name
    main_dir = root / "main"
    main_dir.mkdir(parents=True, exist_ok=True)

    (root / "CMakeLists.txt").write_text(_ROOT_CMAKE.format(name=name))
    (root / "sdkconfig.defaults").write_text(_SDKCONFIG_DEFAULTS)
    (main_dir / "CMakeLists.txt").write_text(_MAIN_CMAKE)
    pins_header = main_dir / "acd_pins.h"
    pins_header.write_text(render_pins_header(lane, target_revision, settings, plan))
    main_source = main_dir / "acd_main.c"
    source = _render_main_source(lane, settings, plan, graph_id)
    main_source.write_text(source)
    return FirmwareProject(
        name=name, root=root, pins_header=pins_header, main_source=main_source
    )
