# AutoViz AI

AutoViz AI is a web-based conversational data visualization and dashboard-building platform (University of Moratuwa CS3501 Data Science and Engineering Project).

Registered users upload a structured CSV, ask analytical questions in natural language, and receive validated chart recommendations rendered with Vega-Lite. Charts can be arranged on an interactive dashboard (move, resize, edit), saved and reopened, and exported as image or PDF.

| Layer | Stack |
| --- | --- |
| Frontend | React, TypeScript, Vite, Vega-Lite |
| Backend | FastAPI, Pandas / DuckDB, LangGraph agent |
| Database | PostgreSQL |
| Charts | Vega-Lite |

### Default local ports

| Service | Port |
| --- | --- |
| Frontend (Vite) | `5173` |
| Backend API | `8000` |
| Postgres (system / pgAdmin) | `5432` |
| Postgres (Docker Compose, host) | `5434` |
| Agent playground | `3000` |

By default the app uses system Postgres on port `5432` (database `autoviz`). Docker Compose maps Postgres as `5434:5432` if you prefer the container DB instead.

---

## Prerequisites

- [Git](https://git-scm.com/)
- [Node.js](https://nodejs.org/) (v20+) and npm
- [uv](https://docs.astral.sh/uv/) (Python 3.11+)
- [Docker](https://www.docker.com/) and Docker Compose (for PostgreSQL / optional full API stack)
- A Google AI API key (only if you use the `/agent` planner routes)

---

## Clone

```bash
git clone https://github.com/codevector-2003/AutoViz-Visualizer.git
cd AutoViz-Visualizer
```

---

## Environment

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env` and set at least:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Postgres connection string |
| `SECRET_KEY` | Auth / token secret |
| `AUTOVIZ_CORS_ORIGINS` | Allowed frontend origins (comma-separated) |
| `OPENAI_API_KEY` | OpenAI planner (set with `AUTOVIZ_PLANNER_MODEL=openai:gpt-4o-mini`) |
| `GOOGLE_API_KEY` | Google Gemini planner (default if `AUTOVIZ_PLANNER_MODEL` unset) |
| `AUTOVIZ_PLANNER_MODEL` | LangChain model id, e.g. `openai:gpt-4o-mini` or `google_genai:gemini-3.5-flash` |
| `GITHUB_OAUTH_CLIENT_ID` / `SECRET` | GitHub OAuth App credentials |
| `GOOGLE_OAUTH_CLIENT_ID` / `SECRET` | Google OAuth Web client credentials |
| `AUTOVIZ_FRONTEND_URL` | Frontend origin for OAuth return — local `http://localhost:5173`, hosted `https://autoviz.duckdns.org` |
| `AUTOVIZ_API_PUBLIC_URL` | Backend public URL for OAuth callbacks — local `http://127.0.0.1:8000`, hosted `https://autoviz.duckdns.org` |
| `GITHUB_OAUTH_REDIRECT_URI` | Optional override (blank → `{AUTOVIZ_API_PUBLIC_URL}/auth/oauth/github/callback`) |
| `GOOGLE_OAUTH_REDIRECT_URI` | Optional override (blank → `{AUTOVIZ_API_PUBLIC_URL}/auth/oauth/google/callback`) |

For system Postgres (pgAdmin, port `5432`) — create a database named `autoviz`, then:

```env
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/autoviz
SECRET_KEY=autoviz-dev-secret-key-change-in-production
AUTOVIZ_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000
OPENAI_API_KEY=your-openai-key-here
AUTOVIZ_PLANNER_MODEL=openai:gpt-4o-mini
# Or use Google instead:
# GOOGLE_API_KEY=your-google-key-here
# AUTOVIZ_PLANNER_MODEL=google_genai:gemini-3.5-flash
```

For Docker Compose Postgres instead:

```env
DATABASE_URL=postgresql://autoviz:autoviz@localhost:5434/autoviz
```

### OAuth console URLs

Register **both** local and hosted callbacks in the provider consoles so the same OAuth app works in either environment. The app picks which one to use from `AUTOVIZ_API_PUBLIC_URL` (or the optional `*_OAUTH_REDIRECT_URI` overrides).

| Provider | Setting | Local | Hosted |
| --- | --- | --- | --- |
| GitHub OAuth App | Authorization callback URL | `http://127.0.0.1:8000/auth/oauth/github/callback` | `https://autoviz.duckdns.org/auth/oauth/github/callback` |
| Google Cloud OAuth client | Authorized JavaScript origins | `http://localhost:5173` | `https://autoviz.duckdns.org` |
| Google Cloud OAuth client | Authorized redirect URIs | `http://127.0.0.1:8000/auth/oauth/google/callback` | `https://autoviz.duckdns.org/auth/oauth/google/callback` |

**Local `.env`:**

```env
AUTOVIZ_FRONTEND_URL=http://localhost:5173
AUTOVIZ_API_PUBLIC_URL=http://127.0.0.1:8000
```

**Hosted server `.env`:**

```env
AUTOVIZ_FRONTEND_URL=https://autoviz.duckdns.org
AUTOVIZ_API_PUBLIC_URL=https://autoviz.duckdns.org
AUTOVIZ_CORS_ORIGINS=https://autoviz.duckdns.org
AUTOVIZ_EXPOSE_RESET_TOKENS=false
```

Do not hardcode duckdns URLs in source. Google treats `localhost` and `127.0.0.1` as different hosts — the redirect URI must match the env value character-for-character.

---

## Database

### Option A — system Postgres (port `5432`)

Create database `autoviz` in pgAdmin (or `createdb -U postgres autoviz`), set `DATABASE_URL` as above, then migrate:

```bash
cd backend
uv sync
uv run alembic upgrade head
```

### Option B — Docker Compose Postgres (host port `5434`)

```bash
docker compose -f backend/docker-compose.yml up -d db
cd backend
uv sync
uv run alembic upgrade head
```

---

## Backend

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn autoviz.api.main:app --reload --host 0.0.0.0 --port 8000
```

API: `http://localhost:8000`  
Docs: `http://localhost:8000/docs`

### Backend + database with Docker

```bash
cp backend/.env.example backend/.env
# edit backend/.env (set DATABASE_URL / OPENAI_API_KEY or GOOGLE_API_KEY as needed)
docker compose -f backend/docker-compose.yml up --build
```

This starts Postgres (host `5434`) and the API on port `8000` (migrations run on container start). The API container connects to the DB at `db:5432` on the Compose network.

---

## Frontend

```bash
cd frontend
cp .env.example .env   # VITE_API_BASE_URL=http://127.0.0.1:8000
npm install
npm run dev
```

App: `http://localhost:5173`

Production build:

```bash
cd frontend
npm run build
npm run preview
```

Tests (Node's built-in runner; no extra dependency):

```bash
cd frontend
npm test
```

---

## Typical local workflow

```bash
# 1. Env
cp backend/.env.example backend/.env
# set DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/autoviz
# set AUTOVIZ_CORS_ORIGINS and OPENAI_API_KEY (or GOOGLE_API_KEY) as needed

# 2. Database — create `autoviz` in pgAdmin (port 5432), then migrate
cd backend && uv sync && uv run alembic upgrade head

# 3. Backend
uv run uvicorn autoviz.api.main:app --reload --port 8000

# 4. Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

---

## Optional: agent playground

Lightweight HTML harness for exercising auth, CSV upload, and agent chat against the live API:

```bash
# backend already running on :8000
cd agent-playground
python -m http.server 3000
```

Open `http://localhost:3000`. Ensure `AUTOVIZ_CORS_ORIGINS` includes `http://localhost:3000`.

Sample CSVs are under `test-data/`.

---

## Repository layout

```
AutoViz-Visualizer/
├── frontend/           # React + TypeScript board UI
├── backend/            # FastAPI, agent, MCP, Alembic, Docker
├── agent-playground/   # Dev-only agent test page
├── test-data/          # Sample CSV datasets
└── docs/               # Project work plan and team docs
```

## Documentation

Team work plan (Route-IQ-style split): start at [`docs/README.md`](./docs/README.md).

| Quick link | Description |
| --- | --- |
| [Project overview](./docs/project-overview.md) | What AutoViz AI is |
| [Problem and scope](./docs/problem-and-scope.md) | P0 / P1 / P2 boundaries |
| [Roadmap](./docs/project-roadmap.md) | Weeks 1–4 milestone + 14-week plan |
| [Team responsibilities](./docs/team-responsibilities.md) | Ownership map |
| [Team briefs](./docs/team/) | Per-member deliverables |
| [API contracts](./docs/api-contracts.md) | Shared HTTP / schema freeze checklist |
| [MCP tools](./docs/mcp-tools.md) | Typed tool responsibilities |
| [Integration plan](./docs/integration-plan.md) | Contracts → mocks → vertical slices |