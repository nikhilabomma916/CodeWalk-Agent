"""Live smoke test against the real Anthropic API.

Runs only when a credential is present in the server environment
(ANTHROPIC_API_KEY or CODEWALK_AI_API_KEY); it is skipped otherwise, so the
normal suite never depends on (or pays for) a provider. The key is never printed.
"""

from __future__ import annotations

import os

import pytest

from app.services.ai.base import StructuredRequest
from app.services.ai.outputs import ModelExplanation, output_schema
from app.services.ai.providers import create_provider
from tests.conftest import make_settings

CREDENTIAL = os.environ.get("CODEWALK_AI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")

pytestmark = pytest.mark.skipif(
    not CREDENTIAL, reason="Live AI provider test not executed: no credential is configured"
)


def test_live_structured_explanation() -> None:
    provider = create_provider(make_settings(ai_enabled=True, ai_api_key=CREDENTIAL))
    assert provider.status().configured
    result = provider.generate_structured(
        StructuredRequest(
            system="You explain Python errors briefly. Answer with the requested JSON structure only.",
            user=(
                "Diagnostic: Undefined name `total` at line 2.\n"
                "1 | def f(items):\n2 |     total += 1\n3 |     return total"
            ),
            schema=output_schema(ModelExplanation),
            max_tokens=4000,
            timeout_seconds=120,
            effort="low",
        )
    )
    explanation = ModelExplanation.model_validate(result.data)  # the real answer parses
    assert explanation.explanation.strip()
    assert explanation.confidence in {"low", "medium", "high"}
    assert result.usage["output_tokens"] > 0
