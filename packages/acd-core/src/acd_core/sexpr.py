"""Minimal deterministic S-expression reader/writer.

Used by adapters to generate and manipulate KiCad and Specctra files. The
independent reload path deliberately uses a different parser (``sexpdata``)
so that generation and verification do not share an origin.
"""

from __future__ import annotations

SExpr = str | list["SExpr"]


class SExprError(ValueError):
    """Raised when an S-expression cannot be parsed."""


def parse(text: str) -> list[SExpr]:
    """Parse text into a list of top-level S-expressions."""
    tokens = _tokenize(text)
    items: list[SExpr] = []
    pos = 0
    while pos < len(tokens):
        node, pos = _parse_one(tokens, pos)
        items.append(node)
    return items


def parse_one(text: str) -> SExpr:
    items = parse(text)
    if len(items) != 1:
        raise SExprError(f"expected exactly one top-level expression, got {len(items)}")
    return items[0]


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c in "()":
            tokens.append(c)
            i += 1
        elif c == '"':
            j = i + 1
            buf: list[str] = []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j : j + 2])
                    j += 2
                else:
                    buf.append(text[j])
                    j += 1
            if j >= n:
                raise SExprError("unterminated string")
            tokens.append('"' + "".join(buf) + '"')
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n()"':
                j += 1
            tokens.append(text[i:j])
            i = j
    return tokens


def _parse_one(tokens: list[str], pos: int) -> tuple[SExpr, int]:
    if pos >= len(tokens):
        raise SExprError("unexpected end of input")
    token = tokens[pos]
    if token == "(":
        items: list[SExpr] = []
        pos += 1
        while pos < len(tokens) and tokens[pos] != ")":
            node, pos = _parse_one(tokens, pos)
            items.append(node)
        if pos >= len(tokens):
            raise SExprError("missing closing parenthesis")
        return items, pos + 1
    if token == ")":
        raise SExprError("unexpected closing parenthesis")
    if token.startswith('"'):
        return _unescape(token[1:-1]), pos + 1
    return token, pos + 1


def _unescape(raw: str) -> str:
    return raw.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n")


_BARE_SAFE = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789_.-+*/:%[]{}~<>=!&|^?@#$"
)


def _atom(value: str, *, quote: bool) -> str:
    if not quote and value and all(ch in _BARE_SAFE for ch in value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


class Sym(str):
    """Marker for atoms that must be written without quotes."""

    __slots__ = ()


class Quoted(str):
    """Marker for atoms that must always be written quoted."""

    __slots__ = ()


def dumps(node: SExpr, *, indent: int = 0) -> str:
    """Serialize an S-expression deterministically."""
    if isinstance(node, str):
        if isinstance(node, Sym):
            return str.__str__(node)
        return _atom(node, quote=isinstance(node, Quoted))
    pad = "  " * indent
    if not node:
        return f"{pad}()"
    if all(isinstance(child, str) for child in node):
        inner = " ".join(dumps(child) for child in node)
        return f"({inner})"
    parts: list[str] = []
    head = node[0]
    parts.append("(" + dumps(head))
    i = 1
    while i < len(node) and isinstance(node[i], str) and not isinstance(node[i], list):
        parts[-1] += " " + dumps(node[i])
        i += 1
    lines = [parts[-1]]
    for child in node[i:]:
        lines.append("  " * (indent + 1) + dumps(child, indent=indent + 1).lstrip())
    lines.append("  " * indent + ")")
    return "\n".join(lines)


def find_all(node: SExpr, tag: str) -> list[list[SExpr]]:
    """Return direct children of ``node`` that are lists starting with ``tag``."""
    if isinstance(node, str):
        return []
    return [child for child in node if isinstance(child, list) and child and child[0] == tag]


def find_one(node: SExpr, tag: str) -> list[SExpr] | None:
    matches = find_all(node, tag)
    if not matches:
        return None
    if len(matches) > 1:
        raise SExprError(f"expected at most one {tag!r}, found {len(matches)}")
    return matches[0]
