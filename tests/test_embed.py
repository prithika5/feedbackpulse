import numpy as np
import pandas as pd

from pipeline.embed import cache_path, embed_reviews, read_vectors


def reviews_with(ids: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"review_id": ids, "text": [f"text of {i}" for i in ids]})


class FakeEncoder:
    """Stands in for the real model and records which texts it was asked to encode."""

    def __init__(self):
        self.seen: list[str] = []

    def __call__(self, texts: list[str]) -> np.ndarray:
        self.seen.extend(texts)
        return np.array([[len(self.seen) + i, 1.0, 0.0] for i in range(len(texts))], dtype=float)

    def factory(self):
        return self


def test_vectors_are_saved_in_review_order(tmp_path):
    path = tmp_path / "vectors.parquet"
    result = embed_reviews(reviews_with(["a", "b"]), path, FakeEncoder().factory)
    ids, vectors = read_vectors(path)
    assert ids == ["a", "b"]
    assert vectors.shape == (2, 3)
    assert result == {"reviews": 2, "encoded": 2, "dimension": 3}


def test_each_review_is_embedded_only_once(tmp_path):
    path = tmp_path / "vectors.parquet"
    encoder = FakeEncoder()
    embed_reviews(reviews_with(["a"]), path, encoder.factory)
    result = embed_reviews(reviews_with(["a", "b"]), path, encoder.factory)
    assert encoder.seen == ["text of a", "text of b"]
    assert result["encoded"] == 1


def test_model_is_not_loaded_when_everything_is_cached(tmp_path):
    path = tmp_path / "vectors.parquet"
    embed_reviews(reviews_with(["a"]), path, FakeEncoder().factory)

    def fail():
        raise AssertionError("the model should not be loaded")

    assert embed_reviews(reviews_with(["a"]), path, fail)["encoded"] == 0


def test_reviews_removed_by_cleaning_leave_the_cache(tmp_path):
    path = tmp_path / "vectors.parquet"
    embed_reviews(reviews_with(["a", "b"]), path, FakeEncoder().factory)
    embed_reviews(reviews_with(["b"]), path, FakeEncoder().factory)
    assert read_vectors(path)[0] == ["b"]


def test_different_models_never_share_a_cache_file(tmp_path):
    first = cache_path(tmp_path, "spotify", "sentence-transformers/all-MiniLM-L6-v2")
    second = cache_path(tmp_path, "spotify", "sentence-transformers/other-model")
    assert first != second
    assert "/" not in first.name
