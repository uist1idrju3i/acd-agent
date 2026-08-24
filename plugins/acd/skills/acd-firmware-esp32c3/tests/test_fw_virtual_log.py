"""Virtual serial-log check tests: required behaviour or failure."""

from __future__ import annotations

import pytest

from fw_qemu import VirtualRunCheckError, assert_virtual_log_ok

GOOD_LOG = """\
I (100) acd_gd1: ACD GD1 fw boot target_revision=r1
I (110) acd_gd1: pins led=7 sda=4 scl=5
I (120) acd_gd1: LED gpio=7 state=1
W (130) acd_gd1: SHT40 read failed: ESP_ERR_TIMEOUT
I (620) acd_gd1: LED gpio=7 state=0
I (1120) acd_gd1: LED gpio=7 state=1
"""


def test_good_virtual_log_passes() -> None:
    assert_virtual_log_ok(
        GOOD_LOG,
        target_revision="r1",
        led_gpio=7,
        boot_log_message="ACD GD1 fw boot target_revision=%s",
    )


def test_missing_boot_line_fails() -> None:
    log = GOOD_LOG.replace("ACD GD1 fw boot", "boot")
    with pytest.raises(VirtualRunCheckError, match="boot line"):
        assert_virtual_log_ok(
            log,
            target_revision="r1",
            led_gpio=7,
            boot_log_message="ACD GD1 fw boot target_revision=%s",
        )


def test_revision_mismatch_fails() -> None:
    with pytest.raises(VirtualRunCheckError, match="boot line"):
        assert_virtual_log_ok(
            GOOD_LOG,
            target_revision="r2",
            led_gpio=7,
            boot_log_message="ACD GD1 fw boot target_revision=%s",
        )


def test_wrong_led_gpio_fails() -> None:
    with pytest.raises(VirtualRunCheckError, match="LED"):
        assert_virtual_log_ok(
            GOOD_LOG,
            target_revision="r1",
            led_gpio=6,
            boot_log_message="ACD GD1 fw boot target_revision=%s",
        )


def test_led_stuck_in_one_state_fails() -> None:
    log = GOOD_LOG.replace("state=0", "state=1")
    with pytest.raises(VirtualRunCheckError, match="LED"):
        assert_virtual_log_ok(
            log,
            target_revision="r1",
            led_gpio=7,
            boot_log_message="ACD GD1 fw boot target_revision=%s",
        )


def test_missing_sensor_attempt_fails() -> None:
    log = GOOD_LOG.replace("SHT40", "sensor")
    with pytest.raises(VirtualRunCheckError, match="SHT40"):
        assert_virtual_log_ok(
            log,
            target_revision="r1",
            led_gpio=7,
            boot_log_message="ACD GD1 fw boot target_revision=%s",
        )
