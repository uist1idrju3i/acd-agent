"""Build the Golden Design #1 design-graph fixture.
Regenerates ``fixtures/golden-design-1/graph.json`` deterministically from the
specification in ``docs/golden-design-1.md``. Library references are pinned
with source, version/commit, and file sha256 so that unpinned references fail
closed downstream (ADR-0004).
"""
# pyright: reportUnknownVariableType=false,reportUnknownArgumentType=false,reportUnknownMemberType=false,reportUnknownParameterType=false,reportInvalidTypeForm=false,reportUnusedVariable=false,reportUnusedImport=false,reportGeneralTypeIssues=false

from __future__ import annotations

# ruff: noqa: E501,RUF100,F405
import argparse
import json
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from acd.core.rationale import subject_hash_for
from acd.schema.design_graph import AttrValue, DesignGraph, GraphNode
from acd.schema.rationale import RationaleDocument

from ..placement_evidence import summarize_placement_evidence
from ..repository import repository_root
from .components import (
    BOARD_ATTRS,
    FAB_PROFILE_FETCHED_AT,
    FAB_PROFILE_ID,
    FAB_PROFILE_SOURCE,
    FW_PIN_ASSIGNMENTS,
    NETS,
    PLACEMENTS,
    REQUIREMENTS,
    LibraryRef,
    components,
    sha256_of,
)
from .mechanical import mechanical_nodes
from .silkscreen import silkscreen_nodes


def _paths() -> tuple[Path, Path, Path, Path, Path]:
    root = repository_root()
    fixture_dir = root / "fixtures" / "golden-design-1"
    placement_skill = root / "plugins/acd/skills/acd-placement-search/scripts/placement_search.py"
    silk_skill = root / "plugins/acd/skills/acd-silkscreen-placement/scripts/silkscreen_search.py"
    fab_profile = root / "profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json"
    return root, fixture_dir, placement_skill, silk_skill, fab_profile


