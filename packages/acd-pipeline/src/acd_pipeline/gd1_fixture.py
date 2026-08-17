"""Build the Golden Design #1 design-graph fixture.
Regenerates ``fixtures/golden-design-1/graph.json`` deterministically from the
specification in ``docs/golden-design-1.md``. Library references are pinned
with source, version/commit, and file sha256 so that unpinned references fail
closed downstream (ADR-0004).
"""

from __future__ import annotations

# ruff: noqa: E501,RUF100
import hashlib
import json
import sys
from pathlib import Path
from typing import NotRequired, TypedDict

from acd_schema.design_graph import AttrValue, DesignGraph, GraphNode

REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURE_DIR = REPO_ROOT / "fixtures" / "golden-design-1"
KICAD_SYMBOLS = Path("/usr/share/kicad/symbols")
KICAD_FOOTPRINTS = Path("/usr/share/kicad/footprints")

KICAD_PACKAGE_VERSION = "10.0.5"
KICAD_LIB_SOURCE = "kicad-official (ppa:kicad/kicad-10.0-releases)"
ESPRESSIF_SOURCE = "https://github.com/espressif/kicad-libraries"
ESPRESSIF_COMMIT = "dd76561812ab300351234ba6e0ec1295641796f0"

PLACEMENTS: dict[str, tuple[float, float, float]] = {
    "C1": (7.53, 20.28, 0.0),
    "C2": (7.53, 22.28, 0.0),
    "C3": (9.28, 14.78, 0.0),
    "C4": (7.28, 2.53, 90.0),
    "C5": (16.53, 14.78, 0.0),
    "C6": (23.03, 4.03, 90.0),
    "D1": (11.78, 12.78, 0.0),
    "H1": (3.0, 3.0, 0.0),
    "H2": (27.0, 3.0, 0.0),
    "H3": (3.0, 22.0, 0.0),
    "H4": (27.0, 22.0, 0.0),
    "J1": (15.0, 21.35, 0.0),
    "R1": (21.53, 21.28, 90.0),
    "R2": (27.53, 17.53, 90.0),
    "R3": (28.28, 13.53, 90.0),
    "R4": (13.28, 15.03, 0.0),
    "R5": (23.28, 19.78, 90.0),
    "R6": (8.78, 17.28, 90.0),
    "SW1": (24.05, 9.05, 90.0),
    "SW2": (4.55, 7.8, 0.0),
    "TP1": (19.8, 13.3, 0.0),
    "TP2": (22.8, 13.8, 0.0),
    "TP3": (22.05, 16.8, 0.0),
    "TP4": (25.8, 13.8, 0.0),
    "TP5": (27.55, 7.3, 0.0),
    "TP6": (27.55, 10.3, 0.0),
    "TP7": (25.05, 16.8, 0.0),
    "U1": (15.0, 2.9, 0.0),
    "U2": (4.15, 14.7, 90.0),
    "U3": (15.0, 13.05, 0.0),
}


def sha256_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class LibraryRef(TypedDict):
    symbol: str
    symbol_file: str
    symbol_source: str
    symbol_source_ref: str
    footprint: str
    footprint_file: str
    footprint_source: str
    footprint_source_ref: str


def kicad_lib(symbol: str, footprint: str) -> LibraryRef:
    sym_lib = symbol.split(":", 1)[0]
    fp_lib, fp_name = footprint.split(":", 1)
    return {
        "symbol": symbol,
        "symbol_file": str(KICAD_SYMBOLS / f"{sym_lib}.kicad_sym"),
        "symbol_source": KICAD_LIB_SOURCE,
        "symbol_source_ref": KICAD_PACKAGE_VERSION,
        "footprint": footprint,
        "footprint_file": str(KICAD_FOOTPRINTS / f"{fp_lib}.pretty" / f"{fp_name}.kicad_mod"),
        "footprint_source": KICAD_LIB_SOURCE,
        "footprint_source_ref": KICAD_PACKAGE_VERSION,
    }


def espressif_lib(symbol: str, footprint: str) -> LibraryRef:
    fp_name = footprint.split(":", 1)[1]
    return {
        "symbol": symbol,
        "symbol_file": "libraries/Espressif.kicad_sym",
        "symbol_source": ESPRESSIF_SOURCE,
        "symbol_source_ref": ESPRESSIF_COMMIT,
        "footprint": footprint,
        "footprint_file": f"libraries/Espressif.pretty/{fp_name}.kicad_mod",
        "footprint_source": ESPRESSIF_SOURCE,
        "footprint_source_ref": ESPRESSIF_COMMIT,
    }


class ComponentSpec(TypedDict):
    refdes: str
    value: str
    mpn: str
    lcsc: str
    jlcpcb_class: str
    assembly: str
    lib: LibraryRef
    # pad number -> net id (None means explicit no-connect)
    pads: dict[str, str | None]
    overlay_file: NotRequired[str]
    overlay_sha256: NotRequired[str]
    decoupling_target: NotRequired[str]


