"""Anthropic AI client — tool use, schema validation, repair attempt, cost logging.

See docs/05-ai-pipeline.md §2, docs/00-decisions.md §AI providers.

Rules:
1. Prompt from docs/prompts/<step>.md, rendered with Django templating.
2. Tool use with a single tool `submit_<step>` whose input_schema = Model.model_json_schema().
3. tool_choice forced to that tool.
4. Validate with Model.model_validate(). One repair attempt on failure.
5. Provider errors (429/500/502/503/529, timeout): retry after 10s and 30s.
6. Cost tracked after every call. Budget check per job.
"""

from __future__ import annotations

import logging
import os
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from apps.core.models import Shop
    from apps.generator.models import JobStep

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"

# Model defaults from 00-decisions
MODELS = {
    "research": os.environ.get("LLM_MODEL_RESEARCH", "claude-sonnet-5-5"),
    "copy": os.environ.get("LLM_MODEL_COPY", "claude-sonnet-5-5"),
    "check": os.environ.get("LLM_MODEL_CHECK", "claude-haiku-4-5-20251001"),
    "url_facts": os.environ.get("LLM_MODEL_CHECK", "claude-haiku-4-5-20251001"),
    "palette": os.environ.get("LLM_MODEL_COPY", "claude-sonnet-5-5"),
    "rewrite": os.environ.get("LLM_MODEL_COPY", "claude-sonnet-5-5"),
}

# Pricing per million tokens (USD) — Anthropic API pricing
PRICING: dict[str, dict[str, Decimal]] = {
    "claude-sonnet-5-5": {"input": Decimal("3.00"), "output": Decimal("15.00")},
    "claude-haiku-4-5-20251001": {"input": Decimal("1.00"), "output": Decimal("5.00")},
    "claude-sonnet-4-5-20250929": {"input": Decimal("3.00"), "output": Decimal("15.00")},
    "claude-opus-5": {"input": Decimal("15.00"), "output": Decimal("75.00")},
}

DEFAULT_PRICING = {"input": Decimal("3.00"), "output": Decimal("15.00")}

# Retry schedule for provider errors (seconds)
RETRY_SCHEDULE = [10, 30]


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """Calculate the cost of an API call in USD."""
    pricing = PRICING.get(model, DEFAULT_PRICING)
    cost = (
        Decimal(input_tokens) / Decimal("1000000") * pricing["input"]
        + Decimal(output_tokens) / Decimal("1000000") * pricing["output"]
    )
    return cost.quantize(Decimal("0.0001"))


class AnthropicToolCallError(Exception):
    """Raised when the AI response cannot be parsed or validated."""

    def __init__(self, message: str, errors: list[dict[str, Any]] | None = None):
        self.errors = errors or []
        super().__init__(message)


