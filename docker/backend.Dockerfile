# syntax=docker/dockerfile:1
# Single image; entrypoint selected by cmd arg (apps.api | apps.mcp | apps.worker).

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
USER appuser
EXPOSE 8000
CMD ["python", "-m", "apps.api"]
