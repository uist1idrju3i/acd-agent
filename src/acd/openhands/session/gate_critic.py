"""Deterministic ACD gate critic for OpenHands iterative refinement."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, cast

from openhands.sdk.critic import CriticBase, CriticResult, IterativeRefinementConfig
from openhands.sdk.event import LLMConvertibleEvent
from pydantic import BaseModel, Field

from acd.openhands.session.context import is_context_artifact
from acd.schema import Evidence
from acd.schema.design_graph import DesignGraph


class AcdEvidenceRequirement(BaseModel):
    """Require a specific Evidence record to support a current-revision pass."""

    kind: Literal["evidence"] = "evidence"
    path: Path = Field(description="Path to an Evidence JSON file.")
    evidence_id: str = Field(description="Required evidence_id.")


class AcdManifestRequirement(BaseModel):
    """Require a manufacturing manifest to be order-ready and fully known."""

    kind: Literal["manifest"] = "manifest"
    path: Path = Field(description="Path to a manufacturing manifest JSON file.")
    manifest_kind: Literal["fab_package", "order_readiness"] = Field(
        default="fab_package",
        description="Manifest shape to validate.",
    )


GateRequirement = AcdEvidenceRequirement | AcdManifestRequirement


class AcdGateCritic(CriticBase):
    """Score only deterministic artifacts, never agent events or patches.

    Scores are deliberately binary: 1.0 means every configured requirement
    passes, while 0.0 means at least one requirement is missing, stale,
    malformed, unknown, or otherwise not proven. Intermediate scores would
    suggest partial pass evidence and conflict with the SDK's 0.5 threshold.
    Critic output steers refinement and is not pass evidence.
    """

    requirements: list[GateRequirement] = Field(
        min_length=1,
        description="Deterministic Evidence and manufacturing artifact requirements.",
    )
    repo_root: Path = Field(
        default=Path("."),
        description="Repository root from which paths and git HEAD are resolved.",
    )
    design_graph_path: Path = Field(
        default=Path("fixtures/golden-design-1/graph.json"),
        description="Design Graph path defining the current ACD revision.",
    )
    iterative_refinement: IterativeRefinementConfig | None = Field(
        default_factory=lambda: IterativeRefinementConfig(
            success_threshold=1.0,
            max_iterations=3,
        ),
        description="Bounded refinement driven by binary deterministic gate results.",
    )

    def evaluate(
        self,
        events: Sequence[LLMConvertibleEvent],
        git_patch: str | None = None,
    ) -> CriticResult:
        """Evaluate configured artifacts at the current git revision."""
        del events, git_patch
        revision, revision_failure = self._current_revision()
        if revision is None:
            failures = [f"revision: {revision_failure}"]
            return self._result(failures, [])

        failures: list[str] = []
        details: list[dict[str, Any]] = []
        for requirement in self.requirements:
            if isinstance(requirement, AcdEvidenceRequirement):
                passed, detail = self._check_evidence(requirement, revision)
            else:
                passed, detail = self._check_manifest(requirement)
            details.append(detail)
            if not passed:
                failures.append(str(detail["failure"]))
        return self._result(failures, details)

    def get_followup_prompt(self, critic_result: CriticResult, iteration: int) -> str:
        """Return deterministic repair guidance without probability language."""
        failures = []
        if critic_result.metadata:
            failures = [
                str(item["failure"])
                for item in critic_result.metadata.get("requirements", [])
                if item.get("passed") is False
            ]
        listed = "\n".join(f"- {failure}" for failure in failures) or (
            "- unknown requirement failure"
        )
        return (
            f"Deterministic ACD gate requirements remain unmet (iteration {iteration}).\n"
            f"{listed}\n"
            "Do not rewrite gates, thresholds, or Evidence files merely to pass.\n"
            "Critic output is not pass evidence.\n"
        )

    def _current_revision(self) -> tuple[str | None, str]:
        try:
            status = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                check=False,
            )
            if status.returncode != 0:
                return None, "git status unavailable"
            if any(
                self._is_design_input(line[3:])
                for line in status.stdout.splitlines()
                if len(line) > 3
            ):
                return None, "design input is dirty"
            graph = DesignGraph.model_validate_json(
                (self.repo_root / self.design_graph_path).read_text(encoding="utf-8")
            )
        except (OSError, ValueError, TypeError):
            return None, "Design Graph is unreadable or invalid"
        return graph.revision, ""

    @staticmethod
    def _is_design_input(path: str) -> bool:
        return (
            (path.startswith("fixtures/") and path.endswith("/graph.json"))
            or path.startswith("profiles/")
        )

    def _check_evidence(
        self, requirement: AcdEvidenceRequirement, revision: str
    ) -> tuple[bool, dict[str, Any]]:
        path = self.repo_root / requirement.path
        detail: dict[str, Any] = {
            "kind": requirement.kind,
            "path": str(requirement.path),
            "evidence_id": requirement.evidence_id,
            "passed": False,
        }
        if not path.is_file():
            detail["failure"] = f"evidence missing: {requirement.path}"
            return False, detail
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if is_context_artifact(payload):
                detail["failure"] = (
                    f"context material is not pass evidence: {requirement.path}"
                )
                return False, detail
            evidence = Evidence.model_validate_json(raw)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            detail["failure"] = f"evidence invalid: {requirement.path}: {exc}"
            return False, detail
        if evidence.evidence_id != requirement.evidence_id:
            detail["failure"] = (
                f"evidence_id mismatch: {requirement.path}: "
                f"expected {requirement.evidence_id}, got {evidence.evidence_id}"
            )
            return False, detail
        if not evidence.supports_authoritative_pass(revision):
            reasons: list[str] = []
            if evidence.status != "valid":
                reasons.append(f"status={evidence.status}")
            if evidence.target_revision != revision:
                reasons.append(f"target_revision={evidence.target_revision}")
            if evidence.envelope.target_revision != revision:
                reasons.append(
                    f"envelope_target_revision={evidence.envelope.target_revision}"
                )
            if evidence.envelope.has_unknown():
                reasons.append("unknown envelope field")
            suffix = f" ({', '.join(reasons)})" if reasons else ""
            detail["failure"] = (
                f"evidence does not support pass: {requirement.path}{suffix}"
            )
            return False, detail
        detail["passed"] = True
        return True, detail

    def _check_manifest(
        self, requirement: AcdManifestRequirement
    ) -> tuple[bool, dict[str, Any]]:
        path = self.repo_root / requirement.path
        detail: dict[str, Any] = {
            "kind": requirement.kind,
            "path": str(requirement.path),
            "passed": False,
        }
        if not path.is_file():
            detail["failure"] = f"manifest missing: {requirement.path}"
            return False, detail
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            detail["failure"] = f"manifest invalid: {requirement.path}: {exc}"
            return False, detail
        if not isinstance(value, dict):
            detail["failure"] = f"manifest schema mismatch: {requirement.path}"
            return False, detail
        manifest = cast(dict[str, Any], value)
        status: Any = manifest.get("status")
        gates: Any = manifest.get("gates")
        unknowns: Any = manifest.get("unknowns")
        if not isinstance(status, str) or not isinstance(unknowns, dict):
            detail["failure"] = f"manifest schema mismatch: {requirement.path}"
            return False, detail
        if status != "ready":
            detail["failure"] = f"manifest status is not ready: {requirement.path}: {status}"
            return False, detail
        if requirement.manifest_kind == "fab_package":
            if not isinstance(gates, dict):
                detail["failure"] = f"manifest schema mismatch: {requirement.path}"
                return False, detail
            gate_values: dict[str, Any] = cast(dict[str, Any], gates)
            if any(result != "pass" for result in gate_values.values()):
                detail["failure"] = f"manifest gates are not all pass: {requirement.path}"
                return False, detail
        if unknowns:
            detail["failure"] = f"manifest has unknowns: {requirement.path}"
            return False, detail
        detail["passed"] = True
        return True, detail

    def _result(
        self, failures: list[str], details: list[dict[str, Any]]
    ) -> CriticResult:
        score = 0.0 if failures else 1.0
        message = (
            "All deterministic ACD gate requirements passed."
            if not failures
            else "Unmet requirements: " + "; ".join(failures)
        )
        return CriticResult(
            score=score,
            message=message,
            metadata={
                "pass_evidence": False,
                "requirements": details,
            },
        )
