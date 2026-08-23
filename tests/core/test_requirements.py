"""Requirement document validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from acd.core.requirements import RequirementError, validate_requirements
from acd.schema import DesignGraph, GraphNode, RequirementDocument, RequirementRecord


def _graph() -> DesignGraph:
    return DesignGraph(
        graph_id="demo",
        revision="r1",
        nodes=[
            GraphNode(id="req.demo", kind="requirement", attrs={"text": "要件"}),
            GraphNode(id="net.led", kind="electrical.net"),
        ],
    )


def test_requirement_graph_consistency_accepts_matching_record() -> None:
    document = RequirementDocument(
        graph_id="demo",
        revision="r1",
        records=[
            RequirementRecord(
                requirement_id="demo",
                statement="要件",
                constrains_node_ids=["net.led"],
                constrains_node_kinds=["electrical.net"],
            )
        ],
    )
    validate_requirements(document, _graph(), registry=None)


def test_requirement_graph_consistency_rejects_text_mismatch() -> None:
    document = RequirementDocument(
        graph_id="demo",
        revision="r1",
        records=[RequirementRecord(requirement_id="demo", statement="別の要件")],
    )
    with pytest.raises(RequirementError, match="text mismatch"):
        validate_requirements(document, _graph())


def test_requirement_graph_consistency_rejects_unlinked_graph_node() -> None:
    document = RequirementDocument(graph_id="demo", revision="r1", records=[])
    with pytest.raises(RequirementError, match="unlinked graph nodes"):
        validate_requirements(document, _graph())


def test_duplicate_requirement_ids_fail_closed() -> None:
    with pytest.raises(ValidationError, match="requirement_id entries must be unique"):
        RequirementDocument(
            graph_id="demo",
            revision="r1",
            records=[
                RequirementRecord(requirement_id="same", statement="一"),
                RequirementRecord(requirement_id="same", statement="二"),
            ],
        )


def test_unknown_node_kind_fails_closed() -> None:
    with pytest.raises(ValidationError):
        RequirementRecord(
            requirement_id="demo",
            statement="要件",
            constrains_node_kinds=["unknown.kind"],  # type: ignore[list-item]
        )


def test_unknown_functional_block_fails_closed() -> None:
    document = RequirementDocument(
        graph_id="demo",
        revision="r1",
        records=[
            RequirementRecord(
                requirement_id="demo",
                statement="要件",
                drives_functional_blocks=["unknown_block"],
            )
        ],
    )
    with pytest.raises(RequirementError, match="unknown functional blocks"):
        validate_requirements(document)
