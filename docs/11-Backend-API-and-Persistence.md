# 11 — Backend API & Persistence (FastAPI Gateway)

The AutoViz HTTP backend as **implemented** in `backend/src/autoviz/api/` +
`backend/src/autoviz/storage/`. It is the Proposal §4.2 **API Gateway** and **Storage Layer**:
a FastAPI app that exposes the existing AutoViz services over HTTP for the Next.js frontend, with
PostgreSQL-backed accounts, dataset metadata, saved charts, and dashboards.

> Every route is a **thin adapter** over the same `services.*` / `agent.*` functions the MCP server
> uses (Docs [07](07-MCP-Tool-Inventory.md)/[08](08-Agentic-Workflow-Architecture.md)); no analysis
> logic is re-implemented, and responses are the **same structured dicts** the services return — the
> API only chooses the HTTP status.

## Running it

```bash
docker compose -f backend/docker-compose.yml up -d          # PostgreSQL on :5432
cp backend/.env.example backend/.env                        # set GOOGLE_API_KEY for /agent
uv --directory backend run uvicorn autoviz.api.main:app --reload
# Swagger UI: http://localhost:8000/docs
```

Config (env, all optional except the DB URL in production):
`AUTOVIZ_DB_URL` (default `postgresql+psycopg://autoviz:autoviz@localhost:5432/autoviz`),
`AUTOVIZ_CORS_ORIGINS` (default `http://localhost:5173,http://localhost:3000`),
`AUTOVIZ_REGISTRY_MEMORY_BYTES` (resident DataFrame budget, default 512 MiB),
`AUTOVIZ_AGENT_CHECKPOINTER=postgres` (durable agent threads; default in-memory), `GOOGLE_API_KEY`.

## Route surface

| Method & path | Backed by | Auth |
|---|---|---|
| `GET /health` | — | no |
| `POST /auth/register` · `POST /auth/login` · `POST /auth/logout` · `GET /auth/me` | `storage` + `api.security` | mixed |
| `POST /datasets/inspect` (multipart) | `services.dataset.list_file_sheets` — the tables in a file, registering none | yes |
| `POST /datasets/upload` (multipart, optional `sheets`) | `services.dataset.register_dataset` + session storage | yes |
| `POST /datasets` (`{file_ref}`) | `services.dataset.register_dataset` | yes |
| `GET /datasets` · `DELETE /datasets/{id}` | `storage.repository` | yes (owner) |
| `GET /datasets/{id}/schema` · `/profile` · `/preview` | `services.dataset.*` | yes (owner) |
| `POST /analysis/validate` · `/execute` · `/pipeline` | `services.validation` / `execution` / `orchestrator` | no¹ |
| `POST /analysis/quality` · `/preview-preprocessing` | `services.quality` / `services.execution` (read-only) | no¹ |
| `POST /datasets/{id}/cleaned` | `services.execution.materialize_cleaned_dataset` + blob persistence | yes (owner) |
| `POST /charts/recommend` · `/generate` · `/export` | `services.charts` / `services.export` | no¹ |
| `POST /charts/save` · `GET /charts` · `GET/DELETE /charts/{id}` | `storage.repository` | yes (owner) |
| `POST /dashboards` · `GET /dashboards` · `GET/PUT/DELETE /dashboards/{id}` | `storage.repository` | yes (owner) |
| `POST /agent/analyze` · `POST /agent/answer` | `agent.service.AgentService` | no¹ |

`POST /analysis/execute` and `/pipeline` both carry an optional `approved_preprocessing_hash`. The
row-removal gate is enforced inside `services.execution.execute_analysis`, not in the route or the
orchestrator, so `/execute` cannot reach the cleaning chain around it. `POST /datasets/{id}/cleaned`
goes through the same gate and persists the result as a Parquet blob like an upload — a dataset the
user now owns must not vanish on cache eviction.

¹ Stateless analysis/chart/agent routes are open in this increment (they touch only the in-memory
registry); dataset access itself is owner-scoped. Tightening these behind auth is a config step when
per-user isolation is enforced end to end (Docs 10 §6).

## Error → HTTP status (`api/errors.py`)

The `respond()` helper keeps the service body byte-for-byte and sets the status from the typed
`error_code` (Docs [10 §1](10-Validation-Security-Resource-Controls.md)):

| Result | Status |
|---|---|
| success | 200 (201 on create) |
| `UNKNOWN_DATASET` | 404 |
| `RESOURCE_LIMIT` | 413 |
| `INVALID_PLAN` / `TYPE_MISMATCH` / `{valid:false}` | 422 |
| `TIMEOUT` | 504 · `EXECUTION_ERROR` | 500 |
| ownership failure | 403 · missing/expired token | 401 |
| other `{error}` / pipeline `{status:"error"}` | 400 |

Agent routes always return their structured envelope at 200 (the body carries `status`:
`completed` / `failed` / `waiting_for_user`), mirroring the MCP tools.

