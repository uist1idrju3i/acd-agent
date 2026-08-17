"""Append one typed rationale record and validate the complete document."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from pydantic import TypeAdapter

JsonObject = dict[str, object]
JSON_OBJECT = TypeAdapter(JsonObject)
JSON_LIST = TypeAdapter(list[object])


def _load_json(path: Path) -> object:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    return value


def _object(value: object, name: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return JSON_OBJECT.validate_python(value)


def _string_list(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a non-empty string list")
    items = JSON_LIST.validate_python(value)
    if not all(
        isinstance(item, str) for item in items
    ):
        raise ValueError(f"{name} must be a non-empty string list")
    result: list[str] = []
    for item in items:
        if isinstance(item, str):
            result.append(item)
    return result


def _objects(value: object, name: str) -> list[JsonObject]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON object list")
    items = JSON_LIST.validate_python(value)
    if not all(isinstance(item, dict) for item in items):
        raise ValueError(f"{name} must be a JSON object list")
    result: list[JsonObject] = []
    for item in items:
        if isinstance(item, dict):
            result.append(JSON_OBJECT.validate_python(item))
    return result


def subject_hash(graph: JsonObject, nodes: list[str], attrs: list[str]) -> str:
    graph_nodes = _objects(graph.get("nodes"), "graph.nodes")
    by_id: dict[str, JsonObject] = {}
    for node in graph_nodes:
        node_id = node.get("id")
        if not isinstance(node_id, str):
            raise ValueError("graph node id must be a string")
        by_id[node_id] = node

    values: list[list[object]] = []
    for node_id in sorted(nodes):
        node = by_id.get(node_id)
        if node is None:
            raise ValueError(f"subject node does not exist: {node_id}")
        node_attrs = _object(node.get("attrs"), f"attrs for {node_id}")
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
        graph = _object(_load_json(args.graph), "graph")
        document = _object(_load_json(args.rationale), "rationale document")
        record = _object(_load_json(args.record), "record")
        nodes = _string_list(record.get("subject_nodes"), "subject_nodes")
        attrs = _string_list(record.get("subject_attrs"), "subject_attrs")
        if len(nodes) != len(set(nodes)):
            raise ValueError("subject_nodes must not contain duplicates")
        if len(attrs) != len(set(attrs)):
            raise ValueError("subject_attrs must not contain duplicates")
        existing = _objects(document.get("records"), "rationale records")
        covered = {
            (old_node, old_attr)
            for old in existing
            for old_node in _string_list(old.get("subject_nodes"), "subject_nodes")
            for old_attr in _string_list(old.get("subject_attrs"), "subject_attrs")
        }
        duplicate = [
            (node_id, attr)
            for node_id in nodes
            for attr in attrs
            if (node_id, attr) in covered
        ]
        if duplicate:
            raise ValueError(f"duplicate rationale coverage: {duplicate}")
        revision = graph.get("revision")
        if not isinstance(revision, str):
            raise ValueError("graph revision must be a string")
        record["subject_hash"] = subject_hash(graph, nodes, attrs)
        record["target_revision"] = revision
        original = args.rationale.read_text(encoding="utf-8")
        existing.append(record)
        records_value: list[object] = []
        records_value.extend(existing)
        document["records"] = records_value
        args.rationale.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        repo_root = Path(__file__).resolve().parents[5]
        check = subprocess.run(
            [
                "uv",
                "run",
                "python",
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
    rationale_id = record.get("rationale_id", "<unknown>")
    print(f"appended rationale record: {rationale_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