NETS: dict[str, dict[str, AttrValue]] = {
    "net.vbus_5v": {
        "name": "VBUS_5V",
        "voltage_nominal_v": 5.0,
        "current_max_a": 0.5,
        "width_basis": "current_ipc2221",
        "width_basis_source": "USB VBUS power net; IPC-2221 external-layer current capacity governs the routed conductor.",
    },  # noqa: E501
    "net.cc1": {
        "name": "CC1",
        "voltage_nominal_v": 5.0,
        "width_basis": "manufacturing_minimum",
        "manufacturing_margin_mm": 0.0,
        "width_basis_source": "USB-C logic configuration signal; current-derived capacity is not the controlling constraint.",
    },  # noqa: E501
    "net.cc2": {
        "name": "CC2",
        "voltage_nominal_v": 5.0,
        "width_basis": "manufacturing_minimum",
        "manufacturing_margin_mm": 0.0,
        "width_basis_source": "USB-C logic configuration signal; current-derived capacity is not the controlling constraint.",
    },  # noqa: E501
    "net.gnd": {
        "name": "GND",
        "voltage_nominal_v": 0.0,
        "width_basis": "current_ipc2221",
        "current_max_a": 0.5,
        "width_basis_source": "GND is a plane plus routed conductors; IPC-2221 external-layer current capacity governs each explicit routed conductor while the plane is independently measured as filled copper.",
    },  # noqa: E501
    "net.p3v3": {
        "name": "+3V3",
        "voltage_nominal_v": 3.3,
        "current_max_a": 0.5,
        "width_basis": "current_ipc2221",
        "width_basis_source": "Regulated 3.3 V power net; IPC-2221 external-layer current capacity governs the routed conductor.",
    },  # noqa: E501
    "net.usb_dn": {
        "name": "USB_D-",
        "voltage_nominal_v": 3.3,
        "width_basis": "manufacturing_minimum",
        "manufacturing_margin_mm": 0.0,
        "width_basis_source": "USB data logic signal; current-derived capacity is not the controlling constraint.",
    },  # noqa: E501
    "net.usb_dp": {
        "name": "USB_D+",
        "voltage_nominal_v": 3.3,
        "width_basis": "manufacturing_minimum",
        "manufacturing_margin_mm": 0.0,
        "width_basis_source": "USB data logic signal; current-derived capacity is not the controlling constraint.",
    },  # noqa: E501
    "net.en": {
        "name": "EN",
        "voltage_nominal_v": 3.3,
        "width_basis": "manufacturing_minimum",
        "manufacturing_margin_mm": 0.0,
        "width_basis_source": "Enable logic signal; current-derived capacity is not the controlling constraint.",
    },  # noqa: E501
    "net.boot": {
        "name": "BOOT",
        "voltage_nominal_v": 3.3,
        "width_basis": "manufacturing_minimum",
        "manufacturing_margin_mm": 0.0,
        "width_basis_source": "Boot logic signal; current-derived capacity is not the controlling constraint.",
    },  # noqa: E501
    "net.led": {
        "name": "LED",
        "voltage_nominal_v": 3.3,
        "width_basis": "manufacturing_minimum",
        "manufacturing_margin_mm": 0.0,
        "width_basis_source": "LED control logic signal; current-derived capacity is not the controlling constraint.",
    },  # noqa: E501
    "net.led_a": {
        "name": "LED_A",
        "voltage_nominal_v": 3.3,
        "width_basis": "manufacturing_minimum",
        "manufacturing_margin_mm": 0.0,
        "width_basis_source": "LED current is limited by the series resistor and manufacturing minimum governs this routed net.",
    },  # noqa: E501
    "net.i2c_sda": {
        "name": "I2C_SDA",
        "voltage_nominal_v": 3.3,
        "width_basis": "manufacturing_minimum",
        "manufacturing_margin_mm": 0.0,
        "width_basis_source": "I2C logic signal; current-derived capacity is not the controlling constraint.",
    },  # noqa: E501
    "net.i2c_scl": {
        "name": "I2C_SCL",
        "voltage_nominal_v": 3.3,
        "width_basis": "manufacturing_minimum",
        "manufacturing_margin_mm": 0.0,
        "width_basis_source": "I2C logic signal; current-derived capacity is not the controlling constraint.",
    },  # noqa: E501
    "net.uart_tx": {
        "name": "UART_TX",
        "voltage_nominal_v": 3.3,
        "width_basis": "manufacturing_minimum",
        "manufacturing_margin_mm": 0.0,
        "width_basis_source": "UART logic signal; current-derived capacity is not the controlling constraint.",
    },  # noqa: E501
    "net.uart_rx": {
        "name": "UART_RX",
        "voltage_nominal_v": 3.3,
        "width_basis": "manufacturing_minimum",
        "manufacturing_margin_mm": 0.0,
        "width_basis_source": "UART logic signal; current-derived capacity is not the controlling constraint.",
    },  # noqa: E501
}

_ESP32_GND_PADS = ["1", "2", "11", "14"] + [str(n) for n in range(36, 54)]
_ESP32_NC_PADS = ["4", "7", "9", "10", "15", "17", "24", "25", "28", "29", "32", "33", "34", "35"]
_ESP32_UNUSED_GPIO_PADS = ["5", "6", "12", "13", "16", "20", "22"]


def esp32_pads() -> dict[str, str | None]:
    pads: dict[str, str | None] = {pad: "net.gnd" for pad in _ESP32_GND_PADS}
    pads["3"] = "net.p3v3"
    pads["8"] = "net.en"
    pads["18"] = "net.i2c_sda"
    pads["19"] = "net.i2c_scl"
    pads["21"] = "net.led"
    pads["23"] = "net.boot"
    pads["26"] = "net.usb_dn"
    pads["27"] = "net.usb_dp"
    pads["30"] = "net.uart_rx"
    pads["31"] = "net.uart_tx"
    for pad in _ESP32_NC_PADS + _ESP32_UNUSED_GPIO_PADS:
        pads[pad] = None
    return pads


def usb_c_pads() -> dict[str, str | None]:
    return {
        "A1": "net.gnd",
        "A12": "net.gnd",
        "B1": "net.gnd",
        "B12": "net.gnd",
        "A4": "net.vbus_5v",
        "A9": "net.vbus_5v",
        "B4": "net.vbus_5v",
        "B9": "net.vbus_5v",
        "A5": "net.cc1",
        "B5": "net.cc2",
        "A6": "net.usb_dp",
        "B6": "net.usb_dp",
        "A7": "net.usb_dn",
        "B7": "net.usb_dn",
        "A8": None,
        "B8": None,
        "SH": "net.gnd",
    }


def two_pad(net1: str, net2: str) -> dict[str, str | None]:
    return {"1": net1, "2": net2}