class AnthropicClient:
    """Client for Anthropic Messages API with tool use and schema validation."""

    def __init__(self, api_key: str | None = None, timeout: float = 120.0):
        # systemd units do not load .env into the process environment, so fall
        # back to Django settings (base.py reads .env via environ.read_env).
        from django.conf import settings

        self.api_key = (
            api_key
            or os.environ.get("ANTHROPIC_API_KEY", "")
            or getattr(settings, "ANTHROPIC_API_KEY", "")
        )
        self.timeout = timeout
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout=timeout, connect=5.0),
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": ANTHROPIC_API_VERSION,
                "content-type": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AnthropicClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def call(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[BaseModel],
        tool_name: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> tuple[BaseModel, dict[str, Any]]:
        """Make an Anthropic API call with tool use and schema validation.

        Returns (validated_model, usage_dict).
        Raises AnthropicToolCallError if validation fails after repair attempt.
        """

        # Build the tool definition from the Pydantic schema
        tool_def = {
            "name": tool_name,
            "description": f"Submit the {tool_name} result",
            "input_schema": schema.model_json_schema(),
        }

        messages = [{"role": "user", "content": user}]

        # First attempt
        response_data = self._make_request(
            model=model,
            system=system,
            messages=messages,
            tools=[tool_def],
            tool_choice={"type": "tool", "name": tool_name},
            temperature=temperature,
            max_tokens=max_tokens,
        )

        usage = self._extract_usage(response_data)
        tool_input = self._extract_tool_input(response_data, tool_name)

        try:
            validated = schema.model_validate(tool_input)
            return validated, usage
        except ValidationError as e:
            # One repair attempt (05 §2.4)
            repair_messages = self._build_repair_messages(messages, tool_input, e, tool_name)
            logger.warning("Schema validation failed for %s, attempting repair: %s", tool_name, e)

            response_data = self._make_request(
                model=model,
                system=system,
                messages=repair_messages,
                tools=[tool_def],
                tool_choice={"type": "tool", "name": tool_name},
                temperature=temperature,
                max_tokens=max_tokens,
            )

            usage = self._extract_usage(response_data)
            tool_input = self._extract_tool_input(response_data, tool_name)

            try:
                validated = schema.model_validate(tool_input)
                return validated, usage
            except ValidationError as e2:
                errors = [{"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]} for err in e2.errors()]
                raise AnthropicToolCallError(
                    f"Schema validation failed after repair attempt for {tool_name}",
                    errors=errors,
                ) from e2

    def _make_request(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any],
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        """Make the HTTP request with retry logic for provider errors."""
        payload = {
            "model": model,
            "system": system,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        last_exception: Exception | None = None
        for attempt in range(len(RETRY_SCHEDULE) + 1):
            if attempt > 0:
                time.sleep(RETRY_SCHEDULE[attempt - 1])

            try:
                response = self._client.post(ANTHROPIC_API_URL, json=payload)
            except httpx.TimeoutException:
                last_exception = TimeoutError(f"Request timed out after {self.timeout}s")
                continue
            except httpx.HTTPError as e:
                last_exception = e
                continue

            if response.status_code == 200:
                data = response.json()
                # Check for top-level errors
                if "error" in data:
                    raise AnthropicToolCallError(f"API error: {data['error']}")
                return data

            if response.status_code in (429, 500, 502, 503, 529):
                # Retryable provider errors
                last_exception = RuntimeError(f"Provider error {response.status_code}: {response.text[:200]}")
                continue

            # Newer models reject some request params outright (400):
            # forced tool_choice ("type tool and any are not supported"),
            # deprecated temperature. Drop the offending param and retry —
            # the tool stays in `tools`, and call() still validates the
            # tool_use output against the schema (no validation bypass).
            if response.status_code == 400:
                dropped = False
                if "tool_choice" in response.text and "tool_choice" in payload:
                    payload.pop("tool_choice")
                    dropped = True
                if "temperature" in response.text and "temperature" in payload:
                    payload.pop("temperature")
                    dropped = True
                if dropped:
                    continue

            # Non-retryable error
            raise AnthropicToolCallError(f"API error {response.status_code}: {response.text[:500]}")

        raise AnthropicToolCallError(f"All retries exhausted: {last_exception}")

    @staticmethod
    def _extract_usage(response_data: dict[str, Any]) -> dict[str, Any]:
        """Extract token usage from the API response."""
        usage = response_data.get("usage", {})
        return {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        }

    @staticmethod
    def _extract_tool_input(response_data: dict[str, Any], tool_name: str) -> dict[str, Any]:
        """Extract the tool input from the API response."""
        for block in response_data.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == tool_name:
                return block.get("input", {})
        raise AnthropicToolCallError(f"No tool_use block found for {tool_name}")

    @staticmethod
    def _build_repair_messages(
        original_messages: list[dict[str, Any]],
        bad_input: dict[str, Any],
        validation_error: ValidationError,
        tool_name: str,
    ) -> list[dict[str, Any]]:
        """Build repair messages with the original output + validation errors."""
        import json

        error_details = json.dumps(
            [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in validation_error.errors()],
            indent=2,
        )
        bad_json = json.dumps(bad_input, indent=2)

        repair_content = (
            f"Your previous output for `{tool_name}` had validation errors. "
            f"Correct ONLY these fields and submit again:\n\n"
            f"Validation errors:\n{error_details}\n\n"
            f"Your previous output:\n{bad_json}"
        )

        # Append the assistant's response and the repair request
        return original_messages + [
            {"role": "assistant", "content": [{"type": "tool_use", "name": tool_name, "input": bad_input}]},
            {"role": "user", "content": repair_content},
        ]


def log_ai_call(
    *,
    shop: Shop,
    step: JobStep | None,
    purpose: str,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: Decimal,
    duration_ms: int,
    success: bool = True,
) -> None:
    """Log an AI call to the database for cost tracking and audit."""
    from apps.generator.models import AiCall

    AiCall.objects.create(
        shop=shop,
        step=step,
        purpose=purpose,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        images=0,
        cost_usd=cost_usd,
        duration_ms=duration_ms,
        success=success,
    )


def call_ai(
    *,
    shop: Shop,
    purpose: str,
    model_key: str,
    system: str,
    user: str,
    schema: type[BaseModel],
    tool_name: str,
    temperature: float = 0.0,
    step: JobStep | None = None,
    max_tokens: int = 4096,
) -> BaseModel:
    """High-level AI call: executes, logs cost, validates schema.

    Returns the validated Pydantic model.
    Raises AnthropicToolCallError on schema failure.
    Raises RuntimeError on provider errors after all retries.
    """
    model = MODELS.get(model_key, model_key)
    client = AnthropicClient()

    start = time.monotonic()
    try:
        validated, usage = client.call(
            model=model,
            system=system,
            user=user,
            schema=schema,
            tool_name=tool_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        cost = calculate_cost(model, usage["input_tokens"], usage["output_tokens"])

        log_ai_call(
            shop=shop,
            step=step,
            purpose=purpose,
            provider="anthropic",
            model=model,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            cost_usd=cost,
            duration_ms=duration_ms,
            success=True,
        )

        # Accumulate cost to job step and job
        if step:
            step.ai_cost_usd += cost
            step.save(update_fields=["ai_cost_usd"])

            job = step.job
            job.ai_cost_usd += cost
            job.save(update_fields=["ai_cost_usd"])

        return validated

    except AnthropicToolCallError:
        duration_ms = int((time.monotonic() - start) * 1000)
        log_ai_call(
            shop=shop,
            step=step,
            purpose=purpose,
            provider="anthropic",
            model=model,
            input_tokens=0,
            output_tokens=0,
            cost_usd=Decimal("0"),
            duration_ms=duration_ms,
            success=False,
        )
        raise
    finally:
        client.close()
