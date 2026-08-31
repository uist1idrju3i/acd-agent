"""Independent L1 manufacturing-submission verdict tests (fail-closed negatives)."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pytest

from acd.core.manufacturing_submission import evaluate_manufacturing_submission
from acd.schema.manufacturing_submission import ManufacturingSubmissionVerdict
from tests.core.manufacturing_tree import (
    BOARD_NAME,
    GRAPH_PATH,
    build_submission_tree,
    load_graph,
    refresh_board_manifest,
    write_lane_evidence,
)


@pytest.fixture(scope="module")
def submission_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("submission-tree")
    build_submission_tree(root)
    return root


@pytest.fixture
def tree(submission_root: Path, tmp_path: Path) -> tuple[Path, Path]:
    destination = tmp_path / "submission"
    shutil.copytree(submission_root, destination)
    return destination / "board", destination / "enclosure"


def _evaluate(
    tree: tuple[Path, Path], *, require_authoritative: bool = False
) -> ManufacturingSubmissionVerdict:
    return evaluate_manufacturing_submission(
        board_dir=tree[0],
        enclosure_dir=tree[1],
        graph_path=GRAPH_PATH,
        require_authoritative=require_authoritative,
    )


def _failed(verdict: ManufacturingSubmissionVerdict) -> set[str]:
    return {check.check_id for check in verdict.checks if check.status == "fail"}


def _read_package(board_dir: Path) -> dict[str, Any]:
    path = board_dir / "fab" / "fab-package.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _write_package(board_dir: Path, package: dict[str, Any]) -> None:
    path = board_dir / "fab" / "fab-package.json"
    path.write_text(
        json.dumps(package, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_complete_submission_passes_with_authoritative_evidence(
    tree: tuple[Path, Path],
) -> None:
    verdict = _evaluate(tree, require_authoritative=True)

    assert verdict.status == "pass"
    assert verdict.record_class == "L1"
    assert verdict.artifact_kind == "manufacturing_submission_verdict"
    assert verdict.reasons == ()
    assert verdict.authoritative is True
    assert verdict.evidence_class == {
        "electrical": "authoritative",
        "mechanical": "authoritative",
    }
    assert verdict.excluded_scope == ("quote_aggregation", "order_execution")
    assert verdict.target_revision == load_graph().revision
    assert {check.check_id for check in verdict.checks} == {
        "required_artifacts",
        "independent_reload",
        "normalized_hashes",
        "dfm",
        "geometry",
        "fab_profile_consistency",
        "revision_consistency",
        "evidence_validity",
    }
    assert verdict.content_sha256.startswith("sha256:")
    assert any(artifact.path == "enclosure.stl" for artifact in verdict.artifacts)


def test_not_order_ready_still_allows_submission_quality_pass(
    tree: tuple[Path, Path],
) -> None:
    verdict = _evaluate(tree)

    assert verdict.order_readiness_status == "not_order_ready"
    assert verdict.status == "pass"


def test_order_ready_does_not_rescue_broken_artifacts(tree: tuple[Path, Path]) -> None:
    board_dir, _ = tree
    readiness = board_dir / "fab" / "order-readiness.json"
    readiness.write_text(
        json.dumps({"schema_version": "0.1", "status": "ready", "reasons": []}) + "\n",
        encoding="utf-8",
    )
    refresh_board_manifest(board_dir)
    (board_dir / "gerbers" / f"{BOARD_NAME}-F_Cu.gtl").unlink()

    verdict = _evaluate(tree)

    assert verdict.order_readiness_status == "ready"
    assert verdict.status == "fail"
    assert "required_artifacts" in _failed(verdict)


def test_missing_gerber_fails_closed(tree: tuple[Path, Path]) -> None:
    (tree[0] / "gerbers" / f"{BOARD_NAME}-B_Cu.gbl").unlink()

    verdict = _evaluate(tree)

    assert verdict.status == "fail"
    assert "required_artifacts" in _failed(verdict)
    assert verdict.reasons


def test_single_byte_gerber_change_fails_normalized_hashes(
    tree: tuple[Path, Path],
) -> None:
    path = tree[0] / "gerbers" / f"{BOARD_NAME}-F_Mask.gts"
    body = path.read_text(encoding="utf-8").replace("X30000000Y0D01*", "X30000001Y0D01*")
    path.write_text(body, encoding="utf-8")

    verdict = _evaluate(tree)

    assert verdict.status == "fail"
    assert "normalized_hashes" in _failed(verdict)


def test_zip_member_substitution_fails_independent_reload(
    tree: tuple[Path, Path],
) -> None:
    board_dir, _ = tree
    zip_path = board_dir / "fab" / f"{BOARD_NAME}-gerbers.zip"
    with zipfile.ZipFile(zip_path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    victim = f"{BOARD_NAME}-F_Paste.gtp"
    members[f"{BOARD_NAME}-unexpected.gtp"] = members.pop(victim)
    with zipfile.ZipFile(zip_path, "w") as archive:
        for name, data in sorted(members.items()):
            archive.writestr(name, data)

    verdict = _evaluate(tree)

    assert verdict.status == "fail"
    assert "independent_reload" in _failed(verdict)


def test_missing_gbrjob_fails_closed(tree: tuple[Path, Path]) -> None:
    (tree[0] / "gerbers" / f"{BOARD_NAME}-job.gbrjob").unlink()

    verdict = _evaluate(tree)

    assert verdict.status == "fail"
    assert "required_artifacts" in _failed(verdict)
    assert "independent_reload" in _failed(verdict)


def test_invalid_gbrjob_json_fails_closed(tree: tuple[Path, Path]) -> None:
    (tree[0] / "gerbers" / f"{BOARD_NAME}-job.gbrjob").write_text("{", encoding="utf-8")

    verdict = _evaluate(tree)

    assert verdict.status == "fail"
    assert "independent_reload" in _failed(verdict)


def test_gbrjob_files_attributes_mismatch_fails_closed(tree: tuple[Path, Path]) -> None:
    board_dir, _ = tree
    path = board_dir / "gerbers" / f"{BOARD_NAME}-job.gbrjob"
    job = json.loads(path.read_text(encoding="utf-8"))
    job["FilesAttributes"] = job["FilesAttributes"][:-1]
    path.write_text(json.dumps(job, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    refresh_board_manifest(board_dir)

    verdict = _evaluate(tree)

    assert verdict.status == "fail"
    assert _failed(verdict) == {"independent_reload"}


def test_dfm_status_fail_fails_closed(tree: tuple[Path, Path]) -> None:
    board_dir, _ = tree
    path = board_dir / "fab" / "dfm-report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["status"] = "fail"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    refresh_board_manifest(board_dir)

    verdict = _evaluate(tree)

    assert verdict.status == "fail"
    assert _failed(verdict) == {"dfm"}


def test_revision_mismatch_fails_closed(tree: tuple[Path, Path]) -> None:
    board_dir, _ = tree
    (board_dir / "gerbers" / "drill.envelope.json").write_text(
        json.dumps({"target_revision": "r0"}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    verdict = _evaluate(tree)

    assert verdict.status == "fail"
    assert _failed(verdict) == {"revision_consistency"}


def test_fab_profile_hash_mismatch_fails_closed(tree: tuple[Path, Path]) -> None:
    board_dir, _ = tree
    package = _read_package(board_dir)
    profile = dict(package["fab_profile"])
    profile["hash"] = "sha256:" + "0" * 64
    package["fab_profile"] = profile
    _write_package(board_dir, package)

    verdict = _evaluate(tree)

    assert verdict.status == "fail"
    assert _failed(verdict) == {"fab_profile_consistency"}


def test_missing_enclosure_stl_fails_closed(tree: tuple[Path, Path]) -> None:
    (tree[1] / "enclosure.stl").unlink()

    verdict = _evaluate(tree)

    assert verdict.status == "fail"
    failed = _failed(verdict)
    assert "required_artifacts" in failed
    assert "independent_reload" in failed


def test_provisional_evidence_fails_when_authoritative_required(
    tree: tuple[Path, Path],
) -> None:
    board_dir, enclosure_dir = tree
    write_lane_evidence(
        board_dir,
        enclosure_dir,
        revision=load_graph().revision,
        execution_context="host",
    )

    strict = _evaluate(tree, require_authoritative=True)
    lenient = _evaluate(tree)

    assert strict.status == "fail"
    assert "evidence_validity" in _failed(strict)
    assert lenient.status == "pass"
    assert lenient.authoritative is False
    assert lenient.evidence_class == {
        "electrical": "provisional",
        "mechanical": "provisional",
    }
