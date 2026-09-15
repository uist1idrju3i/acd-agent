"""End-to-end regression coverage for the mechanism enclosure fixture."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from acd.pipeline.enclosure import run_pipeline

FIXTURE = Path("fixtures/mechanism-library")
EXPECTED_ARTIFACT_HASHES = {
    "enclosure_shell": "sha256:a27fc81df8e81e1e45cea6e6936b9c7c1cb2ebc7b0f0ebf1462389bdc0a62283",
    "enclosure_lid": "sha256:1e7578731289f8310dba3192e19316972a144d10ded244a35ef2aa4ae4d0da0f",
    "enclosure_assembly": "sha256:25af38df8bb769671481a40ed423b1251078a0d4e078c516bd16fe2c13cb537b",
    "enclosure_model": "sha256:8ba34653a23bf5d0d2c299617b63b288c5852441e61c82f8a5f7c5d407d18fa4",
    "enclosure_mesh_stl": "sha256:cb14c9f3d0461f2e8146fe13774ebb8b04a77a7b198bc581654a24c57d4e8288",
}


def test_mechanism_fixture_pipeline_validates_meshes_and_hashes(tmp_path: Path) -> None:
    first = run_pipeline(FIXTURE, tmp_path / "first", pipeline_workers=1)
    second = run_pipeline(FIXTURE, tmp_path / "second", pipeline_workers=1)

    first_artifacts = cast(list[dict[str, object]], first["artifacts"])
    second_artifacts = cast(list[dict[str, object]], second["artifacts"])
    first_hashes = {
        str(item["role"]): str(item["normalized_sha256"]) for item in first_artifacts
    }
    second_hashes = {
        str(item["role"]): str(item["normalized_sha256"]) for item in second_artifacts
    }
    assert first_hashes == second_hashes
    assert first_hashes == EXPECTED_ARTIFACT_HASHES
    assert first["model_part_count"] == 2
    assert cast(int, first["stl_triangle_count"]) > 0
