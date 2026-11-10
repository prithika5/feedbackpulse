"""Filtered semantic search over reviews, using pgvector."""

import os
from functools import lru_cache

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

MAX_K = 20
SEARCH_TIMEOUT_MS = 10_000


@lru_cache
def _embedder():
    # fastembed runs the same model as the pipeline without PyTorch, which keeps the image
    # small. Its vectors matched the stored ones at cosine similarity 1.0 on 200 reviews.
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=os.environ["EMBEDDING_MODEL"])


def embed_query(text: str) -> np.ndarray:
    vector = next(iter(_embedder().embed([text])))
    return vector / np.linalg.norm(vector)


def build_filters(
    app_id: str,
    version: str | None,
    rating_max: int | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[str, list]:
    """Every value goes in as a parameter, so model output can't change the query's shape."""
    clauses, params = ["app_id = %s"], [app_id]
    optional = (
        ("app_version = %s", version),
        ("rating <= %s", rating_max),
        ("review_date >= %s::timestamp", date_from),
        ("review_date < %s::timestamp", date_to),
    )
    for clause, value in optional:
        if value is not None:
            clauses.append(clause)
            params.append(value)
    return " AND ".join(clauses), params


def search_reviews(
    query: str,
    app_id: str,
    version: str | None = None,
    rating_max: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    k: int = 8,
) -> dict:
    """Return the reviews closest in meaning to the query, within the given filters."""
    vector = embed_query(query)
    where, params = build_filters(app_id, version, rating_max, date_from, date_to)
    sql = f"""
        SELECT review_id, rating, review_date::date::text, app_version, theme_id, snippet,
               1 - (embedding <=> %s) AS similarity
        FROM review_embeddings WHERE {where}
        ORDER BY embedding <=> %s LIMIT %s
    """
    with psycopg.connect(
        os.environ["DATABASE_URL"], connect_timeout=10, prepare_threshold=None
    ) as conn:
        conn.execute("SET LOCAL search_path = public, extensions")
        register_vector(conn)
        conn.execute(f"SET LOCAL statement_timeout = {SEARCH_TIMEOUT_MS}")
        # Keeps scanning the index until enough rows pass the filters.
        conn.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order'")
        rows = conn.execute(sql, [vector, *params, vector, min(k, MAX_K)]).fetchall()

    return {
        "reviews": [
            {
                "review_id": row[0],
                "rating": row[1],
                "date": row[2],
                "app_version": row[3],
                "theme_id": row[4],
                "snippet": row[5],
                "similarity": round(float(row[6]), 3),
            }
            for row in rows
        ]
    }
