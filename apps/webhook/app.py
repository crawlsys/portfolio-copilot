"""Schwab OAuth callback service.

Captures the Schwab OAuth redirect, exchanges the auth code for tokens, and
writes the resulting {creation_timestamp, token} blob directly into the
native Kubernetes Secret `tracker-schwab-token` (key `token.json`) — the same
Secret api/worker/mcp mount at /etc/schwab/token.json.

Least privilege: the pod runs as the `tracker-schwab-writer` ServiceAccount,
whose Role grants patch/get on ONLY the `tracker-schwab-token` Secret (see
infra/k8s/base/webhook.yaml). It cannot read or write any other secret — not
tracker-secrets, not BWS, nothing. The Schwab client id/secret it needs for the
exchange arrive as env via secretKeyRef (kubelet-injected; needs no RBAC).

Flow:
1. GET /schwab/login  → authorize URL + CSRF state → redirect to Schwab.
2. GET /schwab/callback?code=&state= → verify state → exchange → patch the
   Secret via `kubectl` (in-cluster ServiceAccount).
"""

from __future__ import annotations

import base64
import json
import logging
import subprocess
import time
from collections.abc import Callable

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse

from apps.common.settings import get_settings

_log = logging.getLogger(__name__)

# CSRF: pending states → issue time. In-memory (single replica, one-sitting flow).
_PENDING_STATES: dict[str, float] = {}
_STATE_TTL_SECONDS = 600


def _prune_states(now: float) -> None:
    for s, t in list(_PENDING_STATES.items()):
        if now - t > _STATE_TTL_SECONDS:
            _PENDING_STATES.pop(s, None)


def _patch_k8s_secret(secret_name: str, namespace: str) -> Callable[..., None]:
    """schwab-py token_write_func: write the wrapped token blob into the native
    k8s Secret's `token.json` key via `kubectl patch` (in-cluster ServiceAccount,
    scoped to just this Secret)."""

    def write(wrapped_token: dict[str, object], *_args: object, **_kwargs: object) -> None:
        b64 = base64.b64encode(json.dumps(wrapped_token).encode()).decode()
        patch = json.dumps({"data": {"token.json": b64}})
        subprocess.run(
            ["kubectl", "patch", "secret", secret_name, "-n", namespace,
             "--type", "merge", "-p", patch],
            check=True,
            capture_output=True,
            text=True,
        )

    return write


def create_app() -> FastAPI:
    app = FastAPI(title="tracker-webhook (Schwab OAuth)", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/schwab/login")
    async def schwab_login() -> RedirectResponse:
        from schwab import auth  # noqa: PLC0415

        settings = get_settings()
        if not settings.schwab_client_id or not settings.schwab_redirect_uri:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Schwab client id / redirect URI not configured.",
            )
        ctx = auth.get_auth_context(settings.schwab_client_id, settings.schwab_redirect_uri)
        now = time.time()
        _prune_states(now)
        _PENDING_STATES[ctx.state] = now
        _log.info("Schwab OAuth login initiated (state=%s…)", ctx.state[:8])
        return RedirectResponse(ctx.authorization_url, status_code=status.HTTP_302_FOUND)

    @app.get("/schwab/callback")
    async def schwab_callback(request: Request) -> HTMLResponse:
        from schwab import auth  # noqa: PLC0415

        settings = get_settings()
        params = request.query_params
        if "error" in params:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"Schwab returned an error: {params.get('error')}"
            )
        code = params.get("code")
        state = params.get("state", "")
        if not code:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing authorization code.")

        _prune_states(time.time())
        if state not in _PENDING_STATES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Unknown or expired state — start again at /schwab/login.",
            )
        _PENDING_STATES.pop(state, None)

        received_url = f"{settings.schwab_redirect_uri}?{request.url.query}"
        ctx = auth.get_auth_context(
            settings.schwab_client_id, settings.schwab_redirect_uri, state=state
        )
        try:
            client = await run_in_threadpool(
                auth.client_from_received_url,
                settings.schwab_client_id,
                settings.schwab_client_secret,
                ctx,
                received_url,
                _patch_k8s_secret(settings.schwab_token_secret_name, settings.pod_namespace),
            )
            client.session.close()
        except subprocess.CalledProcessError as exc:
            _log.error("kubectl patch of the token secret failed: %s", exc.stderr)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "Token exchanged but writing the k8s secret failed."
            ) from exc
        except Exception as exc:  # noqa: BLE001
            _log.exception("Schwab token exchange failed")
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, f"Token exchange failed: {exc}"
            ) from exc

        _log.info("Schwab OAuth token captured and written to %s", settings.schwab_token_secret_name)
        return HTMLResponse(
            "<h2>✓ Schwab connected.</h2>"
            "<p>The token was captured and written to the cluster. Roll the pods "
            "to pick it up:</p>"
            "<pre>kubectl -n tracker rollout restart "
            "deploy/tracker-api deploy/tracker-worker deploy/tracker-mcp</pre>"
            "<p>You can close this tab.</p>"
        )

    return app