def components() -> list[ComponentSpec]:
    r_lib = kicad_lib("Device:R", "Resistor_SMD:R_0603_1608Metric")
    c_lib = kicad_lib("Device:C", "Capacitor_SMD:C_0603_1608Metric")
    sw_lib = kicad_lib("Switch:SW_Push", "Button_Switch_SMD:SW_SPST_TS-1088-xR020")
    tp_lib = kicad_lib("Connector:TestPoint", "TestPoint:TestPoint_Pad_D1.5mm")
    hole_lib = kicad_lib("Mechanical:MountingHole", "MountingHole:MountingHole_2.2mm_M2")

    def resistor(
        refdes: str, value: str, mpn: str, lcsc: str, pads: dict[str, str | None]
    ) -> ComponentSpec:
        return {
            "refdes": refdes,
            "value": value,
            "mpn": mpn,
            "lcsc": lcsc,
            "jlcpcb_class": "basic",
            "assembly": "fitted",
            "lib": r_lib,
            "pads": pads,
        }

    def capacitor(
        refdes: str,
        value: str,
        mpn: str,
        lcsc: str,
        cls: str,
        pads: dict[str, str | None],
        decoupling_target: str | None = None,
    ) -> ComponentSpec:
        spec: ComponentSpec = {
            "refdes": refdes,
            "value": value,
            "mpn": mpn,
            "lcsc": lcsc,
            "jlcpcb_class": cls,
            "assembly": "fitted",
            "lib": c_lib,
            "pads": pads,
        }
        if decoupling_target is not None:
            spec["decoupling_target"] = decoupling_target
        return spec

    def testpoint(refdes: str, net: str, label: str) -> ComponentSpec:
        return {
            "refdes": refdes,
            "value": label,
            "mpn": "",
            "lcsc": "",
            "jlcpcb_class": "none",
            "assembly": "not_fitted",
            "lib": tp_lib,
            "pads": {"1": net},
        }

    def hole(refdes: str) -> ComponentSpec:
        return {
            "refdes": refdes,
            "value": "M2",
            "mpn": "",
            "lcsc": "",
            "jlcpcb_class": "none",
            "assembly": "not_fitted",
            "lib": hole_lib,
            "pads": {},
        }

    return [
        {
            "refdes": "U1",
            "value": "ESP32-C3-MINI-1-N4",
            "mpn": "ESP32-C3-MINI-1-N4",
            "lcsc": "C2838502",
            "jlcpcb_class": "extended",
            "assembly": "fitted",
            "lib": espressif_lib("Espressif:ESP32-C3-MINI-1", "Espressif:ESP32-C3-MINI-1"),
            "pads": esp32_pads(),
        },
        {
            "refdes": "J1",
            "value": "TYPE-C-31-M-12",
            "mpn": "TYPE-C-31-M-12",
            "lcsc": "C165948",
            "jlcpcb_class": "extended",
            "assembly": "fitted",
            "lib": kicad_lib(
                "Connector:USB_C_Receptacle_USB2.0_16P",
                "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
            ),
            "pads": usb_c_pads(),
            "overlay_file": "overlays/j1-usb-c-annular-ring.json",
            "overlay_sha256": (
                "sha256:cc31887bec186674a704e9d1060c3b1a40ab074f2eb9d277973d41311523fb53"
            ),
        },
        {
            "refdes": "U2",
            "value": "AMS1117-3.3",
            "mpn": "AMS1117-3.3",
            "lcsc": "C6186",
            "jlcpcb_class": "basic",
            "assembly": "fitted",
            "lib": kicad_lib(
                "Regulator_Linear:AMS1117-3.3", "Package_TO_SOT_SMD:SOT-223-3_TabPin2"
            ),
            "pads": {"1": "net.gnd", "2": "net.p3v3", "3": "net.vbus_5v"},
        },
        {
            "refdes": "U3",
            "value": "SHT40-AD1B-R3",
            "mpn": "SHT40-AD1B-R3",
            "lcsc": "C2848306",
            "jlcpcb_class": "extended",
            "assembly": "fitted",
            "lib": kicad_lib(
                "Sensor_Humidity:SHT4x",
                "Sensor_Humidity:Sensirion_DFN-4_1.5x1.5mm_P0.8mm_SHT4x_NoCentralPad",
            ),
            "pads": {"1": "net.i2c_sda", "2": "net.i2c_scl", "3": "net.p3v3", "4": "net.gnd"},
        },
        {
            "refdes": "D1",
            "value": "KT-0603R",
            "mpn": "KT-0603R",
            "lcsc": "C2286",
            "jlcpcb_class": "basic",
            "assembly": "fitted",
            "lib": kicad_lib("Device:LED", "LED_SMD:LED_0603_1608Metric"),
            "pads": {"1": "net.gnd", "2": "net.led_a"},
        },
        {
            "refdes": "SW1",
            "value": "RESET",
            "mpn": "TS-1088-AR02016",
            "lcsc": "C720477",
            "jlcpcb_class": "basic",
            "assembly": "fitted",
            "lib": sw_lib,
            "pads": two_pad("net.en", "net.gnd"),
        },
        {
            "refdes": "SW2",
            "value": "BOOT",
            "mpn": "TS-1088-AR02016",
            "lcsc": "C720477",
            "jlcpcb_class": "basic",
            "assembly": "fitted",
            "lib": sw_lib,
            "pads": two_pad("net.boot", "net.gnd"),
        },
        resistor("R1", "5.1k", "0603WAF5101T5E", "C23186", two_pad("net.cc1", "net.gnd")),
        resistor("R2", "5.1k", "0603WAF5101T5E", "C23186", two_pad("net.cc2", "net.gnd")),
        resistor("R3", "10k", "0603WAF1002T5E", "C25804", two_pad("net.p3v3", "net.en")),
        resistor("R4", "4.7k", "0603WAF4701T5E", "C23162", two_pad("net.p3v3", "net.i2c_sda")),
        resistor("R5", "4.7k", "0603WAF4701T5E", "C23162", two_pad("net.p3v3", "net.i2c_scl")),
        resistor("R6", "1k", "0603WAF1001T5E", "C21190", two_pad("net.led", "net.led_a")),
        capacitor(
            "C1", "10uF", "CL10A106MQ8NNNC", "C1691", "extended", two_pad("net.vbus_5v", "net.gnd")
        ),
        capacitor(
            "C2",
            "100nF",
            "CL10B104KB8NNNC",
            "C1591",
            "extended",
            two_pad("net.vbus_5v", "net.gnd"),
        ),
        capacitor(
            "C3",
            "10uF",
            "CL10A106MQ8NNNC",
            "C1691",
            "extended",
            two_pad("net.p3v3", "net.gnd"),
            "U2",
        ),
        capacitor(
            "C4",
            "100nF",
            "CL10B104KB8NNNC",
            "C1591",
            "extended",
            two_pad("net.p3v3", "net.gnd"),
            "U1",
        ),
        capacitor(
            "C5",
            "100nF",
            "CL10B104KB8NNNC",
            "C1591",
            "extended",
            two_pad("net.p3v3", "net.gnd"),
            "U3",
        ),
        capacitor("C6", "1uF", "CL10A105KB8NNNC", "C15849", "basic", two_pad("net.en", "net.gnd")),
        testpoint("TP1", "net.p3v3", "TP_3V3"),
        testpoint("TP2", "net.gnd", "TP_GND"),
        testpoint("TP3", "net.i2c_sda", "TP_SDA"),
        testpoint("TP4", "net.i2c_scl", "TP_SCL"),
        testpoint("TP5", "net.led", "TP_IO7"),
        testpoint("TP6", "net.uart_tx", "TP_TX"),
        testpoint("TP7", "net.uart_rx", "TP_RX"),
        hole("H1"),
        hole("H2"),
        hole("H3"),
        hole("H4"),
    ]


