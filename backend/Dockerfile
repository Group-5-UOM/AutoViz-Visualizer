# syntax=docker/dockerfile:1
#
# AutoViz backend — FastAPI API Gateway (Proposal §4.2).
# Built with uv against the committed uv.lock for reproducible images.
# Build context is backend/:  docker build -t autoviz-api backend/

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# uv: copy (not hardlink) into the image, byte-compile, and keep the venv
# on PATH so `uvicorn`/`alembic` resolve without `uv run`.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 1) Resolve dependencies from the lockfile first. This layer is cached and
#    only rebuilds when uv.lock / pyproject.toml change — not on every code edit.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# 2) Copy the source and install the autoviz package itself.
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Writable runtime dirs (uploads default to /app/uploads per core/config.py).
# Mount a volume over /app/uploads in compose to persist across container swaps.
RUN mkdir -p /app/uploads /app/exports /app/logs \
    && useradd --create-home --uid 10001 autoviz \
    && chown -R autoviz:autoviz /app
USER autoviz

EXPOSE 8000

# Entrypoint applies DB migrations (alembic upgrade head) then execs the CMD.
ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
CMD ["uvicorn", "autoviz.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
