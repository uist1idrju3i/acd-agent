"""Compatibility re-export.

The implementation lives in ``acd.core.electrical.topology_synthesis``.
"""

from acd.core.electrical.topology_synthesis import (
    TopologyFragment,
    TopologySynthesisError,
    default_topology_templates_path,
    load_topology_templates,
    synthesize_topology,
)

__all__ = [
    "TopologyFragment",
    "TopologySynthesisError",
    "default_topology_templates_path",
    "load_topology_templates",
    "synthesize_topology",
]
