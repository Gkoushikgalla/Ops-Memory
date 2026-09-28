# OpsMemory

**On-call incident assistant that remembers every production incident your team has resolved.**

When a new incident fires, OpsMemory recalls similar past incidents from [Hindsight](https://github.com/vectorize-io/hindsight) memory and uses an LLM to produce a diagnosis grounded in what actually worked before. When the incident is resolved, the resolution is retained back into memory — so the agent gets better over time.

---

## Features

- **Memory-informed diagnosis** — recalls the top 3 semantically similar past incidents before generating a fix recommendation
- **Memory ON / OFF toggle** — compare generic vs. memory-informed diagnosis side-by-side
- **Visible recall panel** — see exactly which past incidents were retrieved and why
- **Learning loop** — every resolved incident is retained, making future diagnoses more accurate
- **40 seed incidents** — realistic synthetic data across 6 services and 8 failure patterns
- **Groq LLM** — fast inference using `openai/gpt-oss-120b` with `qwen/qwen3-32b` fallback
- **Three-panel UI** — incident form, diagnosis, and recalled memories all visible simultaneously

---

## Architecture

```
Browser ──▶ FastAPI ──▶ Agent ──▶ Hindsight Memory (recall / retain)
                              └──▶ Groq LLM (diagnose)
                              └──▶ MongoDB (store incidents)
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full diagram and data flows.

---

## Prerequisites

- Python 3.11+
- Docker Desktop (for MongoDB)
- A [Hindsight Cloud](https://ui.hindsight.vectorize.io/signup) account (free tier available)
- A [Groq](https://console.groq.com/) API key

---

## Setup

### 1. Start MongoDB

```bash
docker compose up -d
```

### 2. Create a Python virtual environment

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your keys:

```env
GROQ_API_KEY=gsk_...
GROQ_MODEL=openai/gpt-oss-120b
GROQ_FALLBACK_MODEL=qwen/qwen3-32b
HINDSIGHT_API_KEY=...
HINDSIGHT_BASE_URL=https://api.hindsight.vectorize.io
HINDSIGHT_BANK_ID=opsmemory-prod
MONGO_URI=mongodb://localhost:27017
MONGO_DB=opsmemory
```

### 5. Generate synthetic seed incidents

```bash
python data/generate_incidents.py
```

This creates `data/incidents_seed.json` with 40 realistic resolved incidents.

### 6. Seed MongoDB and Hindsight memory

```bash
python scripts/seed_memory.py
```

This loads all 40 incidents into MongoDB and retains each one into Hindsight memory.

### 7. Start the server

```bash
uvicorn app.main:app --reload
```

Open **http://localhost:8000** in your browser.

---

## Running Tests

```bash
pytest tests/ -v
```

Tests mock Hindsight and Groq — no real API calls needed.

---

## Demo

See [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) for a step-by-step walkthrough of the three-incident demo:

1. **Demo A** (payments-api pool exhaustion) — run with Memory OFF to see generic diagnosis
2. **Demo A** — run with Memory ON to see memory-informed diagnosis citing past incidents
3. Resolve Demo A → memory grows
4. **Demo C** (order-service, similar pattern) — see it now cites both seeded incidents and the just-resolved Demo A

---

## Documentation

| File | Description |
|------|-------------|
| [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) | Problem, solution, business case, features |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Component diagram, data flows |
| [docs/HINDSIGHT_USAGE.md](docs/HINDSIGHT_USAGE.md) | Where and how Hindsight is used |
| [docs/API.md](docs/API.md) | All API endpoints with request/response examples |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | Click-by-click demo walkthrough |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | MongoDB schema and seed data rules |

---

## Hindsight

OpsMemory is built on **Hindsight** — a state-of-the-art agent memory system.

- GitHub: [https://github.com/vectorize-io/hindsight](https://github.com/vectorize-io/hindsight)
- Docs: [https://hindsight.vectorize.io](https://hindsight.vectorize.io)
- Cloud: [https://ui.hindsight.vectorize.io](https://ui.hindsight.vectorize.io)

---

## Reset Demo

To wipe all data and start fresh:

```bash
python scripts/reset_memory.py
python data/generate_incidents.py
python scripts/seed_memory.py
```

Or use the **"↺ Reset Demo"** button in the top bar of the UI.
