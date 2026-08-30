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
    references: list[dict[str, str]] | None = None,
) -> verifier.CapabilityCatalog:
    return verifier.CapabilityCatalog.model_validate(
        {
            "sdk_version": "1.44.1",
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
                    "references": references or [],
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
    monkeypatch.setattr(verifier, "_read_version", lambda: "1.44.1")
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


@pytest.mark.parametrize("package_name", ["missing", "empty"])
def test_extract_public_modules_fails_closed_for_invalid_scan_root(
    package_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if package_name == "empty":
        (tmp_path / package_name).mkdir()
    monkeypatch.setattr(verifier, "REPO_ROOT", tmp_path)

    package = verifier.ScannedPackage(prefix="test", path=package_name)

    with pytest.raises(ValueError):
        verifier.extract_public_modules([package])


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


def test_adopted_capability_requires_reference(
    valid_environment: dict[str, set[str]],
) -> None:
    errors = verifier.validate_catalog(_catalog(), valid_environment)

    assert any("採用には参照宣言が必要" in error for error in errors)


def test_reference_path_must_exist(
    valid_environment: dict[str, set[str]],
) -> None:
    errors = verifier.validate_catalog(
        _catalog(
            references=[
                {
                    "kind": "sdk_internal",
                    "path": "src/acd/missing.py",
                    "symbol": "value",
                    "note": "test",
                }
            ]
        ),
        valid_environment,
    )

    assert any("reference path does not exist" in error for error in errors)


def test_reference_path_must_use_allowed_root(
    valid_environment: dict[str, set[str]],
) -> None:
    errors = verifier.validate_catalog(
        _catalog(
            references=[
                {
                    "kind": "sdk_internal",
                    "path": "vendor/example.py",
                    "symbol": "value",
                    "note": "test",
                }
            ]
        ),
        valid_environment,
    )

    assert any("outside allowed roots" in error for error in errors)


def test_direct_import_reference_requires_openhands_import(
    valid_environment: dict[str, set[str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "src/acd/example.py"
    source.parent.mkdir(parents=True)
    source.write_text("from acd.example import Foo\n", encoding="utf-8")
    monkeypatch.setattr(verifier, "REPO_ROOT", tmp_path)

    errors = verifier.validate_catalog(
        _catalog(
            references=[
                {
                    "kind": "direct_import",
                    "path": "src/acd/example.py",
                    "symbol": "Foo",
                    "note": "test",
                }
            ]
        ),
        valid_environment,
    )

    assert any("not directly imported" in error for error in errors)


def test_sdk_internal_reference_requires_note(
    valid_environment: dict[str, set[str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "src/acd/example.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n", encoding="utf-8")
    monkeypatch.setattr(verifier, "REPO_ROOT", tmp_path)

    errors = verifier.validate_catalog(
        _catalog(
            references=[
                {
                    "kind": "sdk_internal",
                    "path": "src/acd/example.py",
                    "symbol": "value",
                    "note": "",
                }
            ]
        ),
        valid_environment,
    )

    assert any("reference note is empty" in error for error in errors)


def test_plugin_reference_requires_token(
    valid_environment: dict[str, set[str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset = tmp_path / "plugins/acd/agent.md"
    asset.parent.mkdir(parents=True)
    asset.write_text("tools:\n  - terminal\n", encoding="utf-8")
    monkeypatch.setattr(verifier, "REPO_ROOT", tmp_path)

    errors = verifier.validate_catalog(
        _catalog(
            references=[
                {
                    "kind": "plugin_asset",
                    "path": "plugins/acd/agent.md",
                    "symbol": "missing_token",
                    "note": "test",
                }
            ]
        ),
        valid_environment,
    )

    assert any("plugin token is absent" in error for error in errors)


def test_planned_adoption_rejects_references(
    valid_environment: dict[str, set[str]],
) -> None:
    errors = verifier.validate_catalog(
        _catalog(
            adoption="採用予定",
            roadmap="4.5",
            references=[
                {
                    "kind": "sdk_internal",
                    "path": "src/acd/missing.py",
                    "symbol": "value",
                    "note": "test",
                }
            ],
        ),
        valid_environment,
    )

    assert any("採用予定には参照宣言を設定できない" in error for error in errors)


def test_test_direct_import_uses_tests_root(
    valid_environment: dict[str, set[str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "tests/example.py"
    source.parent.mkdir(parents=True)
    source.write_text("from openhands.sdk.testing import Foo\n", encoding="utf-8")
    monkeypatch.setattr(verifier, "REPO_ROOT", tmp_path)

    errors = verifier.validate_catalog(
        _catalog(
            references=[
                {
                    "kind": "direct_import",
                    "path": "tests/example.py",
                    "symbol": "Foo",
                    "note": "test",
                }
            ]
        ),
        valid_environment,
    )

    assert any("outside allowed roots" in error for error in errors)


def test_test_direct_import_rejects_production_root(
    valid_environment: dict[str, set[str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "src/acd/example.py"
    source.parent.mkdir(parents=True)
    source.write_text("from openhands.sdk.testing import Foo\n", encoding="utf-8")
    monkeypatch.setattr(verifier, "REPO_ROOT", tmp_path)

    errors = verifier.validate_catalog(
        _catalog(
            references=[
                {
                    "kind": "test_direct_import",
                    "path": "src/acd/example.py",
                    "symbol": "Foo",
                    "note": "test",
                }
            ]
        ),
        valid_environment,
    )

    assert any("outside allowed roots" in error for error in errors)


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


def test_write_returns_nonzero_for_non_drift_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _catalog()
    markdown = tmp_path / "capabilities.md"
    markdown.write_text(
        "<!-- generated by scripts/verify_sdk_capabilities.py; do not edit -->\n"
        "old\n"
        "<!-- end generated -->\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(verifier, "MARKDOWN_PATH", markdown)
    monkeypatch.setattr(verifier, "load_catalog", lambda: catalog)

    def fake_extract(
        _scanned_packages: list[verifier.ScannedPackage],
    ) -> dict[str, set[str]]:
        return {"sdk.foo": {"Foo"}}

    def fake_validate(
        _catalog: verifier.CapabilityCatalog,
        _modules: dict[str, set[str]],
    ) -> list[str]:
        return [
            "generated Markdown block differs from JSON",
            "representative API is absent",
        ]

    monkeypatch.setattr(
        verifier,
        "extract_public_modules",
        fake_extract,
    )
    monkeypatch.setattr(verifier, "validate_catalog", fake_validate)

    assert verifier.main(["--write"]) == 1


def test_catalog_json_is_valid() -> None:
    catalog = json.loads(verifier.CATALOG_PATH.read_text(encoding="utf-8"))

    assert verifier.CapabilityCatalog.model_validate(catalog).sdk_version == "1.44.1"


def test_current_catalog_has_valid_references() -> None:
    catalog = verifier.load_catalog()
    modules = verifier.extract_public_modules(catalog.scanned_packages)

    assert verifier.validate_catalog(catalog, modules) == []
