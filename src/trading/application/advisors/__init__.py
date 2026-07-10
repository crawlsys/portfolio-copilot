"""Advisor council — persona LLM analysts over point-in-time fundamentals.

Adopted from virattt/ai-hedge-fund v2 (MIT): FundamentalsSnapshot →
persona agent → stance/confidence/reasoning, cached by snapshot hash with
the exact prompt + response persisted for replay and audit.
"""

from __future__ import annotations

from trading.application.advisors.agent import AdvisorAgent, AdvisorView
from trading.application.advisors.buffett import BuffettAdvisor
from trading.application.advisors.llm import (
    AdvisorLLMError,
    LLMClient,
    OpenAICompatLLM,
    extract_json,
)
from trading.application.advisors.snapshot import (
    MIN_PERIODS,
    FundamentalsPort,
    FundamentalsSnapshot,
    InsufficientDataError,
    PeriodFundamentals,
    build_snapshot,
)

ADVISOR_REGISTRY: dict[str, type[AdvisorAgent]] = {
    "buffett": BuffettAdvisor,
}

__all__ = [
    "ADVISOR_REGISTRY",
    "MIN_PERIODS",
    "AdvisorAgent",
    "AdvisorLLMError",
    "AdvisorView",
    "BuffettAdvisor",
    "FundamentalsPort",
    "FundamentalsSnapshot",
    "InsufficientDataError",
    "LLMClient",
    "OpenAICompatLLM",
    "PeriodFundamentals",
    "build_snapshot",
    "extract_json",
]
