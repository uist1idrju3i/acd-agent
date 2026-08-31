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


def normalize_stl(data: bytes) -> bytes:
    """Normalize an ASCII STL, failing closed for non-structural input."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CadNormalizationError("STL is not valid UTF-8 ASCII text") from exc
    try:
        text.encode("ascii")
    except UnicodeEncodeError as exc:
        raise CadNormalizationError("STL contains non-ASCII text") from exc
    lines = [
        line.rstrip()
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    nonempty = [index for index, line in enumerate(lines) if line.strip()]
    opening = [
        index
        for index in nonempty
        if re.fullmatch(r"\s*solid(?:\s+.*)?", lines[index])
    ]
    closing = [
        index
        for index in nonempty
        if re.fullmatch(r"\s*endsolid(?:\s+.*)?", lines[index])
    ]
    if len(opening) != 1 or len(closing) != 1:
        raise CadNormalizationError(
            f"expected exactly one solid/endsolid pair, got {len(opening)}/{len(closing)}"
        )
    if opening[0] != nonempty[0] or closing[0] != nonempty[-1]:
        raise CadNormalizationError("STL solid delimiters must enclose the entire file")
    facet_indices = [
        index
        for index in nonempty
        if re.fullmatch(
            r"\s*facet\s+normal\s+[-+0-9.eE]+\s+[-+0-9.eE]+\s+[-+0-9.eE]+",
            lines[index],
        )
    ]
    if not facet_indices:
        raise CadNormalizationError("STL must contain at least one facet normal block")
    for facet_index in facet_indices:
        try:
            end_index = next(
                index
                for index in nonempty
                if index > facet_index and lines[index].strip() == "endfacet"
            )
        except StopIteration as exc:
            raise CadNormalizationError("STL facet is missing endfacet") from exc
        block = [
            lines[index].strip()
            for index in nonempty
            if facet_index <= index <= end_index
        ]
        if block[1:2] != ["outer loop"] or block[-2:-1] != ["endloop"]:
            raise CadNormalizationError("STL facet has an invalid loop")
        vertices = [line for line in block if line.startswith("vertex ")]
        if len(vertices) != 3:
            raise CadNormalizationError("STL facet must contain exactly three vertices")
    lines[opening[0]] = "solid acd"
    lines[closing[0]] = "endsolid acd"
    return ("\n".join(lines).rstrip("\n") + "\n").encode("utf-8")
