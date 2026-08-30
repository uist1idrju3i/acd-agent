"""Virtual serial-log check tests: required behaviour or failure."""

from __future__ import annotations

import pytest

from fw_graph import (
    FirmwareCapabilityPlan,
    FirmwareCapabilityStep,
    FirmwareDeviceView,
    FirmwareLane,
    FirmwarePinView,
)
from fw_qemu import VirtualRunCheckError, assert_virtual_log_ok

GOOD_LOG = """\
I (100) acd_gd1: ACD GD1 fw boot target_revision=r1
I (110) acd_gd1: pins led=7 sda=4 scl=5
I (120) acd_gd1: LED gpio=7 state=1
W (130) acd_gd1: SHT40 read failed: ESP_ERR_TIMEOUT
I (620) acd_gd1: LED gpio=7 state=0
I (1120) acd_gd1: LED gpio=7 state=1
"""

GD1_LANE = FirmwareLane(
    pins=(
        FirmwarePinView("led", 7, "net.led"),
        FirmwarePinView("sda", 4, "net.i2c_sda"),
        FirmwarePinView("scl", 5, "net.i2c_scl"),
    )
)
GD1_DEVICE = FirmwareDeviceView("SHT40-AD1B-R3", "sht40", 68, 253)
GD1_PLAN = FirmwareCapabilityPlan(
    steps=(
        FirmwareCapabilityStep("firmware_init", "initialize_firmware", 1),
        FirmwareCapabilityStep("i2c_sensor_init", "initialize_sht40", 2, GD1_DEVICE),
        FirmwareCapabilityStep("led_blink", "toggle_led", 3),
        FirmwareCapabilityStep("i2c_sensor_read", "read_temperature_humidity", 4, GD1_DEVICE),
    ),
    pin_role_order=("led", "i2c_sda", "i2c_scl"),
    registry_hash="sha256:" + "0" * 64,
    registry_path="registry.json",
)


def test_good_virtual_log_passes() -> None:
    assert_virtual_log_ok(
        GOOD_LOG,
        target_revision="r1",
        boot_log_message="ACD GD1 fw boot target_revision=%s",
        lane=GD1_LANE,
        plan=GD1_PLAN,
    )


def test_missing_boot_line_fails() -> None:
    log = GOOD_LOG.replace("ACD GD1 fw boot", "boot")
    with pytest.raises(VirtualRunCheckError, match="boot line"):
        assert_virtual_log_ok(
            log,
            target_revision="r1",
            boot_log_message="ACD GD1 fw boot target_revision=%s",
            lane=GD1_LANE,
            plan=GD1_PLAN,
        )


def test_revision_mismatch_fails() -> None:
    with pytest.raises(VirtualRunCheckError, match="boot line"):
        assert_virtual_log_ok(
            GOOD_LOG,
            target_revision="r2",
            boot_log_message="ACD GD1 fw boot target_revision=%s",
            lane=GD1_LANE,
            plan=GD1_PLAN,
        )


def test_wrong_led_gpio_fails() -> None:
    with pytest.raises(VirtualRunCheckError, match="LED"):
        assert_virtual_log_ok(
            GOOD_LOG,
            target_revision="r1",
            boot_log_message="ACD GD1 fw boot target_revision=%s",
            lane=FirmwareLane(pins=(FirmwarePinView("led", 6, "net.led"),)),
            plan=GD1_PLAN,
        )


def test_led_stuck_in_one_state_fails() -> None:
    log = GOOD_LOG.replace("state=0", "state=1")
    with pytest.raises(VirtualRunCheckError, match="LED"):
        assert_virtual_log_ok(
            log,
            target_revision="r1",
            boot_log_message="ACD GD1 fw boot target_revision=%s",
            lane=GD1_LANE,
            plan=GD1_PLAN,
        )


def test_missing_sensor_attempt_fails() -> None:
    log = GOOD_LOG.replace("SHT40", "sensor")
    with pytest.raises(VirtualRunCheckError, match="SHT40"):
        assert_virtual_log_ok(
            log,
            target_revision="r1",
            boot_log_message="ACD GD1 fw boot target_revision=%s",
            lane=GD1_LANE,
            plan=GD1_PLAN,
        )
