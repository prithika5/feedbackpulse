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
| Themes found | 23 distinct named themes (24 clusters, two share a name) plus "Other" | BigQuery `themes` |
| Reviews given a specific theme | 95.6% (33.1% core cluster members, the rest joined at cosine similarity ≥ 0.55) | BigQuery `review_themes`, Step 6 run |
| Pipeline runtime | Not yet measured end to end | |
| Eval accuracy, overall | 18/19 (94.7%) | `evals/results/20261110T234943Z.json` |
| Eval accuracy by category | numeric 5/5, trend 3/3, release comparison 3/3, theme explanation 3/4, refusal 4/4 | same |
| Router accuracy | 15/15 (refusal questions not scored) | same |
| p50 / p95 latency | 10.32 s / 37.25 s, deployed on Cloud Run, free-tier Gemini | same |
| Average tokens per answer | 6,748 | same |
| Automated tests | 107 passing | `pytest` |

**Eval scope:** 19 questions written for this project, numeric truth computed by SQL. Numeric grading passes if the
expected value appears in the answer. Citation relevance was not judged, and theme labels were not manually checked.
