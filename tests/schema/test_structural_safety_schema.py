from __future__ import annotations

import pytest
from pydantic import ValidationError

from acd.schema import DesignGraph


def _graph_with_node(node: dict[str, object]) -> dict[str, object]:
    return {
        "graph_id": "structural-safety-schema",
        "revision": "r1",
        "nodes": [node],
    }


def test_redundant_group_requires_string_lists() -> None:
    with pytest.raises(ValidationError):
        DesignGraph.model_validate(
            _graph_with_node(
                {
                    "id": "safety.group",
                    "kind": "safety.redundant_group",
                    "attrs": {
                        "members": ["net.a"],
                        "resources_shared_forbidden": ["connector", "unknown"],
                    },
                }
            )
        )


def test_net_signal_class_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        DesignGraph.model_validate(
            _graph_with_node(
                {
                    "id": "net.a",
                    "kind": "electrical.net",
                    "attrs": {"signal_class": "unsafe"},
                }
            )
        )


def test_redundant_group_rejects_extra_attributes() -> None:
    with pytest.raises(ValidationError):
        DesignGraph.model_validate(
            _graph_with_node(
                {
                    "id": "safety.group",
                    "kind": "safety.redundant_group",
                    "attrs": {
                        "members": ["net.a"],
                        "resources_shared_forbidden": ["connector"],
                        "note": "unexpected",
                    },
                }
            )
        )
