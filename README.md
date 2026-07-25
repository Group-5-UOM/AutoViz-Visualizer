# AutoViz AI

AutoViz AI is a web-based conversational data visualization and dashboard-building platform (University of Moratuwa CS3501 Data Science and Engineering Project).

Registered users upload a structured CSV, ask analytical questions in natural language, and receive validated chart recommendations rendered with Vega-Lite. Charts can be arranged on an interactive dashboard (move, resize, edit), saved and reopened, and exported as image or PDF.

| Layer | Stack |
| --- | --- |
| Frontend | React, TypeScript, Vite, Vega-Lite |
| Backend | FastAPI, Pandas / DuckDB, LangGraph agent |
| Database | PostgreSQL |
| Charts | Vega-Lite |

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
cd DSEP
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
| `GOOGLE_API_KEY` | Planner LLM (agent routes) |

For local Postgres via Docker Compose (see below):

```env
DATABASE_URL=postgresql://autoviz:autoviz@localhost:5432/autoviz
SECRET_KEY=autoviz-dev-secret-key-change-in-production
AUTOVIZ_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000
GOOGLE_API_KEY=your-key-here
```

---

## Database

Start PostgreSQL only:

```bash
docker compose -f backend/docker-compose.yml up -d db
```

Apply migrations (from a local backend install):

```bash
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
# edit backend/.env (set GOOGLE_API_KEY if needed)
docker compose -f backend/docker-compose.yml up --build
```

This starts Postgres and the API on port `8000` (migrations run on container start).

---

## Frontend

```bash
cd frontend
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

---

## Typical local workflow

```bash
# 1. Env
cp backend/.env.example backend/.env

# 2. Database
docker compose -f backend/docker-compose.yml up -d db

# 3. Backend
cd backend && uv sync && uv run alembic upgrade head
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
DSEP/
├── frontend/           # React + TypeScript board UI
├── backend/            # FastAPI, agent, MCP, Alembic, Docker
├── agent-playground/   # Dev-only agent test page
└── test-data/          # Sample CSV datasets
```
