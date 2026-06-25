"""Digest chat — an interactive, context-aware chatbot on the digest page.

The model sees the SAME context the daily digest is built from (portfolio,
holdings, congressional signal, market regime) PLUS the last several days of
digests, so it can reason about what was already recommended and what the owner
already holds (e.g. "the digest says buy VTI, but I bought it yesterday").

Streams tokens back as Server-Sent Events. Context is assembled once up front
(DB closed before streaming begins); only the OpenRouter HTTP stream stays open
while tokens flow. Ephemeral — no conversation is persisted; the browser sends
the full message history each turn.
"""

from __future__ import annotations

import json
import time
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from apps.common.composition import session_factory
from apps.common.settings import get_settings
from trading.adapters.persistence.models import DigestRow
from trading.application.signals.generate_briefing import (
    _assess_market_regime,
    _fetch_disclosures,
    _fetch_held_tickers,
)
from trading.application.signals.generate_digest import (
    OPENROUTER_URL,
    _build_context,
    _fetch_positions,
    _load_account_file,
)

router = APIRouter()

# Models the owner may pick in the chat UI. Anything else falls back to the
# default — guards against arbitrary-model / cost injection via the request body.
_ALLOWED_MODELS = (
    "anthropic/claude-opus-4.8",
    "anthropic/claude-sonnet-4.6",
    "google/gemini-2.5-flash",
)
_DEFAULT_MODEL = "anthropic/claude-opus-4.8"

# Bound how much digest history we feed the model.
_RECENT_DIGESTS = 5
_DIGEST_TRUNC = 4000  # chars per digest, keeps the prompt sane
_MAX_TOKENS = 2000

_CHAT_SYSTEM_PROMPT = (
    "You are a private investment analyst chatting with the owner about THEIR "
    "OWN portfolio (no fiduciary/third-party context). You have the owner's "
    "current holdings, recent Congressional disclosures, market regime, and the "
    "last several DAILY DIGESTS below. Answer their questions directly, "
    "specifically, and quantitatively. Crucially, account for what the owner has "
    "ALREADY done or holds: if a recent digest recommended an action the owner "
    "appears to have since taken (e.g. a ticker now in the holdings), say so and "
    "don't blindly repeat it. Keep replies focused and conversational — no "
    "boilerplate disclaimers.\n\n"
    "HARD CONSTRAINTS — obey strictly:\n"
    "- The JOINT account is BROKER/ADVISOR-MANAGED and HOLD-ONLY; never "
    "recommend selling or trimming any joint/managed position.\n"
    "- TAX: the owner already realized a large capital gain THIS YEAR; do NOT "
    "recommend realizing further gains in any taxable account.\n"
    "- Any BUY/deploy action applies ONLY to the self-directed individual "
    "account and its available cash.\n"
)

# --- crude in-process rate limit (caps runaway OpenRouter spend) --------------
_RATE_MAX = 30  # requests
_RATE_WINDOW = 60.0  # seconds
_recent_calls: deque[float] = deque()


def _rate_limit() -> None:
    now = time.time()
    while _recent_calls and now - _recent_calls[0] > _RATE_WINDOW:
        _recent_calls.popleft()
    if len(_recent_calls) >= _RATE_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Chat rate limit exceeded; wait a moment.",
        )
    _recent_calls.append(now)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)
    digestDate: str | None = None  # noqa: N815 — frontend JSON convention
    model: str | None = None


def _resolve_model(requested: str | None) -> str:
    if requested in _ALLOWED_MODELS:
        return requested
    configured = get_settings().chat_model or get_settings().digest_model
    return configured if configured in _ALLOWED_MODELS else _DEFAULT_MODEL


