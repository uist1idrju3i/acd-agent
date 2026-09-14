from __future__ import annotations

import pytest
from pydantic import ValidationError

from acd.schema import DesignGraph


def test_functional_block_parent_missing_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DesignGraph.model_validate(
            {
                "graph_id": "hierarchy",
                "revision": "r1",
                "nodes": [
                    {
                        "id": "block.child",
                        "kind": "design.functional_block",
                        "attrs": {"block_id": "child", "parent_block_id": "missing"},
                    }
                ],
            }
        )


def test_functional_block_parent_cycle_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DesignGraph.model_validate(
            {
                "graph_id": "hierarchy",
                "revision": "r1",
                "nodes": [
                    {
                        "id": "block.a",
                        "kind": "design.functional_block",
                        "attrs": {"block_id": "a", "parent_block_id": "b"},
                    },
                    {
                        "id": "block.b",
                        "kind": "design.functional_block",
                        "attrs": {"block_id": "b", "parent_block_id": "a"},
                    },
                ],
            }
        )
