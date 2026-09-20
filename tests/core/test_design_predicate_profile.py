"""Design predicate profile: tracked expectations, hash provenance, fail-closed load."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acd.core.knowledge import design_predicates
from acd.core.knowledge.design_predicate_profile import (
    DEFAULT_DESIGN_PREDICATE_PROFILE_RELPATH,
    DesignPredicateProfileError,
    default_design_predicate_profile,
    load_design_predicate_profile,
)
from acd.core.runtime.fileio import read_json
from acd.pipeline.repository import repository_root


def _default_document() -> dict[str, object]:
    return read_json(repository_root() / DEFAULT_DESIGN_PREDICATE_PROFILE_RELPATH)


def test_module_constants_mirror_tracked_profile() -> None:
    profile = default_design_predicate_profile().document
    assert profile.usb_cc_expected_kohm == design_predicates.CC_EXPECTED_KOHM
    assert profile.i2c_pullup_expected_kohm == design_predicates.I2C_EXPECTED_KOHM
    assert frozenset(profile.strapping_gpios) == design_predicates.STRAPPING_GPIOS
    assert profile.ldo_input_v == design_predicates.LDO_INPUT_V
    assert profile.ldo_output_v == design_predicates.LDO_OUTPUT_V
    assert profile.small_cap_distance_mm == design_predicates.SMALL_CAP_DISTANCE_MM
    assert profile.large_cap_distance_mm == design_predicates.LARGE_CAP_DISTANCE_MM
    assert set(design_predicates.IMPEDANCE_FORMULA_CONSTANTS) == {"microstrip", "stripline"}
    assert "pi_factor" not in design_predicates.IMPEDANCE_FORMULA_CONSTANTS["microstrip"]


def test_profile_hash_is_canonical_and_order_independent(tmp_path: Path) -> None:
    document = _default_document()
    reordered = dict(reversed(list(document.items())))
    reordered["strapping_gpios"] = list(reversed(list(document["strapping_gpios"])))  # type: ignore[arg-type]
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(reordered, indent=4), encoding="utf-8")
    loaded = load_design_predicate_profile(path)
    assert loaded.profile_hash == default_design_predicate_profile().profile_hash
    assert loaded.provenance() == default_design_predicate_profile().provenance()
    assert loaded.provenance()["profile_hash"].startswith("sha256:")


def test_changed_expectation_changes_hash(tmp_path: Path) -> None:
    document = _default_document()
    document["usb_cc_expected_kohm"] = "1k"
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert load_design_predicate_profile(path).profile_hash != (
        default_design_predicate_profile().profile_hash
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"ldo_output_v": -3.3},
        {"strapping_gpios": [2, 2]},
        {"schema_version": "9.9"},
        {"unexpected": 1},
        {"impedance_formula_constants": {"microstrip": {"z0_factor": 87.0}}},
    ],
)
def test_invalid_profile_fails_closed(tmp_path: Path, mutation: dict[str, object]) -> None:
    document = {**_default_document(), **mutation}
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(DesignPredicateProfileError):
        load_design_predicate_profile(path)


def test_missing_profile_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(DesignPredicateProfileError):
        load_design_predicate_profile(tmp_path / "absent.json")