REQUIREMENTS: dict[str, str] = {
    "gd1-req-001": "作者自身が試作し、USB-Cから給電して実機の赤色LEDを1 Hzで点滅させる",
    "gd1-req-004": (
        "電源はUSB-C VBUS 5 Vのみとし、バッテリ、充電回路、USB PDネゴシエーションを持たない"
    ),
    "gd1-req-005": "最大ネット電圧は5 V、最大電流は500 mA未満とする",
    "gd1-req-006": "USB-Cは電力シンク専用とし、CC1/CC2にそれぞれ5.1 kΩのプルダウンを置く",
    "gd1-req-007": "3.3 VはAMS1117-3.3で生成し、入力・出力に10 µFと100 nFを置く",
    "gd1-req-008": "MCUはESP32-C3-MINI-1-N4とし、IO18/IO19の内蔵USBを使用する",
    "gd1-req-010": "LEDはIO7に1 kΩを直列接続し、IO2、IO8、IO9をLEDへ割り当てない",
    "gd1-req-011": "I2CはIO4=SDA、IO5=SCL、アドレス0x44のSHT40とし、各線に4.7 kΩを置く",
    "gd1-req-013": "基板は2層FR-4、板厚1.6 mm、HASL、片面実装、外形およそ30 × 25 mmとする",  # noqa: RUF001
    "gd1-req-014": "M2取付穴を4箇所設け、第2マイルストーンの筐体と共用する",
    "gd1-req-015": (
        "アンテナを基板端からはみ出させ、アンテナ直下・周囲に銅箔、GND、部品、シルクを置かない"
    ),
}

FW_PIN_ASSIGNMENTS: dict[str, tuple[str, int]] = {
    "fw.pin.led": ("net.led", 7),
    "fw.pin.i2c_sda": ("net.i2c_sda", 4),
    "fw.pin.i2c_scl": ("net.i2c_scl", 5),
    "fw.pin.boot": ("net.boot", 9),
    "fw.pin.usb_dn": ("net.usb_dn", 18),
    "fw.pin.usb_dp": ("net.usb_dp", 19),
    "fw.pin.uart_rx": ("net.uart_rx", 20),
    "fw.pin.uart_tx": ("net.uart_tx", 21),
}

BOARD_ATTRS: dict[str, AttrValue] = {
    "layers": 2,
    "material": "FR-4",
    "thickness_mm": 1.6,
    "copper_oz": 1,
    "finish": "HASL",
    "width_mm": 30.0,
    "height_mm": 25.0,
    "assembly_side": "top",
    "unit": "mm",
    "origin": "board_upper_left",
    "y_axis": "down",
    "min_track_mm": 0.15,
    "min_clearance_mm": 0.15,
    "via_drill_mm": 0.3,
    "via_diameter_mm": 0.6,
    "edge_copper_clearance_mm": 0.3,
    "ground_plane_layers": ["F.Cu", "B.Cu"],
    "ground_plane_min_island_area_mm2": 1.0,
    "ground_plane_net": "GND",
    "antenna_keepout": True,
    "mounting_hole_m2_count": 4,
    "fab_capability_source": "https://jlcpcb.com/capabilities/pcb-capabilities",
    "fab_capability_checked_at": "2026-08-11T00:00:00Z",
    "outer_copper_thickness_um": 35.0,
    "stitch_via_basis_source": (
        "IPC-2221A and RF transmission-line wavelength guidance; "
        "guided wavelength c/(f*sqrt(er)), via pitch limited to wavelength fraction"
    ),
    "stitch_via_cost_note": (
        "Adopted 1/20 guided-wavelength pitch; through-via count and drill count are "
        "recorded against the fab profile via cost drivers and reviewed as added process "
        "burden. Perimeter-ring placement is the deterministic base; when an isolated "
        "zone island requires a GND connection, candidates also use the declared pitch "
        "as an interior grid. Both placements exclude signal geometry and are validated "
        "against filled Gerber copper."
    ),
    "stitch_via_dielectric_constant": 4.3,
    "stitch_via_max_frequency_hz": 2.4e9,
    "stitch_via_refill_max_iterations": 3,
    "stitch_via_wavelength_fraction": 0.05,
    "copper_thickness_source": "JLCPCB 1 oz copper capability declaration: 35 µm nominal outer-layer copper",  # noqa: E501
    "allowable_temperature_rise_k": 10.0,
    "ipc2221_external_k": 0.048,
    "ipc2221_external_b": 0.44,
    "ipc2221_external_c": 0.725,
    "ipc2221_internal_k": 0.024,
    "ipc2221_internal_b": 0.44,
    "ipc2221_internal_c": 0.725,
    "width_basis_equation": "ipc2221_external_current_capacity",
    "width_basis_source": "IPC-2221 current-capacity equation: A = (I / (k * ΔT^b))^(1/c), width = A / thickness; IPC-2221, external/internal conductor current-capacity method.",  # noqa: E501
    "width_measurement_tolerance_mm": 0.01,
}

FAB_PROFILE_ID = "jlcpcb-fr4-2l-1oz"
FAB_PROFILE_SOURCE = "https://jlcpcb.com/capabilities/pcb-assembly-capabilities"
FAB_PROFILE_FETCHED_AT = "2026-08-11T00:00:00Z"

