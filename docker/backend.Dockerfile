# syntax=docker/dockerfile:1
# Single image; entrypoint selected by cmd arg
# (apps.api | apps.mcp | apps.worker | apps.webhook).

# kubectl — the webhook (apps.webhook) uses it to patch the native
# tracker-schwab-token Secret in-cluster via its RBAC-scoped ServiceAccount.
FROM debian:bookworm-slim AS kubectl
ARG KUBECTL_VERSION=v1.31.0
ADD https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl /usr/local/bin/kubectl
RUN chmod +x /usr/local/bin/kubectl

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY src ./src
COPY apps ./apps
COPY migrations ./migrations
COPY scripts ./scripts
COPY data ./data
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN useradd -u 10001 -r -s /usr/sbin/nologin appuser
COPY --from=builder /app /app
# kubectl for the webhook's in-cluster Secret patch. Only the webhook pod is
# bound to a ServiceAccount that can use it (scoped to one Secret); other pods
# have no such RBAC.
COPY --from=kubectl /usr/local/bin/kubectl /usr/local/bin/kubectl
USER appuser
EXPOSE 8000
CMD ["python", "-m", "apps.api"]
