"""Canonical normalization for deterministic CAD projection artifacts."""

from __future__ import annotations

import io
import re
import zipfile


class CadNormalizationError(ValueError):
    """Raised when an artifact does not match the measured normalization contract."""


def normalize_step(data: bytes) -> bytes:
    """Normalize measured STEP metadata, failing closed otherwise."""
    text = data.decode("utf-8")
    pattern = r"(FILE_NAME\('Open CASCADE Shape Model',')[^']+(')"
    normalized, count = re.subn(
        pattern,
        r"\g<1>1970-01-01T00:00:00\g<2>",
        text,
    )
    if count != 1:
        raise CadNormalizationError(
            f"expected exactly one Open CASCADE FILE_NAME timestamp, got {count}"
        )
    normalized = re.sub(
        r"(NEXT_ASSEMBLY_USAGE_OCCURRENCE\()'[^']*'",
        r"\g<1>'0'",
        normalized,
    )
    return normalized.encode("utf-8")


def normalize_3mf(data: bytes) -> bytes:
    """Normalize measured 3MF UUID and ZIP timestamp metadata, failing closed otherwise."""
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        model_entries = [
            entry for entry in source.infolist() if entry.filename == "3D/3dmodel.model"
        ]
        if len(model_entries) != 1:
            raise CadNormalizationError(
                f"expected exactly one 3D/3dmodel.model entry, got {len(model_entries)}"
            )
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for entry in source.infolist():
                content = source.read(entry.filename)
                if entry.filename == "3D/3dmodel.model":
                    content = re.sub(
                        rb' p:UUID="[0-9a-fA-F-]+"',
                        b' p:UUID="00000000-0000-0000-0000-000000000000"',
                        content,
                    )
                info = zipfile.ZipInfo(entry.filename, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = entry.external_attr
                target.writestr(info, content)
    return output.getvalue()


def parse_stl(data: bytes) -> tuple[list[str], int, int, int]:
    """Parse an ASCII STL in one pass, returning lines and metadata."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CadNormalizationError("STL is not valid UTF-8 ASCII text") from exc
    try:
        text.encode("ascii")
    except UnicodeEncodeError as exc:
        raise CadNormalizationError("STL contains non-ASCII text") from exc
    lines: list[str] = []
    first_nonempty: int | None = None
    last_nonempty: int | None = None
    opening_count = 0
    closing_count = 0
    opening_index: int | None = None
    closing_index: int | None = None
    facet_count = 0
    facet_state: str | None = None
    vertex_count = 0
    for index, raw_line in enumerate(
        text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ):
        line = raw_line.rstrip()
        lines.append(line)
        stripped = line.strip()
        if not stripped:
            continue
        if first_nonempty is None:
            first_nonempty = index
        last_nonempty = index
        if re.fullmatch(r"\s*solid(?:\s+.*)?", line):
            opening_count += 1
            if opening_index is None:
                opening_index = index
            continue
        if re.fullmatch(r"\s*endsolid(?:\s+.*)?", line):
            closing_count += 1
            if closing_index is None:
                closing_index = index
            continue
        if opening_count == 0:
            continue
        if facet_state is None:
            if re.fullmatch(
                r"\s*facet\s+normal\s+[-+0-9.eE]+\s+[-+0-9.eE]+\s+[-+0-9.eE]+",
                line,
            ):
                facet_count += 1
                facet_state = "outer"
                vertex_count = 0
            continue
        if facet_state == "outer":
            if stripped != "outer loop":
                raise CadNormalizationError("STL facet has an invalid loop")
            facet_state = "vertices"
            continue
        if facet_state == "vertices":
            if stripped.startswith("vertex "):
                vertex_count += 1
                continue
            if stripped == "endloop":
                if vertex_count != 3:
                    raise CadNormalizationError(
                        "STL facet must contain exactly three vertices"
                    )
                facet_state = "endfacet"
                continue
            raise CadNormalizationError("STL facet has an invalid loop")
        if facet_state == "endfacet":
            if stripped != "endfacet":
                raise CadNormalizationError("STL facet has an invalid loop")
            facet_state = None
            continue
    if opening_count != 1 or closing_count != 1:
        raise CadNormalizationError(
            f"expected exactly one solid/endsolid pair, got {opening_count}/{closing_count}"
        )
    if (
        first_nonempty is None
        or last_nonempty is None
        or opening_index is None
        or closing_index is None
    ):
        raise CadNormalizationError("STL solid delimiters must enclose the entire file")
    if opening_index != first_nonempty or closing_index != last_nonempty:
        raise CadNormalizationError("STL solid delimiters must enclose the entire file")
    if facet_count == 0:
        raise CadNormalizationError("STL must contain at least one facet normal block")
    if facet_state is not None:
        raise CadNormalizationError("STL facet is missing endfacet")
    return lines, facet_count, opening_index, closing_index


def normalize_stl(data: bytes) -> bytes:
    """Normalize an ASCII STL, failing closed for non-structural input."""
    lines, _, opening, closing = parse_stl(data)
    lines[opening] = "solid acd"
    lines[closing] = "endsolid acd"
    return ("\n".join(lines).rstrip("\n") + "\n").encode("utf-8")