MECHANICAL_OUTLINE_ATTRS: dict[str, AttrValue] = {
    "width_mm": 30.0,
    "depth_mm": 25.0,
    "thickness_mm": 1.6,
    "corner_radius_mm": 1.0,
    "unit": "mm",
    "origin": "board_upper_left",
    "y_axis": "down",
    "mount_hole_count": 4,
    "mount_hole_1_x_mm": 1.5,
    "mount_hole_1_y_mm": 1.5,
    "mount_hole_1_diameter_mm": 2.2,
    "mount_hole_2_x_mm": 28.5,
    "mount_hole_2_y_mm": 1.5,
    "mount_hole_2_diameter_mm": 2.2,
    "mount_hole_3_x_mm": 1.5,
    "mount_hole_3_y_mm": 23.5,
    "mount_hole_3_diameter_mm": 2.2,
    "mount_hole_4_x_mm": 28.5,
    "mount_hole_4_y_mm": 23.5,
    "mount_hole_4_diameter_mm": 2.2,
    "position_source": "golden-design-1 mechanical declaration",
    "position_source_ref": "docs/golden-design-1.md",
}


def _body(
    component_id: str,
    *,
    x_mm: float,
    y_mm: float,
    width_mm: float,
    depth_mm: float,
    height_mm: float,
    source: str,
    source_ref: str,
    body_type: str = "solid",
) -> tuple[str, dict[str, AttrValue]]:
    return (
        component_id,
        {
            "x_mm": x_mm,
            "y_mm": y_mm,
            "width_mm": width_mm,
            "depth_mm": depth_mm,
            "height_mm": height_mm,
            "body_type": body_type,
            "mounting_side": "top",
            "rotation_deg": 0.0,
            "position_source": "golden-design-1 mechanical declaration",
            "position_source_ref": "docs/golden-design-1.md",
            "dimensions_source": source,
            "dimensions_source_ref": source_ref,
            "dimensions_checked_at": "2026-08-11T00:00:00Z",
        },
    )


