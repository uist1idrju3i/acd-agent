#!/usr/bin/env python3
"""Deterministic documentation verification (AGENTS.md document verification contract).

Checks all tracked Markdown files (excluding vendor/) for:

1. Relative links resolve to existing files.
2. GitHub-compatible anchors (punctuation removal, space-to-hyphen, duplicate
   slug numbering) resolve to existing headings.
3. Mermaid blocks start with a known diagram type.
4. Code fences are balanced.
5. Heading hierarchy does not skip levels and each file starts with one H1.
6. Glossary terms are not defined twice.
7. `git diff --check` reports no whitespace errors.

Unknown or unverifiable states are treated as failures (fail-closed).
Exit code 0 means all checks passed.
"""

from __future__ import annotations

import re
import subprocess
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GLOSSARY = REPO_ROOT / "docs" / "glossary.md"
EXCLUDED_DIRS = {"vendor", ".git", ".venv", "node_modules"}

MERMAID_DIAGRAM_TYPES = (
    "flowchart",
    "graph",
    "sequenceDiagram",
    "classDiagram",
    "stateDiagram",
    "stateDiagram-v2",
    "erDiagram",
    "journey",
    "gantt",
    "pie",
    "mindmap",
    "timeline",
    "gitGraph",
    "quadrantChart",
    "requirementDiagram",
)

