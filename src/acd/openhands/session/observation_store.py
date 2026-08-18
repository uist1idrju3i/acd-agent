"""Fail-closed storage for non-authoritative ACD observations."""

from __future__ import annotations

import json
import os
from pathlib import Path, PureWindowsPath
from typing import Literal

from openhands.sdk.io import FileStore, LocalFileStore
from pydantic import ConfigDict

from acd.schema.common import AcdModel, NonEmptyStr

ObservationArtifactKind = Literal[
    "conversation_metrics",
    "conversation_stats",
    "goal_result",
    "model_routing_observation",
]


class ObservationStoreError(ValueError):
    """Raised when an observation cannot be written safely."""


class ObservationPayload(AcdModel):
    """Typed envelope for non-authoritative observation payloads."""

    model_config = ConfigDict(extra="allow", frozen=True)

    artifact_kind: ObservationArtifactKind
    pass_evidence: Literal[False] = False
    description: NonEmptyStr | None = None


def _validate_store_path(path: str | Path) -> str:
    raw_path = os.fspath(path)
    if not raw_path.strip():
        raise ObservationStoreError("observation store path must not be empty")
    if Path(raw_path).is_absolute() or PureWindowsPath(raw_path).is_absolute():
        raise ObservationStoreError("observation store path must be relative")
    normalized = raw_path.replace("\\", "/")
    parts = normalized.split("/")
    if any(part == ".." for part in parts):
        raise ObservationStoreError("observation store path escapes its root")
    if normalized in {"", "."} or normalized.endswith("/"):
        raise ObservationStoreError("observation store path must name a file")
    return normalized


class AcdObservationStore:
    """Write typed observations through an SDK FileStore."""

    def __init__(self, file_store: FileStore) -> None:
        self.file_store = file_store
        try:
            file_store.get_absolute_path(".")
        except (OSError, TypeError, ValueError) as exc:
            raise ObservationStoreError(
                "observation store root is unavailable"
            ) from exc

    def write(self, path: str | Path, payload: ObservationPayload) -> None:
        """Write deterministic observation bytes at a relative store path."""
        relative_path = _validate_store_path(path)
        serialized_payload = payload.model_dump(mode="json")
        if payload.description is None:
            serialized_payload.pop("description", None)
        contents = (
            json.dumps(
                serialized_payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        try:
            with self.file_store.lock(relative_path):
                self.file_store.write(relative_path, contents)
        except (OSError, TypeError, ValueError) as exc:
            raise ObservationStoreError(
                "observation store write failed"
            ) from exc


def _store_for_path(path: Path) -> tuple[AcdObservationStore, str]:
    raw_path = os.fspath(path)
    if not raw_path.strip():
        raise ObservationStoreError("observation path must not be empty")
    if raw_path in {".", ".."} or raw_path.endswith(("/", "\\")):
        raise ObservationStoreError("observation path must name a file")
    if any(part == ".." for part in path.parts):
        raise ObservationStoreError("observation path escapes its root")
    absolute_path = path if path.is_absolute() else Path.cwd() / path
    absolute_path = absolute_path.absolute()
    if not absolute_path.name:
        raise ObservationStoreError("observation path must name a file")
    try:
        file_store = LocalFileStore(str(absolute_path.parent))
    except (OSError, TypeError, ValueError) as exc:
        raise ObservationStoreError(
            "observation store root is unavailable"
        ) from exc
    return AcdObservationStore(file_store), absolute_path.name


def write_observation_payload(
    payload: ObservationPayload,
    path: Path,
    *,
    file_store: FileStore | None = None,
) -> None:
    """Write an observation using an explicit or path-backed FileStore."""
    if file_store is None:
        store, relative_path = _store_for_path(path)
    else:
        store = AcdObservationStore(file_store)
        relative_path = _validate_store_path(path)
    store.write(relative_path, payload)
