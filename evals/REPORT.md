# Eval report

Run `20261110T234943Z` against the deployed API. Ground truth comes from SQL at eval time.

- Overall accuracy: 95% of 19 questions
- Router accuracy: 100% of 15 questions
- Latency p50 / p95: 10.32 s / 37.25 s
- Average tokens per answer: 6748
- Failed requests: 0

| Category | Correct |
|---|---|
| numeric | 5/5 |
| trend | 3/3 |
| release_comparison | 3/3 |
| theme_explanation | 3/4 |
| refuse | 4/4 |

| Question | Correct | Router | Tools | Latency (s) |
|---|---|---|---|---|
| count_reviews | True | True | run_sql | 16.6 |
| avg_rating | True | True | run_sql | 37.3 |
| pct_negative | True | True | run_sql | 4.9 |
| version_rating | True | True | run_sql | 10.2 |
| version_count | True | True | run_sql | 9.4 |
| rating_2023 | True | True | run_sql | 8.9 |
| best_year | True | True | run_sql | 10.1 |
| worst_month_2023 | True | True | run_sql | 7.2 |
| release_rating_change | True | True | run_sql | 12.8 |
| release_themes | True | True | get_theme_trends | 10.3 |
| why_drop | True | True | run_sql, run_sql, search_reviews, get_theme_trends, run_sql | 45.4 |
| one_star_complaints | True | True | run_sql, search_reviews | 18.5 |
| five_star_love | False | True | search_reviews, run_sql, search_reviews | 26.0 |
| largest_theme | True | True | run_sql | 16.1 |
| ad_opinions | True | True | search_reviews, run_sql, search_reviews, search_reviews | 32.6 |
| refuse_revenue | True | n/a | none | 7.3 |
| refuse_users | True | n/a | none | 5.2 |
| refuse_future | True | n/a | run_sql | 12.6 |
| refuse_competitor | True | n/a | none | 6.4 |
