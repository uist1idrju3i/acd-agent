"""Build the Golden Design #1 design-graph fixture.

Regenerates ``fixtures/golden-design-1/graph.json`` deterministically from the
specification in ``docs/golden-design-1.md``. Library references are pinned
with source, version/commit, and file sha256 so that unpinned references fail
closed downstream (ADR-0004).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import TypedDict

from acd_schema.design_graph import AttrValue, DesignGraph, GraphNode

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "fixtures" / "golden-design-1"
KICAD_SYMBOLS = Path("/usr/share/kicad/symbols")
KICAD_FOOTPRINTS = Path("/usr/share/kicad/footprints")

KICAD_PACKAGE_VERSION = "10.0.5"
KICAD_LIB_SOURCE = "kicad-official (ppa:kicad/kicad-10.0-releases)"
ESPRESSIF_SOURCE = "https://github.com/espressif/kicad-libraries"
ESPRESSIF_COMMIT = "dd76561812ab300351234ba6e0ec1295641796f0"


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
    lib: LibraryRef
    # pad number -> net id (None means explicit no-connect)
    pads: dict[str, str | None]


NETS: dict[str, dict[str, AttrValue]] = {
    "net.vbus_5v": {"name": "VBUS_5V", "voltage_nominal_v": 5.0, "current_max_a": 0.5},
    "net.cc1": {"name": "CC1", "voltage_nominal_v": 5.0},
    "net.cc2": {"name": "CC2", "voltage_nominal_v": 5.0},
    "net.gnd": {"name": "GND", "voltage_nominal_v": 0.0},
    "net.p3v3": {"name": "+3V3", "voltage_nominal_v": 3.3, "current_max_a": 0.5},
    "net.usb_dn": {"name": "USB_D-", "voltage_nominal_v": 3.3},
    "net.usb_dp": {"name": "USB_D+", "voltage_nominal_v": 3.3},
    "net.en": {"name": "EN", "voltage_nominal_v": 3.3},
    "net.boot": {"name": "BOOT", "voltage_nominal_v": 3.3},
    "net.led": {"name": "LED", "voltage_nominal_v": 3.3},
    "net.led_a": {"name": "LED_A", "voltage_nominal_v": 3.3},
    "net.i2c_sda": {"name": "I2C_SDA", "voltage_nominal_v": 3.3},
    "net.i2c_scl": {"name": "I2C_SCL", "voltage_nominal_v": 3.3},
    "net.uart_tx": {"name": "UART_TX", "voltage_nominal_v": 3.3},
    "net.uart_rx": {"name": "UART_RX", "voltage_nominal_v": 3.3},
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
        "S1": "net.gnd",
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
            "lib": r_lib,
            "pads": pads,
        }

    def capacitor(
        refdes: str, value: str, mpn: str, lcsc: str, cls: str, pads: dict[str, str | None]
    ) -> ComponentSpec:
        return {
            "refdes": refdes,
            "value": value,
            "mpn": mpn,
            "lcsc": lcsc,
            "jlcpcb_class": cls,
            "lib": c_lib,
            "pads": pads,
        }

    def testpoint(refdes: str, net: str, label: str) -> ComponentSpec:
        return {
            "refdes": refdes,
            "value": label,
            "mpn": "",
            "lcsc": "",
            "jlcpcb_class": "none",
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
            "lib": espressif_lib("Espressif:ESP32-C3-MINI-1", "Espressif:ESP32-C3-MINI-1"),
            "pads": esp32_pads(),
        },
        {
            "refdes": "J1",
            "value": "TYPE-C-31-M-12",
            "mpn": "TYPE-C-31-M-12",
            "lcsc": "C165948",
            "jlcpcb_class": "extended",
            "lib": kicad_lib(
                "Connector:USB_C_Receptacle_USB2.0_16P",
                "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
            ),
            "pads": usb_c_pads(),
        },
        {
            "refdes": "U2",
            "value": "AMS1117-3.3",
            "mpn": "AMS1117-3.3",
            "lcsc": "C6186",
            "jlcpcb_class": "basic",
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
            "lib": kicad_lib("Device:LED", "LED_SMD:LED_0603_1608Metric"),
            "pads": {"1": "net.gnd", "2": "net.led_a"},
        },
        {
            "refdes": "SW1",
            "value": "RESET",
            "mpn": "TS-1088-AR02016",
            "lcsc": "C720477",
            "jlcpcb_class": "basic",
            "lib": sw_lib,
            "pads": two_pad("net.en", "net.gnd"),
        },
        {
            "refdes": "SW2",
            "value": "BOOT",
            "mpn": "TS-1088-AR02016",
            "lcsc": "C720477",
            "jlcpcb_class": "basic",
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
            "C3", "10uF", "CL10A106MQ8NNNC", "C1691", "extended", two_pad("net.p3v3", "net.gnd")
        ),
        capacitor(
            "C4", "100nF", "CL10B104KB8NNNC", "C1591", "extended", two_pad("net.p3v3", "net.gnd")
        ),
        capacitor(
            "C5", "100nF", "CL10B104KB8NNNC", "C1591", "extended", two_pad("net.p3v3", "net.gnd")
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
    "antenna_keepout": True,
    "mounting_hole_m2_count": 4,
    "fab_capability_source": "https://jlcpcb.com/capabilities/pcb-capabilities",
    "fab_capability_checked_at": "2026-08-11T00:00:00Z",
}

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

MECHANICAL_COMPONENT_BODIES: tuple[tuple[str, dict[str, AttrValue]], ...] = (
    (
        "comp.u1",
        {
            "x_mm": 15.0,
            "y_mm": 13.0,
            "width_mm": 13.2,
            "depth_mm": 16.6,
            "height_mm": 2.4,
            "mounting_side": "top",
            "rotation_deg": 0.0,
            "position_source": "golden-design-1 mechanical declaration",
            "position_source_ref": "docs/golden-design-1.md",
            "dimensions_source": "Espressif ESP32-C3-MINI-1 datasheet",
            "dimensions_source_ref": (
                "https://www.espressif.com/sites/default/files/documentation/"
                "esp32-c3-mini-1_datasheet_en.pdf"
            ),
            "dimensions_checked_at": "2026-08-11T00:00:00Z",
        },
    ),
    (
        "comp.j1",
        {
            "x_mm": 15.0,
            "y_mm": 5.0,
            "width_mm": 9.0,
            "depth_mm": 7.0,
            "height_mm": 3.2,
            "mounting_side": "top",
            "rotation_deg": 0.0,
            "position_source": "golden-design-1 mechanical declaration",
            "position_source_ref": "docs/golden-design-1.md",
            "dimensions_source": "KiCad official footprint library",
            "dimensions_source_ref": (
                "https://github.com/KiCad/kicad-footprints/blob/master/"
                "Connector_USB.pretty/USB_C_Receptacle_HRO_TYPE-C-31-M-12.kicad_mod"
            ),
            "dimensions_checked_at": "2026-08-11T00:00:00Z",
        },
    ),
    (
        "comp.u2",
        {
            "x_mm": 7.0,
            "y_mm": 20.0,
            "width_mm": 6.5,
            "depth_mm": 3.5,
            "height_mm": 1.8,
            "mounting_side": "top",
            "rotation_deg": 0.0,
            "position_source": "golden-design-1 mechanical declaration",
            "position_source_ref": "docs/golden-design-1.md",
            "dimensions_source": "AMS1117 SOT-223 datasheet",
            "dimensions_source_ref": "https://www.advanced-monolithic.com/pdf/ds1117.pdf",
            "dimensions_checked_at": "2026-08-11T00:00:00Z",
        },
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
    "tolerance_source": "golden-design-1 mechanical gate declaration",
    "tolerance_source_ref": "docs/golden-design-1.md",
}


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
            "stock_checked_at": "2026-08-11T00:00:00Z",
        }
        attrs.update(lib_attrs(spec["lib"]))
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
            id="mechanical.outline.gd1",
            kind="mechanical.outline",
            attrs=dict(MECHANICAL_OUTLINE_ATTRS),
            depends_on=["board.gd1"],
        )
    )
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
                "dimensions_source": "KiCad official footprint library",
                "dimensions_source_ref": (
                    "https://github.com/KiCad/kicad-footprints/blob/master/"
                    "Connector_USB.pretty/USB_C_Receptacle_HRO_TYPE-C-31-M-12.kicad_mod"
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
            depends_on=[
                "mechanical.outline.gd1",
                "mechanical.component_body.1",
                "mechanical.component_body.2",
                "mechanical.component_body.3",
                "mechanical.connector_opening.j1",
            ],
        )
    )
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
    return DesignGraph(graph_id="golden-design-1", revision="r1", nodes=nodes)


def main() -> int:
    graph = build_graph()
    payload = graph.model_dump(mode="json")
    out = FIXTURE_DIR / "graph.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out} ({len(graph.nodes)} nodes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
