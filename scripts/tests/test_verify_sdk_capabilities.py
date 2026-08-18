"""Tests for fail-closed SDK capability catalog verification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import verify_sdk_capabilities as verifier


def _catalog(
    *,
    modules: list[str] | None = None,
    representative_apis: list[str] | None = None,
    adoption: str = "採用",
    roadmap: str | None = None,
) -> verifier.CapabilityCatalog:
    return verifier.CapabilityCatalog.model_validate(
        {
            "sdk_version": "1.42.1",
            "submodule_commit": "a" * 40,
            "scanned_packages": [
                {
                    "prefix": "sdk",
                    "path": "vendor/software-agent-sdk/openhands-sdk/openhands/sdk",
                },
                {
                    "prefix": "tools",
                    "path": "vendor/software-agent-sdk/openhands-tools/openhands/tools",
                },
                {
                    "prefix": "workspace",
                    "path": "vendor/software-agent-sdk/openhands-workspace/openhands/workspace",
                },
            ],
            "non_target_packages": [],
            "capabilities": [
                {
                    "domain": "sdk.test",
                    "modules": modules or ["sdk.foo"],
                    "representative_apis": representative_apis or ["Foo"],
                    "use": "test",
                    "adoption": adoption,
                    "rationale": "test",
                    "verification": "test",
                    "roadmap": roadmap,
                }
            ],
        }
    )


@pytest.fixture
def valid_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, set[str]]:
    monkeypatch.setattr(verifier, "_submodule_commit", lambda: "a" * 40)
    monkeypatch.setattr(verifier, "_read_version", lambda: "1.42.1")
    monkeypatch.setattr(
        verifier,
        "_markdown_block",
        lambda: verifier.render_markdown(_catalog()),
    )
    return {"sdk.foo": {"Foo"}}


def test_extract_public_modules_uses_ast_without_importing(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        "__all__ = ['Exported']\nclass Exported: pass\n", encoding="utf-8"
    )
    (package / "public.py").write_text(
        "def function(): pass\nclass _Private: pass\n", encoding="utf-8"
    )
    (package / "_private.py").write_text("class Hidden: pass\n", encoding="utf-8")

    modules = verifier._package_modules("test", package)  # pyright: ignore[reportPrivateUsage]

    assert modules == {"test": {"Exported"}, "test.public": {"function"}}


def test_real_vendor_extraction_is_nonempty() -> None:
    modules = verifier.extract_public_modules()

    assert len(modules) > 0
    assert {"sdk", "tools", "workspace"} <= modules.keys()


def test_unclaimed_module_fails(valid_environment: dict[str, set[str]]) -> None:
    errors = verifier.validate_catalog(
        _catalog(),
        {**valid_environment, "sdk.bar": {"Bar"}},
    )

    assert any("unclaimed module: sdk.bar" in error for error in errors)


def test_stale_claim_fails(valid_environment: dict[str, set[str]]) -> None:
    errors = verifier.validate_catalog(
        _catalog(modules=["sdk.missing"]),
        valid_environment,
    )

    assert any("stale module pattern sdk.missing" in error for error in errors)


def test_missing_representative_api_fails(
    valid_environment: dict[str, set[str]],
) -> None:
    errors = verifier.validate_catalog(
        _catalog(representative_apis=["Missing"]),
        valid_environment,
    )

    assert any("representative API is absent" in error for error in errors)


def test_planned_adoption_requires_roadmap(
    valid_environment: dict[str, set[str]],
) -> None:
    errors = verifier.validate_catalog(
        _catalog(adoption="採用予定"),
        valid_environment,
    )

    assert any("requires roadmap" in error for error in errors)


def test_roadmap_reference_must_exist(
    valid_environment: dict[str, set[str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roadmap = tmp_path / "roadmap.md"
    roadmap.write_text("# Roadmap\n", encoding="utf-8")
    monkeypatch.setattr(verifier, "ROADMAP_PATH", roadmap)

    errors = verifier.validate_catalog(
        _catalog(adoption="採用予定", roadmap="4.4"),
        valid_environment,
    )

    assert any("roadmap reference is absent" in error for error in errors)


def test_markdown_drift_fails(
    valid_environment: dict[str, set[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verifier, "_markdown_block", lambda: "drift")

    errors = verifier.validate_catalog(_catalog(), valid_environment)

    assert "generated Markdown block differs from JSON" in errors


def test_submodule_commit_mismatch_fails(
    valid_environment: dict[str, set[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verifier, "_submodule_commit", lambda: "b" * 40)

    errors = verifier.validate_catalog(_catalog(), valid_environment)

    assert "submodule_commit does not match vendor/software-agent-sdk HEAD" in errors


def test_catalog_json_is_valid() -> None:
    catalog = json.loads(verifier.CATALOG_PATH.read_text(encoding="utf-8"))

    assert verifier.CapabilityCatalog.model_validate(catalog).sdk_version == "1.42.1"
