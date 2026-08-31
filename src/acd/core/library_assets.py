"""Single contract for declared symbol/footprint library assets.

A library declaration is either a container-absolute path pinned by an installed
package, or a path relative to the canonical in-repository asset store
``libraries/``. Both forms are resolved and hash-verified by this module, and a
generated fixture materializes its relative assets locally so the fixture stays
self-contained. A missing or mismatched asset stops fail-closed instead of
producing a fixture whose declarations cannot be resolved.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from acd.pipeline.repository import repository_root
from acd.schema.design_graph import DesignGraph

LIBRARY_ASSET_ROOT = "libraries"
LIBRARY_ASSET_ATTRS: tuple[tuple[str, str], ...] = (
    ("symbol_file", "symbol_sha256"),
    ("footprint_file", "footprint_sha256"),
)


class LibraryAssetError(ValueError):
    """Raised when a declared library asset cannot be resolved or verified."""


@dataclass(frozen=True)
class LibraryAsset:
    """One declared library asset and its declared content hash."""

    declared_path: str
    sha256: str

    @property
    def relative(self) -> bool:
        return not Path(self.declared_path).is_absolute()


def _sha256(path: Path) -> str:
    try:
        return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    except OSError as exc:
        raise LibraryAssetError(
            f"library asset is unavailable: {path}: {exc}"
        ) from exc


def library_asset_store() -> Path:
    """Return the canonical in-repository library asset store."""
    return repository_root() / LIBRARY_ASSET_ROOT


def resolve_library_asset(declared_path: str) -> Path:
    """Resolve one declared library path against its single declared contract."""
    path = Path(declared_path)
    if path.is_absolute():
        return path
    store = library_asset_store()
    resolved = (repository_root() / path).resolve()
    if not resolved.is_relative_to(store.resolve()):
        raise LibraryAssetError(
            "relative library asset must live under the canonical store "
            f"{LIBRARY_ASSET_ROOT}/: {declared_path}"
        )
    return resolved


def resolve_fixture_library_path(declared_path: str, fixture_dir: Path) -> Path:
    """Resolve one declared library path as one fixture resolves it.

    A fixture materialized from the canonical store carries its own copy, which
    keeps the fixture resolvable after it is copied elsewhere. A fixture that
    only declares the asset resolves it in the canonical store instead, so both
    forms answer the same declaration.
    """
    path = Path(declared_path)
    if path.is_absolute():
        return path
    candidate = fixture_dir / path
    if candidate.is_file():
        return candidate
    return resolve_library_asset(declared_path)


def verify_library_asset(asset: LibraryAsset) -> Path:
    """Resolve one declared asset and verify its declared content hash."""
    resolved = resolve_library_asset(asset.declared_path)
    actual = _sha256(resolved)
    if actual != asset.sha256:
        raise LibraryAssetError(
            "library asset sha256 does not match declaration: "
            f"{asset.declared_path}: declared {asset.sha256}, found {actual}"
        )
    return resolved


def graph_library_assets(graph: DesignGraph) -> tuple[LibraryAsset, ...]:
    """Return every declared component library asset in stable declared order."""
    return tuple(_iter_graph_assets(graph))


def _iter_graph_assets(graph: DesignGraph) -> Iterator[LibraryAsset]:
    seen: set[tuple[str, str]] = set()
    for node in sorted(graph.nodes, key=lambda item: item.id):
        if node.kind != "electrical.component":
            continue
        for path_attr, hash_attr in LIBRARY_ASSET_ATTRS:
            declared = node.attrs.get(path_attr)
            digest = node.attrs.get(hash_attr)
            if declared is None and digest is None:
                continue
            if not isinstance(declared, str) or not isinstance(digest, str):
                raise LibraryAssetError(
                    f"{node.id}: {path_attr} declaration is incomplete (fail-closed)"
                )
            key = (declared, digest)
            if key in seen:
                continue
            seen.add(key)
            yield LibraryAsset(declared_path=declared, sha256=digest)


def materialize_library_assets(
    graph: DesignGraph, fixture_dir: Path
) -> tuple[dict[str, str], ...]:
    """Copy declared relative library assets into one fixture directory.

    An absolute declaration is pinned by an installed package and stays where it
    is. A relative declaration is copied from the canonical store into the
    fixture, which makes the generated fixture resolvable by the same
    declaration it carries.
    """
    materialized: list[dict[str, str]] = []
    for asset in graph_library_assets(graph):
        if not asset.relative:
            continue
        source = verify_library_asset(asset)
        target = fixture_dir / asset.declared_path
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(source, target)
        except OSError as exc:
            raise LibraryAssetError(
                f"library asset could not be materialized: {target}: {exc}"
            ) from exc
        written = _sha256(target)
        if written != asset.sha256:
            raise LibraryAssetError(
                "materialized library asset sha256 does not match declaration: "
                f"{target}: declared {asset.sha256}, found {written}"
            )
        materialized.append(
            {
                "declared_path": asset.declared_path,
                "source_path": str(source),
                "sha256": asset.sha256,
            }
        )
    return tuple(materialized)


def verify_fixture_library_asset(asset: LibraryAsset, fixture_dir: Path) -> Path:
    """Verify one declared asset as one fixture resolves it.

    The fixture-local copy is preferred, exactly as the deterministic predicate
    path resolves it, and the canonical store is the declared fallback.
    """
    candidate = resolve_fixture_library_path(asset.declared_path, fixture_dir)
    if not asset.relative or not candidate.is_relative_to(fixture_dir):
        return verify_library_asset(asset)
    actual = _sha256(candidate)
    if actual != asset.sha256:
        raise LibraryAssetError(
            "fixture library asset sha256 does not match declaration: "
            f"{candidate}: declared {asset.sha256}, found {actual}"
        )
    return candidate


def verify_fixture_library_assets(
    graph: DesignGraph, fixture_dir: Path
) -> tuple[Path, ...]:
    """Verify that one fixture resolves and matches every declared asset."""
    return tuple(
        verify_fixture_library_asset(asset, fixture_dir)
        for asset in graph_library_assets(graph)
    )


def verify_materialized_library_assets(
    graph: DesignGraph, fixture_dir: Path
) -> tuple[Path, ...]:
    """Verify that every relative declaration exists inside one fixture.

    A container-absolute declaration is pinned by an installed package and is
    resolved by the deterministic pipeline where that package exists, so it is
    out of scope here. A relative declaration must be present in the fixture
    with the declared content hash, which is what makes a generated fixture
    resolvable by its own declarations.
    """
    resolved: list[Path] = []
    for asset in graph_library_assets(graph):
        if not asset.relative:
            continue
        local = fixture_dir / asset.declared_path
        if not local.is_file():
            raise LibraryAssetError(
                f"declared library asset is missing from the fixture: {local}"
            )
        resolved.append(verify_fixture_library_asset(asset, fixture_dir))
    return tuple(resolved)


__all__ = [
    "LIBRARY_ASSET_ROOT",
    "LibraryAsset",
    "LibraryAssetError",
    "graph_library_assets",
    "library_asset_store",
    "materialize_library_assets",
    "resolve_fixture_library_path",
    "resolve_library_asset",
    "verify_fixture_library_asset",
    "verify_fixture_library_assets",
    "verify_library_asset",
    "verify_materialized_library_assets",
]
