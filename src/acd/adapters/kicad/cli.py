"""kicad-cli invocations (ERC, DRC, netlist, Gerber, drill) with envelopes.

The adapter only runs the tool and reports parsed results; pass/fail
judgment stays in the pipeline. ERC/DRC exit code 5 (violations found) is a
valid tool outcome, not a tool failure.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from acd.core.process import ExternalToolError, ToolRun, run_tool

_EXIT_OK_OR_VIOLATIONS = frozenset({0, 5})


@dataclass(frozen=True)
class RuleCheckResult:
    run: ToolRun
    report_path: Path
    violations: tuple[dict[str, object], ...]
    unconnected_items: tuple[dict[str, object], ...]

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.get("severity") == "error")


class KicadCli:
    def __init__(self, executable: str = "kicad-cli") -> None:
        self.executable = executable
        self._version: str | None = None

    def version(self) -> str:
        if self._version is None:
            try:
                result = subprocess.run(
                    [self.executable, "version"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
            except OSError as exc:
                raise ExternalToolError("kicad-cli version probe failed (fail-closed)") from exc
            match = re.search(r"\d+\.\d+\.\d+", result.stdout)
            if result.returncode != 0 or match is None:
                raise ExternalToolError("kicad-cli version probe failed (fail-closed)")
            self._version = match.group(0)
        return self._version

    def _rule_check(
        self,
        subcommand: list[str],
        source: Path,
        report_path: Path,
        target_revision: str,
        unconnected_key: str | None,
    ) -> RuleCheckResult:
        command = [
            self.executable,
            *subcommand,
            "--format",
            "json",
            "--severity-all",
            "--exit-code-violations",
            "-o",
            str(report_path),
            str(source),
        ]
        run = run_tool(
            tool_name="kicad-cli",
            tool_version=self.version(),
            format_version=self.version(),
            command=command,
            input_paths=[source],
            output_paths=[report_path],
            envelope_path=report_path.with_suffix(report_path.suffix + ".envelope.json"),
            target_revision=target_revision,
            measurement_conditions="single run; project-local library tables",
            allowed_exit_codes=_EXIT_OK_OR_VIOLATIONS,
        )
        report = json.loads(report_path.read_text())
        # DRC reports carry violations at top level; ERC nests them per sheet.
        collected: list[dict[str, object]] = list(report.get("violations", []))
        for sheet in report.get("sheets", []):
            collected.extend(sheet.get("violations", []))
        violations = tuple(collected)
        unconnected: tuple[dict[str, object], ...] = ()
        if unconnected_key is not None:
            unconnected = tuple(report.get(unconnected_key, []))
        return RuleCheckResult(
            run=run,
            report_path=report_path,
            violations=violations,
            unconnected_items=unconnected,
        )

    def erc(self, schematic: Path, report_path: Path, target_revision: str) -> RuleCheckResult:
        return self._rule_check(["sch", "erc"], schematic, report_path, target_revision, None)

    def drc(self, board: Path, report_path: Path, target_revision: str) -> RuleCheckResult:
        return self._rule_check(
            ["pcb", "drc"], board, report_path, target_revision, "unconnected_items"
        )

    def refill_zones(self, board: Path, target_revision: str) -> ToolRun:
        """Refill zones in place before any manufacturing projection."""
        command = [
            self.executable,
            "pcb",
            "drc",
            "--refill-zones",
            "--save-board",
            str(board),
        ]
        return run_tool(
            tool_name="kicad-cli",
            tool_version=self.version(),
            format_version=self.version(),
            command=command,
            input_paths=[board],
            output_paths=[board],
            envelope_path=board.with_suffix(board.suffix + ".refill.envelope.json"),
            target_revision=target_revision,
            measurement_conditions=(
                "zone refill; save-board; sibling project file and project-local "
                "library tables"
            ),
        )

    def export_netlist(self, schematic: Path, out_path: Path, target_revision: str) -> ToolRun:
        command = [
            self.executable,
            "sch",
            "export",
            "netlist",
            "--format",
            "kicadsexpr",
            "-o",
            str(out_path),
            str(schematic),
        ]
        return run_tool(
            tool_name="kicad-cli",
            tool_version=self.version(),
            format_version=self.version(),
            command=command,
            input_paths=[schematic],
            output_paths=[out_path],
            envelope_path=out_path.with_suffix(out_path.suffix + ".envelope.json"),
            target_revision=target_revision,
            measurement_conditions="single run; project-local library tables",
        )

    def export_gerbers(
        self, board: Path, out_dir: Path, layers: list[str], target_revision: str
    ) -> tuple[ToolRun, list[Path]]:
        out_dir.mkdir(parents=True, exist_ok=True)
        command = [
            self.executable,
            "pcb",
            "export",
            "gerbers",
            "--layers",
            ",".join(layers),
            "--no-x2",
            "--no-netlist",
            "--disable-aperture-macros",
            "-o",
            str(out_dir) + "/",
            str(board),
        ]
        expected = [
            out_dir / f"{board.stem}-{_gerber_stem(layer)}.{_gerber_ext(layer)}"
            for layer in layers
        ]
        run = run_tool(
            tool_name="kicad-cli",
            tool_version=self.version(),
            format_version="RS-274X",
            command=command,
            input_paths=[board],
            output_paths=expected,
            envelope_path=out_dir / "gerbers.envelope.json",
            target_revision=target_revision,
            measurement_conditions="single run; no X2 attributes",
        )
        return run, expected

    def export_drill(
        self, board: Path, out_dir: Path, target_revision: str
    ) -> tuple[ToolRun, list[Path]]:
        out_dir.mkdir(parents=True, exist_ok=True)
        command = [
            self.executable,
            "pcb",
            "export",
            "drill",
            "--format",
            "excellon",
            "--excellon-units",
            "mm",
            "--excellon-zeros-format",
            "decimal",
            "-o",
            str(out_dir) + "/",
            str(board),
        ]
        expected = [out_dir / f"{board.stem}.drl"]
        run = run_tool(
            tool_name="kicad-cli",
            tool_version=self.version(),
            format_version="excellon",
            command=command,
            input_paths=[board],
            output_paths=expected,
            envelope_path=out_dir / "drill.envelope.json",
            target_revision=target_revision,
            measurement_conditions="single run; mm decimal excellon",
        )
        return run, expected

    def export_pos(self, board: Path, out_path: Path, target_revision: str) -> ToolRun:
        command = [
            self.executable,
            "pcb",
            "export",
            "pos",
            "--format",
            "csv",
            "--units",
            "mm",
            "--side",
            "both",
            "--exclude-dnp",
            "-o",
            str(out_path),
            str(board),
        ]
        return run_tool(
            tool_name="kicad-cli",
            tool_version=self.version(),
            format_version="KiCad position CSV",
            command=command,
            input_paths=[board],
            output_paths=[out_path],
            envelope_path=out_path.with_suffix(out_path.suffix + ".envelope.json"),
            target_revision=target_revision,
            measurement_conditions="csv; mm; both sides; exclude DNP; shared board origin",
        )


_GERBER_FILES = {
    "F.Cu": ("F_Cu", "gtl"),
    "B.Cu": ("B_Cu", "gbl"),
    "F.Mask": ("F_Mask", "gts"),
    "B.Mask": ("B_Mask", "gbs"),
    "F.SilkS": ("F_Silkscreen", "gto"),
    "B.SilkS": ("B_Silkscreen", "gbo"),
    "F.Paste": ("F_Paste", "gtp"),
    "B.Paste": ("B_Paste", "gbp"),
    "Edge.Cuts": ("Edge_Cuts", "gm1"),
}


def _gerber_stem(layer: str) -> str:
    entry = _GERBER_FILES.get(layer)
    if entry is None:
        raise ExternalToolError(f"unknown gerber layer {layer!r} (fail-closed)")
    return entry[0]


def _gerber_ext(layer: str) -> str:
    entry = _GERBER_FILES.get(layer)
    if entry is None:
        raise ExternalToolError(f"unknown gerber layer {layer!r} (fail-closed)")
    return entry[1]
