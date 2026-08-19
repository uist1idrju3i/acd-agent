"""KiCad CLI adapter for reproducible visual projection records."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from acd.adapters.kicad.cli import KicadCli
from acd.core.process import ExternalToolError, run_tool, sha256_bytes
from acd.core.visual_projection import (
    SVG_TITLE_NORMALIZATION_RULE_DESCRIPTION,
    SVG_TITLE_NORMALIZATION_RULE_ID,
    measure_svg_resolution,
    normalized_svg_sha256,
)
from acd.pipeline.repository import repository_root
from acd.schema.visual_projection import (
    VisualProjectionDomain,
    VisualProjectionInput,
    VisualProjectionRecord,
    VisualProjectionType,
    VisualRegenerationCheck,
    VisualRendererProvenance,
    VisualResolution,
)

_KICAD_COPPER_LAYERS_BY_COUNT: dict[int, tuple[str, ...]] = {
    2: ("F.Cu", "B.Cu"),
    4: ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"),
}


def copper_layers_for_layer_count(layer_count: int) -> tuple[str, ...]:
    """Return KiCad copper-layer names for a supported board layer count."""
    if isinstance(layer_count, bool) or layer_count not in _KICAD_COPPER_LAYERS_BY_COUNT:
        raise ValueError(f"unsupported KiCad copper layer count: {layer_count!r}")
    return _KICAD_COPPER_LAYERS_BY_COUNT[layer_count]


class KicadVisualRenderer:
    """Render supported KiCad visual projections and verify regeneration."""

    def __init__(self, kicad: KicadCli | None = None) -> None:
        self.kicad = kicad or KicadCli()

    def _export(
        self,
        projection_type: VisualProjectionType,
        source: Path,
        output: Path,
        envelope: Path,
        target_revision: str,
        layer: str | None,
    ) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
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
            envelope_path=envelope,
            target_revision=target_revision,
            measurement_conditions="single SVG export; measured root dimensions",
        )

    @staticmethod
    def _resolve_within_base(path: Path, base_dir: Path, field_name: str) -> Path:
        candidate = path if path.is_absolute() else base_dir / path
        resolved = candidate.resolve()
        try:
            resolved.relative_to(base_dir)
        except ValueError as exc:
            raise ExternalToolError(
                f"visual projection {field_name} must stay within base directory"
            ) from exc
        return resolved

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
        base_dir: Path | None = None,
    ) -> VisualProjectionRecord:
        root = (base_dir or repository_root()).resolve()
        source_path = self._resolve_within_base(source, root, "source")
        output = self._resolve_within_base(output_path, root, "output")
        reproduction_path = output.parent / "reproduction" / (
            f"{output.stem}.reproduced{output.suffix}"
        )
        reproduction_path.parent.mkdir(parents=True, exist_ok=True)
        self._export(
            projection_type,
            source_path,
            output,
            output.with_suffix(output.suffix + ".envelope.json"),
            source_revision,
            layer,
        )
        first = output.read_bytes()
        first_hash = normalized_svg_sha256(first)
        measured = measure_svg_resolution(first)
        self._export(
            projection_type,
            source_path,
            reproduction_path,
            reproduction_path.with_suffix(reproduction_path.suffix + ".envelope.json"),
            source_revision,
            layer,
        )
        second_hash = normalized_svg_sha256(reproduction_path.read_bytes())
        if first_hash != second_hash:
            raise ExternalToolError("visual projection regeneration hash mismatch")
        source_record_path = source_path.relative_to(root).as_posix()
        output_record_path = output.relative_to(root).as_posix()
        return VisualProjectionRecord(
            projection_id=projection_id,
            projection_type=projection_type,
            domain=domain,
            source_revision=source_revision,
            input_files=[
                VisualProjectionInput(
                    path=source_record_path,
                    content_hash=sha256_bytes(source_path.read_bytes()),
                )
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
            image_path=output_record_path,
        )
