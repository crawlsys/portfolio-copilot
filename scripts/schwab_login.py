#!/usr/bin/env python3
"""Schwab OAuth login flow — run LOCALLY (not in k8s).

Why local: schwab-py's login flow starts a temporary HTTPS server on
127.0.0.1:<port> and opens a browser to Schwab's authorize page. After you
log in, Schwab redirects to that local server with the auth code, which
schwab-py exchanges for tokens. This can't run in a headless k8s pod.

Usage:
    uv run python scripts/schwab_login.py

You'll be prompted to open a browser. After login completes, the token is
written to ~/.tracker/schwab_token.json AND printed as base64 + a kubectl
command to load it into the cluster.

Env (or read from .env):
    SCHWAB_CLIENT_ID, SCHWAB_CLIENT_SECRET, SCHWAB_REDIRECT_URI

The redirect URI MUST exactly match what's registered in Schwab's developer
portal (https://developer.schwab.com), including the path and port.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

# Make the repo importable when run from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    client_id = os.environ.get("SCHWAB_CLIENT_ID", "")
    client_secret = os.environ.get("SCHWAB_CLIENT_SECRET", "")
    callback_url = os.environ.get(
        "SCHWAB_REDIRECT_URI", "https://127.0.0.1:8080/callback"
    )

    if not client_id or not client_secret:
        # Try reading from the repo .env as a convenience.
        env_file = Path(__file__).resolve().parents[1] / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("SCHWAB_CLIENT_ID="):
                    client_id = client_id or line.split("=", 1)[1].strip()
                elif line.startswith("SCHWAB_CLIENT_SECRET="):
                    client_secret = client_secret or line.split("=", 1)[1].strip()
                elif line.startswith("SCHWAB_REDIRECT_URI="):
                    callback_url = callback_url or line.split("=", 1)[1].strip()

    if not client_id or not client_secret:
        print(
            "ERROR: SCHWAB_CLIENT_ID and SCHWAB_CLIENT_SECRET must be set.\n"
            "Export them or put them in .env, then re-run.",
            file=sys.stderr,
        )
        return 1

    from schwab import auth  # noqa: PLC0415

    token_path = Path.home() / ".tracker" / "schwab_token.json"
    token_path.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  SCHWAB OAUTH LOGIN")
    print("=" * 60)
    print(f"  callback_url : {callback_url}")
    print(f"  token_path   : {token_path}")
    print()
    print("A browser will open to Schwab. Log in with your Schwab")
    print("credentials and approve the app. You'll get a browser security")
    print("warning about the self-signed cert on the local redirect —")
    print("that's expected; click through it.")
    print()

    client = auth.client_from_login_flow(
        api_key=client_id,
        app_secret=client_secret,
        callback_url=callback_url,
        token_path=str(token_path),
        asyncio=False,
    )

    # Sanity check: pull account numbers to confirm the tokens work.
    print("\nLogin complete. Verifying access...")
    try:
        resp = client.get_account_numbers()
        if resp.status_code == 200:
            accounts = resp.json()
            print(f"  ✓ Linked accounts: {len(accounts)}")
            for a in accounts:
                print(f"      {a.get('hashValue', '?'):>16}  {a.get('accountNumber')}")
        else:
            print(f"  ⚠ get_account_numbers returned HTTP {resp.status_code}")
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ verification call failed: {e}")

    # Load the written token and emit the kubectl command.
    if not token_path.exists():
        print(f"\nERROR: token file not written at {token_path}", file=sys.stderr)
        return 1

    token_bytes = token_path.read_bytes()
    token_b64 = base64.b64encode(token_bytes).decode()

    print("\n" + "=" * 60)
    print("  TOKEN CAPTURED — load it into the cluster:")
    print("=" * 60)
    print()
    print("The token file is at:", token_path)
    print()
    print("To load into k8s as a secret (run from the repo root):")
    print()
    print("  kubectl create secret generic tracker-schwab-token -n tracker \\")
    print(f"    --from-file=token.json=<PASTE_TOKEN_PATH> \\")
    print("    --dry-run=client -o yaml | kubectl apply -f -")
    print()
    print("Or, base64-encoded single-line (for embedding):")
    print()
    print(f"  TOKEN_B64={token_b64}")
    print()
    print("NOTE: the refresh token expires in 7 DAYS (Schwab hard cap).")
    print("Re-run this script before then to refresh, or set up the")
    print("token-canary job to alert you.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
