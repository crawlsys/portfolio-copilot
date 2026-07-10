"""MCP tool signature validation tests.

Every tool module must have:
- A module docstring
- Typed conversion helpers
- No "order" or "approval" parameters
- The module contract: a TOOLS list + an async handle() dispatcher
  (modules never register on the Server directly — see apps/mcp/tools/__init__.py)
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import get_type_hints

import pytest
from apps.mcp.tools import briefing, congressional, market, portfolio
from mcp.types import Tool

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

ALL_MODULES = [portfolio, congressional, market, briefing]
MODULE_IDS = ["portfolio", "congressional", "market", "briefing"]


def _get_conversion_functions(module: object) -> list[tuple[str, Callable]]:
    """Extract helper functions that convert domain objects."""
    funcs = []
    for name, obj in inspect.getmembers(module, inspect.isfunction):
        if name.startswith("_") and "_to_dict" in name:
            funcs.append((name, obj))
    return funcs


class TestToolModulesHaveDocstrings:
    """Every tool module must have a module-level docstring."""

    @pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
    def test_module_has_docstring(self, module: object) -> None:
        assert module.__doc__, f"{module.__name__} has no docstring"


class TestConversionFunctionsAreTyped:
    """All _to_dict conversion functions should have return type hints."""

    @pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
    def test_conversion_functions_have_return_type(self, module: object) -> None:
        funcs = _get_conversion_functions(module)
        for name, func in funcs:
            hints = get_type_hints(func)
            assert "return" in hints, f"{module.__name__}.{name} has no return type hint"


class TestNoForbiddenParameters:
    """No tool may declare order/approval/trade parameters — in conversion
    helpers or in the tool input schemas themselves."""

    @pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
    def test_no_forbidden_params(self, module: object) -> None:
        funcs = _get_conversion_functions(module)
        for name, func in funcs:
            sig = inspect.signature(func)
            for param_name in sig.parameters:
                assert param_name.lower() not in FORBIDDEN_PARAM_NAMES, (
                    f"{module.__name__}.{name} has forbidden parameter '{param_name}'. "
                    "MCP tools must not accept order/approval/trade parameters."
                )

    @pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
    def test_no_forbidden_schema_properties(self, module: object) -> None:
        for tool in module.TOOLS:
            for prop in tool.inputSchema.get("properties", {}):
                assert prop.lower() not in FORBIDDEN_PARAM_NAMES, (
                    f"Tool '{tool.name}' declares forbidden input '{prop}'. "
                    "MCP tools must not accept order/approval/trade parameters."
                )


class TestModuleContract:
    """Each tool module must expose the passive TOOLS + handle() contract.

    Modules must NOT register handlers on the Server themselves: the
    low-level Server keeps one handler per request type, so a second
    @server.list_tools() registration silently replaces the first (the bug
    that hid every non-briefing tool from connected agents).
    """

    @pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
    def test_module_exposes_tools_list(self, module: object) -> None:
        assert isinstance(module.TOOLS, list) and module.TOOLS, (
            f"{module.__name__} must expose a non-empty TOOLS list"
        )
        assert all(isinstance(t, Tool) for t in module.TOOLS)

    @pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
    def test_module_exposes_async_handle(self, module: object) -> None:
        assert callable(getattr(module, "handle", None)), (
            f"{module.__name__} must expose handle(name, arguments, comp)"
        )
        assert inspect.iscoroutinefunction(module.handle)

    @pytest.mark.parametrize("module", ALL_MODULES, ids=MODULE_IDS)
    def test_module_does_not_register_directly(self, module: object) -> None:
        for name, _obj in inspect.getmembers(module, inspect.isfunction):
            assert not name.startswith("register_"), (
                f"{module.__name__}.{name}: modules must not register on the "
                "Server directly — expose TOOLS/handle() and let "
                "apps.mcp.tools.register_all_tools own the single registration."
            )

    def test_tool_names_unique_across_modules(self) -> None:
        names = [t.name for m in ALL_MODULES for t in m.TOOLS]
        dupes = {n for n in names if names.count(n) > 1}
        assert not dupes, f"Duplicate tool names across modules: {dupes}"
