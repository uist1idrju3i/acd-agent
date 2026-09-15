"""Tests for strict analysis-result loading and rendering summaries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from doc_inputs import DocumentGenerationError, analysis_summary, load_analysis_results

REPOSITORY = Path(__file__).resolve().parents[5]
GRAPH_ID = "golden-design-1"
REVISION = "r1"
FIXTURE_DIR = REPOSITORY / "fixtures" / "golden-design-1" / "analysis"


def test_gd1_analysis_bundle_has_fixed_six_kind_order() -> None:
    bundle = load_analysis_results(
        FIXTURE_DIR,
        graph_id=GRAPH_ID,
        revision=REVISION,
    )
    assert [artifact.artifact_kind for artifact in bundle.artifacts] == [
        "spice_result",
        "pdn_result",
        "wca_result",
        "thermal_result",
        "fem_result",
        "firmware_analysis_result",
    ]
    assert [artifact.status for artifact in bundle.artifacts] == [
        "pass",
        "pass",
        "pass",
        "pass",
        "unknown",
        "unknown",
    ]
    assert analysis_summary(bundle.artifacts[-1])["authority"] == "estimate"


def test_absent_analysis_is_explicit_not_run() -> None:
    bundle = load_analysis_results(
        [],
        graph_id=GRAPH_ID,
        revision=REVISION,
    )
    assert len(bundle.artifacts) == 6
    assert all(artifact.status == "not_run" for artifact in bundle.artifacts)
    assert all(artifact.path is None for artifact in bundle.artifacts)


def test_analysis_revision_mismatch_fails_closed(tmp_path: Path) -> None:
    source = FIXTURE_DIR / "spice-result.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["revision"] = "r9"
    path = tmp_path / source.name
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    with pytest.raises(DocumentGenerationError, match="targets graph/revision"):
        load_analysis_results(path, graph_id=GRAPH_ID, revision=REVISION)
