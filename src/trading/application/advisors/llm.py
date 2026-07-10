"""Advisor LLM protocol + the OpenAI-compatible (litellm) implementation.

Advisors depend on the `LLMClient` protocol, never a concrete provider — any
class with `complete(system, user) -> str` plugs in. The default transport is
the litellm gateway (OpenAI-compatible chat/completions), same path the daily
briefing uses; the `advisor-frontier` alias routes to a frontier upstream.

We deliberately do NOT use provider structured-output machinery: we ask for
JSON in the prompt and parse it ourselves (extract_json), which keeps the
provider swappable. Ported from ai-hedge-fund v2 llm/client.py (MIT).
"""

from __future__ import annotations

import json
import re
from typing import Protocol, runtime_checkable

import httpx

DEFAULT_LITELLM_BASE_URL = "http://127.0.0.1:30400"


class AdvisorLLMError(RuntimeError):
    """LLM transport failure — the agent layer decides to abstain, not us."""


class LLMParseError(ValueError):
    """The model's response did not contain parseable JSON."""


@runtime_checkable
class LLMClient(Protocol):
    """Protocol all advisor LLM providers must satisfy.

    complete() returns the model's raw text. Providers raise on transport
    failure — the AdvisorAgent layer decides to abstain, not the provider.
    """

    model: str

    async def complete(self, system: str, user: str) -> str: ...


class OpenAICompatLLM:
    """OpenAI-compatible chat/completions transport (litellm gateway)."""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = DEFAULT_LITELLM_BASE_URL,
        timeout: float = 120.0,
        max_tokens: int = 1024,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_tokens = max_tokens

    async def complete(self, system: str, user: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "content-type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "max_tokens": self._max_tokens,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise AdvisorLLMError(f"advisor LLM call failed: {exc}") from exc

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AdvisorLLMError(f"unexpected LLM response shape: {exc}") from exc
        if not isinstance(content, str):
            raise AdvisorLLMError(f"LLM content is not text: {type(content).__name__}")
        return content


def extract_json(text: str) -> dict[str, object]:
    """Pull the first JSON object out of an LLM response.

    Tries: ```json fence -> whole string -> first balanced {...} block.
    Raises LLMParseError if nothing parses.
    """
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            parsed = json.loads(fence.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    try:
        parsed = json.loads(text.strip())
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start : i + 1])
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        break

    raise LLMParseError(f"no JSON object found in response: {text[:200]!r}")
