"""
Unit tests for src.core.pipeline.resolve_override(): offline, network-free
validation of a profile's model override against the active LLM backend's
provider_id. Pure function — no catalog lookup, no I/O (see
src.llm.model_catalog.provider_of_model_id for the prefix map it relies on).
"""

import pytest

from src.core.pipeline import resolve_override


class TestResolveOverride:
    @pytest.mark.parametrize(
        "override,active_provider_id,expected_override,expect_notice",
        [
            # Matching provider — kept, no notice.
            ("gpt-5.6-terra", "gpt", "gpt-5.6-terra", False),
            ("claude-haiku-4-5-20251001", "claude", "claude-haiku-4-5-20251001", False),
            # Foreign provider — dropped, notice emitted.
            ("gpt-5.6-terra", "claude", "", True),
            ("claude-haiku-4-5-20251001", "gpt", "", True),
            # Unknown prefix — kept unchanged (can't confirm mismatch offline).
            ("llama-3-70b", "gpt", "llama-3-70b", False),
            # Empty override — nothing to validate.
            ("", "gpt", "", False),
            # No active provider info (getattr-guarded None) — forward unchanged.
            ("gpt-5.6-terra", None, "gpt-5.6-terra", False),
            ("", None, "", False),
        ],
    )
    def test_resolution_matrix(self, override, active_provider_id, expected_override, expect_notice):
        resolved, notice = resolve_override(override, active_provider_id)
        assert resolved == expected_override
        if expect_notice:
            assert notice is not None
        else:
            assert notice is None
