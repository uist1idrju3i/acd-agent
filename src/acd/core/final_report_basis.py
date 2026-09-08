"""Machine-generate the final report's source-change and design-value basis.

An agent-written final report must not claim "no source changes" or restate
component values and nets from memory: the facts come from
``git log --stat <bootstrap>..HEAD`` plus the worktree state, and from the
design input (spec) or graph. This module collects both deterministically and
renders them verbatim. Everything here is an L3 observation; it never grants
pass authority and never inspects Evidence.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, cast

from acd.schema.design_fixture import DesignFixtureSpec
from acd.schema.design_graph import DesignGraph
from acd.schema.final_report_basis import (
    DesignComponentValue,
    DesignNetValue,
    DesignValueSection,
    FinalReportBasis,
    SourceChangeSection,
)

DEFAULT_BOOTSTRAP_RECORD = Path(".openhands") / "bootstrap-record.json"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _bootstrap_revision(
    root: Path, explicit: str | None, record_path: Path | None
) -> tuple[str | None, str | None, str | None]:
    """Return (revision, record path used, failure reason)."""
    record_revision: str | None = None
    used_record: str | None = None
    candidate = record_path or root / DEFAULT_BOOTSTRAP_RECORD
    if candidate.is_file():
        used_record = str(candidate)
        try:
            payload: object = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return None, used_record, f"bootstrap record is unreadable: {exc}"
        value = (
            cast(dict[str, Any], payload).get("resolved_revision")
            if isinstance(payload, dict)
            else None
        )
        if not isinstance(value, str) or not value:
            return (
                None,
                used_record,
                f"bootstrap record has no resolved_revision: {candidate}",
            )
        record_revision = value
    if explicit is not None and record_revision is not None and explicit != record_revision:
        return (
            None,
            used_record,
            f"explicit bootstrap revision {explicit} disagrees with the "
            f"record's resolved_revision {record_revision}",
        )
    revision = explicit or record_revision
    if revision is None:
        return None, used_record, (
            "bootstrap revision unavailable; the committed source changes "
            "cannot be enumerated"
        )
    return revision, used_record, None


def collect_source_changes(
    root: Path,
    *,
    bootstrap_record: Path | None = None,
    bootstrap_revision: str | None = None,
) -> SourceChangeSection:
    """Collect git facts for the report's source-change section."""
    revision, used_record, failure = _bootstrap_revision(
        root, bootstrap_revision, bootstrap_record
    )
    head_result = _git(root, "rev-parse", "HEAD")
    head = head_result.stdout.strip() if head_result.returncode == 0 else None
    status_result = _git(
        root, "status", "--porcelain", "--untracked-files=all"
    )
    diff_result = _git(root, "diff", "HEAD", "--stat")
    worktree_status = status_result.stdout if status_result.returncode == 0 else ""
    worktree_diff_stat = diff_result.stdout if diff_result.returncode == 0 else ""
    section = SourceChangeSection(
        status="unknown",
        bootstrap_record=used_record,
        bootstrap_revision=revision,
        head_revision=head,
        worktree_status=worktree_status,
        worktree_diff_stat=worktree_diff_stat,
    )
    if failure is not None:
        return section.model_copy(update={"reason": failure})
    if revision is None:  # pragma: no cover - failure covers this
        return section.model_copy(
            update={
                "reason": (
                    "bootstrap revision unavailable; the committed source "
                    "changes cannot be enumerated"
                )
            }
        )
    if head is None:
        return section.model_copy(
            update={"reason": f"git rev-parse HEAD failed: {head_result.stderr.strip()}"}
        )
    ancestor = _git(root, "merge-base", "--is-ancestor", revision, "HEAD")
    if ancestor.returncode != 0:
        return section.model_copy(
            update={
                "reason": (
                    f"bootstrap revision {revision} is not an ancestor of HEAD"
                )
            }
        )
    commits_result = _git(root, "log", "--format=%H", f"{revision}..HEAD")
    log_result = _git(
        root, "log", "--stat", "--format=%H %s", f"{revision}..HEAD"
    )
    if commits_result.returncode != 0 or log_result.returncode != 0:
        return section.model_copy(
            update={
                "reason": (
                    "git log failed: "
                    f"{(commits_result.stderr or log_result.stderr).strip()}"
                )
            }
        )
    commits = [line for line in commits_result.stdout.splitlines() if line.strip()]
    committed_log = log_result.stdout.strip()
    status = "clean" if not commits and not worktree_status.strip() else "changed"
    return section.model_copy(
        update={
            "status": status,
            "committed_commits": commits,
            "committed_log": committed_log,
        }
    )


