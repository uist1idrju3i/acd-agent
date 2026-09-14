"""Shipping inspection projection tests."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import cast

import pytest
from test_interface_spec import GRAPH, _config_report, _pins_header

from acd.schema.firmware_inspection import FirmwareInspectionItem, FirmwareInspectionSequence
from acd.schema.shipping_inspection import ShippingInspectionDocument
from doc_inputs import DocumentGenerationError
from generate_shipping_inspection import main as shipping_main


def _run(tmp_path: Path, *, lang: str = "ja", revision: str = "r1") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    header = _pins_header(tmp_path, revision=revision)
    report = _config_report(tmp_path, revision=revision)
    out_dir = tmp_path / "out"
    arguments = [
        "--graph",
        str(GRAPH),
        "--pins-header",
        str(header),
        "--firmware-config-report",
        str(report),
        "--out-dir",
        str(out_dir),
        "--base-dir",
        str(tmp_path),
    ]
    if lang != "ja":
        arguments.extend(["--lang", lang])
    assert shipping_main(arguments) == 0
    return out_dir if lang == "ja" else out_dir / lang


def test_gd1_covers_all_categories_and_validates_contract(tmp_path: Path) -> None:
    output = _run(tmp_path)
    payload = json.loads(
        (output / "shipping-inspection.json").read_text(encoding="utf-8")
    )
    document = ShippingInspectionDocument.model_validate(payload)
    assert {item.category for item in document.items} == {
        "visual",
        "continuity",
        "power",
        "flash_boot",
        "led",
        "sensor",
        "serial",
    }
    assert document.unknown_count == sum(
        item.manual_decision_required for item in document.items
    )
    assert all(
        item.criterion.unknown_reason
        for item in document.items
        if item.criterion.kind == "unknown"
    )
    assert all(
        item.criterion.source is not None
        for item in document.items
        if item.criterion.kind != "unknown"
    )
    assert any(
        item.criterion.expected == "ACD GD1 fw boot target_revision=r1"
        for item in document.items
        if item.category == "flash_boot"
    )


def test_japanese_and_english_outputs(tmp_path: Path) -> None:
    ja = _run(tmp_path / "ja")
    en = _run(tmp_path / "en", lang="en")
    assert "項目" in (ja / "shipping-inspection.md").read_text(encoding="utf-8")
    assert not re.search(
        r"[\u3400-\u9fff\u3040-\u30ff]",
        (en / "shipping-inspection.md").read_text(encoding="utf-8"),
    )


def test_shipping_output_is_deterministic(tmp_path: Path) -> None:
    first = _run(tmp_path / "first")
    second = _run(tmp_path / "second")
    assert (first / "shipping-inspection.md").read_bytes() == (
        second / "shipping-inspection.md"
    ).read_bytes()
    assert (first / "shipping-inspection.json").read_bytes() == (
        second / "shipping-inspection.json"
    ).read_bytes()


def test_revision_mismatch_writes_nothing(tmp_path: Path) -> None:
    header = _pins_header(tmp_path, revision="r99")
    report = _config_report(tmp_path, revision="r99")
    out_dir = tmp_path / "out"
    with pytest.raises(DocumentGenerationError, match="targets revision"):
        shipping_main(
            [
                "--graph",
                str(GRAPH),
                "--pins-header",
                str(header),
                "--firmware-config-report",
                str(report),
                "--out-dir",
                str(out_dir),
            ]
        )
    assert not out_dir.exists()


def test_inspection_sequence_adds_self_test_items_and_validates_revision(
    tmp_path: Path,
) -> None:
    sequence = FirmwareInspectionSequence(
        schema_version="0.1",
        graph_id="golden-design-1",
        target_revision="r1",
        entry_command="ACD INSPECT",
        begin_line="ACD_INSPECT begin target_revision=r1",
        end_line="ACD_INSPECT end items=2",
        items=[
            FirmwareInspectionItem(
                item_id="led-led",
                kind="led",
                subject_node_ids=["fw.pin.led"],
                source={
                    "kind": "firmware_projection",
                    "ref": "firmware-inspection-sequence.json#led-led",
                },
                expected_line="ACD_INSPECT led:led gpio=7 result=executed",
                status="derived",
            ),
            FirmwareInspectionItem(
                item_id="power-self-check",
                kind="power_self_check",
                subject_node_ids=["fw.module"],
                status="unknown",
                unknown_reason="no self-measurement source declared in graph",
            ),
        ],
    )
    sequence_path = tmp_path / "firmware-inspection-sequence.json"
    sequence_path.write_text(
        json.dumps(sequence.model_dump(mode="json"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    header = _pins_header(tmp_path)
    report = _config_report(tmp_path)
    out_dir = tmp_path / "out"
    assert shipping_main(
        [
            "--graph",
            str(GRAPH),
            "--pins-header",
            str(header),
            "--firmware-config-report",
            str(report),
            "--inspection-sequence",
            str(sequence_path),
            "--out-dir",
            str(out_dir),
        ]
    ) == 0
    document = ShippingInspectionDocument.model_validate(
        json.loads((out_dir / "shipping-inspection.json").read_text(encoding="utf-8"))
    )
    self_test = [item for item in document.items if item.category == "self_test"]
    assert len(self_test) == 3
    assert any(item.criterion.unknown_reason for item in self_test)
    assert all(
        item.criterion.source is not None
        for item in self_test
        if item.criterion.kind != "unknown"
    )
    broken = sequence.model_copy(update={"target_revision": "r99"})
    sequence_path.write_text(
        json.dumps(broken.model_dump(mode="json"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(DocumentGenerationError, match="target_revision"):
        shipping_main(
            [
                "--graph",
                str(GRAPH),
                "--pins-header",
                str(header),
                "--firmware-config-report",
                str(report),
                "--inspection-sequence",
                str(sequence_path),
                "--out-dir",
                str(tmp_path / "broken-out"),
            ]
        )


def test_missing_nominal_voltage_is_unknown(tmp_path: Path) -> None:
    graph_payload = cast(
        dict[str, object], json.loads(GRAPH.read_text(encoding="utf-8"))
    )
    nodes = cast(list[dict[str, object]], graph_payload["nodes"])
    for node in nodes:
        if node["kind"] == "electrical.net":
            attrs = cast(dict[str, object], node["attrs"])
            if attrs.get("power_rail") is True:
                attrs.pop("voltage_nominal_v", None)
                break
    graph = tmp_path / "graph.json"
    graph.write_text(
        json.dumps(graph_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    header = _pins_header(tmp_path)
    report = _config_report(tmp_path)
    out_dir = tmp_path / "out"
    assert shipping_main(
        [
            "--graph",
            str(graph),
            "--pins-header",
            str(header),
            "--firmware-config-report",
            str(report),
            "--out-dir",
            str(out_dir),
        ]
    ) == 0
    payload = json.loads(
        (out_dir / "shipping-inspection.json").read_text(encoding="utf-8")
    )
    document = ShippingInspectionDocument.model_validate(payload)
    assert any(
        item.category == "power"
        and item.criterion.kind == "unknown"
        and item.criterion.expected is None
        for item in document.items
    )
