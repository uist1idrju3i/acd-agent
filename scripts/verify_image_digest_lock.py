#!/usr/bin/env python3
"""Verify locked GHCR digests against current registry manifests."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ManifestOpener = Callable[..., Any]
_MANIFEST_ACCEPT = (
    "application/vnd.oci.image.index.v1+json,"
    "application/vnd.docker.distribution.manifest.list.v2+json,"
    "application/vnd.docker.distribution.manifest.v2+json"
)


def _response_json(response: Any) -> dict[str, object]:
    with response:
        value: Any = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("registry token response is not an object")
    return cast(dict[str, object], value)


def registry_manifest_digest(
    image: str,
    tag: str,
    *,
    opener: ManifestOpener = urlopen,
) -> str:
    """Resolve the current GHCR manifest digest through anonymous auth."""
    if not image.startswith("ghcr.io/") or "/" not in image.removeprefix("ghcr.io/"):
        raise ValueError(f"unsupported registry image: {image}")
    repository = image.removeprefix("ghcr.io/")
    token_request = Request(
        f"https://ghcr.io/token?scope=repository:{quote(repository, safe='/')}:pull",
        headers={"Accept": "application/json"},
    )
    token_payload = _response_json(opener(token_request, timeout=20))
    token = token_payload.get("token") or token_payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise ValueError("registry token response has no token")
    manifest_request = Request(
        f"https://ghcr.io/v2/{quote(repository, safe='/')}/manifests/{quote(tag, safe='')}",
        method="HEAD",
        headers={
            "Accept": _MANIFEST_ACCEPT,
            "Authorization": f"Bearer {token}",
        },
    )
    with opener(manifest_request, timeout=20) as response:
        digest = response.headers.get("Docker-Content-Digest")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise ValueError(f"registry manifest has no digest: {image}:{tag}")
    return digest


def verify_lock(path: Path, *, opener: ManifestOpener = urlopen) -> bool:
    """Return whether every lock entry matches its current registry manifest."""
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("image lock must be a JSON object")
        payload = cast(dict[str, Any], payload)
        entries: dict[str, Any] = {
            name: value
            for name, value in payload.items()
            if name in {"acd_tools", "acd_server"} and value is not None
        }
        if not entries:
            raise ValueError("image lock has no published entries")
        results: list[dict[str, str]] = []
        for name, value in entries.items():
            if not isinstance(value, dict):
                raise ValueError(f"malformed image entry: {name}")
            value = cast(dict[str, Any], value)
            image = value.get("image")
            tag = value.get("tag")
            digest = value.get("digest")
            if not isinstance(image, str) or not image:
                raise ValueError(f"malformed image entry: {name}")
            if not isinstance(tag, str) or not tag:
                raise ValueError(f"malformed image entry: {name}")
            if not isinstance(digest, str) or not digest:
                raise ValueError(f"malformed image entry: {name}")
            observed = registry_manifest_digest(image, tag, opener=opener)
            result = {
                "entry": name,
                "image": image,
                "tag": tag,
                "locked_digest": digest,
                "observed_digest": observed,
            }
            results.append(result)
            if observed != digest:
                print(
                    json.dumps(
                        {"ok": False, "status": "mismatch", "results": results},
                        sort_keys=True,
                    )
                )
                return False
    except (
        OSError,
        UnicodeDecodeError,
        ValueError,
        HTTPError,
        URLError,
    ) as exc:
        print(json.dumps({"ok": False, "status": "unknown", "reason": str(exc)}, sort_keys=True))
        return False
    print(json.dumps({"ok": True, "status": "match", "results": results}, sort_keys=True))
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lock",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docker" / "image-digests.json",
    )
    args = parser.parse_args(argv)
    return 0 if verify_lock(args.lock) else 1


if __name__ == "__main__":
    sys.exit(main())
