"""Fetch and archive one LCSC/EasyEDA footprint response as immutable Evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from acd.core.lcsc_record import (
    LcscMpnCheck,
    check_declared_lcsc,
    check_declared_mpn,
    check_declared_package,
    extract_lcsc_identity,
)


def fetch_part(lcsc: str) -> tuple[str, bytes]:
    url = f"https://easyeda.com/api/products/{lcsc}/components?version=6.4.19.5"
    request = urllib.request.Request(url, headers={"User-Agent": "acd-agent-evidence/1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read()
    return url, payload


def build_record(
    *,
    refdes: str,
    lcsc: str,
    url: str,
    payload: bytes,
    retrieved_at: str,
    expect_mpn: str | None,
    expect_package: str | None,
) -> tuple[dict[str, object], int]:
    """Build one immutable record and return its expected CLI exit code."""
    decoded = json.loads(payload)
    if not isinstance(decoded, Mapping):
        raise ValueError("LCSC response must be a JSON object")
    response = cast(Mapping[str, object], decoded)
    identity = extract_lcsc_identity(response)
    response_hash = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    canonical_response = json.dumps(
        decoded,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    canonical_hash = f"sha256:{hashlib.sha256(canonical_response).hexdigest()}"
    document: dict[str, object] = {
        "schema_version": "0.1",
        "refdes": refdes,
        "lcsc": lcsc,
        "url": url,
        "retrieved_at": retrieved_at,
        "response_sha256": response_hash,
        "response_canonical_sha256": canonical_hash,
        "response": dict(response),
        "identity": identity.as_dict(),
    }
    checks: list[tuple[str, LcscMpnCheck]] = []
    if expect_mpn is not None:
        checks.append(
            ("mpn_check", check_declared_mpn(identity, declared_mpn=expect_mpn))
        )
    if expect_package is not None:
        checks.append(
            (
                "package_check",
                check_declared_package(
                    identity,
                    declared_package=expect_package,
                ),
            )
        )
    lcsc_check = check_declared_lcsc(identity, declared_lcsc=lcsc)
    checks.append(("lcsc_check", lcsc_check))
    for name, check in checks:
        document[name] = check.as_dict()
    exit_code = 0
    for name, check in checks:
        if name == "lcsc_check":
            if check.state == "mismatch":
                exit_code = 2
        elif check.state != "match":
            exit_code = 2
    return document, exit_code


def _summary(
    refdes: str,
    lcsc: str,
    identity: Mapping[str, object],
    checks: Mapping[str, object],
) -> str:
    manufacturer_part = identity.get("manufacturer_part") or "<unknown>"
    package = identity.get("package") or "<unknown>"
    manufacturer = identity.get("manufacturer") or "<unknown>"
    description = identity.get("description") or "<no description>"
    suffix = " ".join(
        f"{name}={cast(Mapping[str, object], value).get('state')}"
        for name, value in checks.items()
        if isinstance(value, Mapping)
    )
    return (
        f"{refdes}: {lcsc} = {manufacturer_part} ({package}) {manufacturer} "
        f"— {description}" + (f" {suffix}" if suffix else "")
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refdes", required=True)
    parser.add_argument("--lcsc", required=True)
    parser.add_argument("--expect-mpn")
    parser.add_argument("--expect-package")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    url, payload = fetch_part(args.lcsc)
    retrieved_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    document, exit_code = build_record(
        refdes=args.refdes,
        lcsc=args.lcsc,
        url=url,
        payload=payload,
        retrieved_at=retrieved_at,
        expect_mpn=args.expect_mpn,
        expect_package=args.expect_package,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    identity = cast(dict[str, object], document["identity"])
    checks = {
        key: value
        for key, value in document.items()
        if key.endswith("_check")
    }
    print(_summary(args.refdes, args.lcsc, identity, checks))
    if exit_code == 2:
        reasons = [
            cast(Mapping[str, object], value).get("reason")
            for value in checks.values()
            if isinstance(value, Mapping)
            and cast(Mapping[str, object], value).get("state") != "match"
            and cast(Mapping[str, object], value).get("reason")
        ]
        for reason in reasons:
            print(
                f"{reason}; next: correct `lcsc`/`mpn` in the spec and re-fetch, "
                "or pick another part; do not edit the record"
            )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
