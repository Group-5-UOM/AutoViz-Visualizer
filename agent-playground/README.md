# AutoViz · Agent Playground

A tiny, **zero-build** test harness for the agentic workflow — a chat box, CSV upload,
and inline Vega-Lite chart renderer in a single `index.html`. It talks to the real
FastAPI backend (`/auth`, `/datasets/upload`, `/agent/analyze`, `/agent/answer`), so
it's a fast way to exercise the agent end-to-end without the full frontend.

This folder lives **outside** `backend/` on purpose — it's throwaway dev tooling,
not part of the deployed app.

## Run

**1. Start the backend** (needs `GOOGLE_API_KEY` set for the real planner):

```bash
uv --directory backend run uvicorn autoviz.api.main:app --reload
# → http://localhost:8000
```

**2. Serve this page on port 3000** (see the CORS note below for *why* 3000):

```bash
cd agent-playground
python -m http.server 3000
# → open http://localhost:3000
```

## Use it

1. **Backend** — confirm the `API ● up` pill (top-right). Adjust the base URL if needed.
2. **Account** — click **Register** once, then **Login**. The Bearer token is held in
   memory only (never persisted).
3. **Dataset** — pick a CSV (e.g. anything under `test-data/`) and **Upload**.
4. **Chat** — ask something like *"average fare by passenger class"*. Charts render
   inline; each response has a **raw response** disclosure for debugging.
   - If the agent needs clarification, its question appears with **option buttons** —
     clicking one (or typing a reply) resumes the same `thread_id`.
   - Follow-up questions reuse the `thread_id` (refinement). **New conversation**
     resets it.

## Why port 3000?

The backend's default CORS allow-list is `http://localhost:3000` /
`http://127.0.0.1:3000` (`api/main.py:_cors_origins`). Serve the playground on any
other origin and the browser will block the calls. Either use `:3000`, or start the
backend with a wider list:

```bash
AUTOVIZ_CORS_ORIGINS="http://localhost:5500,http://localhost:3000" \
  uv --directory backend run uvicorn autoviz.api.main:app --reload
```

## Notes

- The Vega runtime loads from jsDelivr (CDN) — fine for local dev; there are no other
  external calls.
- `/agent` routes require `GOOGLE_API_KEY`. Without it, analyze requests come back as
  a `failed` envelope (shown as a red bubble), while auth/upload still work.
- Requests are stateless per token; uploads land in the backend's session-isolated
  upload dir and are subject to its TTL sweep.
