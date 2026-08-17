<div align="center">

<img src="docs/images/banner.svg" alt="AutoViz AI — ask a question in plain English, get a chart you can trust" width="100%">

### Upload a spreadsheet. Ask a question. Get a chart.

**No formulas. No SQL. No chart menus.**
And every number on screen can be traced back to the query that produced it.

[![Live demo](https://img.shields.io/badge/demo-autoviz.duckdns.org-2a78d6?style=flat-square)](https://autoviz.duckdns.org)
[![Tests](https://img.shields.io/badge/tests-864%20backend%20%C2%B7%2035%20frontend-1baf7a?style=flat-square)](#-how-we-know-it-works)
[![Charts](https://img.shields.io/badge/charts-10%20types-eda100?style=flat-square)](#what-it-can-draw)
[![MCP](https://img.shields.io/badge/MCP-connect%20Claude%20or%20Gemini-8b5cf6?style=flat-square)](#-plug-it-into-claude-or-gemini)
[![Python](https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![React](https://img.shields.io/badge/react-19-61dafb?style=flat-square&logo=react&logoColor=white)](https://react.dev/)

[**Try it**](https://autoviz.duckdns.org) · [What it does](#-what-it-actually-does) · [Run it locally](#-run-it-yourself) · [How it works](#-how-it-works) · [Docs](docs/README.md)

</div>

---

## 🎬 See it in one loop

<div align="center">

<img src="docs/images/demo.gif" alt="Uploading a CSV, asking a question, and getting a chart on the dashboard" width="90%">

*Upload → ask → chart → dashboard. That's the whole product.*

</div>

---

## 🤔 What it actually does

You have a spreadsheet. You have a question about it. Between those two things
normally sits a pivot table, a tutorial, and forty minutes.

AutoViz removes the middle part:

<table>
<tr>
<td width="50%" valign="top">

**You type**

> *"Which day brings in the most revenue?"*

> *"Show survival rate by class and sex"*

> *"How did rainfall change over the years?"*

</td>
<td width="50%" valign="top">

**You get**

✅ A chart, with the right type chosen for you
✅ The actual numbers, computed — not guessed
✅ A note if the data had problems
✅ The exact SQL, if you want to check

</td>
</tr>
</table>

Then drag it onto a dashboard, resize it, restyle it, save it, and export the
whole board as an image or PDF.

<img src="docs/images/chat-to-chart.png" alt="The chat panel beside a finished chart" width="100%">

---

## ✨ The bit that makes it different

Most "AI + data" tools let the model write code and run it. That is fast, and it
is how you get a confident answer that happens to be wrong.

> ### 🔒 Here, the AI never touches your numbers.
>
> It reads only the **column names and types** — never the values. It writes a
> **plan**, not code. The plan is checked against a fixed list of allowed
> operations, then a real database engine computes the answer.
>
> **The AI decides what to ask. It does not decide what the answer is.**

Which means a few things you can actually rely on:

| | |
|---|---|
| 🧾 **Every number is traceable** | Each result carries the SQL that produced it |
| 🚫 **It can't invent a column** | Anything outside the allowed list is rejected before it runs |
| 🙋 **It asks when unsure** | *"Show me the best ones"* → *"Best by what measure?"* rather than a guess |
| ⛔ **It says no** | Ask it to forecast next year and it tells you it can't, instead of quietly showing you last year |
| 📢 **It owns up** | If it filled in missing values to answer you, the answer says so |

---

## 🧹 It reads messy files too

Real spreadsheets are messy. AutoViz looks before it calculates, fixes what is
safe to fix silently, and **asks about anything that would change your answer**.

<table>
<tr><th align="left">What it finds</th><th align="left">What it does</th></tr>
<tr><td>Extra spaces, blank-looking cells, <code>USA</code> vs <code>usa</code></td><td>Fixes it quietly — can't change a result</td></tr>
<tr><td><code>$1,240.50</code> stored as text</td><td>Reads it as a number, or refuses if it isn't sure</td></tr>
<tr><td>Missing values in a column you're grouping by</td><td><b>Asks you</b>, with the exact row count</td></tr>
<tr><td>A step that would drop 40% of your rows</td><td><b>Stops and asks permission</b></td></tr>
<tr><td>One huge outlier flattening the chart</td><td>Rescales the axis <i>and tells you it did</i></td></tr>
</table>

It reads **8 file types** — `.csv` `.tsv` `.txt` `.xlsx` `.xlsm` `.parquet` `.json` `.jsonl` —
and works out the delimiter, the encoding and the date format on its own.

---

## What it can draw

Ten chart types, picked for you based on the question you asked:

📊 Bar · 📈 Line · 🔵 Scatter · 🥧 Pie · 🍩 Donut · 🏔️ Area · 📶 Histogram · 🔥 Heatmap · 📦 Box plot · 📊 Grouped bar

<img src="docs/images/dashboard.png" alt="Several charts arranged on a dashboard" width="100%">

Drag them around, resize them, change colours and titles, save the layout, and
come back to it tomorrow. Export as **PNG** or **PDF**.

---

## 🔌 Plug it into Claude or Gemini

This is the part we're proudest of.

AutoViz can hand its tools to **another** AI assistant. Generate a link in
**Settings → Connections**, paste it into Claude Desktop or Gemini, and that
assistant can now analyse *your* data — while AutoViz still does every
calculation and still guarantees every number.

```
Settings → Connections → Generate link
   ↓
https://autoviz.duckdns.org/c/••••••••/mcp
   ↓
Paste into Claude, Gemini CLI, or any MCP host
```

<img src="docs/images/connections.png" alt="The Connections settings page with a generated link" width="100%">

Links are **shown once**, can be **revoked any time**, and only ever reach *your*
datasets — never anyone else's.

> Built on the [Model Context Protocol](https://modelcontextprotocol.io/), so it
> works with any host that speaks it, not just one vendor.

---

## 🚀 Run it yourself

**You'll need:** [Node 20+](https://nodejs.org/), [uv](https://docs.astral.sh/uv/) (Python 3.11+), and PostgreSQL.

```bash
git clone https://github.com/Group-5-UOM/AutoViz-Visualizer.git
cd AutoViz-Visualizer

# 1 — settings
cp backend/.env.example backend/.env      # then set DATABASE_URL + a planner API key

# 2 — backend
cd backend && uv sync && uv run alembic upgrade head
uv run uvicorn autoviz.api.main:app --reload --port 8000

# 3 — frontend (new terminal)
cd frontend && npm install && npm run dev
```

Open **http://localhost:5173** and upload something from [`test-data/`](test-data/).

<details>
<summary><b>⚙️ Full configuration — API keys, OAuth, Docker, ports</b></summary>

<br>

### Ports

| Service | Port |
|---|---|
| Frontend (Vite) | `5173` |
| Backend API | `8000` |
| Postgres (system) | `5432` |
| Postgres (Docker Compose) | `5434` |

### The settings that matter

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection string |
| `SECRET_KEY` | Auth / token secret |
| `AUTOVIZ_CORS_ORIGINS` | Allowed frontend origins, comma-separated |
| `GOOGLE_API_KEY` | Gemini planner (the default) |
| `OPENAI_API_KEY` | Use with `AUTOVIZ_PLANNER_MODEL=openai:gpt-4o-mini` |
| `AUTOVIZ_PLANNER_MODEL` | e.g. `google_genai:gemini-3.5-flash` |
| `AUTOVIZ_FRONTEND_URL` | Frontend origin — local `http://localhost:5173` |
| `AUTOVIZ_API_PUBLIC_URL` | Backend public URL — local `http://127.0.0.1:8000` |
| `AUTOVIZ_REMOTE_MCP` | `1` to enable connection links (off by default) |

Example for local Postgres:

```env
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/autoviz
SECRET_KEY=dev-secret-change-in-production
AUTOVIZ_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
GOOGLE_API_KEY=your-key-here
AUTOVIZ_FRONTEND_URL=http://localhost:5173
AUTOVIZ_API_PUBLIC_URL=http://127.0.0.1:8000
```

### Sign in with Google / GitHub

Register **both** local and hosted callbacks so one OAuth app covers both.

| Provider | Setting | Local | Hosted |
|---|---|---|---|
| GitHub | Callback URL | `http://127.0.0.1:8000/auth/oauth/github/callback` | `https://autoviz.duckdns.org/api/auth/oauth/github/callback` |
| Google | JavaScript origins | `http://localhost:5173` | `https://autoviz.duckdns.org` |
| Google | Redirect URIs | `http://127.0.0.1:8000/auth/oauth/google/callback` | `https://autoviz.duckdns.org/api/auth/oauth/google/callback` |

> ⚠️ Google treats `localhost` and `127.0.0.1` as different hosts, and compares
> redirect URIs character-for-character. The hosted callback includes `/api`
> because nginx strips that prefix before the backend sees it.

### Everything in Docker

```bash
cp backend/.env.example backend/.env
docker compose -f backend/docker-compose.yml up --build
```

Postgres on host `5434`, API on `8000`, migrations run at container start.

### Tests

```bash
cd backend  && uv run pytest tests/ -q     # 864
cd frontend && npm test                    # 35
cd frontend && npm run verify:specs        # renders all 14 chart specs for real
```

</details>

---

## 🏗 How it works

```mermaid
flowchart LR
    A["🙋 You ask<br/>a question"] --> B["🧠 AI writes<br/>a plan"]
    B --> C{"🛡️ Checked<br/>against the<br/>allowed list"}
    C -->|"looks wrong"| B
    C -->|"ok"| D["⚙️ Database<br/>computes it"]
    D --> E["📊 Chart<br/>+ the SQL"]

    style A fill:#e8f1fd,stroke:#2a78d6,color:#0f172a
    style B fill:#f3e8ff,stroke:#8b5cf6,color:#0f172a
    style C fill:#fff4e0,stroke:#eda100,color:#0f172a
    style D fill:#e6f8f1,stroke:#1baf7a,color:#0f172a
    style E fill:#e8f1fd,stroke:#2a78d6,color:#0f172a
```

The AI only ever occupies the purple box. Everything that touches your actual
data is ordinary, testable, deterministic code — which is why the same question
gives the same answer every time.

<details>
<summary><b>🔬 The engineering underneath</b></summary>

<br>

| Layer | Built with |
|---|---|
| Frontend | React 19, TypeScript, Vite, Vega-Lite |
| Backend | FastAPI, Pandas, DuckDB |
| Agent | LangGraph, Gemini (swappable) |
| Tool access | Model Context Protocol — 18 tools |
| Database | PostgreSQL |
| Deployment | Docker → ECR → CodeDeploy → EC2, nginx + TLS |

**The plan is a closed grammar.** 11 filter operations, 7 aggregations, 15 derive
functions, 14 cleaning operations, 10 chart types. Written as `Literal` types, so
an invalid plan can't even be constructed — not "caught later", *impossible to
build*. Identifiers are quoted and values are bound as parameters, so there is no
path from model output to raw SQL.

**Your spreadsheet is untrusted input.** Cell contents and column names are
neutralised before they reach a prompt, because a CSV is a place someone can hide
instructions.

**Resource limits are real.** 50 MiB per upload, 100,000 rows per result, a 30
second query timeout and a memory ceiling — all enforced, all tested.

</details>

---

## 📈 How we know it works

Not vibes — measurements. Full write-up in
[**Docs/24 — Performance and Evaluation**](docs/24-Performance-and-Evaluation.md).

<div align="center">

| | |
|:--|:--|
| ⚡ **Question → chart on 1,000,000 rows** | **68–78 ms** |
| 📉 **1000× more data costs** | **2.3× more time** |
| 🎯 **Understood the question** | **39 / 39** on a frozen benchmark |
| ❌ **Confidently wrong answers** | **0** |
| 📊 **Chart specs valid** | **10 / 10** against the real Vega-Lite schema |
| 🧪 **Tests** | **864** backend · **35** frontend |

</div>

Building that benchmark found **eight real bugs** that the passing test suite had
missed — including a query operator we advertised and had never implemented. All
eight are fixed, each with a regression test.

---

## 📚 Documentation

| Start here | What's in it |
|---|---|
| [📋 Project status](docs/21-Project-Status.md) | Where everything actually stands |
| [📊 Performance & evaluation](docs/24-Performance-and-Evaluation.md) | Every number above, and how it was measured |
| [🏛 System architecture](docs/09-System-Architecture.md) | The five layers, and the rule they all serve |
| [🔌 Remote MCP access](docs/26-Remote-MCP-Access.md) | Connecting Claude or Gemini |
| [🧹 Data cleaning](docs/14-Disclosure-and-Outlier-Handling.md) | What it fixes, and what it tells you |
| [📖 All documents](docs/README.md) | The full index |

---

## 👥 The team

**Group 5 · Project P09** — Data Science and Engineering Project (CS3501)
Department of Computer Science and Engineering, **University of Moratuwa**

| | Who | What they built |
|---|---|---|
| 🧠 | **K.S.H. Daishika** · 230112C | LLM orchestration, MCP, system integration |
| 🎨 | **J.M.T.D. Chandrasiri** · 230101R | Frontend, visualisation, dashboard canvas |
| ⚙️ | **D.W.K.G. Bulagala** · 230094U | Data engine, profiling, backend services |

Mentor: Dr. Chathuranga Hettiaracchi · TA: Shaveen Silva

<div align="center">

---

**[⬆ back to top](#)**

*Built at the University of Moratuwa · 2026*

</div>