MECHANICAL_COMPONENT_BODIES: tuple[tuple[str, dict[str, AttrValue]], ...] = (
    _body(
        "comp.u1",
        x_mm=15.0,
        y_mm=13.0,
        width_mm=13.2,
        depth_mm=16.6,
        height_mm=2.4,
        source="Espressif ESP32-C3-MINI-1 datasheet",
        source_ref="https://www.espressif.com/sites/default/files/documentation/esp32-c3-mini-1_datasheet_en.pdf",
    ),
    _body(
        "comp.j1",
        x_mm=15.0,
        y_mm=5.0,
        width_mm=9.0,
        depth_mm=7.0,
        height_mm=3.2,
        source="KiCad official footprint library, package version 10.0.5",
        source_ref="https://github.com/KiCad/kicad-footprints/tree/10.0.5/Connector_USB.pretty",
    ),
    _body(
        "comp.u2",
        x_mm=10.0,
        y_mm=18.0,
        width_mm=6.5,
        depth_mm=3.5,
        height_mm=1.8,
        source="Advanced Monolithic AMS1117 datasheet",
        source_ref="https://www.advanced-monolithic.com/pdf/ds1117.pdf",
    ),
    _body(
        "comp.u3",
        x_mm=24.0,
        y_mm=8.0,
        width_mm=1.5,
        depth_mm=1.5,
        height_mm=0.5,
        source="Sensirion SHT4x datasheet",
        source_ref="https://sensirion.com/resource/datasheet/sht4x",
    ),
    _body(
        "comp.d1",
        x_mm=5.0,
        y_mm=20.0,
        width_mm=1.6,
        depth_mm=0.8,
        height_mm=0.55,
        source="LCSC KT-0603R LED datasheet",
        source_ref="https://www.lcsc.com/datasheet/lcsc_datasheet_C2286.pdf",
    ),
    _body(
        "comp.sw1",
        x_mm=7.0,
        y_mm=5.0,
        width_mm=6.0,
        depth_mm=6.0,
        height_mm=4.3,
        source="TS-1088 tactile switch datasheet",
        source_ref="https://www.lcsc.com/datasheet/lcsc_datasheet_C720477.pdf",
    ),
    _body(
        "comp.sw2",
        x_mm=23.0,
        y_mm=5.0,
        width_mm=6.0,
        depth_mm=6.0,
        height_mm=4.3,
        source="TS-1088 tactile switch datasheet",
        source_ref="https://www.lcsc.com/datasheet/lcsc_datasheet_C720477.pdf",
    ),
    *(
        _body(
            f"comp.{prefix}{index}",
            x_mm=8.0 + (index % 2) * 4.0,
            y_mm=8.0 + (index // 2) * 3.0,
            width_mm=1.6,
            depth_mm=0.8,
            height_mm=0.8,
            source="LCSC 0603 chip component datasheet",
            source_ref="https://www.lcsc.com/datasheet/lcsc_datasheet_C1591.pdf",
        )
        for prefix, count in (("r", 6), ("c", 6))
        for index in range(1, count + 1)
    ),
    *(
        _body(
            f"comp.tp{index}",
            x_mm=2.0 + (index % 4) * 8.0,
            y_mm=23.0,
            width_mm=1.5,
            depth_mm=1.5,
            height_mm=0.0,
            body_type="none",
            source="KiCad TestPoint_Pad_D1.5mm has no declared component body",
            source_ref="https://github.com/KiCad/kicad-footprints/tree/10.0.5/TestPoint.pretty",
        )
        for index in range(1, 8)
    ),
    *(
        _body(
            f"comp.h{index}",
            x_mm=1.5 if index % 2 else 28.5,
            y_mm=1.5 if index <= 2 else 23.5,
            width_mm=2.2,
            depth_mm=2.2,
            height_mm=0.0,
            body_type="none",
            source="KiCad MountingHole_2.2mm_M2 has no component body",
            source_ref="https://github.com/KiCad/kicad-footprints/tree/10.0.5/MountingHole.pretty",
        )
        for index in range(1, 5)
    ),
)

MECHANICAL_ENCLOSURE_ATTRS: dict[str, AttrValue] = {
    "wall_thickness_mm": 2.0,
    "min_wall_thickness_mm": 1.2,
    "internal_clearance_mm": 1.0,
    "lid_fit_gap_mm": 0.2,
    "standoff_height_mm": 4.0,
    "standoff_radius_mm": 2.0,
    "material": "PETG",
    "unit": "mm",
    "tolerance_mm": 0.05,
    "interference_tolerance_mm3": 0.01,
    "tolerance_source": "golden-design-1 mechanical gate declaration",
    "tolerance_source_ref": "docs/golden-design-1.md",
}


def mechanical_nodes() -> list[GraphNode]:
    nodes = [
        GraphNode(
            id="mechanical.outline.gd1",
            kind="mechanical.outline",
            attrs=dict(MECHANICAL_OUTLINE_ATTRS),
            depends_on=["board.gd1"],
        )
    ]
    for index, (component_id, attrs) in enumerate(MECHANICAL_COMPONENT_BODIES, start=1):
        nodes.append(
            GraphNode(
                id=f"mechanical.component_body.{index}",
                kind="mechanical.component_body",
                attrs=dict(attrs),
                depends_on=[component_id],
            )
        )
    nodes.append(
        GraphNode(
            id="mechanical.connector_opening.j1",
            kind="mechanical.connector_opening",
            attrs={
                "connector": "comp.j1",
                "face": "front",
                "center_x_mm": 15.0,
                "center_y_mm": 5.0,
                "width_mm": 8.0,
                "height_mm": 5.0,
                "margin_mm": 0.5,
                "dimensions_source": ("KiCad official footprint library, package version 10.0.5"),
                "dimensions_source_ref": (
                    "https://github.com/KiCad/kicad-footprints/tree/10.0.5/Connector_USB.pretty"
                ),
                "dimensions_checked_at": "2026-08-11T00:00:00Z",
            },
            depends_on=["comp.j1"],
        )
    )
    nodes.append(
        GraphNode(
            id="mechanical.enclosure.gd1",
            kind="mechanical.enclosure",
            attrs=dict(MECHANICAL_ENCLOSURE_ATTRS),
            depends_on=[node.id for node in nodes[1:]],
        )
    )
    nodes.extend(
        [
            GraphNode(
                id="mechanical.board_edge_overhang.u1",
                kind="mechanical.board_edge_overhang",
                attrs={
                    "component_refdes": "U1",
                    "overhang_mm": 5.4,
                    "requirement_id": "req.gd1-req-015",
                    "edge": "top",
                },
                depends_on=["comp.u1", "req.gd1-req-015"],
            ),
        ]
    )
    return nodes


def silkscreen_nodes(graph_id: str, revision: str) -> list[GraphNode]:
    board_label = f"{graph_id}-{revision}"
    common = {
        "layer": "F.SilkS",
        "height_mm": 1.5,
        "stroke_width_mm": 0.15,
        "rotation_deg": 0.0,
        "placement_search_order": (
            "top,bottom,right,left,top_right,bottom_right,bottom_left,top_left"
        ),
        "placement_offset_step_mm": 0.25,
        "placement_search_limit_mm": 8.0,
        "board_edge_margin_mm": 0.15,
        "board_edge_margin_source": (
            "fab_profile:jlcpcb-fr4-2l-1oz.min_silk_width=0.15 mm; "
            "declared edge keepout equals the profiled minimum silk stroke"
        ),
        "placement_rotation_degrees": ["0", "90"],
        "placement_safety_margin_mm": 0.15,
    }
    text_nodes = [
        (
            "mechanical.silk_text.reset",
            "functional_label_sw1",
            "RESET",
            29.5,
            5.0,
            "SW1",
            "SW1 center and surrounding footprint clearance",
        ),
        (
            "mechanical.silk_text.boot",
            "functional_label_sw2",
            "BOOT",
            4.55,
            5.4,
            "SW2",
            "SW2 center and surrounding footprint clearance",
        ),
        (
            "mechanical.silk_text.led",
            "functional_label_d1",
            "D1",
            11.0,
            9.0,
            "D1",
            "D1 center and surrounding footprint clearance",
        ),
        (
            "mechanical.silk_text.usb",
            "connector_identifier",
            "USB",
            15.0,
            19.0,
            "J1",
            "J1 center and connector keepout clearance",
        ),
        (
            "mechanical.silk_text.dev_board",
            "board_type",
            "DEV BOARD",
            25.0,
            1.0,
            "board.gd1",
            "open board area after reference and pad clearance search",
        ),
        (
            "mechanical.silk_text.board_id",
            "board_part_number",
            board_label,
            21.8,
            12.7,
            "board.gd1",
            "graph_id and revision derived part-number placement; branding and "
            "identification intentionally remain on B.SilkS after front-side "
            "functional-label clearance measurement",
        ),
    ]
    nodes = [
        GraphNode(
            id=node_id,
            kind="mechanical.silk_text",
            attrs={
                **common,
                "layer": "B.SilkS"
                if role in {"board_type", "board_part_number"}
                else common["layer"],
                "height_mm": 1.0
                if role in {"board_type", "board_part_number"}
                else common["height_mm"],
                "rotation_deg": 90.0 if role == "functional_label_sw1" else common["rotation_deg"],
                "role": role,
                "text": text,
                "x_mm": x_mm,
                "y_mm": y_mm,
                "placement_reference": reference,
                "placement_basis": basis,
            },
            depends_on=["board.gd1"],
        )
        for node_id, role, text, x_mm, y_mm, reference, basis in text_nodes
    ]
    nodes.append(
        GraphNode(
            id="mechanical.silk_graphic.vibebb",
            kind="mechanical.silk_graphic",
            attrs={
                "role": "vibebb_logo",
                "layer": "B.SilkS",
                "stroke_width_mm": 0.15,
                "polygon_points": [
                    "25.0,5.0",
                    "25.8,6.0",
                    "26.6,5.0",
                    "27.4,6.0",
                    "28.2,5.0",
                    "27.4,6.2",
                    "26.6,5.4",
                    "25.8,6.2",
                ],
                "placement_basis": (
                    "branding is intentionally placed on B.SilkS because the "
                    "front functional-label search records pad/mask congestion"
                ),
                "placement_search_order": common["placement_search_order"],
                "board_edge_margin_mm": 0.15,
                "board_edge_margin_source": common["board_edge_margin_source"],
            },
            depends_on=["board.gd1"],
        )
    )
    return nodes


def lib_attrs(lib: LibraryRef) -> dict[str, AttrValue]:
    def file_hash(rel_or_abs: str) -> str:
        path = Path(rel_or_abs)
        if not path.is_absolute():
            path = FIXTURE_DIR / path
        return sha256_of(path)

    return {
        "symbol": lib["symbol"],
        "symbol_file": lib["symbol_file"],
        "symbol_source": lib["symbol_source"],
        "symbol_source_ref": lib["symbol_source_ref"],
        "symbol_sha256": file_hash(lib["symbol_file"]),
        "footprint": lib["footprint"],
        "footprint_file": lib["footprint_file"],
        "footprint_source": lib["footprint_source"],
        "footprint_source_ref": lib["footprint_source_ref"],
        "footprint_sha256": file_hash(lib["footprint_file"]),
    }


def build_graph() -> DesignGraph:
    nodes: list[GraphNode] = []
    for req_id, text in sorted(REQUIREMENTS.items()):
        nodes.append(GraphNode(id=f"req.{req_id}", kind="requirement", attrs={"text": text}))
    for net_id, attrs in NETS.items():
        nodes.append(GraphNode(id=net_id, kind="electrical.net", attrs=dict(attrs)))
    board_deps: list[str] = []
    for spec in components():
        comp_id = f"comp.{spec['refdes'].lower()}"
        board_deps.append(comp_id)
        attrs: dict[str, AttrValue] = {
            "refdes": spec["refdes"],
            "value": spec["value"],
            "mpn": spec["mpn"],
            "lcsc": spec["lcsc"],
            "jlcpcb_class": spec["jlcpcb_class"],
            "assembly": spec["assembly"],
            "stock_checked_at": "2026-08-11T00:00:00Z",
        }
        placement = PLACEMENTS.get(spec["refdes"])
        if placement is None:
            raise ValueError(f"missing design placement for {spec['refdes']}")
        attrs.update(
            {
                "placement_x_mm": placement[0],
                "placement_y_mm": placement[1],
                "placement_rotation_deg": placement[2],
                "placement_source": "golden-design-1 placement declaration",
                "placement_source_ref": "fixtures/golden-design-1/graph.json",
            }
        )
        attrs.update(lib_attrs(spec["lib"]))
        if spec["refdes"] in {"J1", "U1"}:
            attrs.update(
                {
                    "cpl_position_basis": "pad_bbox_center",
                    "cpl_position_source_url": (
                        "https://jlcpcb.com/help/article/how-to-generate-the-bom-and-centroid-file-from-kicad"
                    ),
                    "cpl_position_evidence_at": "2026-08-11T00:00:00Z",
                    "cpl_position_evidence_method": (
                        "independent comparison of KiCad footprint geometry and pad-bbox centroid"
                    ),
                    "cpl_position_evidence_revision": "golden-design-1-r1",
                    "cpl_position_evidence_basis": "confirmed",
                    "cpl_position_evidence_note": (
                        "GD1 uses pad_bbox_center as the declared centroid basis after independent "
                        "comparison of the generated footprint geometry."
                    ),
                }
            )
        if spec["assembly"] == "fitted":
            attrs.update(
                {
                    "cpl_rotation_basis": "component_part_number",
                    "cpl_rotation_source_url": (
                        "https://jlcpcb.com/help/article/pick-and-place-file-for-pcb-assembly"
                    ),
                    "cpl_rotation_evidence_at": "2026-08-11T00:00:00Z",
                    "cpl_rotation_evidence_method": (
                        "component-part-number rotation declaration cross-checked against "
                        "the generated KiCad placement"
                    ),
                    "cpl_rotation_evidence_revision": "golden-design-1-r1",
                    "cpl_rotation_evidence_basis": "confirmed",
                    "cpl_rotation_evidence_note": (
                        "GD1 preserves the declared component rotation in the generated "
                        "assembly placement with a zero-degree centroid offset."
                    ),
                    "cpl_rotation_offset_deg": 180.0 if spec["refdes"] == "U2" else 0.0,
                    "cpl_rotation_polarized": spec["refdes"] in {"U1", "J1", "U2", "U3", "D1"},
                }
            )
            if spec["refdes"] == "J1":
                attrs.update(
                    {
                        "cpl_rotation_geometry_exception": True,
                        "cpl_rotation_geometry_exception_reason": (
                            "archived LCSC package geometry is the orientation evidence for GD1"
                        ),
                        "cpl_rotation_geometry_exception_source": (
                            "evidence/gd1-cpl-orientation/J1.json"
                        ),
                    }
                )
                attrs["cpl_rotation_pin_functions"] = [
                    "A1=GND",
                    "A12=GND",
                    "B1=GND",
                    "B12=GND",
                    "A4=VBUS",
                    "A9=VBUS",
                    "B4=VBUS",
                    "B9=VBUS",
                    "A5=CC1",
                    "B5=CC2",
                    "A6=DP1",
                    "B6=DP2",
                    "A7=DN1",
                    "B7=DN2",
                    "A8=SBU1",
                    "B8=SBU2",
                    "1=EH",
                    "2=EH",
                    "3=EH",
                    "4=EH",
                ]
                attrs["cpl_rotation_pin_aliases"] = [
                    "DP1=D+",
                    "DP2=D+",
                    "DN1=D-",
                    "DN2=D-",
                ]
                attrs["cpl_rotation_unverified_pads"] = ["1", "2", "3", "4"]
                attrs["cpl_rotation_unverified_pad_reason"] = (
                    "USB-C shield padsはKiCad symbolのSHピンに直接対応せず、"
                    "極性判定に影響しない機械シールドである。"
                )
                attrs["cpl_rotation_unverified_pad_source"] = (
                    "KiCad USB_C_Receptacle_HRO_TYPE-C-31-M-12、LCSC C165948 Evidence、"
                    "USB Type-C仕様のシールド端子定義"
                )
            if spec["refdes"] == "U2":
                attrs["cpl_rotation_pin_functions"] = [
                    "1=GND",
                    "2=VO",
                    "3=VI",
                ]
                attrs["cpl_rotation_pin_aliases"] = ["VO=VOUT", "VI=VIN"]
            elif spec["refdes"] == "U1":
                attrs["cpl_rotation_pin_functions"] = [
                    "1=GND",
                    "2=GND",
                    "3=3V3",
                    "4=NC",
                    "5=IO2",
                    "6=IO3",
                    "7=NC",
                    "8=EN",
                    "9=NC",
                    "10=NC",
                    "11=GND",
                    "12=IO0",
                    "13=IO1",
                    "14=GND",
                    "15=NC",
                    "16=IO10",
                    "17=NC",
                    "18=IO4",
                    "19=IO5",
                    "20=IO6",
                    "21=IO7",
                    "22=IO8",
                    "23=IO9",
                    "24=NC",
                    "25=NC",
                    "26=IO18",
                    "27=IO19",
                    "28=NC",
                    "29=NC",
                    "30=RXD0",
                    "31=TXD0",
                    "32=NC",
                    "33=NC",
                    "34=NC",
                    "35=NC",
                    "36=GND",
                    "37=GND",
                    "38=GND",
                    "39=GND",
                    "40=GND",
                    "41=GND",
                    "42=GND",
                    "43=GND",
                    "44=GND",
                    "45=GND",
                    "46=GND",
                    "47=GND",
                    "48=GND",
                    "50=GND",
                    "51=GND",
                    "52=GND",
                    "53=GND",
                ]
                attrs["cpl_rotation_pin_aliases"] = [
                    "GPIO2/ADC1_CH2=IO2",
                    "GPIO3/ADC1_CH3=IO3",
                    "EN/CHIP_PU=EN",
                    "GPIO0/ADC1_CH0/XTAL_32K_P=IO0",
                    "GPIO1/ADC1_CH1/XTAL_32K_N=IO1",
                    "GPIO10=IO10",
                    "GPIO4/ADC1_CH4=IO4",
                    "GPIO5/ADC2_CH0=IO5",
                    "GPIO6=IO6",
                    "GPIO7=IO7",
                    "GPIO8=IO8",
                    "GPIO9=IO9",
                    "GPIO18/USB_D-=IO18",
                    "GPIO19/USB_D+=IO19",
                    "GPIO20/U0RXD=RXD0",
                    "GPIO21/U0TXD=TXD0",
                ]
            elif spec["refdes"] == "U3":
                attrs["cpl_rotation_pin_functions"] = [
                    "1=SDA",
                    "2=SCL",
                    "3=VDD",
                    "4=VSS",
                    "5=EP",
                ]
                attrs["cpl_rotation_unverified_pads"] = ["5"]
                attrs["cpl_rotation_unverified_pad_reason"] = (
                    "U3のEP (露出パッド) はKiCad symbolに対応する番号付きピンがなく、"
                    "温度・機械的接地用で極性判定に影響しない。"
                )
                attrs["cpl_rotation_unverified_pad_source"] = (
                    "KiCad SHT40-AD1B-R3 footprint/symbol、LCSC C2848306 Evidence、"
                    "Sensirion SHT40 datasheetの露出パッド定義"
                )
            elif spec["refdes"] == "D1":
                attrs["cpl_rotation_pin_functions"] = ["1=K", "2=A"]
        overlay_file = spec.get("overlay_file")
        overlay_sha256 = spec.get("overlay_sha256")
        if overlay_file is not None and overlay_sha256 is not None:
            attrs["overlay_file"] = overlay_file
            attrs["overlay_sha256"] = overlay_sha256
        decoupling_target = spec.get("decoupling_target")
        if decoupling_target is not None:
            attrs["decoupling_target"] = decoupling_target
        nodes.append(GraphNode(id=comp_id, kind="electrical.component", attrs=attrs))
        for pad, net in sorted(spec["pads"].items(), key=lambda kv: (len(kv[0]), kv[0])):
            pin_attrs: dict[str, AttrValue] = {
                "component": comp_id,
                "pad": pad,
                "net": net,
                "no_connect": net is None,
            }
            deps = [comp_id] + ([net] if net is not None else [])
            nodes.append(
                GraphNode(
                    id=f"pin.{spec['refdes'].lower()}.{pad.lower()}",
                    kind="electrical.pin",
                    attrs=pin_attrs,
                    depends_on=deps,
                )
            )
    nodes.append(
        GraphNode(
            id="board.gd1",
            kind="electrical.board",
            attrs=dict(BOARD_ATTRS),
            depends_on=sorted(board_deps),
        )
    )
    nodes.append(
        GraphNode(
            id="fab.order_intent.gd1",
            kind="fab.order_intent",
            attrs={
                "fab_profile": FAB_PROFILE_ID,
                "profile_source": FAB_PROFILE_SOURCE,
                "profile_fetched_at": FAB_PROFILE_FETCHED_AT,
                "pcba_class_target": "economic",
                "quantity_pcs": 5,
                "delivery_format": "single",
                "soldermask_color": "green",
                "surface_finish": "HASL",
                "assembly_sides": "top",
            },
            depends_on=["board.gd1", "req.gd1-req-013"],
        )
    )
    nodes.extend(mechanical_nodes())
    for fw_id, (net_id, gpio) in sorted(FW_PIN_ASSIGNMENTS.items()):
        nodes.append(
            GraphNode(
                id=fw_id,
                kind="firmware.pin_assignment",
                attrs={"net": net_id, "gpio": gpio},
                depends_on=[net_id],
            )
        )
    nodes.append(
        GraphNode(
            id="sb.gd1",
            kind="safety.boundary",
            attrs={
                "profile": "hobby",
                "intended_use": "author_prototype",
                "max_net_voltage_v": 5.0,
                "max_current_a": 0.5,
                "battery": False,
                "charger": False,
                "motor_actuator_laser": False,
                "module_certified": "unknown",
            },
        )
    )
    graph_id = "golden-design-1"
    revision = "r1"
    nodes.extend(silkscreen_nodes(graph_id, revision))
    return DesignGraph(graph_id=graph_id, revision=revision, nodes=nodes)


def main() -> int:
    graph = build_graph()
    payload = graph.model_dump(mode="json")
    out = FIXTURE_DIR / "graph.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out} ({len(graph.nodes)} nodes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
