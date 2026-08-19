"""KiCad CLI adapter for reproducible visual projection records."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from acd.adapters.kicad.cli import KicadCli
from acd.core.process import ExternalToolError, run_tool
from acd.core.visual_projection import (
    SVG_TITLE_NORMALIZATION_RULE_DESCRIPTION,
    SVG_TITLE_NORMALIZATION_RULE_ID,
    measure_svg_resolution,
    normalized_svg_sha256,
)
from acd.schema.visual_projection import (
    VisualProjectionDomain,
    VisualProjectionInput,
    VisualProjectionRecord,
    VisualProjectionType,
    VisualRegenerationCheck,
    VisualRendererProvenance,
    VisualResolution,
)


def _content_hash(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


class KicadVisualRenderer:
    """Render supported KiCad visual projections and verify regeneration."""

    def __init__(self, kicad: KicadCli | None = None) -> None:
        self.kicad = kicad or KicadCli()

    def _export(
        self,
        projection_type: VisualProjectionType,
        source: Path,
        output: Path,
        target_revision: str,
        layer: str | None,
    ) -> None:
        if projection_type == "schematic_view":
            command = [
                self.kicad.executable,
                "sch",
                "export",
                "svg",
                "-o",
                str(output),
                str(source),
            ]
        else:
            if layer is None or not layer.strip():
                raise ExternalToolError("layered layout view requires a layer")
            command = [
                self.kicad.executable,
                "pcb",
                "export",
                "svg",
                "--layers",
                layer,
                "-o",
                str(output),
                str(source),
            ]
        run_tool(
            tool_name="kicad-cli",
            tool_version=self.kicad.version(),
            format_version="SVG",
            command=command,
            input_paths=[source],
            output_paths=[output],
            envelope_path=output.with_suffix(output.suffix + ".envelope.json"),
            target_revision=target_revision,
            measurement_conditions="single SVG export; measured root dimensions",
        )

    def render(
        self,
        *,
        projection_id: str,
        projection_type: VisualProjectionType,
        domain: VisualProjectionDomain,
        source_revision: str,
        source: Path,
        output_path: Path,
        layer: str | None = None,
    ) -> VisualProjectionRecord:
        if source.is_absolute() or output_path.is_absolute():
            raise ExternalToolError("visual projection paths must be repository-relative")
        reproduction_path = output_path.with_name(
            f"{output_path.stem}.reproduced{output_path.suffix}"
        )
        self._export(projection_type, source, output_path, source_revision, layer)
        first = output_path.read_bytes()
        first_hash = normalized_svg_sha256(first)
        measured = measure_svg_resolution(first)
        self._export(projection_type, source, reproduction_path, source_revision, layer)
        second_hash = normalized_svg_sha256(reproduction_path.read_bytes())
        if first_hash != second_hash:
            raise ExternalToolError("visual projection regeneration hash mismatch")
        return VisualProjectionRecord(
            projection_id=projection_id,
            projection_type=projection_type,
            domain=domain,
            source_revision=source_revision,
            input_files=[
                VisualProjectionInput(path=source.as_posix(), content_hash=_content_hash(source))
            ],
            renderer=VisualRendererProvenance(tool_version=self.kicad.version()),
            resolution=VisualResolution(
                width=measured.width,
                height=measured.height,
                view_box=measured.view_box,
            ),
            normalization_rule_id=SVG_TITLE_NORMALIZATION_RULE_ID,
            normalization_rule_description=SVG_TITLE_NORMALIZATION_RULE_DESCRIPTION,
            image_hash=first_hash,
            generated_at=datetime.now(UTC),
            regeneration_check=VisualRegenerationCheck(
                status="reproduced",
                first_image_hash=first_hash,
                second_image_hash=second_hash,
            ),
            image_path=output_path.as_posix(),
        )