def _str_attr(attrs: dict[str, Any], key: str) -> str | None:
    value = attrs.get(key)
    return value if isinstance(value, str) else None


def _spec_values(path: Path, spec: DesignFixtureSpec) -> DesignValueSection:
    components = [
        DesignComponentValue(
            refdes=component.refdes,
            value=_str_attr(component.attrs, "value"),
            mpn=_str_attr(component.attrs, "mpn"),
            lcsc=_str_attr(component.attrs, "lcsc"),
            footprint=_str_attr(component.attrs, "footprint"),
            pads=dict(component.pads),
        )
        for component in sorted(spec.components, key=lambda item: item.refdes)
    ]
    net_connections: dict[str, list[str]] = {net.net_id: [] for net in spec.nets}
    for component in spec.components:
        for pad, net_id in component.pads.items():
            if net_id is None:
                continue
            net_connections.setdefault(net_id, []).append(f"{component.refdes}.{pad}")
    nets = [
        DesignNetValue(net_id=net_id, connections=sorted(connections))
        for net_id, connections in sorted(net_connections.items())
    ]
    return DesignValueSection(
        source=str(path),
        source_kind="spec",
        design_name=spec.design_name,
        graph_id=spec.graph_id,
        revision=spec.revision,
        components=components,
        nets=nets,
    )


def _graph_values(path: Path, graph: DesignGraph) -> DesignValueSection:
    refdes_by_node: dict[str, str] = {}
    components: list[DesignComponentValue] = []
    for node in sorted(graph.nodes, key=lambda item: item.id):
        if node.kind != "electrical.component":
            continue
        refdes = _str_attr(node.attrs, "refdes") or node.id
        refdes_by_node[node.id] = refdes
        components.append(
            DesignComponentValue(
                refdes=refdes,
                value=_str_attr(node.attrs, "value"),
                mpn=_str_attr(node.attrs, "mpn"),
                lcsc=_str_attr(node.attrs, "lcsc"),
                footprint=_str_attr(node.attrs, "footprint"),
            )
        )
    pads_by_component: dict[str, dict[str, str | None]] = {
        component.refdes: {} for component in components
    }
    net_connections: dict[str, list[str]] = {}
    for node in sorted(graph.nodes, key=lambda item: item.id):
        if node.kind != "electrical.pin":
            continue
        refdes = refdes_by_node.get(_str_attr(node.attrs, "component") or "")
        pad = _str_attr(node.attrs, "pad")
        net = _str_attr(node.attrs, "net")
        no_connect = node.attrs.get("no_connect") is True
        if refdes is None or pad is None:
            continue
        member = f"{refdes}.{pad}"
        if no_connect or net is None:
            pads_by_component.setdefault(refdes, {})[pad] = None
            continue
        pads_by_component.setdefault(refdes, {})[pad] = net
        net_connections.setdefault(net, []).append(member)
    for component in components:
        component.pads.update(pads_by_component.get(component.refdes, {}))
    for node in graph.nodes:
        if node.kind == "electrical.net":
            net_connections.setdefault(node.id, [])
    nets = [
        DesignNetValue(net_id=net_id, connections=sorted(connections))
        for net_id, connections in sorted(net_connections.items())
    ]
    return DesignValueSection(
        source=str(path),
        source_kind="graph",
        graph_id=graph.graph_id,
        revision=graph.revision,
        components=components,
        nets=nets,
    )