## Persistence (`storage/`, PostgreSQL via SQLAlchemy)

PostgreSQL is the database (Proposal §4.2; Docs 08 §12 / 09). Models use portable types (`JSON`),
so the identical schema runs on a throwaway SQLite for offline tests via `AUTOVIZ_DB_URL`.

- **Tables** — `users`, `sessions`, `datasets`, `dataset_blobs`, `saved_charts`, `dashboards`,
  `dashboard_widgets` (`models/`).
- **Datasets are durable.** `dataset_blobs` holds the parsed rows as **Parquet bytes** plus the
  cached schema and profile. Parquet rather than the original CSV because it round-trips dtypes
  exactly — re-parsing a CSV re-runs `_coerce_datetimes`, so the reloaded schema would only
  *probably* match the one a plan was validated against. Caching the profile matters equally:
  `_build_profile` is the expensive half of registration, not the parse.
- **The registry is a bounded cache in front of it.** `services.registry.DatasetRegistry` is an LRU
  keyed by `dataset_id` with a resident-bytes budget (`AUTOVIZ_REGISTRY_MEMORY_BYTES`, 512 MiB).
  A miss calls an injected **loader** (`storage/blobs.make_loader()`, wired in the app lifespan),
  so a frame evicted under memory pressure — or lost to a restart — is restored transparently.
  Every caller already goes through `registry.get()`, so `execution`, `validation` and the agent
  nodes needed no changes. The loader is injected rather than imported because `storage` depends on
  `services`, not the reverse; a bare `DatasetRegistry()` stays purely in-memory for the MCP server
  and the offline tests.
- `repository.resolve_dataset()` now only enforces **ownership** — reloading is the registry's job.
- **Auth** — Bearer tokens; passwords hashed with stdlib PBKDF2-HMAC-SHA256 (`api/security.py`), no
  external crypto dependency.
- **Durable agent threads** — set `AUTOVIZ_AGENT_CHECKPOINTER=postgres` to swap the LangGraph
  `InMemorySaver` → `PostgresSaver` (`storage/checkpoint.py`); `build_graph`/`AgentService` already
  accept the checkpointer, so no graph code changes. Defensive: falls back to in-memory if the DB is
  unreachable.

## Upload staging (`storage/uploads.py`, Proposal §4.7)

An upload is written to `backend/uploads/<user_id>/<uuid>.csv`, registered through the full
`register_dataset` path (resource limits + profiling + neutralization apply), recorded in
`datasets`, persisted as a Parquet blob — and then **the file is deleted**. The directory is
staging only; nothing durable points at it, so the API does not depend on local disk and a second
worker or replica sees the same datasets through the database.

There is deliberately **no TTL sweep**. Deleting upload directories on a timer left the `datasets`
rows behind, so a dataset kept appearing in `GET /datasets` while every use of it failed.
`DELETE /datasets/{id}` is the single deletion path and clears the cached frame, the blob, any
staged file, and the metadata together.

## Observability

An ASGI middleware logs one JSON line per HTTP call (`{http, path, status, ms}`) to the shared
`autoviz.observability` logger — the transport-level companion to the `@observed` decorator on MCP
tools (Docs 07 §Observability). No request bodies or headers are logged.

## Deferred (documented, not built this increment)

- Dashboard **image/PDF export** (Proposal §6): a rendering concern for the frontend canvas; the
  backend persists layout + serves specs and the existing self-contained HTML export (`/charts/export`).
- Rate limiting / OAuth / Origin hardening for a public deployment (Docs 10 §6); agent `thread_id`
  ownership (the broader session-ownership work).

## Verification

- **Automated (offline):** `uv --directory backend run pytest -q` — **371 tests**, no network, no
  API key, no running Postgres. API suites (`tests/test_api_*.py`) use Starlette's `TestClient`
  against a temp SQLite DB (`api_db` fixture) and a `FakePlanner`-injected agent. Covers every route
  group, auth (401), ownership (403), unknown ids (404), and a `RESOURCE_LIMIT` upload (413).
  `test_registry_cache.py` pins eviction and loader behaviour; `test_dataset_blobs.py` pins the
  dtype-exact reload, the no-registry/no-file restart case, and the pre-blob CSV fallback.
- **Manual (Postgres):** the run steps above, then register → login → upload titanic.csv → profile →
  `/analysis/pipeline` (avg age by sex) → `/charts/save` → `/dashboards` with that chart as a
  widget → `GET /dashboards/{id}`. Then **stop uvicorn entirely and start a new process**: the same
  `dataset_id` still profiles, previews and executes, with no CSV left under `uploads/` — the rows
  come back from `dataset_blobs`.
- **Shared registry:** the HTTP API and `python -m autoviz.mcp` use the same `REGISTRY` instance, so
  datasets are visible across both entry paths; the MCP suite stays green.
