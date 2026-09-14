"""Tests for documentation quote-validity checks."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_docs.py"


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("verify_docs", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _markdown(module: Any, tmp_path: Path, body: str) -> Any:
    path = tmp_path / "example.md"
    path.write_text(body, encoding="utf-8")
    return module.MarkdownFile(path)


def _quote(
    path: Path,
    *,
    fetched_at: str = "2025-01-10T09:00:00Z",
    valid_until: str = "2025-01-17T09:00:00Z",
) -> None:
    path.write_text(
        json.dumps({"fetched_at": fetched_at, "valid_until": valid_until}),
        encoding="utf-8",
    )


def test_evaluated_at_inside_default_quote_window_has_no_errors(tmp_path: Path) -> None:
    module = _module()
    md = _markdown(
        module,
        tmp_path,
        "```bash\nrun --evaluated-at 2025-01-14T00:00:00Z\n```\n",
    )
    module.check_evaluated_at(md)
    assert md.errors == []


def test_evaluated_at_after_valid_until_is_rejected(tmp_path: Path) -> None:
    module = _module()
    md = _markdown(
        module,
        tmp_path,
        "```bash\nrun --evaluated-at 2025-01-18T00:00:00Z\n```\n",
    )
    module.check_evaluated_at(md)
    assert len(md.errors) == 1
    assert "valid_until" in md.errors[0]


def test_evaluated_at_before_fetched_at_is_rejected(tmp_path: Path) -> None:
    module = _module()
    md = _markdown(
        module,
        tmp_path,
        "```bash\nrun --evaluated-at 2025-01-09T00:00:00Z\n```\n",
    )
    module.check_evaluated_at(md)
    assert len(md.errors) == 1
    assert "fetched_at" in md.errors[0]


def test_explicit_quote_record_uses_its_window(tmp_path: Path) -> None:
    module = _module()
    quote = tmp_path / "quote.json"
    _quote(
        quote,
        fetched_at="2026-02-01T00:00:00Z",
        valid_until="2026-02-10T00:00:00Z",
    )
    md = _markdown(
        module,
        tmp_path,
        f"```bash\nrun --quote-record {quote} --evaluated-at 2026-02-05T00:00:00Z\n```\n",
    )
    module.check_evaluated_at(md)
    assert md.errors == []


def test_missing_explicit_quote_record_is_rejected(tmp_path: Path) -> None:
    module = _module()
    quote = tmp_path / "missing.json"
    md = _markdown(
        module,
        tmp_path,
        f"```bash\nrun --quote-record {quote} --evaluated-at 2026-02-05T00:00:00Z\n```\n",
    )
    module.check_evaluated_at(md)
    assert len(md.errors) == 1
    assert "quote record could not be read" in md.errors[0]


def test_fence_without_evaluated_at_is_ignored(tmp_path: Path) -> None:
    module = _module()
    md = _markdown(module, tmp_path, "```bash\nrun --quote-record quote.json\n```\n")
    module.check_evaluated_at(md)
    assert md.errors == []
