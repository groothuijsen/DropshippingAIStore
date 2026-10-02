"""Regression: AI repair messages must replay the original tool_use content.

A synthesized tool_use block without an `id` is rejected by Anthropic with
HTTP 400 (live lesson on the T-161 PDP re-run).
"""

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from apps.ai.anthropic_client import AnthropicClient


class _Payload(BaseModel):
    seo_description: str = Field(max_length=155)


def _client() -> AnthropicClient:
    return AnthropicClient(shop_domain="x.myshopify.com", access_token="tok")


def test_repair_messages_replay_original_content():
    original = [{"role": "user", "content": "go"}]
    assistant_content: list[dict[str, Any]] = [
        {"type": "text", "text": "here"},
        {"type": "tool_use", "id": "toolu_abc123", "name": "sections_payload", "input": {"seo_description": "x" * 200}},
    ]
    try:
        _Payload.model_validate({"seo_description": "x" * 200})
    except ValidationError as exc:
        messages = AnthropicClient._build_repair_messages(
            original, assistant_content, {"seo_description": "x" * 200}, exc, "sections_payload"
        )
    assert messages[-2]["role"] == "assistant"
    assert messages[-2]["content"] is assistant_content
    assert messages[-2]["content"][1]["id"] == "toolu_abc123"
    assert messages[-1]["role"] == "user"
    assert "validation errors" in messages[-1]["content"].lower()
