"""Build the Golden Design #1 design-graph fixture.
Regenerates ``fixtures/golden-design-1/graph.json`` deterministically from the
specification in ``docs/golden-design-1.md``. Library references are pinned
with source, version/commit, and file sha256 so that unpinned references fail
closed downstream (ADR-0004).
"""

from __future__ import annotations

# ruff: noqa: E501,RUF100
import hashlib
from pathlib import Path
from typing import NotRequired, TypedDict

from acd.schema.design_graph import AttrValue

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
