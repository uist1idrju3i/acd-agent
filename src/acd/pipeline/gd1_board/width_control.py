"""KiCad netclass width positive controls and DSN class correspondence."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

from acd.adapters.kicad.cli import KicadCli
from acd.adapters.kicad.gates import assert_rule_check_input_matches
from acd.core.electrical.board_model import NetClass
from acd.core.runtime.fileio import read_json

from .evidence import summarize_width_violations


def run_ordered_arms(
    run_arm: Callable[[str, bool], dict[str, object]],
    workers: int,
) -> tuple[dict[str, object], dict[str, object]]:
    """Run independent controls concurrently while collecting them in arm order."""
    if workers < 1:
        raise ValueError("width control worker count must be at least 1")
    controls = (
        ("arm-a-class-only", False),
        ("arm-b-class-and-board-minimum", True),
    )
    if workers == 1:
        results = [run_arm(name, board_minimum) for name, board_minimum in controls]
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(run_arm, name, board_minimum) for name, board_minimum in controls
            ]
            results = [future.result() for future in futures]
    return results[0], results[1]


def run_kicad_netclass_positive_control(
    kicad: KicadCli,
    routed_path: Path,
    project_path: Path,
    dru_path: Path,
    out_dir: Path,
    revision: str,
    normal_width_mm: float,
    workers: int,
) -> dict[str, object]:
    """Measure class-only and board-level KiCad width controls."""
    control_dir = out_dir / "kicad-netclass-positive-control"
    control_dir.mkdir(parents=True, exist_ok=True)
    project_data = cast(dict[str, object], read_json(project_path))
    net_settings = project_data.get("net_settings")
    net_settings = cast(dict[str, object], net_settings) if isinstance(net_settings, dict) else None
    classes = (
        cast(list[dict[str, object]], net_settings["classes"])
        if net_settings is not None and isinstance(net_settings.get("classes"), list)
        else None
    )
    patterns = (
        cast(list[dict[str, object]], net_settings["netclass_patterns"])
        if net_settings is not None and isinstance(net_settings.get("netclass_patterns"), list)
        else None
    )
    if not isinstance(classes, list) or not isinstance(patterns, list):
        raise ValueError("KiCad netclass positive-control schema is missing")
    custom: dict[str, object] | None = next(
        (item for item in classes if item.get("name") != "Default"),
        None,
    )
    pattern: dict[str, object] | None = next(
        (item for item in patterns if item.get("netclass") == (custom or {}).get("name")),
        None,
    )
    if custom is None or pattern is None:
        raise ValueError("KiCad netclass positive-control mapping is missing")
    class_name = custom.get("name")
    net_name = pattern.get("pattern")
    if not isinstance(class_name, str) or not isinstance(net_name, str):
        raise ValueError("KiCad netclass positive-control names are invalid")
    inflated_width_mm = max(normal_width_mm * 2.0, normal_width_mm + 0.25)
    custom["track_width"] = inflated_width_mm
    board_settings_obj = project_data.get("board")
    board_settings = (
        cast(dict[str, object], board_settings_obj)
        if isinstance(board_settings_obj, dict)
        else None
    )
    design_settings_obj = (
        board_settings.get("design_settings") if board_settings is not None else None
    )
    design_settings = (
        cast(dict[str, object], design_settings_obj)
        if isinstance(design_settings_obj, dict)
        else None
    )
    rules_obj = design_settings.get("rules") if design_settings is not None else None
    rules = cast(dict[str, object], rules_obj) if isinstance(rules_obj, dict) else None
    if not isinstance(rules, dict):
        raise ValueError("KiCad board DRC rules are missing")
    original_min_track_width = rules.get("min_track_width")
    if not isinstance(original_min_track_width, (int, float)):
        raise ValueError("KiCad board minimum track width is invalid")

    def run_arm(name: str, change_board_minimum: bool) -> dict[str, object]:
        arm_dir = control_dir / name
        arm_dir.mkdir(parents=True, exist_ok=True)
        arm_board = arm_dir / routed_path.name
        arm_project = arm_dir / project_path.name
        arm_dru = arm_dir / dru_path.name
        shutil.copy2(routed_path, arm_board)
        shutil.copy2(project_path, arm_project)
        if dru_path.is_file():
            shutil.copy2(dru_path, arm_dru)
        arm_project_data = cast(
            dict[str, object],
            read_json(arm_project),
        )
        arm_net_settings_obj = arm_project_data.get("net_settings")
        arm_net_settings = (
            cast(dict[str, object], arm_net_settings_obj)
            if isinstance(arm_net_settings_obj, dict)
            else None
        )
        if arm_net_settings is None:
            raise ValueError(f"{name}: KiCad net settings are missing")
        arm_classes_obj = arm_net_settings.get("classes")
        arm_classes = (
            cast(list[dict[str, object]], arm_classes_obj)
            if isinstance(arm_classes_obj, list)
            else None
        )
        if arm_classes is None:
            raise ValueError(f"{name}: KiCad netclass list is missing")
        arm_custom = next(
            (item for item in arm_classes if item.get("name") == class_name),
            None,
        )
        if arm_custom is None:
            raise ValueError(f"{name}: selected KiCad netclass is missing")
        arm_custom["track_width"] = inflated_width_mm
        arm_board_settings_obj = arm_project_data.get("board")
        arm_board_settings = (
            cast(dict[str, object], arm_board_settings_obj)
            if isinstance(arm_board_settings_obj, dict)
            else None
        )
        if arm_board_settings is None:
            raise ValueError(f"{name}: KiCad board settings are missing")
        arm_design_settings_obj = arm_board_settings.get("design_settings")
        arm_design_settings = (
            cast(dict[str, object], arm_design_settings_obj)
            if isinstance(arm_design_settings_obj, dict)
            else None
        )
        if arm_design_settings is None:
            raise ValueError(f"{name}: KiCad design settings are missing")
        arm_rules_obj = arm_design_settings.get("rules")
        arm_rules = (
            cast(dict[str, object], arm_rules_obj) if isinstance(arm_rules_obj, dict) else None
        )
        if arm_rules is None:
            raise ValueError(f"{name}: KiCad DRC rules are missing")
        if change_board_minimum:
            arm_rules["min_track_width"] = inflated_width_mm
        else:
            arm_rules["min_track_width"] = original_min_track_width
        arm_project.write_text(
            json.dumps(arm_project_data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report_path = arm_dir / "positive-control.drc.json"
        result = kicad.drc(arm_board, report_path, revision)
        assert_rule_check_input_matches(f"DRC {name}", result, [arm_board])
        summary = summarize_width_violations(
            result,
            net_name,
            report_path.relative_to(out_dir),
        )
        summary.update(
            {
                "class_track_width_mm": inflated_width_mm,
                "board_min_track_width_mm": arm_rules["min_track_width"],
                "board_min_track_width_changed": change_board_minimum,
            }
        )
        return summary

    arm_a, arm_b = run_ordered_arms(run_arm, workers)
    class_only_detected = bool(arm_a["width_violation_count"])
    board_level_detected = bool(arm_b["width_violation_count"])
    if not class_only_detected and not board_level_detected:
        raise ValueError(
            "KiCad width projection positive controls produced no width violation "
            "in either arm (fail-closed)"
        )
    return {
        "class": class_name,
        "net": net_name,
        "normal_track_width_mm": normal_width_mm,
        "intentionally_inflated_track_width_mm": inflated_width_mm,
        "original_board_min_track_width_mm": original_min_track_width,
        "arm_a_class_only": arm_a,
        "arm_b_class_and_board_minimum": arm_b,
        "class_only_width_violation_detected": class_only_detected,
        "board_level_width_violation_detected": board_level_detected,
        "interpretation": (
            "Arm A measures whether class-only projection affects existing-track "
            "DRC; Arm B measures board-level minimum-width enforcement."
        ),
    }


def measure_dsn_class_correspondence(
    dsn_path: Path,
    netclasses: tuple[NetClass, ...],
    net_evidence: dict[str, object],
    tolerance_mm: float,
) -> dict[str, object]:
    text = dsn_path.read_text(encoding="utf-8")
    class_matches = list(
        re.finditer(
            r'(?ms)^\s*\(class "([^"]+)" ""(.*?)^\s*\)\s*$',
            text,
        )
    )
    if not class_matches:
        raise ValueError("DSN netclass declarations are missing (fail-closed)")
    expected_names = {item.name for item in netclasses}
    observed: dict[str, dict[str, object]] = {}
    for match in class_matches:
        name = match.group(1)
        body = match.group(2)
        width_match = re.search(r"\(rule \(width ([0-9]+(?:\.[0-9]+)?)\)", body)
        member_names = re.findall(r'"([^"]+)"', body.split("(circuit", 1)[0])
        if width_match is None or name in observed:
            raise ValueError("DSN netclass width declaration is malformed (fail-closed)")
        width_mm = float(width_match.group(1)) / 1000.0
        measured: dict[str, float] = {}
        for net_name in member_names:
            raw_obj = net_evidence.get(net_name)
            raw = cast(dict[str, object], raw_obj) if isinstance(raw_obj, dict) else None
            measured_minimum = raw.get("measured_minimum_mm") if raw is not None else None
            if not isinstance(measured_minimum, (int, float)):
                raise ValueError(f"DSN net {net_name!r} measurement is missing (fail-closed)")
            measured[net_name] = float(measured_minimum)
        observed[name] = {
            "dsn_width_mm": width_mm,
            "members": sorted(member_names),
            "measured_minimum_widths_mm": measured,
            "measured_width_at_least_dsn_width": all(
                value + tolerance_mm >= width_mm for value in measured.values()
            ),
        }
    if set(observed) != expected_names:
        raise ValueError("DSN netclass set differs from projected netclasses (fail-closed)")
    return {
        "measurement_method": (
            "independent parse of generated DSN class rule widths matched to "
            "post-refill Gerber net widths"
        ),
        "tolerance_mm": tolerance_mm,
        "classes": observed,
        "all_classes_correspond": all(
            bool(item["measured_width_at_least_dsn_width"]) for item in observed.values()
        ),
    }