def collect_design_values(path: Path) -> DesignValueSection:
    """Extract the component/net value table from a spec or graph file."""
    document: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"design input is not a JSON object: {path}")
    if "design_name" in cast(dict[str, Any], document):
        spec = DesignFixtureSpec.model_validate(document)
        return _spec_values(path, spec)
    graph = DesignGraph.model_validate(document)
    return _graph_values(path, graph)


def collect_final_report_basis(
    root: Path,
    *,
    design_input: Path | None = None,
    bootstrap_record: Path | None = None,
    bootstrap_revision: str | None = None,
) -> FinalReportBasis:
    """Assemble the machine-generated basis for the final report."""
    notes: list[str] = []
    source_changes = collect_source_changes(
        root,
        bootstrap_record=bootstrap_record,
        bootstrap_revision=bootstrap_revision,
    )
    design_values: DesignValueSection | None = None
    if design_input is not None:
        try:
            design_values = collect_design_values(design_input)
        except (OSError, ValueError) as exc:
            notes.append(f"design values could not be loaded: {exc}")
    else:
        notes.append("no design input was given; design values are absent")
    unknown = source_changes.status == "unknown" or (
        design_input is not None and design_values is None
    )
    return FinalReportBasis(
        status="unknown" if unknown else "pass",
        source_changes=source_changes,
        design_values=design_values,
        notes=notes,
    )


def _fence(body: str) -> str:
    return f"```\n{body.rstrip()}\n```" if body.strip() else "```\n<empty>\n```"


def render_final_report_basis(report: FinalReportBasis) -> str:
    """Render the basis as Markdown for verbatim inclusion in the report."""
    section = report.source_changes
    lines = [
        "## source changes (machine-generated; bootstrap "
        f"{section.bootstrap_revision or 'unknown'}..HEAD "
        f"{section.head_revision or 'unknown'}, status: {section.status})",
        "",
    ]
    if section.reason is not None:
        lines.append(f"reason: {section.reason}")
        lines.append("")
    lines.append(_fence(section.committed_log or "no commits past the bootstrap revision"))
    lines.append("")
    lines.append("worktree `git status --porcelain`:")
    lines.append(_fence(section.worktree_status))
    lines.append("")
    lines.append("worktree `git diff HEAD --stat`:")
    lines.append(_fence(section.worktree_diff_stat))
    lines.append("")
    if report.design_values is not None:
        values = report.design_values
        lines.append(f"## design values (machine-extracted from {values.source})")
        lines.append("")
        lines.append("| refdes | value | mpn | lcsc | footprint | pads |")
        lines.append("|---|---|---|---|---|---|")
        for component in values.components:
            pads = ", ".join(
                f"{pad}->{net or 'no_connect'}"
                for pad, net in sorted(component.pads.items())
            )
            lines.append(
                "| {refdes} | {value} | {mpn} | {lcsc} | {footprint} | {pads} |".format(
                    refdes=component.refdes,
                    value=component.value or "",
                    mpn=component.mpn or "",
                    lcsc=component.lcsc or "",
                    footprint=component.footprint or "",
                    pads=pads,
                )
            )
        lines.append("")
        for net in values.nets:
            members = ", ".join(net.connections) or "<none>"
            lines.append(f"- `{net.net_id}`: {members}")
        lines.append("")
    for note in report.notes:
        lines.append(f"- note: {note}")
    if report.notes:
        lines.append("")
    lines.append(
        "authoritative Evidence: unverified by this basis; do not report pass "
        "or order-ready from it"
    )
    return "\n".join(lines)


__all__ = [
    "collect_design_values",
    "collect_final_report_basis",
    "collect_source_changes",
    "render_final_report_basis",
]
