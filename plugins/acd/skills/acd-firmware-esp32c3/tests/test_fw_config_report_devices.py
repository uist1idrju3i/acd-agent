"""Firmware config report provenance lists each device once."""

from __future__ import annotations

from fw_graph import FirmwareCapabilityStep, FirmwareDeviceView
from run_fw_pipeline import unique_report_devices

SHT40 = FirmwareDeviceView(
    mpn="SHT40-AD1B-R3", driver_id="sht40", i2c_address=0x44, measurement_command=0xFD
)
BME280 = FirmwareDeviceView(
    mpn="BME280", driver_id="bme280", i2c_address=0x76, measurement_command=0xF7
)


def test_device_shared_by_init_and_read_steps_is_listed_once() -> None:
    steps = (
        FirmwareCapabilityStep("firmware_init", "initialize_firmware", 1),
        FirmwareCapabilityStep("i2c_sensor_init", "initialize_sht40", 2, SHT40),
        FirmwareCapabilityStep("i2c_sensor_read", "read_temperature_humidity", 3, SHT40),
    )

    assert unique_report_devices(steps) == [
        {"mpn": "SHT40-AD1B-R3", "driver_id": "sht40", "i2c_address": 0x44}
    ]


def test_distinct_devices_are_sorted_by_driver_id() -> None:
    steps = (
        FirmwareCapabilityStep("i2c_sensor_init", "initialize_sht40", 1, SHT40),
        FirmwareCapabilityStep("i2c_sensor_init", "initialize_bme280", 2, BME280),
    )

    assert [device["driver_id"] for device in unique_report_devices(steps)] == ["bme280", "sht40"]
