"""Dedicated Schwab OAuth callback service.

A tiny, isolated FastAPI app whose ONLY job is to capture the Schwab OAuth
redirect, exchange the auth code for tokens, and push the token blob to
Bitwarden Secrets Manager (from which the CSI driver syncs it into the pods).

It is deployed separately from the main API (`tracker-webhook`) and exposed on
a public hostname (webhook.example.com) with NO auth gate — safe because
the endpoint only receives a short-lived, single-use auth code that is useless
without the server-side client secret. It serves nothing else.

Re-auth becomes: visit /schwab/login → log into Schwab → redirected back →
token captured and stored. No local script, no laptop BWS token.
"""
