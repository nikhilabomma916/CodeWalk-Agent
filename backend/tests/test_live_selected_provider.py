"""Optional live smoke test of the configured AI provider (any of the five).

Runs only with CODEWALK_AI_LIVE_TEST=1 and a configured provider, because it makes one real, billed
request. The request goes only to the selected provider with its own credential; nothing else is
called. Skipped (with the reason) otherwise; a skip is not a pass.

    CODEWALK_AI_LIVE_TEST=1 uv run pytest tests/test_live_selected_provider.py -ra
"""

from __future__ import annotations

import os

import pytest

from app.core.config import Settings
from app.services.ai.base import StructuredRequest
from app.services.ai.providers import create_provider


def test_selected_provider_answers_a_structured_request() -> None:
    if os.environ.get("CODEWALK_AI_LIVE_TEST") != "1":
        pytest.skip("Live provider test not executed: set CODEWALK_AI_LIVE_TEST=1 to make one billed request")
    settings = Settings()
    provider = create_provider(settings)
    status = provider.status()
    if not status.configured:
        pytest.skip(f"Live provider test not executed: {settings.ai_provider_name} is not configured")
    result = provider.generate_structured(
        StructuredRequest(
            system="Reply with JSON only.",
            user='Return {"answer": "pong"}.',
            schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
            max_tokens=256,
            timeout_seconds=min(settings.ai_timeout_seconds, 60),
            effort="low",
        )
    )
    assert isinstance(result.data.get("answer"), str)
    assert result.model
