"""Deterministic security analysis for the ACD agent boundary."""

from __future__ import annotations

import re
from collections.abc import Mapping

from openhands.sdk.event import ActionEvent
from openhands.sdk.security import (
    EnsembleSecurityAnalyzer,
    PatternSecurityAnalyzer,
    SecurityAnalyzerBase,
    SecurityRisk,
)
from pydantic import TypeAdapter, ValidationError

_ORDER_TERMS = re.compile(r"\b(?:order|purchase|procure|procurement|checkout)\b")
_DESTRUCTIVE_GIT = re.compile(
    r"\b(?:git\s+push\b[^\n]*--force(?:-with-lease)?|"
    r"git\s+[^\n]*--no-verify\b|git\s+reset\s+--hard\b)"
)
_WRITE_OPERATOR = re.compile(r"(?:>|>>|\b(?:tee|cp|mv|install)\b)")
_PROTECTED_PATH = re.compile(
    r"(?:^|[\s\"'])((?:evidence|projection(?:s)?)(?:/|[.]))"
)


_ARGUMENTS = TypeAdapter(dict[str, object])


def _action_arguments(action: ActionEvent) -> Mapping[str, object]:
    if action.action is not None:
        return _ARGUMENTS.validate_json(action.action.model_dump_json())
    else:
        return _ARGUMENTS.validate_json(action.tool_call.arguments)


def _flatten_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        typed_mapping = TypeAdapter(dict[str, object]).validate_python(value)
        values: list[str] = []
        for nested in typed_mapping.values():
            values.extend(_flatten_values(nested))
        return values
    if isinstance(value, (list, tuple)):
        typed_values = TypeAdapter(list[object]).validate_python(value)
        values = []
        for nested in typed_values:
            values.extend(_flatten_values(nested))
        return values
    return []


class AcdSecurityAnalyzer(SecurityAnalyzerBase):
    """Classify ACD-protected actions without LLM or network calls."""

    def security_risk(self, action: ActionEvent) -> SecurityRisk:
        try:
            arguments = _action_arguments(action)
            text = " ".join(
                [action.tool_name, *(_flatten_values(arguments))]
            )
        except (TypeError, ValueError, ValidationError):
            return SecurityRisk.HIGH

        if _ORDER_TERMS.search(text) or _DESTRUCTIVE_GIT.search(text):
            return SecurityRisk.HIGH

        if _PROTECTED_PATH.search(text) and (
            _WRITE_OPERATOR.search(text)
            or action.tool_name.lower() in {"write_file", "edit_file", "file_editor"}
        ):
            return SecurityRisk.HIGH

        return SecurityRisk.LOW


def build_acd_security_analyzer() -> EnsembleSecurityAnalyzer:
    """Build the SDK ensemble used by ACD conversations."""
    return EnsembleSecurityAnalyzer(
        analyzers=[AcdSecurityAnalyzer(), PatternSecurityAnalyzer()],
    )
