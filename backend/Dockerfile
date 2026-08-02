FROM python:3.12-slim
WORKDIR /app

# Copy uv from the official image (Fastest/Best Practice)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Runtime user and writable dirs (uploads default to /app/uploads per
# core/config.py). Done before the venv exists so this layer stays cached across
# code edits, and so the chown never has to walk /app/.venv — ownership changes
# force an overlayfs copy-up of every file touched, which would duplicate the
# whole venv into a new layer on every rebuild. The venv and source stay
# root-owned: autoviz needs to read them, not write them.
# Mount a volume over /app/uploads in compose to persist across container swaps;
# a named volume inherits this ownership when it is first created.
RUN useradd --create-home --uid 10001 autoviz \
    && mkdir -p /app/uploads /app/exports /app/logs \
    && chown autoviz:autoviz /app/uploads /app/exports /app/logs

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

# Add the virtual environment to the PATH so that python, alembic, and uvicorn are found
ENV PATH="/app/.venv/bin:$PATH"

USER autoviz

EXPOSE 8000

# Entrypoint applies DB migrations (alembic upgrade head) then execs the CMD.
ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
CMD ["uvicorn", "autoviz.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
