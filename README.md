# FeedbackPulse

**Understand why your ratings change, in seconds.**

FeedbackPulse is an AI product-feedback analyst. It reads thousands of app reviews, groups them into
themes, connects those themes to ratings, app versions, and release dates, and answers questions like
*"Why did our rating drop after v2.3?"* with charts and cited reviews.

> 🚧 Work in progress. Screenshots, architecture diagram, real metrics, and a demo will be added as the
> project is built.

## Stack (planned)
- **Pipeline:** Python, sentence-transformers (local embeddings), UMAP + HDBSCAN, Gemini for theme labels
- **Data:** BigQuery (structured analytics) + Supabase Postgres/pgvector (review embeddings)
- **API:** FastAPI on Cloud Run with a tool-calling LLM "Analyst"
- **Web:** Next.js + TypeScript + Tailwind + shadcn/ui

## Local setup
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # then fill in values
ruff check .
```

## Data
Built on a public reviews dataset. See [DATA_SOURCES.md](DATA_SOURCES.md).
