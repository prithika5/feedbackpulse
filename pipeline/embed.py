"""Stage 4: turn each cleaned review into a vector, locally, and cache the result on disk."""

import os
import re
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

Encoder = Callable[[list[str]], np.ndarray]
BATCH_SIZE = 64


def load_encoder() -> Encoder:
    # Imported here because it pulls in PyTorch, which takes seconds to load and isn't
    # needed when every review is already cached (or in tests).
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(os.environ["EMBEDDING_MODEL"])

    def encode(texts: list[str]) -> np.ndarray:
        # Unit-length vectors make cosine similarity a plain dot product.
        return model.encode(
            texts, batch_size=BATCH_SIZE, normalize_embeddings=True, show_progress_bar=True
        )

    return encode


def cache_path(processed_dir: Path, app_id: str, model_name: str) -> Path:
    # The model is part of the filename: vectors from different models can't be mixed.
    slug = re.sub(r"[^\w.-]+", "_", model_name)
    return processed_dir / app_id / f"embeddings_{slug}.parquet"


def save_vectors(path: Path, ids: list[str], vectors: np.ndarray) -> None:
    flat = pa.array(vectors.astype(np.float32).ravel())
    embedding = pa.FixedSizeListArray.from_arrays(flat, vectors.shape[1])
    pq.write_table(pa.table({"review_id": ids, "embedding": embedding}), path)


def read_vectors(path: Path) -> tuple[list[str], np.ndarray]:
    table = pq.read_table(path)
    column = table["embedding"].combine_chunks()
    return table["review_id"].to_pylist(), column.values.to_numpy().reshape(len(table), -1)


def embed_reviews(
    reviews: pd.DataFrame, path: Path, get_encoder: Callable[[], Encoder] = load_encoder
) -> dict:
    """Encode only reviews missing from the cache, so each review is embedded once."""
    cached: dict[str, np.ndarray] = {}
    if path.exists():
        ids, vectors = read_vectors(path)
        cached = dict(zip(ids, vectors, strict=True))

    missing = reviews[~reviews["review_id"].isin(cached.keys())]
    if not missing.empty:
        new_vectors = get_encoder()(missing["text"].tolist())
        cached.update(zip(missing["review_id"].tolist(), new_vectors, strict=True))

    # Saved in review order, leaving out any review that cleaning no longer keeps.
    ordered_ids = reviews["review_id"].tolist()
    matrix = np.stack([cached[review_id] for review_id in ordered_ids])
    save_vectors(path, ordered_ids, matrix)
    return {"reviews": len(reviews), "encoded": len(missing), "dimension": int(matrix.shape[1])}
