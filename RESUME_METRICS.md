# Resume metrics

Only real, measured numbers go here (from `pipeline/last_run.json` and `evals/results/`).

| Metric | Value | Source |
|---|---|---|
| Raw reviews ingested | 84,165 | `data/processed/spotify/clean_report.json` |
| Reviews processed (after cleaning) | 83,716 | `clean_report.json`, reconciled against BigQuery |
| Apps | 1 (Spotify) | BigQuery `apps` |
| Versions | 441 (252 with 50+ reviews before cleaning) | BigQuery `releases`, notebook |
| Vectors indexed (384-dim, HNSW) | 83,716 | Supabase `review_embeddings` |
| Local embedding runtime | 683.7 s for 83,716 reviews | Step 5 run |
| Filtered vector search latency | about 75 ms | Step 5 test, 3 runs per filter |
| Postgres size with index | 364 MB (500 MB free-tier limit) | `pg_database_size` |
| Themes found | 16 plus "Other" (24 clusters, overlapping ones merged) | BigQuery `themes` |
| Reviews given a specific theme | 95.1% (33.1% core cluster members, the rest joined at cosine similarity ≥ 0.55) | BigQuery `review_themes`, Step 6 run |
| Pipeline runtime | Not yet measured end to end | |
| Eval accuracy, latest run | 19/19 | `evals/results/20261111T031414Z.json` |
| Eval accuracy, first run (before fixing the bug it found) | 18/19 | `evals/results/20261110T234943Z.json` |
| Eval accuracy by category, latest | numeric 5/5, trend 3/3, release comparison 3/3, theme explanation 4/4, refusal 4/4 | latest run |
| Router accuracy, latest | 15/15 (refusal questions not scored) | latest run |
| p50 / p95 latency, latest | 13.61 s / 27.66 s, deployed on Cloud Run, free-tier Gemini | latest run |
| Average tokens per answer, latest | 6,069 | latest run |
| Automated tests | 114 passing | `pytest` |

**Eval scope:** 19 questions written for this project, numeric truth computed by SQL. Numeric grading passes if the
expected value appears in the answer. The citation bug was found and fixed using these same questions, so 19/19 is
not an independent measure. Citation relevance was not judged, and theme labels were not manually checked.