async def _assemble_context(request: Request, digest_date: str | None) -> str:
    """Build the same portfolio/congressional context the digest uses, plus the
    last few digests. Fully awaited here so the DB session closes before we
    start streaming from OpenRouter."""
    comp = request.app.state.composition
    if comp.engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DATABASE_URL not configured.",
        )

    now = comp.clock.now()
    target_date = now.date()
    if digest_date:
        try:
            target_date = datetime.fromisoformat(digest_date).date()
        except ValueError:
            target_date = now.date()

    period_end = datetime.combine(
        target_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC
    )
    period_start = period_end - timedelta(days=45)

    async with session_factory(comp) as session:
        disclosures = await _fetch_disclosures(session, period_start, period_end)
        held = await _fetch_held_tickers(session)
        overlaps = [d for d in disclosures if d.symbol and d.symbol in held]
        positions = await _fetch_positions(session)
        recent = (
            (
                await session.execute(
                    select(DigestRow)
                    .order_by(DigestRow.generated_at.desc())
                    .limit(_RECENT_DIGESTS + 3)
                )
            )
            .scalars()
            .all()
        )

    regime = await _assess_market_regime(comp.market_data)

    individual = _load_account_file("holdings-individual.json")
    joint = _load_account_file("holdings.json")
    joint_managed = bool(joint and joint.managed)
    cash_to_deploy = str(individual.cash) if individual is not None else "0"

    total_sec = sum((p.mv for p in positions), Decimal("0"))
    base = _build_context(
        target_date, positions, total_sec, disclosures, overlaps, regime,
        cash_to_deploy, individual, joint_managed,
    )

    # Recent digests (dedup by date, newest first, bounded length) so the model
    # knows what it already recommended on prior days.
    seen: set[str] = set()
    blocks: list[str] = []
    for row in recent:
        iso = row.digest_date.date().isoformat()
        if iso in seen:
            continue
        seen.add(iso)
        body = row.summary_markdown[:_DIGEST_TRUNC]
        blocks.append(f"### Digest {iso} (model: {row.model})\n{body}")
        if len(blocks) >= _RECENT_DIGESTS:
            break

    history = "\n\n".join(blocks) if blocks else "No prior digests on record."
    return f"{base}\n\nRECENT DAILY DIGESTS (newest first):\n\n{history}"


async def _stream_openrouter(
    api_key: str, model: str, messages: list[dict[str, str]]
) -> AsyncIterator[str]:
    """Stream assistant tokens from OpenRouter, re-emitting them as SSE
    `data: <json-string>` events, terminated by `data: [DONE]`."""
    payload = {
        "model": model,
        "max_tokens": _MAX_TOKENS,
        "stream": True,
        "messages": messages,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://trackdash.example.com",
        "X-Title": "Tracker Digest Chat",
    }
    try:
        async with httpx.AsyncClient(timeout=180.0) as client, client.stream(
            "POST", OPENROUTER_URL, headers=headers, json=payload
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0]["delta"]
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                token = delta.get("content")
                if token:
                    yield f"data: {json.dumps(token)}\n\n"
    except httpx.HTTPStatusError as exc:
        yield f"data: {json.dumps(f'[error: upstream {exc.response.status_code}]')}\n\n"
    except Exception:  # noqa: BLE001 — surface a clean error to the client, never 500 mid-stream
        yield f"data: {json.dumps('[error: chat stream failed]')}\n\n"
    yield "data: [DONE]\n\n"


@router.post("/chat")
async def digest_chat(request: Request, body: ChatRequest) -> StreamingResponse:
    """Stream a context-aware chat reply over SSE."""
    _rate_limit()

    settings = get_settings()
    if not settings.openrouter_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENROUTER_API_KEY not configured.",
        )
    if not body.messages:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "messages must not be empty.")

    model = _resolve_model(body.model)
    context = await _assemble_context(request, body.digestDate)

    # System prompt + injected context, then the conversation. Cap history length
    # defensively and drop any client-sent system messages.
    convo = [
        {"role": m.role, "content": m.content}
        for m in body.messages[-20:]
        if m.role in ("user", "assistant") and m.content.strip()
    ]
    messages = [
        {"role": "system", "content": _CHAT_SYSTEM_PROMPT + "\n\n--- CONTEXT ---\n" + context},
        *convo,
    ]

    return StreamingResponse(
        _stream_openrouter(settings.openrouter_api_key, model, messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


__all__ = ["router"]
