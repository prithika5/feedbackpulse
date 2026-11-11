# FeedbackPulse

**Understand why your ratings change, in seconds.**

FeedbackPulse is an AI product-feedback analyst. It reads thousands of app reviews, groups them into
themes, connects those themes to ratings and app versions, and answers questions like
*"Why did ratings drop after version 8.8.18.509?"* with numbers from SQL and citations to real reviews.

It currently runs on 83,716 public Google Play reviews of Spotify, from September 2018 to May 2024.

## Try it

The API is live on Cloud Run:

```bash
curl -N -X POST https://feedbackpulse-api-cjk3yvcpja-uc.a.run.app/ask \
  -H 'content-type: application/json' \
  -d '{"question": "What do 1-star reviewers complain about?"}'
```

## What it does

### Review pipeline
Run with `python -m pipeline run --app spotify`. Re-running is safe at every stage.

- **Ingest:** normalizes the raw dataset to one schema and never loads reviewer names.
- **Clean:** scrubs emails, URLs, and phone numbers, removes short, duplicate, and non-English reviews, and
  reports how many rows each rule removed.
- **Derive releases:** finds each version's first-seen date and flags versions with under 50 reviews.
- **Load to BigQuery:** uses free batch load jobs, and creates daily rating and theme views.
- **Embed:** creates 384-dimension vectors locally with `all-MiniLM-L6-v2`, embedding each review only once.
- **Index for search:** stores vectors in Postgres with pgvector and an HNSW cosine index.
- **Discover themes:** clusters reviews with UMAP and HDBSCAN, then merges overlapping clusters.
- **Label themes:** Gemini names each theme from its most typical reviews. Output is validated with Pydantic,
  rejected labels are retried with the reason, and answers are cached.

### The Analyst (`POST /ask`)
A Gemini function-calling loop chooses from three typed tools, and streams its work over server-sent events.

| Tool | What it does |
|---|---|
| `run_sql` | Runs read-only SQL on BigQuery for counts, averages, and rankings |
| `search_reviews` | Finds reviews by meaning, filtered by version, rating, or date |
| `get_theme_trends` | Compares each theme's share of reviews between two releases |

- **Streaming events:** `tool_call`, `tool_result`, `chart`, `citation`, `answer_delta`, `done`, and `error`.
  Each answer shows the exact SQL and reviews behind it. Charts are returned as JSON specifications.
- **Grounded answers:** numbers come from tool results, and sentiment claims cite retrieved reviews.
  Citations to reviews that were never retrieved are removed in code.
- **Honest refusals:** questions the data can't answer, such as revenue or dates after May 2024, are declined.

### Safety and reliability
- **SQL guard:** parses each query, allows only a single `SELECT` on allowlisted tables, caps rows at 1,000, and
  uses a BigQuery dry run to reject queries over a byte limit.
- **Least privilege:** the API runs as a read-only BigQuery service account, with secrets in Secret Manager.
- **Abuse and quota protection:** per-IP rate limit, daily question cap, repeated-question cache, timeouts on
  external calls, retries with backoff, and a clear message when the free-tier quota runs out.
- **Observability:** structured JSON logs record latency, tools used, and tokens for each question.

### Evals
`python -m evals run <api_url>` runs 19 questions across numeric, trend, release comparison, theme explanation,
and refusal categories. Expected answers are computed with SQL at eval time.

## Results

All numbers are measured. Sources are in [RESUME_METRICS.md](RESUME_METRICS.md).

| Metric | Result |
|---|---|
| Reviews ingested / kept after cleaning | 84,165 / 83,716 |
| App versions | 441 |
| Themes | 16 plus "Other", covering 95.1% of reviews with a specific theme |
| Filtered vector search | about 75 ms |
| Eval, first run | 18/19 |
| Eval, after fixing the citation bug it found | 19/19 |
| Tool selection | 15/15 scored questions |
| Latency on Cloud Run, p50 / p95 | 13.61 s / 27.66 s |
| Automated tests | 114 passing |

The eval is small and was written for this project, and the fix was tested on the same questions, so 19/19 is
not an independent measure. See [the full report](evals/REPORT.md).

## Architecture

```
Dataset ─► ingest ─► clean ─► releases ─► embed ─► cluster ─► label themes
                       │                    │                     │
                       ▼                    ▼                     ▼
                   BigQuery ◄────── Postgres + pgvector ◄─────────┘
                       ▲                    ▲
                       │  read-only SQL     │  vector search
                       └───── FastAPI "Analyst" on Cloud Run ──► streamed answers
```

- **BigQuery** handles SQL analytics, and **pgvector** handles similarity search next to its metadata.
- **Embeddings run locally**, so they're free and reproducible. The API uses `fastembed` to run the same model
  without PyTorch, which keeps the image small. Its vectors matched the stored ones on a 200-review check.
- **The LLM is used only where it adds value:** naming themes, choosing tools, and writing answers. Clustering
  and math run in code, so they're cheap, deterministic, and testable.

## Run it yourself

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,embed]" -r api/requirements.txt
cp .env.example .env               # fill in Google Cloud, Supabase, and Gemini values
./scripts/download_data.sh         # download the dataset and verify its checksum
python -m pipeline run --app spotify
uvicorn api.main:app --reload      # start the API locally
pytest                             # run the tests
./infra/deploy.sh                  # deploy the API to Cloud Run
```

## Data

Built on a public Spotify reviews dataset. Source, license, and limitations are in
[DATA_SOURCES.md](DATA_SOURCES.md). Reviews are unevenly spread over time, and ratings describe this sample rather
than Spotify's store rating.
