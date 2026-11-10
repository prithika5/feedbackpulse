# CLAUDE.md — FeedbackPulse

> An AI product-feedback analyst. It reads thousands of app reviews, finds the themes inside them,
> connects those themes to ratings, app versions, and release dates, and answers questions like
> **"Why did our rating drop after v2.3?"** with charts and cited reviews.

You (Claude Code) are helping **Prithika**, a CS student, build this solo. She will present it to recruiters
at companies like Amazon and Workday and in Forward Deployed Engineer interviews. Two things matter equally:

1. **The product must look and feel polished**, like a real B2B SaaS tool and not a hackathon demo.
2. **Prithika must understand every part.** After each step, explain what you built, *why* you made each
   design choice, and what an interviewer might ask about it (see "Teach-back" in the checkpoint format).

---

## 0. Ground rules (read first, follow always)

- **FREE ONLY.** Use only free tiers and free trial credits. Never create resources that bill by the hour
  when idle. Specifically **do not use**: Vertex AI Vector Search (charges per deployed index hour), Cloud SQL,
  GKE, Compute Engine VMs beyond the free e2-micro, BigQuery streaming inserts, or GPUs. If a step seems to need
  a paid service, **stop and ask** before doing anything.
- **Never commit secrets.** `.env`, `.env.local`, service-account JSON keys, and API keys stay out of git.
  Add them to `.gitignore` in step 1. Use `.env.example` with placeholder values.
- **Never scrape websites.** Use a public dataset with a license that allows this use (see §3).
- **Never invent numbers.** All metrics in the UI, README, and evals must come from real queries on real data.
- **One step at a time.** Finish a step, run it, show results, write the checkpoint, then **wait for Prithika's
  "go"** before starting the next step.
- **Prefer simple, readable code** over clever code. Add short comments explaining *why*, not *what*.
- **Do not hardcode model names.** Read them from env vars (`GEMINI_MODEL`, `EMBEDDING_MODEL`). Before step 6,
  check which Gemini models are currently available on the free tier and suggest a value.

---

## 1. Human setup checklist (Prithika does these; Claude Code guides)

These need a human because they involve accounts, billing, or logins:

1. Create a Google Cloud project named `feedbackpulse`. Link billing (needed for Cloud Run), then **immediately
   create a budget alert at $1** with email notifications. New accounts get free trial credits; we still aim for $0.
2. Install and log in to the `gcloud` CLI: `gcloud auth login` and `gcloud auth application-default login`.
3. Enable APIs: BigQuery, Cloud Run, Cloud Build, Artifact Registry, Cloud Scheduler, Secret Manager.
4. Create a free Supabase project (for Postgres + pgvector). Copy the connection string.
5. Create a Gemini API key in Google AI Studio (free tier).
6. Create a GitHub repo `feedbackpulse` (public, so recruiters can see it).

Claude Code: when a step needs one of these, tell Prithika exactly what to click or run, then verify it worked
(e.g., `gcloud config list`, `bq ls`).

---

## 2. Architecture

```
            ┌──────────────────────── Offline / scheduled pipeline (Python) ────────────────────────┐
 Dataset ──►│ ingest → clean → derive releases → embed → cluster → LLM-label themes → load         │
 (CSV)      └───────────────┬─────────────────────────────────────────────┬───────────────────────────┘
                            ▼                                             ▼
                 BigQuery (structured)                         Supabase Postgres + pgvector
                 reviews, releases, themes,                    review embeddings (+ metadata)
                 review_themes, daily metrics                  HNSW index for similarity search
                            ▲                                             ▲
                            │ read-only SQL (guarded)                     │ vector search
                     ┌──────┴─────────────────────────────────────────────┴──────┐
                     │        FastAPI backend on Cloud Run ("the Analyst")       │
                     │  LLM router (Gemini function calling) chooses tools:      │
                     │   • run_sql  • search_reviews  • get_theme_trends         │
                     │  → streams answer + charts + citations (SSE)              │
                     └──────────────────────────┬────────────────────────────────┘
                                                ▼
                     Next.js frontend on Cloud Run (polished dashboard + Ask)
```

**Why this design (Prithika should be able to say this in an interview):**
- **BigQuery** for structured data: SQL analytics over ratings/versions/dates, free 1 TB of queries per month,
  and it's what enterprises actually use for analytics.
- **pgvector** for embeddings: free on Supabase, standard Postgres, and cheaper than a managed vector service at
  this scale. Trade-off: fine for up to a few million vectors, but a dedicated vector DB would scale further.
- **Local embeddings** (`sentence-transformers`): free, unlimited, and reproducible. Each review is embedded once.
- **LLM only where it adds value**: labeling themes, routing questions, and writing answers. Clustering and math
  are done in code (cheaper, deterministic, testable).
