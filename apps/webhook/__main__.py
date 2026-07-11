"""Run the Schwab OAuth webhook service: python -m apps.webhook."""

from __future__ import annotations

import logging
import os

import uvicorn


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("WEBHOOK_PORT", "8090"))
    uvicorn.run(
        "apps.webhook.app:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 — behind the cluster + cloudflared
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
