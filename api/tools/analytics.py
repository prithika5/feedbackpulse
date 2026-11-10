"""The BigQuery-backed tools: guarded SQL and theme comparison between two releases."""

import datetime as dt
import decimal
import os
from functools import lru_cache

from google.cloud import bigquery

from api.sql_guard import guard_sql

MAX_BYTES_PER_QUERY = 100_000_000  # All our tables together are about 40 MB.
QUERY_TIMEOUT_SECONDS = 30
MAX_ROWS_FOR_MODEL = 100  # More rows than this only burns tokens.
THEME_ROWS = 12


@lru_cache
def _client() -> bigquery.Client:
    return bigquery.Client(project=os.environ["GCP_PROJECT_ID"], location="US")


def _dataset() -> str:
    return os.environ.get("BQ_DATASET", "feedbackpulse")


def _json_safe(value):
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    return value


def _rows(job) -> list[dict]:
    return [
        {key: _json_safe(value) for key, value in row.items()}
        for row in job.result(timeout=QUERY_TIMEOUT_SECONDS)
    ]


def run_sql(query: str) -> dict:
    """Run one guarded, read-only SELECT against the analytics tables."""
    client = _client()
    safe_sql = guard_sql(query, dataset=_dataset(), project=client.project)
    default_dataset = bigquery.DatasetReference(client.project, _dataset())

    # A dry run costs nothing and tells us how much the real query would scan.
    dry_run = client.query(
        safe_sql,
        job_config=bigquery.QueryJobConfig(dry_run=True, default_dataset=default_dataset),
    )
    if dry_run.total_bytes_processed > MAX_BYTES_PER_QUERY:
        raise ValueError("Query would scan too much data")

    job = client.query(
        safe_sql,
        job_config=bigquery.QueryJobConfig(
            default_dataset=default_dataset, maximum_bytes_billed=MAX_BYTES_PER_QUERY
        ),
    )
    rows = _rows(job)
    return {
        "sql": safe_sql,
        "row_count": len(rows),
        "truncated": len(rows) > MAX_ROWS_FOR_MODEL,
        "rows": rows[:MAX_ROWS_FOR_MODEL],
    }


def _parameterized(sql: str, **params: str) -> list[dict]:
    config = bigquery.QueryJobConfig(
        default_dataset=bigquery.DatasetReference(_client().project, _dataset()),
        maximum_bytes_billed=MAX_BYTES_PER_QUERY,
        query_parameters=[
            bigquery.ScalarQueryParameter(name, "STRING", value) for name, value in params.items()
        ],
    )
    return _rows(_client().query(sql, job_config=config))


def get_theme_trends(
    app_id: str, version_a: str | None = None, version_b: str | None = None
) -> dict:
    """Compare each theme's share of reviews between two releases."""
    if not (version_a and version_b):
        latest = _parameterized(
            """
            SELECT version FROM releases
            WHERE app_id = @app_id AND NOT low_volume
            ORDER BY first_seen_date DESC LIMIT 2
            """,
            app_id=app_id,
        )
        if len(latest) < 2:
            return {"error": "Not enough releases with 50+ reviews to compare"}
        version_b, version_a = latest[0]["version"], latest[1]["version"]

    themes = _parameterized(
        f"""
        WITH per_version AS (
          SELECT r.app_version AS version, rt.theme_id, COUNT(*) AS reviews,
                 AVG(r.rating) AS avg_rating
          FROM reviews AS r JOIN review_themes AS rt USING (review_id)
          WHERE r.app_id = @app_id AND r.app_version IN (@version_a, @version_b)
          GROUP BY version, rt.theme_id
        ),
        shares AS (
          SELECT *, 100 * reviews / SUM(reviews) OVER (PARTITION BY version) AS share
          FROM per_version
        ),
        compared AS (
          SELECT theme_id,
                 COALESCE(MAX(IF(version = @version_a, share, NULL)), 0) AS share_a,
                 COALESCE(MAX(IF(version = @version_b, share, NULL)), 0) AS share_b,
                 COALESCE(SUM(IF(version = @version_a, reviews, NULL)), 0) AS reviews_a,
                 COALESCE(SUM(IF(version = @version_b, reviews, NULL)), 0) AS reviews_b,
                 MAX(IF(version = @version_a, avg_rating, NULL)) AS avg_rating_a,
                 MAX(IF(version = @version_b, avg_rating, NULL)) AS avg_rating_b
          FROM shares GROUP BY theme_id
        )
        SELECT c.theme_id, t.name, t.sentiment,
               ROUND(c.share_a, 1) AS share_pct_a, ROUND(c.share_b, 1) AS share_pct_b,
               ROUND(c.share_b - c.share_a, 1) AS change_points,
               c.reviews_a, c.reviews_b,
               ROUND(c.avg_rating_a, 2) AS avg_rating_a, ROUND(c.avg_rating_b, 2) AS avg_rating_b
        FROM compared AS c JOIN themes AS t USING (theme_id)
        ORDER BY ABS(c.share_b - c.share_a) DESC
        LIMIT {THEME_ROWS}
        """,
        app_id=app_id,
        version_a=version_a,
        version_b=version_b,
    )
    if not themes:
        return {"error": f"No themed reviews found for {version_a} or {version_b}"}
    return {"version_a": version_a, "version_b": version_b, "themes": themes}