- **Tools instead of free-form SQL generation**: the LLM calls a small set of safe, typed tools. This keeps
  answers grounded and prevents dangerous queries.

---

## 3. Data

**Find a dataset first (step 2).** Requirements:
- Public on **Kaggle or Hugging Face**, with a license that allows non-commercial/educational use.
  Record the dataset name, URL, and license in `DATA_SOURCES.md`.
- Columns (or equivalents): review text, star rating (1–5), review date, **app version** (critical; Google Play
  review datasets often have a `reviewCreatedVersion` or `appVersion` field), app name, optional thumbs-up count.
- At least **20,000 reviews** across 1–5 apps, spanning several versions.

If no good dataset has app versions, stop and discuss options with Prithika. Do **not** fabricate versions
silently. A clearly labeled fallback is to derive "release windows" from dates.

**BigQuery dataset `feedbackpulse`:**

| Table | Columns |
|---|---|
| `apps` | app_id, name, category, review_count |
| `reviews` | review_id, app_id, rating, text, review_date, app_version, thumbs_up, text_len |
| `releases` | app_id, version, first_seen_date, review_count (derived from first appearance of each version) |
| `themes` | theme_id, app_id, name, description, sentiment (neg/neutral/pos), keywords, created_at |
| `review_themes` | review_id, theme_id, distance |
| `daily_metrics` (view) | app_id, date, avg_rating, review_count, pct_negative |
| `theme_daily` (view) | app_id, theme_id, date, review_count, avg_rating |

