# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@38a0dce164220e6c5df5947e11b8d411c1aebe9c",
# ]
# ///
"""Generate a deterministic, non-authoritative review package."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, cast

from acd.schema.design_graph import DesignGraph
from doc_inputs import (
    DesignPredicates,
    DfmReport,
    DocumentGenerationError,
    DocumentInput,
    ProjectionFigure,
    load_design_predicates,
    load_dfm_report,
    load_graph,
    load_projection_figures,
    relative_path,
    sha256_file,
    write_document,
)

TEMPLATE_ID = "acd-review-package-ja-v1"
DOCUMENT_NAME = "review-package.md"
JSON_DOCUMENT_NAME = "review-package.json"
GRAPH_DIFF_DOCUMENT_NAME = "graph-diff.json"


def _edge_keys(graph: DesignGraph) -> list[str]:
    edges = getattr(graph, "edges", ())
    keys: list[str] = []
    for edge in edges:
        raw: object = edge.model_dump(mode="json") if hasattr(edge, "model_dump") else edge
        if not isinstance(raw, dict):
            raise DocumentGenerationError("design graph edge is not an object")
        data = cast(dict[str, Any], raw)
        source = data.get("source", data.get("source_id"))
        target = data.get("target", data.get("target_id"))
        kind = data.get("kind", data.get("edge_kind", ""))
        if not isinstance(source, str) or not isinstance(target, str) or not isinstance(kind, str):
            raise DocumentGenerationError("design graph edge has invalid fields")
        keys.append(f"{source}->{target}:{kind}")
    return sorted(keys)


def build_graph_diff(previous: DesignGraph, current: DesignGraph) -> dict[str, object]:
    """Compare two revisions of the same design graph."""
    if previous.graph_id != current.graph_id:
        raise DocumentGenerationError(
            f"previous graph targets graph {previous.graph_id!r}, not {current.graph_id!r}"
        )
    if previous.revision == current.revision:
        raise DocumentGenerationError(
            f"previous graph has the same revision {current.revision!r}"
        )
    previous_nodes: dict[str, dict[str, Any]] = {
        node.id: node.model_dump(mode="json") for node in previous.nodes
    }
    current_nodes: dict[str, dict[str, Any]] = {
        node.id: node.model_dump(mode="json") for node in current.nodes
    }
    added = sorted(set(current_nodes) - set(previous_nodes))
    removed = sorted(set(previous_nodes) - set(current_nodes))
    changed: list[dict[str, object]] = []
    for node_id in sorted(set(previous_nodes) & set(current_nodes)):
        before = previous_nodes[node_id]
        after = current_nodes[node_id]
        fields = sorted(
            field
            for field in set(before) | set(after)
            if field != "id" and before.get(field) != after.get(field)
        )
        if fields:
            changed.append({"id": node_id, "changed_fields": fields})
    previous_edges = set(_edge_keys(previous))
    current_edges = set(_edge_keys(current))
    return {
        "status": "computed",
        "previous_revision": previous.revision,
        "current_revision": current.revision,
        "nodes": {
            "added": added,
            "removed": removed,
            "changed": changed,
        },
        "edges": {
            "added": sorted(current_edges - previous_edges),
            "removed": sorted(previous_edges - current_edges),
        },
    }


def _unknown_graph_diff(current: DesignGraph) -> dict[str, object]:
    return {
        "status": "unknown",
        "reason": "previous revision not declared",
        "current_revision": current.revision,
    }


def _checklist_item(
    item_id: str,
    source: str,
    subject: str,
    status: str,
    detail: str,
) -> dict[str, str]:
    return {
        "item_id": item_id,
        "source": source,
        "subject": subject,
        "status": status,
        "detail": detail,
        "reviewer_decision": "pending",
    }


def _diff_checklist(diff: dict[str, Any]) -> list[dict[str, str]]:
    if diff.get("status") != "computed":
        return [
            _checklist_item(
                "diff:unknown",
                "graph-diff",
                "previous revision",
                "unknown",
                str(diff.get("reason", "previous revision not declared")),
            )
        ]
    items: list[dict[str, str]] = []
    nodes = diff["nodes"]
    edges = diff["edges"]
    assert isinstance(nodes, dict)
    assert isinstance(edges, dict)
    for node_id in cast(list[str], nodes["added"]):
        items.append(
            _checklist_item(
                f"diff:node-added:{node_id}",
                "graph-diff",
                str(node_id),
                "changed",
                "node added",
            )
        )
    for node_id in cast(list[str], nodes["removed"]):
        items.append(
            _checklist_item(
                f"diff:node-removed:{node_id}",
                "graph-diff",
                str(node_id),
                "changed",
                "node removed",
            )
        )
    for entry in cast(list[dict[str, Any]], nodes["changed"]):
        assert isinstance(entry, dict)
        node_id = str(entry["id"])
        fields = ", ".join(str(field) for field in entry["changed_fields"])
        items.append(
            _checklist_item(
                f"diff:node-changed:{node_id}",
                "graph-diff",
                node_id,
                "changed",
                f"changed fields: {fields}",
            )
        )
    for edge in cast(list[str], edges["added"]):
        items.append(
            _checklist_item(
                f"diff:edge-added:{edge}",
                "graph-diff",
                str(edge),
                "changed",
                "edge added",
            )
        )
    for edge in cast(list[str], edges["removed"]):
        items.append(
            _checklist_item(
                f"diff:edge-removed:{edge}",
                "graph-diff",
                str(edge),
                "changed",
                "edge removed",
            )
        )
    return items


def build_checklist(
    predicates: DesignPredicates,
    dfm: DfmReport,
    figures: tuple[ProjectionFigure, ...],
    diff: dict[str, Any],
    *,
    base_dir: Path,
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for predicate in predicates.predicates:
        items.append(
            _checklist_item(
                f"design-predicates:{predicate.name}",
                "design-predicates",
                predicate.name,
                predicate.status,
                f"{predicate.evaluation_stage}: {predicate.detail}",
            )
        )
    for finding in dfm.findings:
        items.append(
            _checklist_item(
                f"dfm:finding:{finding.rule_id}",
                "dfm-report",
                finding.rule_id,
                "finding",
                finding.message,
            )
        )
    for name in sorted(dfm.unknowns):
        items.append(
            _checklist_item(
                f"dfm:unknown:{name}",
                "dfm-report",
                name,
                "unknown",
                dfm.unknowns[name],
            )
        )
    for check in dfm.checks_not_implemented:
        items.append(
            _checklist_item(
                f"dfm:not-implemented:{check.rule_id}",
                "dfm-report",
                check.rule_id,
                "not_implemented",
                check.message,
            )
        )
    for figure in figures:
        items.append(
            _checklist_item(
                f"visual-projection:{figure.projection_id}",
                "visual-projection",
                figure.projection_id,
                "view",
                (
                    f"image_path={relative_path(figure.image_path, base_dir)}; "
                    f"kind={figure.projection_type}; renderer={figure.renderer_type}; "
                    f"renderer_tool_version={figure.renderer_tool_version}; "
                    f"media_type={figure.media_type}; image_hash={figure.image_hash}"
                ),
            )
        )
    items.extend(_diff_checklist(diff))
    return items


def _projection_records(
    figures: tuple[ProjectionFigure, ...], *, base_dir: Path
) -> list[dict[str, str]]:
    return [
        {
            "projection_id": figure.projection_id,
            "kind": figure.projection_type,
            "domain": figure.domain,
            "image_path": relative_path(figure.image_path, base_dir),
            "renderer": figure.renderer_type,
            "renderer_tool_version": figure.renderer_tool_version,
            "media_type": figure.media_type,
            "image_hash": figure.image_hash,
        }
        for figure in figures
    ]


def build_review_package(
    graph: DesignGraph,
    predicates: DesignPredicates,
    dfm: DfmReport,
    figures: tuple[ProjectionFigure, ...],
    diff: dict[str, object],
    *,
    base_dir: Path,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifact_kind": "review_package",
        "record_class": "L3",
        "pass_evidence": False,
        "authority": "none",
        "graph_id": graph.graph_id,
        "target_revision": graph.revision,
        "graph_diff": diff,
        "projections": _projection_records(figures, base_dir=base_dir),
        "design_predicates": [
            {
                "name": predicate.name,
                "evaluation_stage": predicate.evaluation_stage,
                "status": predicate.status,
                "detail": predicate.detail,
            }
            for predicate in predicates.predicates
        ],
        "dfm": {
            "status": dfm.status,
            "profile_id": dfm.profile_id,
            "findings": [
                {"rule_id": finding.rule_id, "message": finding.message}
                for finding in dfm.findings
            ],
            "unknowns": dfm.unknowns,
            "checks_not_implemented": [
                {"rule_id": check.rule_id, "reason": check.message}
                for check in dfm.checks_not_implemented
            ],
        },
        "checklist": build_checklist(
            predicates, dfm, figures, diff, base_dir=base_dir
        ),
    }


def _markdown(
    graph: DesignGraph,
    package: dict[str, Any],
    figures: tuple[ProjectionFigure, ...],
    *,
    out_dir: Path,
) -> str:
    diff = package["graph_diff"]
    assert isinstance(diff, dict)
    lines = [
        f"# レビュー資料: {graph.graph_id}",
        "",
        f"- revision: `{graph.revision}`",
        "- record class: `L3`",
        "- authority: `none`",
        "",
        "## 概要",
        "",
        "本資料は設計入力と記録済み投影から生成したレビュー用L3観測であり、"
        "判定権限を持たない。所見と差分は入力の追跡可能な要約である。",
        "",
        "## graph差分",
        "",
        "```json",
        json.dumps(diff, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        "## 視覚投影一式",
        "",
    ]
    for figure in figures:
        image_link = Path(os.path.relpath(figure.image_path, out_dir)).as_posix()
        lines.extend(
            [
                f"### {figure.projection_id}",
                "",
                f"- kind: `{figure.projection_type}`",
                f"- renderer: `{figure.renderer_type}`",
                f"- hash: `{figure.image_hash}`",
                "",
                f"![{figure.projection_id}]({image_link})",
                "",
            ]
        )
    lines.extend(["## 設計述語所見", ""])
    for predicate in package["design_predicates"]:
        lines.append(
            f"- `{predicate['name']}`: `{predicate['status']}` — "
            f"{predicate['detail']}"
        )
    lines.extend(["", "## DFM所見", "", f"- status: `{package['dfm']['status']}`"])
    for finding in package["dfm"]["findings"]:
        lines.append(f"- `{finding['rule_id']}`: {finding['message']}")
    for name, reason in sorted(package["dfm"]["unknowns"].items()):
        lines.append(f"- unknown `{name}`: {reason}")
    for check in package["dfm"]["checks_not_implemented"]:
        lines.append(f"- not_implemented `{check['rule_id']}`: {check['reason']}")
    lines.extend(
        [
            "",
            "## チェックリスト表",
            "",
            "| item_id | source | subject | status | detail | reviewer_decision |",
            "|---|---|---|---|---|---|",
        ]
    )
    for item in package["checklist"]:
        detail = str(item["detail"]).replace("|", "\\|")
        lines.append(
            f"| `{item['item_id']}` | {item['source']} | `{item['subject']}` "
            f"| {item['status']} | {detail} | {item['reviewer_decision']} |"
        )
    lines.extend(
        [
            "",
            "## 権限注記",
            "",
            "この資料は`authority: none`のL3記録であり、レビュー担当者の判断欄は"
            "`pending`で初期化される。資料の欠落や読み取り不能はunknownとして扱う。",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--projections", type=Path, action="append", required=True)
    parser.add_argument("--design-predicates", type=Path, required=True)
    parser.add_argument("--dfm-report", type=Path, required=True)
    parser.add_argument("--previous-graph", type=Path, default=None)
    parser.add_argument("--no-previous-revision", action="store_true")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--base-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if (args.previous_graph is None) == (not args.no_previous_revision):
        raise DocumentGenerationError(
            "exactly one of --previous-graph or --no-previous-revision is required"
        )
    graph, graph_input = load_graph(args.graph)
    figures, projection_inputs = load_projection_figures(
        args.projections, target_revision=graph.revision
    )
    predicates = load_design_predicates(args.design_predicates, graph)
    if predicates.target_revision != graph.revision:
        raise DocumentGenerationError(
            f"design predicates {args.design_predicates} targets revision "
            f"{predicates.target_revision!r}, not {graph.revision!r}"
        )
    dfm = load_dfm_report(args.dfm_report, graph)
    if dfm.target_revision != graph.revision:
        raise DocumentGenerationError(
            f"DFM report {args.dfm_report} targets revision "
            f"{dfm.target_revision!r}, not {graph.revision!r}"
        )
    previous_input: DocumentInput | None = None
    if args.previous_graph is not None:
        previous, previous_input = load_graph(args.previous_graph)
        diff = build_graph_diff(previous, graph)
    else:
        diff = _unknown_graph_diff(graph)
    inputs = [
        graph_input,
        *projection_inputs,
        *(
            DocumentInput(path=figure.image_path, content_hash=sha256_file(figure.image_path))
            for figure in figures
        ),
        DocumentInput(
            path=args.design_predicates,
            content_hash=sha256_file(args.design_predicates),
        ),
        DocumentInput(path=args.dfm_report, content_hash=sha256_file(args.dfm_report)),
    ]
    if previous_input is not None:
        inputs.append(previous_input)
    package = build_review_package(
        graph, predicates, dfm, figures, diff, base_dir=args.base_dir
    )
    outputs = (
        (
            "review_package",
            _markdown(graph, package, figures, out_dir=args.out_dir),
            DOCUMENT_NAME,
        ),
        (
            "review_package_json",
            json.dumps(package, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            JSON_DOCUMENT_NAME,
        ),
        (
            "graph_diff_json",
            json.dumps(diff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            GRAPH_DIFF_DOCUMENT_NAME,
        ),
    )
    for document_kind, body, document_name in outputs:
        document_path, provenance_path = write_document(
            document_kind=document_kind,
            body=body,
            out_dir=args.out_dir,
            document_name=document_name,
            template_id=TEMPLATE_ID,
            generator=Path(__file__).resolve(),
            graph=graph,
            inputs=inputs,
            base_dir=args.base_dir,
        )
        print(f"generated {document_path}")
        print(f"provenance {provenance_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DocumentGenerationError as error:
        print(f"review package generation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
