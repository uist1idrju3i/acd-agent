"""Append one typed rationale record and validate the complete document."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, TypedDict, cast

# pyright: reportUnknownVariableType=false,reportUnknownMemberType=false,reportUnknownArgumentType=false,reportUnnecessaryIsInstance=false,reportUnnecessaryCast=false,reportGeneralTypeIssues=false


class GraphNode(TypedDict):
    id: str
    attrs: dict[str, Any]


class RationaleRecord(TypedDict, total=False):
    rationale_id: str
    subject_nodes: list[str]
    subject_attrs: list[str]
    driving_requirements: list[str]
    driving_requirement_refs: list[str]


class RationaleDocument(TypedDict):
    schema_version: str
    graph_id: str
    revision: str
    records: list[RationaleRecord]


def subject_hash(graph: dict[str, Any], nodes: list[str], attrs: list[str]) -> str:
    by_id = {cast(GraphNode, node)["id"]: cast(GraphNode, node) for node in graph["nodes"]}
    values = []
    for node_id in sorted(nodes):
        if node_id not in by_id:
            raise ValueError(f"subject node does not exist: {node_id}")
        node_attrs = by_id[node_id].get("attrs", {})
        for attr in sorted(attrs):
            if attr not in node_attrs:
                raise ValueError(f"subject attribute does not exist: {node_id}.{attr}")
            values.append([node_id, attr, node_attrs[attr]])
    payload = json.dumps(
        values, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--rationale", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    args = parser.parse_args()
    try:
        graph = cast(dict[str, Any], json.loads(args.graph.read_text(encoding="utf-8")))
        document = cast(
            RationaleDocument, json.loads(args.rationale.read_text(encoding="utf-8"))
        )
        record = cast(RationaleRecord, json.loads(args.record.read_text(encoding="utf-8")))
        if not isinstance(record, dict):
            raise ValueError("record must be a JSON object")
        nodes = cast(list[str], record.get("subject_nodes"))
        attrs = cast(list[str], record.get("subject_attrs"))
        if not isinstance(nodes, list) or not nodes or not all(
            isinstance(value, str) for value in nodes
        ):
            raise ValueError("subject_nodes must be a non-empty string list")
        if len(nodes) != len(set(nodes)):
            raise ValueError("subject_nodes must not contain duplicates")
        if not isinstance(attrs, list) or not attrs or not all(
            isinstance(value, str) for value in attrs
        ):
            raise ValueError("subject_attrs must be a non-empty string list")
        if len(attrs) != len(set(attrs)):
            raise ValueError("subject_attrs must not contain duplicates")
        existing = cast(list[RationaleRecord], document.get("records"))
        if not isinstance(existing, list):
            raise ValueError("rationale records must be a list")
        covered = {
            (node_id, attr)
            for old in existing
            for node_id in cast(list[str], old.get("subject_nodes", []))
            for attr in cast(list[str], old.get("subject_attrs", []))
        }
        duplicate = [
            (node_id, attr)
            for node_id in nodes
            for attr in attrs
            if (node_id, attr) in covered
        ]
        if duplicate:
            raise ValueError(f"duplicate rationale coverage: {duplicate}")
        record["subject_hash"] = subject_hash(graph, nodes, attrs)
        record["target_revision"] = graph["revision"]
        original = args.rationale.read_text(encoding="utf-8")
        document["records"].append(record)
        args.rationale.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        repo_root = Path(__file__).resolve().parents[5]
        check = subprocess.run(
            [
                sys.executable,
                str(repo_root / "scripts/check_rationale.py"),
                "--graph",
                str(args.graph),
                "--rationale",
                str(args.rationale),
            ],
            cwd=repo_root,
            check=False,
        )
        if check.returncode != 0:
            args.rationale.write_text(original, encoding="utf-8")
            return 2
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"rationale record failed closed: {exc}", file=sys.stderr)
        return 2
    print(f"appended rationale record: {record.get('rationale_id', '<unknown>')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
