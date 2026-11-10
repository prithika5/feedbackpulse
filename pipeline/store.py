"""Copy review vectors into Postgres (pgvector) so the Analyst can search them."""

import os
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from pgvector.psycopg import register_vector

SCHEMA_SQL = Path("infra/pgvector_schema.sql")
SNIPPET_CHARS = 300
COPY_COLUMNS = "review_id, app_id, embedding, rating, review_date, app_version, snippet, theme_id"
COPY_TYPES = ["text", "text", "vector", "int2", "timestamp", "text", "text", "text"]
HNSW_INDEX = "review_embeddings_embedding_hnsw_idx"


def connect() -> psycopg.Connection:
    # prepare_threshold=None because connection poolers can't track prepared statements.
    conn = psycopg.connect(
        os.environ["DATABASE_URL"], connect_timeout=15, autocommit=True, prepare_threshold=None
    )
    conn.execute("SET search_path = public, extensions")
    return conn


def apply_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_SQL.read_text())
    register_vector(conn)


def rows_for_copy(
    reviews: pd.DataFrame,
    ids: list[str],
    vectors: np.ndarray,
    theme_by_review: dict[str, str] | None = None,
) -> Iterator[tuple]:
    """Pair each review with its vector by ID, so a change in row order can't mismatch them."""
    vector_by_id = dict(zip(ids, vectors, strict=True))
    themes = theme_by_review or {}
    for row in reviews.itertuples(index=False):
        version = None if pd.isna(row.app_version) else row.app_version
        yield (
            row.review_id,
            row.app_id,
            vector_by_id[row.review_id],
            int(row.rating),
            row.review_date.to_pydatetime(),
            version,
            row.text[:SNIPPET_CHARS],
            themes.get(row.review_id),
        )


def upsert_embeddings(
    conn: psycopg.Connection, reviews: pd.DataFrame, ids: list[str], vectors: np.ndarray
) -> dict[str, int]:
    """Make the table match this app's reviews, writing only rows that actually changed.

    Skipping unchanged rows matters on a 500 MB free tier: every rewritten row leaves a dead
    copy behind in the table and the index. theme_id is left alone because Step 6 owns it.
    """
    app_id = reviews["app_id"].iloc[0]
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "CREATE TEMP TABLE staging (LIKE review_embeddings INCLUDING DEFAULTS) ON COMMIT DROP"
        )
        with cur.copy(f"COPY staging ({COPY_COLUMNS}) FROM STDIN WITH (FORMAT BINARY)") as copy:
            copy.set_types(COPY_TYPES)
            for row in rows_for_copy(reviews, ids, vectors):
                copy.write_row(row)
        cur.execute(
            """
            INSERT INTO review_embeddings AS t (review_id, app_id, embedding, rating,
                                                review_date, app_version, snippet)
            SELECT review_id, app_id, embedding, rating, review_date, app_version, snippet
            FROM staging
            ON CONFLICT (review_id) DO UPDATE SET
              app_id = EXCLUDED.app_id, embedding = EXCLUDED.embedding, rating = EXCLUDED.rating,
              review_date = EXCLUDED.review_date, app_version = EXCLUDED.app_version,
              snippet = EXCLUDED.snippet
            WHERE (t.app_id, t.embedding, t.rating, t.review_date, t.app_version, t.snippet)
              IS DISTINCT FROM (EXCLUDED.app_id, EXCLUDED.embedding, EXCLUDED.rating,
                                EXCLUDED.review_date, EXCLUDED.app_version, EXCLUDED.snippet)
            """
        )
        written = cur.rowcount
        cur.execute(
            """
            DELETE FROM review_embeddings AS t
            WHERE t.app_id = %s
              AND NOT EXISTS (SELECT 1 FROM staging AS s WHERE s.review_id = t.review_id)
            """,
            (app_id,),
        )
        return {"written": written, "deleted": cur.rowcount}


def write_themes(
    conn: psycopg.Connection,
    reviews: pd.DataFrame,
    ids: list[str],
    vectors: np.ndarray,
    theme_by_review: dict[str, str],
) -> dict[str, int]:
    """Store each review's theme by reloading the table, unless nothing has changed.

    An UPDATE of every row would leave a dead copy of each one in the table and the index,
    roughly doubling their size and passing the 500 MB free-tier limit. Reloading never
    needs more space than the finished table.
    """
    apps = conn.execute("SELECT DISTINCT app_id FROM review_embeddings").fetchall()
    if {row[0] for row in apps} - set(reviews["app_id"]):
        raise RuntimeError("write_themes reloads the whole table; pass every app's reviews")

    current = dict(conn.execute("SELECT review_id, theme_id FROM review_embeddings").fetchall())
    changed = sum(current.get(review_id) != theme for review_id, theme in theme_by_review.items())
    if changed == 0:
        return {"changed": 0, "reloaded": 0}

    with conn.transaction(), conn.cursor() as cur:
        cur.execute(f"DROP INDEX IF EXISTS {HNSW_INDEX}")
        cur.execute("TRUNCATE review_embeddings")
        with cur.copy(
            f"COPY review_embeddings ({COPY_COLUMNS}) FROM STDIN WITH (FORMAT BINARY)"
        ) as copy:
            copy.set_types(COPY_TYPES)
            for row in rows_for_copy(reviews, ids, vectors, theme_by_review):
                copy.write_row(row)
    build_hnsw_index(conn)
    return {"changed": changed, "reloaded": len(reviews)}


def build_hnsw_index(conn: psycopg.Connection) -> None:
    # Index builds outlast the default statement timeout, and more memory speeds them up.
    conn.execute("SET statement_timeout = 0")
    conn.execute("SET maintenance_work_mem = '128MB'")
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {HNSW_INDEX}
        ON review_embeddings USING hnsw (embedding vector_cosine_ops)
        """
    )
    # Without fresh statistics after a bulk load, Postgres skips the index and scans instead.
    conn.execute("ANALYZE review_embeddings")