**Postgres (Supabase) table `review_embeddings`:**
review_id (PK), app_id, embedding `vector(384)` (or the model's dimension), rating, review_date, app_version,
theme_id, snippet (first 300 chars). Add an **HNSW index** on `embedding` (cosine) and B-tree indexes on
`app_id`, `app_version`, `review_date` so vector search can be filtered.

Load into BigQuery with **batch load jobs** (from Parquet/CSV in Cloud Storage or local files), never streaming
inserts.

---

## 4. Tech stack

**Backend / pipeline (Python 3.11+)**
- `uv` or `pip` + `pyproject.toml`; `ruff` for lint/format; `pytest` for tests
- FastAPI + Pydantic v2; `sse-starlette` for streaming
- `google-cloud-bigquery`, `psycopg` + `pgvector`, `sentence-transformers`
- Clustering: `umap-learn` + `hdbscan` (fallback: `scikit-learn` KMeans with silhouette-based k)
- LLM: `google-genai` SDK, model from `GEMINI_MODEL`; structured outputs validated with Pydantic
- Simple on-disk/in-memory cache for LLM calls (hash of prompt → response) to respect free-tier rate limits

**Frontend**
- Next.js (App Router) + TypeScript + Tailwind CSS + shadcn/ui
- Charts: Recharts (or Tremor, if it gives a cleaner result)
- Motion: Framer Motion (subtle only); icons: lucide-react; font: Geist or Inter
- Data fetching: TanStack Query; command palette: `cmdk`

**Cloud (GCP)**
- Cloud Run: `api` service and `web` service (scale to zero, so no idle cost)
- Cloud Run Job + Cloud Scheduler: nightly incremental pipeline run
- Artifact Registry for images; Cloud Build or GitHub Actions for CI/CD
- Secret Manager for `GEMINI_API_KEY` and `DATABASE_URL`
- Cloud Logging: structured JSON logs with latency, tool calls, and token counts per question

**Env vars** (`.env.example`): `GCP_PROJECT_ID`, `BQ_DATASET=feedbackpulse`, `DATABASE_URL`, `GEMINI_API_KEY`,
`GEMINI_MODEL`, `EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2`, `API_BASE_URL`, `DEMO_MODE=true`

---

## 5. The pipeline (`pipeline/`)

Run as `python -m pipeline run --app <app_id|all> [--incremental]`. Every stage is **idempotent** (safe to re-run)
and logs counts.

1. **Ingest**: read raw dataset, normalize column names and types.
2. **Clean**: drop empty/very short text, remove exact duplicates, keep English, and **scrub PII**
   (emails, phone numbers, URLs) with regex. Log how many rows each rule removed.
3. **Derive releases**: first-seen date per (app, version); flag versions with too few reviews.
4. **Embed**: batch-encode text locally; store vectors in pgvector.
5. **Cluster** (per app): UMAP → HDBSCAN; mark noise as "Other"; target roughly 8–25 themes per app.
6. **Label themes**: for each cluster, send ~20 representative reviews (closest to centroid) to Gemini and get
   JSON back: `{name (2–4 words), description (1 sentence), sentiment, keywords[]}`. Validate with Pydantic and
   cache by cluster hash.
7. **Load**: write tables to BigQuery (batch), update `theme_id` in pgvector, refresh views.
8. **Summary report**: print totals (reviews processed, themes found, versions, time taken). Save the summary to
   `pipeline/last_run.json`. These are the real numbers for the resume later.

---

## 6. The Analyst (backend, `api/`)

**Endpoints**
- `GET /health`
- `GET /apps`: list of apps with review counts
- `GET /apps/{app_id}/overview?from&to`: KPIs, rating trend, release markers, rising/falling themes
- `GET /apps/{app_id}/themes`: themes with size, sentiment, avg rating, 30-day trend
- `GET /themes/{theme_id}`: summary, rating distribution, versions affected, representative reviews
- `GET /apps/{app_id}/releases/compare?a=<ver>&b=<ver>`: rating change and theme share diff
- `POST /ask` (SSE stream): question → streamed events: `tool_call`, `tool_result`, `chart`, `citation`,
  `answer_delta`, `done`

**LLM router with function calling.** Tools:
- `run_sql(query)`: **read-only** and guarded: must be a single `SELECT`, only on allowlisted tables/views in
  `feedbackpulse`, auto-adds `LIMIT 1000`, and uses a BigQuery **dry run** to reject queries over a byte cap.
  Use a service account with read-only BigQuery permissions.
- `search_reviews(query, app_id, version?, rating_max?, date_from?, date_to?, k=8)`: filtered vector search
  in pgvector; returns snippets with IDs.
- `get_theme_trends(app_id, version_a?, version_b?)`: precomputed theme share before/after a release.

**Answer rules (system prompt):** answer only from tool results; every claim about user sentiment cites ≥1 review
ID; numbers come only from SQL results; if data is insufficient, say so. Return a chart spec (type, title, series)
when a chart helps.

**Reliability:** timeouts on every external call, retries with backoff on 429s, cache identical questions,
a per-IP rate limit on `/ask`, and a clear error message in the UI when the free-tier quota is hit.

---

## 7. UI design spec (make it look like a real product)

**Visual direction:** calm, premium, data-dense but airy, like Linear, Vercel, or Stripe dashboards.
- Dark mode by default with a light-mode toggle. Neutral zinc/slate base, **one accent color** (indigo or
  violet), and semantic colors only for sentiment (muted red/amber/green, never neon).
- Typography: Geist or Inter; clear hierarchy (page title 24–28px, section 16–18px, body 14px); numbers use
  tabular figures.
- Layout: 8px spacing grid, `rounded-2xl` cards with 1px subtle borders and soft shadows, generous padding,
  max content width ~1280px.
- Motion: 150–250ms fades and slides; numbers count up on load; no bouncy or flashy effects.
- States: skeleton loaders for every async block, friendly empty states with an illustration or icon and a next
  action, inline error states with retry.
- Accessible: WCAG AA contrast, visible focus rings, full keyboard navigation, `aria-label`s on icon buttons,
  and charts with text summaries for screen readers.
- Responsive: looks great at 1440px and still usable at 390px (mobile).

**App shell**
- Left sidebar: logo (simple pulse/waveform mark), app switcher dropdown, nav (Overview, Themes, Releases,
  Ask, Evals), and a theme toggle at the bottom.
- Top bar: date-range picker, global search, and a **⌘K command palette** (jump to theme/version, or
  "Ask: …" to open Ask with the query).
- Subtle "Demo data: public reviews dataset" badge so it's honest about the data source.

**Pages**
1. **Overview**
   - Four KPI cards: Avg rating, Reviews, % negative, Top rising theme (each with delta vs. previous period and a
     sparkline).
   - Hero chart: rating over time (line) plus review volume (bars), with **vertical release markers** labeled
     with version numbers; hover shows a tooltip with the top theme that week.
   - "What changed" card: auto-generated 3-bullet summary of the biggest shifts, each linking to evidence.
   - Rising and falling themes lists with colored delta chips.
2. **Themes**
   - Grid of theme cards: name, sentiment dot, size, avg rating, mini trend line. Filter and sort controls.
   - Click opens a **side drawer**: LLM description, rating distribution bar, versions most affected, and
     representative review quotes with star ratings and dates.
   - Optional: a 2D "theme map" scatter (UMAP coordinates) colored by theme. This is very impressive in demos.
3. **Releases**
   - Pick version A vs. B → rating change headline, **diverging bar chart** of theme share change, and the top new
     complaints and praises with example reviews.
4. **Ask** (the centerpiece)
   - Large input with suggested questions as chips ("Why did ratings drop after v2.3?", "What do 5-star reviewers
     love?").
   - Streaming answer with a **"How I answered" trace**: step chips such as `SQL query`, `Searched 8 reviews` and
     `Compared releases` that expand to show the exact SQL and retrieved reviews.
   - Inline charts rendered from the chart spec; citations as numbered chips that show the review on hover.
   - Copy answer and "Share as report" (exports a clean markdown/PDF summary).
5. **Evals** (shows engineering rigor)
   - Table of the latest eval run: accuracy by category, router accuracy, p50/p95 latency, avg tokens per answer,
     with a run history chart.

**Landing page (`/`)**: a short hero ("Understand why your ratings change, in seconds."), an animated product
screenshot, three feature tiles, a "Try the live demo" button, and links to GitHub and the architecture diagram.

---

## 8. Evals (`evals/`)

- `evals/questions.yaml`: 40–50 questions across categories: numeric (ratings, counts), trend, release
  comparison, theme explanation, and "should refuse / insufficient data".
- **Ground truth for numeric questions is computed with SQL**, not written by hand.
- Metrics:
  - numeric accuracy (exact or within tolerance)
  - router accuracy (did it pick the right tools?)
  - citation relevance (LLM-as-judge with a written rubric, plus 20 manually checked answers)
  - theme label quality (Prithika manually labels 100 random reviews; measure agreement)
  - latency p50/p95, tokens per answer
- `python -m evals run` writes `evals/results/<timestamp>.json` and `evals/REPORT.md`; the Evals page reads the
  latest JSON.

---

## 9. Testing and quality

- pytest: SQL guard (must reject `DROP`, multiple statements, non-allowlisted tables), PII scrubber, release
  derivation, theme JSON validation, and API contract tests with mocked LLM.
- Frontend: TypeScript strict mode, ESLint, and a Playwright smoke test (load Overview, open a theme, ask a
  question in mock mode).
- GitHub Actions: lint + test on every push; deploy to Cloud Run on push to `main`.

---

## 10. Repo layout

```
feedbackpulse/
  CLAUDE.md  README.md  DATA_SOURCES.md  .env.example  .gitignore
  pipeline/   (ingest.py, clean.py, releases.py, embed.py, cluster.py, label.py, load.py, __main__.py)
  api/        (main.py, tools/, router.py, prompts.py, sql_guard.py, cache.py, schemas.py, Dockerfile)
  web/        (Next.js app: app/, components/, lib/, Dockerfile)
  evals/      (questions.yaml, run.py, judge.py, results/, REPORT.md)
  infra/      (deploy.sh, scheduler.sh, bigquery_schema.sql, pgvector_schema.sql)
  tests/
  .github/workflows/ci.yml
```

---

## 11. Build order (one person, with checkpoints)

1. **Repo scaffold**: folders, `.gitignore`, `.env.example`, pyproject, README stub, CI with lint only.
2. **Dataset**: find and evaluate 2–3 candidate datasets; Prithika picks one; document it in `DATA_SOURCES.md`;
   quick exploratory notebook (row counts, versions, rating distribution).
3. **Ingest + clean**: with tests for cleaning and PII scrub; print a removal summary.
4. **BigQuery load**: create the dataset and tables, batch load, and create views; verify with sample queries.
5. **Embeddings + pgvector**: schema, HNSW index, batch embed and insert; test a similarity query.
6. **Clustering + theme labeling**: tune clusters, label with Gemini, and review themes with Prithika for
   quality.
7. **Read APIs**: `/apps`, `/overview`, `/themes`, `/themes/{id}`, `/releases/compare`.
8. **Analyst**: tools, SQL guard, router, and streaming `/ask` with citations and chart specs.
9. **Frontend shell + design system**: layout, sidebar, theme toggle, ⌘K, and shared components.
10. **Overview + Themes pages**.
11. **Releases + Ask pages**: the "How I answered" trace and inline charts.
12. **Evals**: dataset, runner, report, and Evals page.
13. **Deploy**: Dockerfiles, Artifact Registry, Cloud Run (api + web), Secret Manager, scheduled pipeline job.
14. **Polish**: landing page, empty/error states, mobile pass, accessibility pass, performance.
15. **README + demo**: architecture diagram, screenshots/GIF, "Why these choices", real metrics from
    `last_run.json` and the eval report, and a 2-minute demo script.

---

## 12. Required checkpoint format (after every step)

```
✅ CHECKPOINT — Step N: <name>
What I built:        <2–4 bullets>
How to verify:       <exact commands to run / page to open, and what you should see>
Real numbers:        <any counts/metrics produced, or "none yet">
Teach-back:          <plain-English explanation of how it works and WHY these choices>
Interview questions: <2–3 questions an interviewer might ask about this step, with short answers>
Cost check:          <which GCP/API resources this step uses and confirmation it's within free tier>
Next step:           <what Step N+1 will do>
Waiting for your "go".
```

---

## 13. Resume tracking

Keep `RESUME_METRICS.md` updated with **only real, measured numbers**: reviews processed, apps, versions,
themes found, eval accuracy by category, router accuracy, p50/p95 latency, pipeline runtime. Prithika will use
these to update her resume bullets when the project is done.
