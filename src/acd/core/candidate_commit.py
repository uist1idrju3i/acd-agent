"""Atomic commit of an accepted exploration candidate into design inputs.

A committed graph change invalidates every rationale subject hash, so an
accepted candidate is written together with rationale refreshed by the same rule
requirement compilation uses. Committing never grants pass authority; the caller
must rerun the deterministic gates afterwards.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from acd.core.rationale import RationaleRefreshError, refresh_rationale_document
from acd.schema import RationaleDocument
from acd.schema.design_graph import DesignGraph


class CandidateCommitError(ValueError):
    """Raised when an accepted candidate cannot be committed atomically."""


def _write_json(path: Path, body: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def commit_candidate_graph(
    graph: DesignGraph, graph_path: Path, fixture_dir: Path
) -> dict[str, Any]:
    """Write the accepted graph and its refreshed rationale in one transaction."""
    rationale_path = fixture_dir / "rationale.json"
    if not rationale_path.is_file():
        raise CandidateCommitError(
            f"rationale document is missing for the accepted candidate: {rationale_path}"
        )
    try:
        document = RationaleDocument.model_validate_json(
            rationale_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise CandidateCommitError(f"rationale document is invalid: {exc}") from exc
    try:
        refreshed = refresh_rationale_document(graph, document)
    except RationaleRefreshError as exc:
        raise CandidateCommitError(
            f"rationale could not be refreshed for the accepted candidate: {exc}"
        ) from exc
    graph_tmp = graph_path.with_name(graph_path.name + ".tmp")
    rationale_tmp = rationale_path.with_name(rationale_path.name + ".tmp")
    previous_graph = graph_path.read_bytes() if graph_path.is_file() else None
    try:
        _write_json(graph_tmp, graph.model_dump(mode="json"))
        _write_json(rationale_tmp, refreshed.model_dump(mode="json"))
        os.replace(graph_tmp, graph_path)
        try:
            os.replace(rationale_tmp, rationale_path)
        except OSError:
            if previous_graph is not None:
                graph_path.write_bytes(previous_graph)
            raise
    except OSError as exc:
        graph_tmp.unlink(missing_ok=True)
        rationale_tmp.unlink(missing_ok=True)
        raise CandidateCommitError(
            f"accepted candidate could not be written: {exc}"
        ) from exc
    return {
        "graph_path": str(graph_path),
        "rationale_path": str(rationale_path),
        "rationale_records": len(refreshed.records),
        "target_revision": graph.revision,
        "pass_evidence": False,
    }


__all__ = ["CandidateCommitError", "commit_candidate_graph"]
