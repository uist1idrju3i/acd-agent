"""Compatibility re-export.

The implementation lives in ``acd.core.runtime.source_tree``.
"""

from acd.core.runtime.source_tree import (
    SOURCE_TREE_PATHS,
    SourceProvenance,
    collect_source_provenance,
    source_provenance_env,
)

__all__ = [
    "SOURCE_TREE_PATHS",
    "SourceProvenance",
    "collect_source_provenance",
    "source_provenance_env",
]
