"""Contract tests for the responsibility declaration schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from acd.schema.responsibility import (
    CrossDomainInterface,
    FunctionDependency,
    ResponsibilityDeclaration,
    SharedAssignmentContract,
)


def test_function_dependency_rejects_self() -> None:
    with pytest.raises(ValidationError):
        FunctionDependency(function_id="fn-a", depends_on="fn-a")


def test_interface_rejects_duplicate_domains() -> None:
    with pytest.raises(ValidationError):
        CrossDomainInterface(
            interface_id="if-x",
            domains=("firmware", "firmware"),
            signal="s",
            protocol="p",
            power="pw",
            declared_by=["firmware"],
        )


def test_interface_rejects_unsorted_domains() -> None:
    with pytest.raises(ValidationError):
        CrossDomainInterface(
            interface_id="if-x",
            domains=("pc_software", "firmware"),
            signal="s",
            protocol="p",
            power="pw",
            declared_by=["firmware", "pc_software"],
        )


def test_shared_assignment_requires_two_distinct_domains() -> None:
    with pytest.raises(ValidationError):
        SharedAssignmentContract(
            function_id="fn-a", domains=["firmware"], split="none"
        )
    with pytest.raises(ValidationError):
        SharedAssignmentContract(
            function_id="fn-a",
            domains=["firmware", "firmware"],
            split="none",
        )


def test_declaration_rejects_duplicate_capability_domains() -> None:
    with pytest.raises(ValidationError):
        ResponsibilityDeclaration.model_validate(
            {
                "graph_id": "g",
                "revision": "r1",
                "capabilities": [
                    {"domain": "firmware"},
                    {"domain": "firmware"},
                ],
            }
        )


def test_declaration_rejects_duplicate_interface_ids() -> None:
    interface = {
        "interface_id": "if-x",
        "domains": ["firmware", "pc_software"],
        "signal": "s",
        "protocol": "p",
        "power": "pw",
        "declared_by": ["firmware", "pc_software"],
    }
    with pytest.raises(ValidationError):
        ResponsibilityDeclaration.model_validate(
            {
                "graph_id": "g",
                "revision": "r1",
                "interfaces": [interface, interface],
            }
        )


def test_declaration_rejects_duplicate_function_needs() -> None:
    with pytest.raises(ValidationError):
        ResponsibilityDeclaration.model_validate(
            {
                "graph_id": "g",
                "revision": "r1",
                "functions": [
                    {"function_id": "fn-a"},
                    {"function_id": "fn-a"},
                ],
            }
        )


def test_declaration_rejects_duplicate_shared_assignments() -> None:
    shared = {
        "function_id": "fn-a",
        "domains": ["firmware", "pc_software"],
        "split": "half",
    }
    with pytest.raises(ValidationError):
        ResponsibilityDeclaration.model_validate(
            {
                "graph_id": "g",
                "revision": "r1",
                "shared_assignments": [shared, shared],
            }
        )


def test_function_need_rejects_negative_gpio() -> None:
    from acd.schema.responsibility import FunctionNeed

    with pytest.raises(ValidationError):
        FunctionNeed(function_id="fn-a", gpio_count=-1)
