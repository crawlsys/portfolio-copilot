"""Advisor council — persona LLM analysts over point-in-time fundamentals.

Adopted from virattt/ai-hedge-fund v2 (MIT): FundamentalsSnapshot →
persona agent → stance/confidence/reasoning, cached by snapshot hash with
the exact prompt + response persisted for replay and audit.
"""

from __future__ import annotations

from trading.application.advisors.agent import AdvisorAgent, AdvisorView
from trading.application.advisors.buffett import BuffettAdvisor
from trading.application.advisors.burry import BurryAdvisor
from trading.application.advisors.graham import GrahamAdvisor
from trading.application.advisors.llm import (
    AdvisorLLMError,
    LLMClient,
    OpenAICompatLLM,
    extract_json,
)
from trading.application.advisors.munger import MungerAdvisor
from trading.application.advisors.snapshot import (
    MIN_PERIODS,
    FundamentalsPort,
    FundamentalsSnapshot,
    InsufficientDataError,
    PeriodFundamentals,
    build_snapshot,
)

# Value-council personas: fundamentals-driven analysts matching the data the
# FundamentalsSnapshot carries. Add a persona = one file (name + system prompt)
# and one line here.
ADVISOR_REGISTRY: dict[str, type[AdvisorAgent]] = {
    "buffett": BuffettAdvisor,
    "munger": MungerAdvisor,
    "graham": GrahamAdvisor,
    "burry": BurryAdvisor,
}

__all__ = [
    "ADVISOR_REGISTRY",
    "MIN_PERIODS",
    "AdvisorAgent",
    "AdvisorLLMError",
    "AdvisorView",
    "BuffettAdvisor",
    "BurryAdvisor",
    "FundamentalsPort",
    "FundamentalsSnapshot",
    "GrahamAdvisor",
    "InsufficientDataError",
    "LLMClient",
    "MungerAdvisor",
    "OpenAICompatLLM",
    "PeriodFundamentals",
    "build_snapshot",
    "extract_json",
]
