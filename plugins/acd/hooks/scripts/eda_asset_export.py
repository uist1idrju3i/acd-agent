"""Refuse terminal commands that export container EDA assets to the host.

Locked container images carry KiCad and FreeRouting assets that make
authoritative Evidence reproducible. Copying those assets out of a container
(``docker cp``, ``docker exec ... tar``, ``run_in_workspace.py --download``)
builds a host toolchain that mixes container-derived files into provisional
host runs, which the authoritative path must never depend on.  The hook denies
the export; it does not change how host runs are classified.
"""

from __future__ import annotations

import shlex
from pathlib import PurePosixPath
from typing import Any, cast

from common import event, result

CONTAINER_ASSET_PREFIXES = (
    "/usr/share/kicad",
    "/usr/local/share/kicad",
    "/usr/share/freerouting",
    "/opt/freerouting",
)
CONTAINER_COMMANDS = frozenset({"docker", "podman", "nerdctl"})
COPY_COMMANDS = frozenset({"tar", "cp", "rsync", "scp", "cat", "dd", "zip", "install"})
REASON = (
    "Exporting container EDA assets (KiCad symbols, footprints, 3D models, "
    "FreeRouting) to the host is denied. Run gates inside the locked container "
    "with scripts/run_in_workspace.py; host execution stays provisional and must "
    "not mix container-derived assets."
)


def references_container_asset(token: str) -> bool:
    """Return whether a token points at a container EDA asset path."""
    for prefix in CONTAINER_ASSET_PREFIXES:
        if token == prefix or token.startswith(prefix + "/"):
            return True
        for separator in (":", "="):
            _, _, tail = token.partition(separator)
            if tail == prefix or tail.startswith(prefix + "/"):
                return True
    return False


def _names(tokens: list[str]) -> list[str]:
    return [PurePosixPath(token).name for token in tokens]


def _container_copy(tokens: list[str]) -> bool:
    names = _names(tokens)
    return any(
        name in CONTAINER_COMMANDS and "cp" in names[index + 1 :]
        for index, name in enumerate(names)
    )


def _download_of_asset(tokens: list[str]) -> bool:
    return any(
        token == "--download" and references_container_asset(tokens[index + 1])
        for index, token in enumerate(tokens[:-1])
    ) or any(
        token.startswith("--download=") and references_container_asset(token)
        for token in tokens
    )


def _copies_asset(tokens: list[str]) -> bool:
    return any(name in COPY_COMMANDS for name in _names(tokens))


def export_denied(command: str) -> bool:
    """Return whether a terminal command exports container EDA assets.

    Read-only references (``ls``, ``kicad-cli`` environment variables) stay
    allowed; copying, archiving, ``docker cp``, and workspace downloads of an
    asset path are denied.
    """
    if not any(prefix in command for prefix in CONTAINER_ASSET_PREFIXES):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        # An unparseable command that names a container asset fails closed.
        return True
    if not any(references_container_asset(token) for token in tokens):
        return False
    return _container_copy(tokens) or _download_of_asset(tokens) or _copies_asset(tokens)


def main() -> int:
    payload = event()
    tool_input: Any = payload.get("tool_input")
    command = (
        cast(dict[str, Any], tool_input).get("command", "")
        if isinstance(tool_input, dict)
        else ""
    )
    if not isinstance(command, str) or not export_denied(command):
        return 0
    result(decision="deny", reason=REASON)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
