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
