from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from acd.core.electrical.electrical import extract_electrical_lane
from acd.core.electrical.emc_esd import evaluate_emc_esd
from acd.core.knowledge.design_predicates import PREDICATE_CATALOG
from acd.schema import DesignGraph, UseEnvironment

ROOT = Path(__file__).parents[2]
GRAPH_PATH = ROOT / "fixtures/golden-design-1/graph.json"
ENVIRONMENT_PATH = ROOT / "fixtures/use-environment/gd1-indoor-usb.json"


def _graph_payload() -> dict[str, object]:
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))


def _environment(**updates: object) -> UseEnvironment:
    payload = json.loads(ENVIRONMENT_PATH.read_text(encoding="utf-8"))
    payload.update(updates)
    return UseEnvironment.model_validate(payload)


def _result(graph_payload: dict[str, object], environment: UseEnvironment):
    graph = DesignGraph.model_validate(graph_payload)
    return evaluate_emc_esd(graph, extract_electrical_lane(graph), environment)


def test_gd1_emc_esd_is_opt_in_and_fails_esd_closed() -> None:
    result = _result(_graph_payload(), _environment())
    by_id = {item.predicate_id: item for item in result.predicates}
    assert result.status == "fail"
    assert by_id["esd_protection_external_ports"].status == "fail"
    assert all(
        net in by_id["esd_protection_external_ports"].reason
        for net in ("USB_D+", "USB_D-", "CC1", "CC2")
    )
    assert by_id["power_loop_area"].details["threshold_mm2"] == 50.0
    assert by_id["return_path_continuity"].status == "pass"
    assert "emc_esd" not in PREDICATE_CATALOG


def test_internal_port_passes_esd_predicate() -> None:
    result = _result(
        _graph_payload(),
        _environment(
            external_ports=[{"connector_node_id": "comp.j1", "exposure": "internal"}]
        ),
    )
    by_id = {item.predicate_id: item for item in result.predicates}
    assert by_id["esd_protection_external_ports"].status == "pass"
    assert "internal port" in json.dumps(by_id["esd_protection_external_ports"].details)


def test_added_esd_devices_pass_external_port() -> None:
    payload = _graph_payload()
    nodes = cast(list[dict[str, Any]], payload["nodes"])
    template = deepcopy(next(node for node in nodes if node["id"] == "comp.c1"))
    for index, net_id in enumerate(("net.cc1", "net.cc2", "net.usb_dp", "net.usb_dn")):
        component = deepcopy(template)
        component["id"] = f"comp.esd{index}"
        component["attrs"]["refdes"] = f"ESD{index}"
        component["attrs"]["esd_protection"] = True
        component["attrs"]["placement_x_mm"] = 1.0 + index
        component["attrs"]["placement_y_mm"] = 1.0
        nodes.append(component)
        nodes.append(
            {
                "id": f"pin.esd{index}",
                "kind": "electrical.pin",
                "attrs": {
                    "component": component["id"],
                    "net": net_id,
                    "no_connect": False,
                    "pad": "1",
                },
            }
        )
    result = _result(payload, _environment())
    predicate = next(
        item for item in result.predicates if item.predicate_id == "esd_protection_external_ports"
    )
    assert predicate.status == "pass"


def test_unknown_environment_propagates_unknown() -> None:
    result = _result(_graph_payload(), _environment(installation="unknown"))
    assert result.status == "fail"
    assert next(
        item for item in result.predicates if item.predicate_id == "environment_derating_inputs"
    ).status == "unknown"


def test_missing_ground_plane_is_unknown() -> None:
    payload = _graph_payload()
    nodes = cast(list[dict[str, Any]], payload["nodes"])
    board = next(node for node in nodes if node["kind"] == "electrical.board")
    del board["attrs"]["ground_plane_net"]
    result = _result(payload, _environment())
    predicate = next(
        item for item in result.predicates if item.predicate_id == "return_path_continuity"
    )
    assert predicate.status == "unknown"
    assert predicate.reason == "no ground plane declared"


def test_evaluation_is_deterministic() -> None:
    payload = _graph_payload()
    first = _result(payload, _environment()).model_dump_json()
    second = _result(payload, _environment()).model_dump_json()
    assert first == second


def test_cli_revision_mismatch_exits_two_without_output(tmp_path: Path) -> None:
    environment = json.loads(ENVIRONMENT_PATH.read_text(encoding="utf-8"))
    environment["revision"] = "r2"
    environment_path = tmp_path / "environment.json"
    environment_path.write_text(json.dumps(environment), encoding="utf-8")
    output = tmp_path / "out"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/check_emc_esd.py"),
            "--graph",
            str(GRAPH_PATH),
            "--environment",
            str(environment_path),
            "--out",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert not output.exists()


def test_cli_evaluated_failure_exits_one_and_writes_result(tmp_path: Path) -> None:
    output = tmp_path / "out"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/check_emc_esd.py"),
            "--graph",
            str(GRAPH_PATH),
            "--environment",
            str(ENVIRONMENT_PATH),
            "--out",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1
    result = json.loads((output / "emc-esd.json").read_text(encoding="utf-8"))
    assert result["status"] == "fail"
    assert result["certification_claim"] is False
