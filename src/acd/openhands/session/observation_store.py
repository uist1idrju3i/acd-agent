"""Fail-closed storage for non-authoritative ACD observations."""

from __future__ import annotations

import json
import os
from pathlib import Path, PureWindowsPath

from openhands.sdk.io import FileStore, LocalFileStore

from acd.openhands.session.observation_log import (
    ObservationLogError,
    emit_observation_log,
    observation_log_record,
)
from acd.schema.observation import ObservationArtifactKind, ObservationPayload
from acd.schema.observation_log import ObservationLogRecord

__all__ = [
    "AcdObservationStore",
    "ObservationArtifactKind",
    "ObservationPayload",
    "ObservationStoreError",
    "write_observation_payload",
]


class ObservationStoreError(ValueError):
    """Raised when an observation cannot be written safely."""


def _validate_observation_path(
    path: str | Path,
    *,
    allow_absolute: bool,
) -> str:
    raw_path = os.fspath(path)
    if not raw_path.strip():
        raise ObservationStoreError("observation path must not be empty")
    if (
        not allow_absolute
        and (Path(raw_path).is_absolute() or PureWindowsPath(raw_path).is_absolute())
    ):
        raise ObservationStoreError("observation path must be relative")
    normalized = raw_path.replace("\\", "/")
    parts = normalized.split("/")
    if any(part == ".." for part in parts):
        raise ObservationStoreError("observation path escapes its root")
    if normalized in {"", "."} or normalized.endswith("/") or parts[-1] == ".":
        raise ObservationStoreError("observation path must name a file")
    return normalized


def _validate_store_path(path: str | Path) -> str:
    return _validate_observation_path(path, allow_absolute=False)


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

    def write(
        self,
        path: str | Path,
        payload: ObservationPayload,
    ) -> ObservationLogRecord:
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
        record = observation_log_record(serialized_payload, relative_path, contents)
        try:
            with self.file_store.lock(relative_path):
                self.file_store.write(relative_path, contents)
        except (OSError, TypeError, ValueError) as exc:
            raise ObservationStoreError(
                "observation store write failed"
            ) from exc
        try:
            emit_observation_log(record)
        except ObservationLogError as exc:
            raise ObservationStoreError(
                "observation structured log emission failed"
            ) from exc
        return record


def _store_for_path(path: Path) -> tuple[AcdObservationStore, str]:
    _validate_observation_path(path, allow_absolute=True)
    absolute_path = path if path.is_absolute() else Path.cwd() / path
    absolute_path = absolute_path.absolute()
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
) -> ObservationLogRecord:
    """Write an observation using an explicit or path-backed FileStore."""
    if file_store is None:
        store, relative_path = _store_for_path(path)
    else:
        store = AcdObservationStore(file_store)
        relative_path = _validate_store_path(path)
    return store.write(relative_path, payload)
