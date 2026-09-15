from __future__ import annotations

import pytest

from acd.schema.visual_quality import ReadabilityPolicy, ReadabilityReport


def test_policy_hash_is_stable() -> None:
    policy = ReadabilityPolicy()
    assert policy.policy_hash() == ReadabilityPolicy().policy_hash()


def test_report_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        ReadabilityReport.model_validate(
            {
                "status": "pass",
                "findings": [],
                "text_count": 0,
                "policy_hash": "sha256:" + "a" * 64,
                "unexpected": True,
            }
        )