FENCE_RE = re.compile(r"^(\s*)(```+|~~~+)(.*)$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
INLINE_LINK_RE = re.compile(r"!?\[(?:[^\]\[]|\[[^\]]*\])*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
INLINE_CODE_RE = re.compile(r"`([^`]+)`")


def list_markdown_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.md", "**/*.md"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    files: list[Path] = []
    for line in out.stdout.splitlines():
        path = Path(line)
        if path.parts and path.parts[0] in EXCLUDED_DIRS:
            continue
        files.append(REPO_ROOT / path)
    if not files:
        raise SystemExit("fail-closed: no tracked Markdown files found")
    return sorted(files)


def strip_markdown_inline(text: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!?\[((?:[^\]\[]|\[[^\]]*\])*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"</?[a-zA-Z][^>]*>", "", text)
    text = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", text)
    return text


def github_slug(heading: str, seen: dict[str, int]) -> str:
    text = strip_markdown_inline(heading).strip().lower()
    chars: list[str] = []
    for ch in text:
        if ch in {" ", "-", "_"}:
            chars.append(ch)
            continue
        category = unicodedata.category(ch)
        if category.startswith(("L", "N")) or category == "Mn":
            chars.append(ch)
    slug = "".join(chars).replace(" ", "-")
    count = seen.get(slug, 0)
    seen[slug] = count + 1
    return slug if count == 0 else f"{slug}-{count}"


class MarkdownFile:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lines = path.read_text(encoding="utf-8").splitlines()
        self.errors: list[str] = []
        self.headings: list[tuple[int, int, str]] = []  # (line_no, level, text)
        self.anchors: set[str] = set()
        self.links: list[tuple[int, str]] = []  # (line_no, target)
        self.inline_codes: list[tuple[int, str]] = []
        self.mermaid_blocks: list[tuple[int, list[str]]] = []
        self._parse()

    def error(self, line_no: int, message: str) -> None:
        rel = self.path.relative_to(REPO_ROOT)
        self.errors.append(f"{rel}:{line_no}: {message}")

    def _parse(self) -> None:
        fence_stack: list[tuple[int, str, str]] = []  # (line_no, marker, info)
        mermaid_lines: list[str] | None = None
        mermaid_start = 0
        for idx, line in enumerate(self.lines, start=1):
            fence = FENCE_RE.match(line)
            if fence:
                marker = fence.group(2)[0] * 3
                info = fence.group(3).strip()
                if fence_stack and fence_stack[-1][1][0] == fence.group(2)[0] and not info:
                    _, _, open_info = fence_stack.pop()
                    if open_info.startswith("mermaid") and mermaid_lines is not None:
                        self.mermaid_blocks.append((mermaid_start, mermaid_lines))
                        mermaid_lines = None
                else:
                    fence_stack.append((idx, marker, info))
                    if info.startswith("mermaid"):
                        mermaid_lines = []
                        mermaid_start = idx
                continue
            if fence_stack:
                if mermaid_lines is not None:
                    mermaid_lines.append(line)
                continue
            heading = HEADING_RE.match(line)
            if heading:
                self.headings.append((idx, len(heading.group(1)), heading.group(2)))
            for match in INLINE_LINK_RE.finditer(line):
                self.links.append((idx, match.group(1)))
            no_links = INLINE_LINK_RE.sub(" ", line)
            for match in INLINE_CODE_RE.finditer(no_links):
                self.inline_codes.append((idx, match.group(1)))
        for line_no, marker, _ in fence_stack:
            self.error(line_no, f"unclosed code fence ({marker})")
        seen: dict[str, int] = {}
        for _, _, text in self.headings:
            self.anchors.add(github_slug(text, seen))


def check_headings(md: MarkdownFile) -> None:
    if not md.headings:
        md.error(1, "no headings found")
        return
    first_line, first_level, _ = md.headings[0]
    if first_level != 1:
        md.error(first_line, "first heading must be H1")
    h1_count = sum(1 for _, level, _ in md.headings if level == 1)
    if h1_count != 1:
        md.error(md.headings[0][0], f"expected exactly one H1, found {h1_count}")
    previous = md.headings[0][1]
    for line_no, level, text in md.headings[1:]:
        if level > previous + 1:
            md.error(line_no, f"heading level skips from H{previous} to H{level}: {text!r}")
        previous = level


def check_links(md: MarkdownFile, anchor_index: dict[Path, set[str]]) -> None:
    for line_no, raw_target in md.links:
        target = raw_target.strip("<>")
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        if target.startswith("#"):
            anchor = target[1:]
            if anchor not in md.anchors:
                md.error(line_no, f"anchor not found in this file: #{anchor}")
            continue
        path_part, _, anchor = target.partition("#")
        resolved = (md.path.parent / path_part).resolve()
        if not resolved.exists():
            md.error(line_no, f"relative link target does not exist: {raw_target}")
            continue
        if anchor:
            if resolved not in anchor_index:
                md.error(line_no, f"anchor target is not a checked Markdown file: {raw_target}")
            elif anchor not in anchor_index[resolved]:
                md.error(line_no, f"anchor not found: {raw_target}")


def check_mermaid(md: MarkdownFile) -> None:
    for start_line, lines in md.mermaid_blocks:
        stripped = [line.strip() for line in lines if line.strip()]
        if not stripped:
            md.error(start_line, "empty mermaid block")
            continue
        first = stripped[0].split()[0]
        if first not in MERMAID_DIAGRAM_TYPES:
            md.error(start_line, f"unknown mermaid diagram type: {first!r}")
        for offset, line in enumerate(lines, start=1):
            for open_ch, close_ch in (("[", "]"), ("(", ")"), ("{", "}")):
                if line.count(open_ch) != line.count(close_ch):
                    md.error(
                        start_line + offset,
                        f"unbalanced {open_ch}{close_ch} in mermaid line: {line.strip()!r}",
                    )


def glossary_terms(md: MarkdownFile) -> tuple[set[str], list[str]]:
    terms: set[str] = set()
    errors: list[str] = []
    in_table = False
    section = ""
    for idx, line in enumerate(md.lines, start=1):
        heading = HEADING_RE.match(line)
        if heading:
            section = heading.group(2).strip()
        if not line.startswith("|"):
            in_table = False
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells:
            continue
        head = strip_markdown_inline(cells[0]).strip()
        if set(head) <= {"-", ":", " "}:
            in_table = True
            continue
        if not in_table:
            continue
        for part in re.split(r"[\uFF0F/]", head):  # fullwidth or ASCII solidus
            term = part.strip()
            if not term:
                continue
            if term in terms and section == "用語":
                errors.append(f"docs/glossary.md:{idx}: duplicate glossary term: {term!r}")
            terms.add(term)
    return terms, errors


def check_git_diff() -> list[str]:
    errors: list[str] = []
    for args in (["git", "diff", "--check"], ["git", "diff", "--cached", "--check"]):
        result = subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True)
        if result.returncode != 0:
            errors.extend(f"git diff --check: {line}" for line in result.stdout.splitlines())
    return errors


def main() -> int:
    files = list_markdown_files()
    mds = [MarkdownFile(path) for path in files]
    anchor_index = {md.path.resolve(): md.anchors for md in mds}

    glossary_md = next((md for md in mds if md.path == GLOSSARY), None)
    if glossary_md is None:
        print("fail-closed: docs/glossary.md not found", file=sys.stderr)
        return 1
    terms, term_errors = glossary_terms(glossary_md)

    all_errors: list[str] = list(term_errors)
    for md in mds:
        check_headings(md)
        check_links(md, anchor_index)
        check_mermaid(md)
        all_errors.extend(md.errors)
    all_errors.extend(check_git_diff())

    if all_errors:
        for error in sorted(all_errors):
            print(error, file=sys.stderr)
        print(f"verify_docs: FAILED ({len(all_errors)} error(s))", file=sys.stderr)
        return 1
    print(f"verify_docs: OK ({len(mds)} Markdown file(s) checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
