"""MCP tool signature validation tests.

Every tool must have:
- A docstring
- Typed parameters
- No "order" or "approval" parameters
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import get_type_hints

import pytest
from apps.mcp.tools import briefing, congressional, market, portfolio

FORBIDDEN_PARAM_NAMES = frozenset(
    {
        "order",
        "orders",
        "approval",
        "approvals",
        "trade",
        "trades",
        "execution",
        "submit",
    }
)


def _get_conversion_functions(module: object) -> list[tuple[str, Callable]]:
    """Extract helper functions that convert domain objects."""
    funcs = []
    for name, obj in inspect.getmembers(module, inspect.isfunction):
        if name.startswith("_") and "_to_dict" in name:
            funcs.append((name, obj))
    return funcs


class TestToolModulesHaveDocstrings:
    """Every tool module must have a module-level docstring."""

    @pytest.mark.parametrize(
        "module",
        [portfolio, congressional, market, briefing],
        ids=["portfolio", "congressional", "market", "briefing"],
    )
    def test_module_has_docstring(self, module: object) -> None:
        assert module.__doc__, f"{module.__name__} has no docstring"


class TestConversionFunctionsAreTyped:
    """All _to_dict conversion functions should have return type hints."""

    @pytest.mark.parametrize(
        "module",
        [portfolio, congressional, market, briefing],
        ids=["portfolio", "congressional", "market", "briefing"],
    )
    def test_conversion_functions_have_return_type(self, module: object) -> None:
        funcs = _get_conversion_functions(module)
        for name, func in funcs:
            hints = get_type_hints(func)
            assert "return" in hints, f"{module.__name__}.{name} has no return type hint"


class TestNoForbiddenParameters:
    """No tool conversion function may accept order/approval/trade parameters."""

    @pytest.mark.parametrize(
        "module",
        [portfolio, congressional, market, briefing],
        ids=["portfolio", "congressional", "market", "briefing"],
    )
    def test_no_forbidden_params(self, module: object) -> None:
        funcs = _get_conversion_functions(module)
        for name, func in funcs:
            sig = inspect.signature(func)
            for param_name in sig.parameters:
                assert param_name.lower() not in FORBIDDEN_PARAM_NAMES, (
                    f"{module.__name__}.{name} has forbidden parameter '{param_name}'. "
                    "MCP tools must not accept order/approval/trade parameters."
                )


class TestRegisterFunctionsExist:
    """Each tool module must expose a register_*_tools function."""

    def test_portfolio_has_register(self) -> None:
        assert hasattr(portfolio, "register_portfolio_tools")
        assert callable(portfolio.register_portfolio_tools)

    def test_congressional_has_register(self) -> None:
        assert hasattr(congressional, "register_congressional_tools")
        assert callable(congressional.register_congressional_tools)

    def test_market_has_register(self) -> None:
        assert hasattr(market, "register_market_tools")
        assert callable(market.register_market_tools)

    def test_briefing_has_register(self) -> None:
        assert hasattr(briefing, "register_briefing_tools")
        assert callable(briefing.register_briefing_tools)
