"""Fetch and archive one LCSC/EasyEDA footprint response as immutable Evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


def fetch_part(lcsc: str) -> tuple[str, bytes]:
    url = f"https://easyeda.com/api/products/{lcsc}/components?version=6.4.19.5"
    request = urllib.request.Request(url, headers={"User-Agent": "acd-agent-evidence/1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read()
    return url, payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refdes", required=True)
    parser.add_argument("--lcsc", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    url, payload = fetch_part(args.lcsc)
    retrieved_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    response_hash = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    canonical_response = json.dumps(
        json.loads(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    canonical_hash = f"sha256:{hashlib.sha256(canonical_response).hexdigest()}"
    document = {
        "schema_version": "0.1",
        "refdes": args.refdes,
        "lcsc": args.lcsc,
        "url": url,
        "retrieved_at": retrieved_at,
        "response_sha256": response_hash,
        "response_canonical_sha256": canonical_hash,
        "response": json.loads(payload),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"{args.refdes}: {url} {response_hash} {retrieved_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
