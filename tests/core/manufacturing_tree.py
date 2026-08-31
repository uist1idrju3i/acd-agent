"""Reusable manufacturing-submission artifact tree for fail-closed tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from acd.adapters.cad.project import project_enclosure
from acd.adapters.kicad.fab.archive import deterministic_zip, zip_content_hash
from acd.adapters.kicad.reload import normalized_hash
from acd.core.fab import resolve_fab_profile_path
from acd.core.mechanical import extract_mechanical_lane
from acd.schema.design_graph import DesignGraph
from acd.schema.evidence import Evidence, EvidenceClaim
from acd.schema.tool_envelope import ToolEnvelope

GRAPH_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "golden-design-1" / "graph.json"
BOARD_NAME = "gd1"
REQUIRED_LAYERS = [
    "F.Cu",
    "B.Cu",
    "F.Mask",
    "B.Mask",
    "F.SilkS",
    "B.SilkS",
    "F.Paste",
    "Edge.Cuts",
]
_GERBER_FILES = (
    ("F_Cu", "gtl"),
    ("B_Cu", "gbl"),
    ("F_Mask", "gts"),
    ("B_Mask", "gbs"),
    ("F_Silkscreen", "gto"),
    ("B_Silkscreen", "gbo"),
    ("F_Paste", "gtp"),
    ("Edge_Cuts", "gm1"),
)
_DIGEST = "sha256:" + "1" * 64
_IMAGE_DIGEST = "sha256:" + "2" * 64
_GERBER_BODY = "\n".join(
    (
        "G04 fixture gerber*",
        "%FSLAX46Y46*%",
        "%MOMM*%",
        "%LPD*%",
        "%ADD10C,0.100000*%",
        "D10*",
        "X0Y0D02*",
        "X30000000Y0D01*",
        "X30000000Y25000000D01*",
        "X0Y25000000D01*",
        "X0Y0D01*",
        "M02*",
        "",
    )
)
_DRILL_BODY = "\n".join(
    (
        "M48",
        "FMAT,2",
        "METRIC",
        "T1C0.300",
        "%",
        "G90",
        "G05",
        "T1",
        "X10.0Y10.0",
        "X20.0Y15.0",
        "T0",
        "M30",
        "",
    )
)
_BOM_BODY = "\n".join(
    (
        "Comment,Designator,Footprint,LCSC Part #",
        "10k,R1,R_0402_1005Metric,C25744",
        "100nF,C1,C_0402_1005Metric,C1525",
        "",
    )
)
_CPL_BODY = "\n".join(
    (
        "Designator,Mid X,Mid Y,Rotation,Layer",
        "R1,10.0000,10.0000,0.0000,top",
        "C1,20.0000,15.0000,90.0000,top",
        "",
    )
)
_POS_BODY = "\n".join(
    (
        "Ref,Val,Package,PosX,PosY,Rot,Side",
        "R1,10k,R_0402_1005Metric,10.0000,10.0000,0.0000,top",
        "C1,100nF,C_0402_1005Metric,20.0000,15.0000,90.0000,top",
        "",
    )
)


def load_graph() -> DesignGraph:
    """Load the golden design graph used by the fixture tree."""
    return DesignGraph.model_validate_json(GRAPH_PATH.read_text(encoding="utf-8"))


def _gerber_names() -> list[str]:
    return [f"{BOARD_NAME}-{stem}.{ext}" for stem, ext in _GERBER_FILES]


def _write_evidence(
    path: Path,
    *,
    evidence_id: str,
    revision: str,
    subject_node: str,
    execution_context: str,
) -> None:
    envelope = ToolEnvelope(
        tool_name="acd-fixture",
        tool_version="0.0.1",
        format_version="fixture-1",
        config_hash=_DIGEST,
        input_hash=_DIGEST,
        output_hash=_DIGEST,
        execution_env="pytest",
        execution_context="container" if execution_context == "container" else "host",
        container_image_digest=_IMAGE_DIGEST if execution_context == "container" else None,
        measurement_conditions="fixture submission tree",
        convergence_state="converged",
        target_revision=revision,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        finished_at=datetime(2026, 1, 1, tzinfo=UTC),
        exit_code=0,
    )
    evidence = Evidence(
        evidence_id=evidence_id,
        target_revision=revision,
        status="valid",
        envelope=envelope,
        claims=[
            EvidenceClaim(
                subject_node=subject_node,
                property="fixture_claim",
                value=True,
                verified=True,
            )
        ],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    path.write_text(evidence.model_dump_json(indent=2) + "\n", encoding="utf-8")


def write_lane_evidence(
    board_dir: Path,
    enclosure_dir: Path,
    *,
    revision: str,
    execution_context: str = "container",
) -> None:
    """Write both lane Evidence records with the requested execution provenance."""
    _write_evidence(
        board_dir / "evidence-electrical.json",
        evidence_id="fixture-electrical",
        revision=revision,
        subject_node="board-main",
        execution_context=execution_context,
    )
    _write_evidence(
        enclosure_dir / "evidence-mechanical.json",
        evidence_id="fixture-mechanical",
        revision=revision,
        subject_node="enclosure-main",
        execution_context=execution_context,
    )


def _manifest_files(board_dir: Path, members: list[Path], readiness: Path, zip_path: Path) -> list[
    dict[str, str]
]:
    entries: list[dict[str, str]] = []
    for path in [*members, zip_path, readiness]:
        entries.append(
            {
                "path": path.relative_to(board_dir).as_posix(),
                "content_hash": (
                    zip_content_hash(path) if path.suffix == ".zip" else normalized_hash(path)
                ),
            }
        )
    return entries


def _package_members(board_dir: Path) -> list[Path]:
    gerber_dir = board_dir / "gerbers"
    fab_dir = board_dir / "fab"
    return [
        *(gerber_dir / name for name in _gerber_names()),
        gerber_dir / f"{BOARD_NAME}.drl",
        gerber_dir / f"{BOARD_NAME}-job.gbrjob",
        fab_dir / f"{BOARD_NAME}-bom-jlcpcb.csv",
        fab_dir / f"{BOARD_NAME}-cpl-jlcpcb.csv",
        fab_dir / f"{BOARD_NAME}.pos.csv",
        fab_dir / "dfm-report.json",
        fab_dir / "cpl-basis.json",
    ]


def refresh_board_manifest(board_dir: Path) -> None:
    """Recompute the manufacturing package so only the mutated check fails."""
    fab_dir = board_dir / "fab"
    zip_path = fab_dir / f"{BOARD_NAME}-gerbers.zip"
    members = _package_members(board_dir)
    deterministic_zip(zip_path, members, board_dir)
    package_path = fab_dir / "fab-package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["files"] = _manifest_files(
        board_dir, members, fab_dir / "order-readiness.json", zip_path
    )
    package["content_hash"] = zip_content_hash(zip_path)
    package_path.write_text(
        json.dumps(package, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_board_tree(board_dir: Path, *, revision: str, profile_id: str) -> None:
    """Write a complete, self-consistent board manufacturing output tree."""
    gerber_dir = board_dir / "gerbers"
    fab_dir = board_dir / "fab"
    gerber_dir.mkdir(parents=True, exist_ok=True)
    fab_dir.mkdir(parents=True, exist_ok=True)
    for name in _gerber_names():
        (gerber_dir / name).write_text(_GERBER_BODY, encoding="utf-8")
    (gerber_dir / f"{BOARD_NAME}.drl").write_text(_DRILL_BODY, encoding="utf-8")
    gbrjob = {
        "Header": {
            "GenerationSoftware": {"Vendor": "KiCad", "Application": "Pcbnew"},
            "CreationDate": "2026-08-31T14:48:04+00:00",
        },
        "GeneralSpecs": {"Size": {"X": 30.1, "Y": 25.1}, "ProjectId": {"Name": BOARD_NAME}},
        "FilesAttributes": [
            {"Path": name} for name in _gerber_names()
        ],
    }
    (gerber_dir / f"{BOARD_NAME}-job.gbrjob").write_text(
        json.dumps(gbrjob, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    for name in ("gerbers.envelope.json", "drill.envelope.json"):
        (gerber_dir / name).write_text(
            json.dumps({"target_revision": revision}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    (fab_dir / f"{BOARD_NAME}-bom-jlcpcb.csv").write_text(_BOM_BODY, encoding="utf-8")
    (fab_dir / f"{BOARD_NAME}-cpl-jlcpcb.csv").write_text(_CPL_BODY, encoding="utf-8")
    (fab_dir / f"{BOARD_NAME}.pos.csv").write_text(_POS_BODY, encoding="utf-8")
    (fab_dir / "dfm-report.json").write_text(
        json.dumps(
            {"status": "pass", "findings": [], "target_revision": revision},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (fab_dir / "cpl-basis.json").write_text(
        json.dumps(
            {
                "position_bases": {"R1": "measured", "C1": "measured"},
                "rotation_offsets": {"R1": 0.0, "C1": 0.0},
                "unknowns": {},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (fab_dir / "order-readiness.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "status": "not_order_ready",
                "target_revision": revision,
                "reasons": ["fixture order readiness is not required for submission quality"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    profile_hash = normalized_hash(resolve_fab_profile_path(profile_id))
    (fab_dir / "fab-package.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "status": "not_order_ready",
                "target_revision": revision,
                "fab_profile": {"profile_id": profile_id, "hash": profile_hash},
                "required_layers": list(REQUIRED_LAYERS),
                "files": [],
                "gates": {"dfm": "pass"},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    refresh_board_manifest(board_dir)


def build_submission_tree(
    root: Path, *, execution_context: str = "container"
) -> tuple[Path, Path]:
    """Build a passing board and enclosure submission tree and return both directories."""
    graph = load_graph()
    intent = next(node for node in graph.nodes if node.kind == "fab.order_intent")
    profile_id = str(intent.attrs["fab_profile"])
    board_dir = root / "board"
    enclosure_dir = root / "enclosure"
    board_dir.mkdir(parents=True, exist_ok=True)
    enclosure_dir.mkdir(parents=True, exist_ok=True)
    build_board_tree(board_dir, revision=graph.revision, profile_id=profile_id)
    project_enclosure(
        extract_mechanical_lane(graph),
        graph_path=GRAPH_PATH,
        out_dir=enclosure_dir,
        target_revision=graph.revision,
    )
    write_lane_evidence(
        board_dir,
        enclosure_dir,
        revision=graph.revision,
        execution_context=execution_context,
    )
    return board_dir, enclosure_dir