def _run_skill(
    script: Path,
    input_data: dict[str, object],
    output: Path,
    *,
    extra_args: Sequence[str] = (),
) -> dict[str, Any]:
    root, _, _, _, _ = _paths()
    input_path = output.with_suffix(".input.json")
    input_path.write_text(
        json.dumps(input_data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    command = [sys.executable, str(script), "--input", str(input_path)]
    command.extend(extra_args)
    command.extend(["--output", str(output)])
    subprocess.run(command, check=True, cwd=root)
    value = json.loads(output.read_text(encoding="utf-8"))
    if not isinstance(value, dict | list):
        raise ValueError(f"skill output is not a JSON object or array: {script}")
    return value if isinstance(value, dict) else {"placements": value}


def _resolve_skill_inputs(graph: DesignGraph) -> DesignGraph:
    root, fixture_dir, placement_skill, silk_skill, fab_profile = _paths()
    graph_payload = graph.model_dump(mode="json")
    with tempfile.TemporaryDirectory(prefix="acd-gd1-skill-") as directory:
        directory_path = Path(directory)
        placement_result = _run_skill(
            placement_skill,
            graph_payload,
            directory_path / "placements.json",
            extra_args=(
                "--fixture-dir",
                str(fixture_dir),
                "--fab-profile",
                str(fab_profile),
            ),
        )
        placements = placement_result.get("placements")
        if not isinstance(placements, list):
            raise ValueError("placement skill output is missing placements")
        placement_by_refdes = {
            str(item["refdes"]): item for item in placements if isinstance(item, dict)
        }
        updated_nodes: list[GraphNode] = []
        for node in graph.nodes:
            if node.kind == "electrical.component":
                refdes = node.attrs.get("refdes")
                placement = placement_by_refdes.get(str(refdes))
                if placement is None:
                    raise ValueError(f"placement skill omitted {refdes}")
                attrs = dict(node.attrs)
                attrs.update(
                    {
                        "placement_x_mm": placement["x_mm"],
                        "placement_y_mm": placement["y_mm"],
                        "placement_rotation_deg": placement["rotation_deg"],
                        "placement_source": "acd-placement-search",
                        "placement_source_ref": f"plugins/acd/skills/acd-placement-search/scripts/placement_search.py:{sha256_of(placement_skill)}",
                    }
                )
                updated_nodes.append(node.model_copy(update={"attrs": attrs}))
            else:
                updated_nodes.append(node)
        graph = graph.model_copy(update={"nodes": updated_nodes})

        from acd.adapters.kicad.board import generate_board
        from acd.adapters.kicad.library import FootprintLibrary
        from acd.adapters.kicad.placement import Placement
        from acd.core.electrical import extract_electrical_lane
        from acd.core.fab import load_fab_profile
        from acd.core.silkscreen import extract_silkscreen_lane

        electrical = extract_electrical_lane(graph)
        profile = load_fab_profile(fab_profile)
        placement_values = tuple(
            Placement(
                str(item["refdes"]),
                float(item["x_mm"]),
                float(item["y_mm"]),
                float(item["rotation_deg"]),
            )
            for item in placements
        )
        projection = generate_board(
            electrical,
            FootprintLibrary(),
            fixture_dir,
            profile,
            placement_values,
        )
        silk_lane = extract_silkscreen_lane(graph)
        silk_result = _run_skill(
            silk_skill,
            {"board": asdict(projection.model), "lane": asdict(silk_lane)},
            directory_path / "silkscreen.json",
        )
        evidence_archive = root / "out" / "gd1-fixture-evidence"
        evidence_archive.mkdir(parents=True, exist_ok=True)
        evidence_archive.joinpath("silkscreen.json").write_text(
            json.dumps(silk_result, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        resolved_texts = silk_result.get("texts")
        evidence = silk_result.get("placement_evidence")
        if not isinstance(resolved_texts, list) or not isinstance(evidence, list):
            raise ValueError("silkscreen skill output is incomplete")
        resolved_by_id = {
            str(item["node_id"]): item for item in resolved_texts if isinstance(item, dict)
        }
        evidence_by_id = {str(item["node_id"]): item for item in evidence if isinstance(item, dict)}
        updated_nodes = []
        for node in graph.nodes:
            resolved = resolved_by_id.get(node.id)
            if node.kind == "mechanical.silk_text" and resolved is not None:
                attrs = dict(node.attrs)
                attrs.update(
                    {
                        "x_mm": resolved["x_mm"],
                        "y_mm": resolved["y_mm"],
                        "rotation_deg": resolved["rotation_deg"],
                        "placement_rotation_deg": resolved["rotation_deg"],
                        "placement_source": "acd-silkscreen-placement",
                        "placement_source_ref": f"plugins/acd/skills/acd-silkscreen-placement/scripts/silkscreen_search.py:{sha256_of(silk_skill)}",
                        "placement_evidence": json.dumps(
                            summarize_placement_evidence(evidence_by_id[node.id]),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "placement_evidence_input_sha256": sha256_of(
                            directory_path / "silkscreen.input.json"
                        ),
                        "placement_evidence_output_sha256": sha256_of(
                            evidence_archive / "silkscreen.json"
                        ),
                    }
                )
                updated_nodes.append(node.model_copy(update={"attrs": attrs}))
            else:
                updated_nodes.append(node)
        graph = graph.model_copy(update={"nodes": updated_nodes})
    return graph


def lib_attrs(lib: LibraryRef) -> dict[str, AttrValue]:
    fixture_dir = _paths()[1]
    def file_hash(rel_or_abs: str) -> str:
        path = Path(rel_or_abs)
        if not path.is_absolute():
            path = fixture_dir / path
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
    _, _, placement_skill, _, _ = _paths()
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
                "placement_source": "acd-placement-search",
                "placement_source_ref": (
                    "plugins/acd/skills/acd-placement-search/scripts/"
                    f"placement_search.py:{sha256_of(placement_skill)}"
                ),
            }
        )
        attrs.update(lib_attrs(spec["lib"]))
        if spec["refdes"] == "U1":
            attrs.update(
                {
                    "radio_module": True,
                    "certification_ids": [
                        "FCC:2AC7Z-ESPC3MINI1",
                        "IC:21098-ESPC3MINI1",
                    ],
                    "certification_hvin": "ESP32-C3-MINI-1",
                    "certification_grant_dates": [
                        "FCC:2021-06-16",
                        "IC:2024-07-24",
                    ],
                    "certification_document_refs": [
                        "https://documentation.espressif.com/ESP32-C3-MINI-1%20FCC%20Certification.pdf",
                        "https://documentation.espressif.com/ESP32-C3-MINI-1%20IC%20Certification_0.pdf",
                    ],
                    "certification_source": (
                        "Espressif Systems published module certification documents"
                    ),
                    "certification_source_ref": (
                        "https://www.espressif.com/en/support/documents/certificates"
                    ),
                    "certification_checked_at": "2026-08-18T00:00:00Z",
                }
            )
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
    functional_blocks = (
        (
            "fb.safety-power-boundary",
            "safety_power_boundary",
            "req.gd1-req-004",
            "req.gd1-req-005",
        ),
        ("fb.usb-c-cc-termination", "usb_c_cc_termination", "req.gd1-req-006"),
        ("fb.i2c-bus-pullup", "i2c_bus_pullup", "req.gd1-req-011"),
        ("fb.esp32c3-strapping-boot", "esp32c3_strapping_boot", "req.gd1-req-010"),
        ("fb.firmware-pin-map", "firmware_pin_map", "req.gd1-req-008"),
        ("fb.single-ldo-power-tree", "single_ldo_power_tree", "req.gd1-req-007"),
    )
    nodes.extend(
        GraphNode(
            id=node_id,
            kind="design.functional_block",
            attrs={"block_id": block_id},
            depends_on=list(requirement_ids),
        )
        for node_id, block_id, *requirement_ids in functional_blocks
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
                "module_certified": "certified",
            },
        )
    )
    graph_id = "golden-design-1"
    revision = "r1"
    nodes.extend(silkscreen_nodes(graph_id, revision))
    return _resolve_skill_inputs(DesignGraph(graph_id=graph_id, revision=revision, nodes=nodes))


def check_rationale_hashes(
    graph: DesignGraph,
    rationale_path: Path,
    *,
    refresh: bool,
) -> int:
    if not rationale_path.is_file():
        return 0
    try:
        document = RationaleDocument.model_validate(
            json.loads(rationale_path.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        print(f"rationale validation failed; graph was not written: {exc}", file=sys.stderr)
        return 2
    stale: list[tuple[str, str]] = []
    refreshed = []
    for record in document.records:
        try:
            expected_hash = subject_hash_for(
                graph, record.subject_nodes, record.subject_attrs
            )
        except KeyError as exc:
            stale.append((record.rationale_id, str(exc)))
            continue
        if record.subject_hash != expected_hash or record.target_revision != graph.revision:
            subjects = ", ".join(
                f"({node_id}, {attr})"
                for node_id in record.subject_nodes
                for attr in record.subject_attrs
            )
            stale.append((record.rationale_id, subjects))
            refreshed.append(
                record.model_copy(
                    update={
                        "subject_hash": expected_hash,
                        "target_revision": graph.revision,
                    }
                )
            )
    if stale and not refresh:
        print("rationale hashes are stale; graph was not written:", file=sys.stderr)
        for rationale_id, subjects in stale:
            print(f"  {rationale_id}: {subjects}", file=sys.stderr)
        print(
            "Re-record the rationale or pass --refresh-rationale-hashes explicitly.",
            file=sys.stderr,
        )
        return 2
    if stale and refresh:
        refreshed_by_id = {record.rationale_id: record for record in refreshed}
        updated_records = [
            refreshed_by_id.get(record.rationale_id, record)
            for record in document.records
        ]
        updated_document = document.model_copy(update={"records": updated_records})
        rationale_path.write_text(
            updated_document.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"refreshed rationale hashes in {rationale_path}")
    return 0


def main() -> int:
    _, fixture_dir, _, _, _ = _paths()
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-rationale-hashes", action="store_true")
    args = parser.parse_args()
    graph = build_graph()
    rationale_status = check_rationale_hashes(
        graph,
        fixture_dir / "rationale.json",
        refresh=args.refresh_rationale_hashes,
    )
    if rationale_status != 0:
        return rationale_status
    payload = graph.model_dump(mode="json")
    out = fixture_dir / "graph.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out} ({len(graph.nodes)} nodes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
