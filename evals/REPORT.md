# Eval report

Run `20261111T031414Z` against the deployed API. Ground truth comes from SQL at eval time.

- Overall accuracy: 100% of 19 questions
- Router accuracy: 100% of 15 questions
- Latency p50 / p95: 13.61 s / 27.66 s
- Average tokens per answer: 6069
- Failed requests: 0

| Category | Correct |
|---|---|
| numeric | 5/5 |
| trend | 3/3 |
| release_comparison | 3/3 |
| theme_explanation | 4/4 |
| refuse | 4/4 |

| Question | Correct | Router | Tools | Latency (s) |
|---|---|---|---|---|
| count_reviews | True | True | run_sql | 0.2 |
| avg_rating | True | True | run_sql | 13.3 |
| pct_negative | True | True | run_sql | 13.1 |
| version_rating | True | True | run_sql | 12.2 |
| version_count | True | True | run_sql | 21.9 |
| rating_2023 | True | True | run_sql | 14.1 |
| best_year | True | True | run_sql | 14.5 |
| worst_month_2023 | True | True | run_sql, run_sql | 9.7 |
| release_rating_change | True | True | run_sql | 18.6 |
| release_themes | True | True | get_theme_trends, search_reviews, search_reviews | 27.7 |
| why_drop | True | True | run_sql, run_sql, get_theme_trends, run_sql, run_sql, search_reviews | 32.6 |
| one_star_complaints | True | True | run_sql, search_reviews, search_reviews | 20.7 |
| five_star_love | True | True | search_reviews, run_sql, search_reviews | 14.3 |
| largest_theme | True | True | run_sql | 13.6 |
| ad_opinions | True | True | search_reviews, run_sql, search_reviews | 19.0 |
| refuse_revenue | True | n/a | none | 10.3 |
| refuse_users | True | n/a | none | 11.6 |
| refuse_future | True | n/a | run_sql | 7.4 |
| refuse_competitor | True | n/a | run_sql | 8.6 |
