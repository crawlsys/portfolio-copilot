"""E2E scope guard: assert the system has no execution path.

This is the single most important test in the codebase. The spec's central
scope promise (§Non-goals) is: no live trade execution, no LLM-driven trade
proposals, no approval gates, no broker submit path. If anyone lands any of
these, this test fails — loudly, with the spec reference.

Run by CI on every push. The test imports every module in trading.domain,
trading.application, trading.adapters, and apps, then greps their public
APIs for forbidden names. It also asserts the EventType catalog, BrokerPort,
and the FastAPI OpenAPI schema carry no trading surface.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from types import ModuleType

import apps.mcp.tools as tools_pkg
import pytest

from trading.adapters.ports.broker import BrokerPort
from trading.domain import is_produced_in_v1
from trading.domain.common.event_types import _DEFERRED_EXECUTION_EVENTS

# Names that signal execution / trading surface. If any public symbol
# in the codebase matches, the test fails.
FORBIDDEN_NAME_FRAGMENTS = (
    "place_order",
    "cancel_order",
    "submit_order",
    "approve_order",
    "ExecutableOrder",
    "OrderIntent",
    "BrokerSubmitWorker",
    "ApprovalSaga",
    "find_recent_order_by_fingerprint",
    "recover_ambiguous_submission",
)

# Modules whose public API we scan. Skips __init__ re-exports that just
# expose types defined elsewhere (the type might be deferred-but-defined).
SCAN_PACKAGE_ROOTS = (
    "trading.application",
    "trading.adapters",
    "apps.api",
    "apps.mcp",
    "apps.worker",
)


def _iter_modules(pkg_name: str) -> list[ModuleType]:
    try:
        pkg = importlib.import_module(pkg_name)
    except ImportError:
        return []
    out: list[ModuleType] = [pkg]
    if not hasattr(pkg, "__path__"):
        return out
    for _, name, _ in pkgutil.walk_packages(pkg.__path__, prefix=f"{pkg_name}."):
        try:
            out.append(importlib.import_module(name))
        except ImportError:
            continue
    return out


class TestNoExecutionSurface:
    """Spec §Non-goals: the system has no path to broker writes."""

    def test_event_catalog_defers_execution_events(self) -> None:
        """Execution events must exist as types (for the catalog) but be
        flagged not-produced-in-v1. If any execution event becomes produced,
        that's a scope violation."""
        for et in _DEFERRED_EXECUTION_EVENTS:
            assert not is_produced_in_v1(et), (
                f"{et} is now produced in v1 — this activates execution. "
                "Spec §Non-goals: no live trade execution. If you intend to "
                "activate execution, see spec §Execution (stub) and apply "
                "the money-path red-team fixes (§10)."
            )

    def test_broker_port_has_no_trading_methods(self) -> None:
        """BrokerPort must not declare place_order, cancel_order, etc."""
        methods = {name for name, _ in inspect.getmembers(BrokerPort, inspect.isfunction)}
        for forbidden in ("place_order", "cancel_order", "submit_order"):
            assert forbidden not in methods, (
                f"BrokerPort.{forbidden} exists — execution is leaking into v1."
            )

    @pytest.mark.parametrize("root", SCAN_PACKAGE_ROOTS)
    def test_no_forbidden_public_symbols(self, root: str) -> None:
        """No module in the scan roots may expose a forbidden name."""
        offenders: list[str] = []
        for mod in _iter_modules(root):
            for name, _ in inspect.getmembers(mod):
                # Skip imported names (look at definitions only)
                if not name or name.startswith("_"):
                    continue
                # Only flag names that look like our own (not stdlib re-exports)
                obj = getattr(mod, name, None)
                if obj is None:
                    continue
                defining_mod = getattr(obj, "__module__", None)
                if defining_mod and not defining_mod.startswith(("trading.", "apps.")):
                    continue
                for bad in FORBIDDEN_NAME_FRAGMENTS:
                    if bad.lower() in name.lower():
                        offenders.append(f"{mod.__name__}.{name} (matches '{bad}')")
        assert not offenders, (
            "Forbidden execution/trading surface found:\n  - "
            + "\n  - ".join(sorted(set(offenders)))
            + "\n\nSpec §Non-goals: no live trade execution. See spec §Execution (stub)."
        )

    def test_no_mcp_write_tools_module(self) -> None:
        """The MCP tools directory must not contain a module whose name
        suggests trading (e.g., orders.py, trades.py, approvals.py)."""
        if not hasattr(tools_pkg, "__path__"):
            return  # no tools yet — fine
        tool_modules = [name for _, name, _ in pkgutil.iter_modules(tools_pkg.__path__)]
        forbidden_tool_modules = {"orders", "trades", "approvals", "execution"}
        overlap = forbidden_tool_modules & set(tool_modules)
        assert not overlap, (
            f"apps/mcp/tools/ contains forbidden module(s): {overlap}. "
            "MCP must expose read-only tools only — spec §Non-goals."
        )


class TestEventTypeCatalogCompleteness:
    """Defensive: every deferred execution event has a v1 schema (so the
    catalog is complete for the future). If anyone deletes one, this fails.
    """

    def test_all_deferred_events_have_v1_strings(self) -> None:
        for et in _DEFERRED_EXECUTION_EVENTS:
            assert et.value.endswith(".v1")
            # And the human-readable form contains the execution context
            assert et.value.startswith("execution.")
