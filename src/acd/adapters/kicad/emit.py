"""Shared KiCad emit helpers: deterministic UUIDs, number formatting, requoting."""

from __future__ import annotations

import uuid

from acd.core.sexpr import Quoted, SExpr, Sym

_UUID_NS = uuid.UUID("9f2c1a34-5b7e-4c0d-9a68-2f4f7e6d5c4b")


def det_uuid(*parts: str) -> str:
    """Deterministic UUIDv5 derived from a stable key."""
    return str(uuid.uuid5(_UUID_NS, "/".join(parts)))


def fmt(value: float) -> str:
    """Format a coordinate/number without trailing zeros."""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text if text not in ("-0", "") else "0"


def requote(node: SExpr) -> SExpr:
    """Convert a parsed KiCad subtree back into emit-ready atoms.

    Parsed atoms lost their original quoting; KiCad requires strings such as
    names to stay quoted, while numbers and keywords stay bare. Atoms that
    round-trip as numbers or known keywords are emitted bare, everything else
    quoted. Direct string arguments of tags in ``_QUOTED_ARG_TAGS`` are always
    quoted because they are user text even when they look numeric.
    """
    if isinstance(node, str):
        if isinstance(node, Sym | Quoted):
            return node
        if _is_number(node) or node in _KEYWORDS:
            return Sym(node)
        return Quoted(node)
    if not node:
        return node
    head = node[0]
    force_quote = isinstance(head, str) and head in _QUOTED_ARG_TAGS
    rebuilt: list[SExpr] = [Sym(str(head)) if isinstance(head, str) else requote(head)]
    for child in node[1:]:
        if force_quote and isinstance(child, str) and not isinstance(child, Sym | Quoted):
            rebuilt.append(Quoted(child))
        else:
            rebuilt.append(requote(child))
    return rebuilt


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


_QUOTED_ARG_TAGS = frozenset(
    {"name", "number", "property", "symbol", "text", "alternate", "lib_id"}
)

_KEYWORDS = frozenset(
    {
        "yes",
        "no",
        "left",
        "right",
        "top",
        "bottom",
        "center",
        "input",
        "output",
        "bidirectional",
        "tri_state",
        "passive",
        "free",
        "unspecified",
        "power_in",
        "power_out",
        "open_collector",
        "open_emitter",
        "no_connect",
        "line",
        "inverted",
        "clock",
        "inverted_clock",
        "input_low",
        "clock_low",
        "output_low",
        "edge_clock_high",
        "non_logic",
        "none",
        "outline",
        "background",
        "default",
        "solid",
        "dash",
        "dot",
        "dash_dot",
        "dash_dot_dot",
        "reference",
        "value",
        "user",
        "smd",
        "thru_hole",
        "np_thru_hole",
        "connect",
        "circle",
        "rect",
        "roundrect",
        "oval",
        "trapezoid",
        "custom",
        "through_hole",
        "virtual",
        "board_only",
        "exclude_from_pos_files",
        "exclude_from_bom",
        "allow_solder_mask_bridges",
        "allow_missing_courtyard",
        "dnp",
        "edge",
        "full",
        "global",
        "not_allowed",
        "allowed",
    }
)
