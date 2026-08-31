"""Independent L1 evaluation of manufacturing-submission artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from gerbonara.rs274x import GerberFile  # pyright: ignore[reportMissingTypeStubs]

from acd.adapters.cad.mechanical import (
    measure_enclosure_artifacts,
    measure_enclosure_mesh_artifacts,
)
from acd.adapters.kicad.fab.archive import zip_content_hash
from acd.adapters.kicad.reload import (
    ReloadError,
    normalized_hash,
    verify_drill,
    verify_gerber,
)
from acd.core.cad_normalize import normalize_3mf, normalize_step, normalize_stl
from acd.core.fab import resolve_fab_profile_path
from acd.schema.common import canonical_json_sha256
from acd.schema.design_graph import DesignGraph
from acd.schema.evidence import Evidence
from acd.schema.manufacturing_submission import (
    CheckId,
    ManufacturingSubmissionArtifact,
    ManufacturingSubmissionCheck,
    ManufacturingSubmissionVerdict,
)


class ManufacturingSubmissionError(ValueError):
    """Raised when the submission evaluator cannot construct a fail-closed verdict."""


_CHECK_IDS = (
    "required_artifacts",
    "independent_reload",
    "normalized_hashes",
    "dfm",
    "geometry",
    "fab_profile_consistency",
    "revision_consistency",
    "evidence_validity",
)
_REQUIRED_LAYERS = (
    "F.Cu",
    "B.Cu",
    "F.Mask",
    "B.Mask",
    "F.SilkS",
    "B.SilkS",
    "F.Paste",
    "Edge.Cuts",
)
_GERBER_SUFFIXES = frozenset(
    {".gtl", ".gbl", ".gts", ".gbs", ".gto", ".gbo", ".gtp", ".gbp", ".gm1", ".gbr"}
)
_BOARD_OUTLINE_TOLERANCE_MM = 0.2


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManufacturingSubmissionError(f"{path}: invalid JSON") from exc
    if not isinstance(value, dict):
        raise ManufacturingSubmissionError(f"{path}: JSON root is not an object")
    return cast(dict[str, Any], value)


def _path_from_entry(root: Path, entry: dict[str, Any]) -> Path:
    raw = entry.get("path")
    if not isinstance(raw, str) or not raw:
        raise ManufacturingSubmissionError("fab-package file entry has no path")
    path = root / raw
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ManufacturingSubmissionError(f"artifact path escapes output directory: {raw}")
    return path


def _artifact_hash(path: Path, fmt: str) -> str:
    if fmt == "ZIP":
        return zip_content_hash(path)
    if fmt == "STEP":
        data = normalize_step(path.read_bytes())
    elif fmt == "3MF":
        data = normalize_3mf(path.read_bytes())
    elif fmt == "STL":
        data = normalize_stl(path.read_bytes())
    else:
        return normalized_hash(path)
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _format_for(path: Path) -> str:
    return {
        ".step": "STEP",
        ".3mf": "3MF",
        ".stl": "STL",
        ".zip": "ZIP",
        ".gbrjob": "GBRJOB",
        ".drl": "DRILL",
        ".csv": "CSV",
        ".json": "JSON",
    }.get(path.suffix.lower(), path.suffix.upper().lstrip(".") or "FILE")


def _check(
    check_id: CheckId,
    operation: Callable[[], str],
) -> ManufacturingSubmissionCheck:
    try:
        return ManufacturingSubmissionCheck(check_id=check_id, status="pass", detail=operation())
    except Exception as exc:
        return ManufacturingSubmissionCheck(
            check_id=check_id,
            status="fail",
            detail=f"{type(exc).__name__}: {exc}",
        )


def _read_evidence(path: Path) -> Evidence:
    try:
        return Evidence.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ManufacturingSubmissionError(f"{path}: invalid Evidence") from exc


def _revision_from_envelope(path: Path) -> str:
    value = _load_json(path)
    revision = value.get("target_revision")
    if not isinstance(revision, str) or not revision:
        raise ManufacturingSubmissionError(f"{path}: target_revision is missing")
    return revision


def _fitted_refdes_from_bom(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or not {"Comment", "Designator", "Footprint", "LCSC Part #"} <= set(rows[0]):
        raise ManufacturingSubmissionError(f"{path.name}: BOM headers or rows are missing")
    refs: set[str] = set()
    for row in rows:
        values = {item.strip() for item in row["Designator"].split(",") if item.strip()}
        if not values or refs.intersection(values):
            raise ManufacturingSubmissionError(f"{path.name}: invalid designator rows")
        refs.update(values)
    return refs


def _fitted_refdes_from_cpl(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or not {"Designator", "Mid X", "Mid Y", "Rotation", "Layer"} <= set(rows[0]):
        raise ManufacturingSubmissionError(f"{path.name}: CPL headers or rows are missing")
    refs = {row["Designator"].strip() for row in rows if row["Designator"].strip()}
    if len(refs) != len(rows):
        raise ManufacturingSubmissionError(f"{path.name}: invalid designator rows")
    return refs


def _gbrjob_files(path: Path) -> tuple[set[str], dict[str, Any]]:
    value = _load_json(path)
    header = value.get("Header")
    files = value.get("FilesAttributes")
    if not isinstance(header, dict) or not isinstance(files, list):
        raise ManufacturingSubmissionError(f"{path.name}: FilesAttributes or Header is missing")
    names: set[str] = set()
    for item in cast(list[Any], files):
        if not isinstance(item, dict):
            raise ManufacturingSubmissionError(f"{path.name}: malformed FilesAttributes entry")
        item_mapping = cast(dict[str, Any], item)
        filename = item_mapping.get("Path", item_mapping.get("FileName"))
        if not isinstance(filename, str) or not filename:
            raise ManufacturingSubmissionError(f"{path.name}: file name is missing")
        names.add(Path(filename).name)
    return names, value


def _edge_bbox(path: Path) -> tuple[float, float, float, float]:
    try:
        layer = cast(Any, GerberFile.open(path))  # pyright: ignore[reportUnknownMemberType]
        bounds: Any = layer.bounding_box()
    except Exception as exc:
        raise ManufacturingSubmissionError(f"{path.name}: Edge.Cuts cannot be reloaded") from exc
    if bounds is None:
        raise ManufacturingSubmissionError(f"{path.name}: Edge.Cuts has no geometry")
    lower, upper = cast(tuple[tuple[float, float], tuple[float, float]], bounds)
    return float(lower[0]), float(lower[1]), float(upper[0]), float(upper[1])


def evaluate_manufacturing_submission(
    *,
    board_dir: Path,
    enclosure_dir: Path,
    graph_path: Path,
    require_authoritative: bool = False,
) -> ManufacturingSubmissionVerdict:
    """Evaluate all manufacturing artifacts without consulting order execution."""
    try:
        graph = DesignGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
        package_path = board_dir / "fab" / "fab-package.json"
        package = _load_json(package_path)
    except Exception as exc:
        raise ManufacturingSubmissionError(f"submission inputs are invalid: {exc}") from exc
    files_obj = package.get("files")
    if not isinstance(files_obj, list):
        raise ManufacturingSubmissionError("fab-package files are missing")
    file_items = cast(list[Any], files_obj)
    entries = [cast(dict[str, Any], item) for item in file_items if isinstance(item, dict)]
    if len(entries) != len(file_items):
        raise ManufacturingSubmissionError("fab-package file entry is malformed")
    path_entries = {
        str(item["path"]): item for item in entries if isinstance(item.get("path"), str)
    }
    paths = {name: _path_from_entry(board_dir, item) for name, item in path_entries.items()}
    enclosure_manifest_path = enclosure_dir / "enclosure-artifacts.json"
    enclosure_manifest = _load_json(enclosure_manifest_path)
    enclosure_entries_obj = enclosure_manifest.get("artifacts")
    if not isinstance(enclosure_entries_obj, list):
        raise ManufacturingSubmissionError("enclosure-artifacts artifacts are missing")
    enclosure_items = cast(list[Any], enclosure_entries_obj)
    if any(not isinstance(item, dict) for item in enclosure_items):
        raise ManufacturingSubmissionError("enclosure artifact entry is malformed")
    enclosure_entries = [cast(dict[str, Any], item) for item in enclosure_items]
    required_enclosure_names = (
        "enclosure-shell.step",
        "enclosure-lid.step",
        "enclosure-assembly.step",
        "enclosure.3mf",
        "enclosure.stl",
    )
    required_enclosure_manifest_names = (
        "enclosure-artifacts.json",
        "envelope-cad.json",
    )
    required_board_suffixes = (
        ".gbrjob",
        ".zip",
        "-bom-jlcpcb.csv",
        "-cpl-jlcpcb.csv",
        ".pos.csv",
        "dfm-report.json",
        "cpl-basis.json",
    )
    artifact_records: list[ManufacturingSubmissionArtifact] = []
    empty_hash = "sha256:" + hashlib.sha256(b"").hexdigest()
    for entry in entries:
        path = paths.get(str(entry.get("path")))
        present = path is not None and path.is_file() and path.stat().st_size > 0
        recorded = entry.get("content_hash", entry.get("normalized_sha256"))
        fmt = _format_for(path) if path is not None else "FILE"
        artifact_records.append(
            ManufacturingSubmissionArtifact(
                role="board_artifact",
                path=str(entry.get("path", "")),
                format=fmt,
                normalized_sha256=(
                    recorded
                    if isinstance(recorded, str) and recorded.startswith("sha256:")
                    else empty_hash
                ),
                present=present,
            )
        )
    enclosure_paths: dict[str, Path] = {}
    for entry in enclosure_entries:
        raw = entry.get("path")
        path = _path_from_entry(enclosure_dir, entry)
        enclosure_paths[str(raw)] = path
        present = path.is_file() and path.stat().st_size > 0
        recorded = entry.get("normalized_sha256")
        artifact_records.append(
            ManufacturingSubmissionArtifact(
                role=str(entry.get("role", "enclosure_artifact")),
                path=str(raw or ""),
                format=str(entry.get("format", _format_for(path))),
                normalized_sha256=(
                    recorded
                    if isinstance(recorded, str) and recorded.startswith("sha256:")
                    else empty_hash
                ),
                present=present,
            )
        )
    for name in ("enclosure-artifacts.json", "envelope-cad.json"):
        path = enclosure_dir / name
        artifact_records.append(
            ManufacturingSubmissionArtifact(
                role="enclosure_manifest",
                path=name,
                format="JSON",
                normalized_sha256="sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
                if path.is_file() and path.stat().st_size
                else empty_hash,
                present=path.is_file() and path.stat().st_size > 0,
            )
        )

    def required_artifacts() -> str:
        missing = [
            name
            for name, path in paths.items()
            if not path.is_file() or path.stat().st_size == 0
        ]
        missing.extend(
            name for name in required_enclosure_names
            if not (enclosure_dir / name).is_file() or (enclosure_dir / name).stat().st_size == 0
        )
        missing.extend(
            name
            for name in required_enclosure_manifest_names
            if not (enclosure_dir / name).is_file()
            or (enclosure_dir / name).stat().st_size == 0
        )
        declared_enclosure_names = {Path(name).name for name in enclosure_paths}
        missing.extend(
            name for name in required_enclosure_names
            if name not in declared_enclosure_names
        )
        required_layers = package.get("required_layers")
        if required_layers != list(_REQUIRED_LAYERS):
            missing.append("required_layers")
        for suffix in required_board_suffixes:
            if not any(Path(name).name.endswith(suffix) for name in paths):
                missing.append(suffix)
        if not any(Path(name).suffix.lower() in {".drl", ".xln"} for name in paths):
            missing.append("drill")
        if missing:
            raise ManufacturingSubmissionError(
                f"missing required artifacts: {sorted(set(missing))}"
            )
        return "all declared board and enclosure artifacts are present"

    gerber_paths = [
        path for path in paths.values()
        if path.suffix.lower() in _GERBER_SUFFIXES
    ]
    drill_paths = [path for path in paths.values() if path.suffix.lower() in {".drl", ".xln"}]
    gbrjob_paths = [path for path in paths.values() if path.suffix.lower() == ".gbrjob"]
    zip_paths = [path for path in paths.values() if path.suffix.lower() == ".zip"]
    bom_paths = [path for path in paths.values() if path.name.endswith("-bom-jlcpcb.csv")]
    cpl_paths = [path for path in paths.values() if path.name.endswith("-cpl-jlcpcb.csv")]
    pos_paths = [path for path in paths.values() if path.name.endswith(".pos.csv")]

    def independent_reload() -> str:
        for path in gerber_paths:
            layer = "B.SilkS" if path.name.endswith("-B_Silkscreen.gbo") else "other"
            verify_gerber(path, min_objects=0 if layer == "B.SilkS" else 1)
        for path in drill_paths:
            verify_drill(path)
        if len(gbrjob_paths) != 1:
            raise ReloadError("exactly one gbrjob is required")
        job_names, _job = _gbrjob_files(gbrjob_paths[0])
        exported_names = {path.name for path in gerber_paths}
        if job_names != exported_names:
            raise ReloadError("gbrjob FilesAttributes does not match Gerber files")
        for name in job_names:
            if not (gbrjob_paths[0].parent / name).is_file():
                raise ReloadError(f"gbrjob file is missing: {name}")
        if not zip_paths:
            raise ReloadError("gerbers.zip is missing")
        declared = set(path_entries) - {
            name for name in path_entries if Path(name).name == Path(zip_paths[0]).name
        }
        declared = {
            name for name in declared if Path(name).name != "order-readiness.json"
        }
        with zipfile.ZipFile(zip_paths[0]) as archive:
            members = set(archive.namelist())
            if members != declared:
                raise ReloadError("zip member set differs from declared manufacturing artifacts")
            for member in members:
                source = board_dir / member
                if not source.is_file() or archive.read(member) != source.read_bytes():
                    raise ReloadError(f"zip member differs from source: {member}")
        if len(bom_paths) != 1 or len(cpl_paths) != 1 or len(pos_paths) != 1:
            raise ReloadError("BOM, CPL, and position CSV are incomplete")
        if _fitted_refdes_from_bom(bom_paths[0]) != _fitted_refdes_from_cpl(cpl_paths[0]):
            raise ReloadError("BOM and CPL fitted refdes sets differ")
        assembly_report = measure_enclosure_artifacts(
            shell_step_path=enclosure_dir / "enclosure-shell.step",
            lid_step_path=enclosure_dir / "enclosure-lid.step",
            assembly_step_path=enclosure_dir / "enclosure-assembly.step",
        )
        measure_enclosure_mesh_artifacts(
            model_3mf_path=enclosure_dir / "enclosure.3mf",
            mesh_stl_path=enclosure_dir / "enclosure.stl",
            assembly_report=assembly_report,
        )
        return "Gerber, drill, gbrjob, ZIP, BOM/CPL, and enclosure reload passed"

    def normalized_hashes() -> str:
        failures: list[str] = []
        for entry in entries:
            path = _path_from_entry(board_dir, entry)
            if not path.is_file():
                continue
            expected = entry.get("content_hash", entry.get("normalized_sha256"))
            if not isinstance(expected, str) or _artifact_hash(path, _format_for(path)) != expected:
                failures.append(str(entry.get("path")))
        for entry in enclosure_entries:
            path = _path_from_entry(enclosure_dir, entry)
            expected = entry.get("normalized_sha256")
            if (
                not path.is_file()
                or not isinstance(expected, str)
                or _artifact_hash(path, str(entry.get("format", _format_for(path))))
                != expected
            ):
                failures.append(str(entry.get("path")))
        if failures:
            raise ManufacturingSubmissionError(f"normalized hash mismatch: {sorted(failures)}")
        return "all manifest normalized hashes match"

    def dfm() -> str:
        dfm_paths = [path for path in paths.values() if path.name == "dfm-report.json"]
        if len(dfm_paths) != 1 or _load_json(dfm_paths[0]).get("status") != "pass":
            raise ManufacturingSubmissionError("DFM report status is not pass")
        return "DFM report status is pass"

    def geometry() -> str:
        edge_paths = [path for path in gerber_paths if "Edge_Cuts" in path.name]
        if len(edge_paths) != 1:
            raise ManufacturingSubmissionError("Edge.Cuts Gerber is missing")
        bbox = _edge_bbox(edge_paths[0])
        board = next((node for node in graph.nodes if node.kind == "electrical.board"), None)
        if board is None:
            raise ManufacturingSubmissionError("graph electrical board declaration is missing")
        width = board.attrs.get("width_mm")
        height = board.attrs.get("height_mm")
        if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
            raise ManufacturingSubmissionError("graph board dimensions are missing")
        measured = (bbox[2] - bbox[0], bbox[3] - bbox[1])
        if not math.isclose(
            measured[0], float(width), abs_tol=_BOARD_OUTLINE_TOLERANCE_MM
        ) or not math.isclose(
            measured[1], float(height), abs_tol=_BOARD_OUTLINE_TOLERANCE_MM
        ):
            raise ManufacturingSubmissionError("Edge.Cuts bbox differs from graph board dimensions")
        if len(gbrjob_paths) != 1:
            raise ManufacturingSubmissionError("gbrjob is missing")
        _, job = _gbrjob_files(gbrjob_paths[0])
        general_specs = cast(object, job.get("GeneralSpecs", {}))
        if not isinstance(general_specs, dict):
            raise ManufacturingSubmissionError("gbrjob GeneralSpecs is missing")
        specs = cast(dict[str, Any], general_specs)
        if not isinstance(specs.get("Size"), dict):
            raise ManufacturingSubmissionError("gbrjob GeneralSpecs.Size is missing")
        size = cast(dict[str, Any], specs["Size"])
        if not math.isclose(
            measured[0], float(size["X"]), abs_tol=_BOARD_OUTLINE_TOLERANCE_MM
        ) or not math.isclose(
            measured[1], float(size["Y"]), abs_tol=_BOARD_OUTLINE_TOLERANCE_MM
        ):
            raise ManufacturingSubmissionError(
                "Edge.Cuts bbox differs from gbrjob GeneralSpecs.Size"
            )
        return "Edge.Cuts bbox matches graph and gbrjob dimensions"

    def fab_profile_consistency() -> str:
        profile_obj = cast(object, package.get("fab_profile"))
        if not isinstance(profile_obj, dict):
            raise ManufacturingSubmissionError("fab profile declaration is missing")
        profile = cast(dict[str, Any], profile_obj)
        profile_id = cast(object, profile.get("profile_id"))
        intent = next((node for node in graph.nodes if node.kind == "fab.order_intent"), None)
        expected_id = intent.attrs.get("fab_profile") if intent else None
        if not isinstance(profile_id, str) or profile_id != expected_id:
            raise ManufacturingSubmissionError("fab profile id differs from graph")
        profile_path = resolve_fab_profile_path(profile_id)
        if normalized_hash(profile_path) != profile.get("hash"):
            raise ManufacturingSubmissionError("fab profile normalized hash differs")
        return "fab profile id and normalized hash match graph"

    def revision_consistency() -> str:
        revisions = {graph.revision, str(package.get("target_revision"))}
        for name in ("gerbers.envelope.json", "drill.envelope.json"):
            path = board_dir / "gerbers" / name
            if not path.is_file():
                raise ManufacturingSubmissionError(f"envelope is missing: {name}")
            revisions.add(_revision_from_envelope(path))
        revisions.add(_revision_from_envelope(enclosure_dir / "envelope-cad.json"))
        for name in ("evidence-electrical.json", "evidence-mechanical.json"):
            evidence_path = (
                board_dir / name
                if name == "evidence-electrical.json"
                else enclosure_dir / name
            )
            evidence = _read_evidence(evidence_path)
            revisions.add(evidence.target_revision)
            revisions.add(evidence.envelope.target_revision)
        if len(revisions) != 1:
            raise ManufacturingSubmissionError(f"revision mismatch: {sorted(revisions)}")
        return "all graph, envelope, manifest, and Evidence revisions match"

    evidence_class: dict[str, str] = {}
    def evidence_validity() -> str:
        for lane, path in (
            ("electrical", board_dir / "evidence-electrical.json"),
            ("mechanical", enclosure_dir / "evidence-mechanical.json"),
        ):
            evidence = _read_evidence(path)
            if evidence.status != "valid" or not evidence.supports_pass(graph.revision):
                raise ManufacturingSubmissionError(f"{lane} Evidence is not valid for revision")
            is_authoritative = evidence.supports_authoritative_pass(graph.revision)
            evidence_class[lane] = "authoritative" if is_authoritative else "provisional"
        if require_authoritative and any(
            value != "authoritative" for value in evidence_class.values()
        ):
            raise ManufacturingSubmissionError("authoritative Evidence is required")
        details = ", ".join(f"{key}={value}" for key, value in sorted(evidence_class.items()))
        return f"Evidence validity passed ({details})"

    operations: tuple[tuple[CheckId, Callable[[], str]], ...] = (
        ("required_artifacts", required_artifacts),
        ("independent_reload", independent_reload),
        ("normalized_hashes", normalized_hashes),
        ("dfm", dfm),
        ("geometry", geometry),
        ("fab_profile_consistency", fab_profile_consistency),
        ("revision_consistency", revision_consistency),
        ("evidence_validity", evidence_validity),
    )
    checks = tuple(_check(check_id, operation) for check_id, operation in operations)
    status = "pass" if all(check.status == "pass" for check in checks) else "fail"
    reasons = tuple(check.detail for check in checks if check.status == "fail")
    readiness_path = board_dir / "fab" / "order-readiness.json"
    readiness_status = "unknown"
    if readiness_path.is_file():
        readiness = _load_json(readiness_path).get("status")
        if isinstance(readiness, str) and readiness:
            readiness_status = readiness
    authoritative = bool(evidence_class) and all(
        value == "authoritative" for value in evidence_class.values()
    )
    payload = {
        "schema_version": "0.1",
        "artifact_kind": "manufacturing_submission_verdict",
        "record_class": "L1",
        "status": status,
        "graph_id": graph.graph_id,
        "target_revision": graph.revision,
        "artifacts": [artifact.model_dump(mode="json") for artifact in artifact_records],
        "checks": [check.model_dump(mode="json") for check in checks],
        "reasons": list(reasons),
        "authoritative": authoritative,
        "evidence_class": evidence_class,
        "order_readiness_status": readiness_status,
        "excluded_scope": ["quote_aggregation", "order_execution"],
    }
    payload["content_sha256"] = canonical_json_sha256(payload)
    return ManufacturingSubmissionVerdict.model_validate(payload)
