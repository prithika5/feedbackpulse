import datetime as dt

import numpy as np
import pandas as pd
import pytest

from pipeline.store import SNIPPET_CHARS, rows_for_copy


def make_reviews() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "review_id": ["a", "b"],
            "app_id": ["spotify", "spotify"],
            "rating": [1, 5],
            "text": ["x" * (SNIPPET_CHARS + 50), "short review"],
            "review_date": [pd.Timestamp("2024-01-02 03:04:05"), pd.Timestamp("2024-02-01")],
            "app_version": pd.array(["8.9.1", pd.NA], dtype="string"),
        }
    )


def test_vectors_are_matched_by_id_even_when_order_differs():
    vectors = np.array([[0.0, 1.0], [1.0, 0.0]])
    rows = list(rows_for_copy(make_reviews(), ["b", "a"], vectors))
    assert rows[0][0] == "a"
    assert rows[0][2].tolist() == [1.0, 0.0]
    assert rows[1][2].tolist() == [0.0, 1.0]


def test_snippet_is_capped_and_short_text_is_unchanged():
    rows = list(rows_for_copy(make_reviews(), ["a", "b"], np.zeros((2, 2))))
    assert len(rows[0][6]) == SNIPPET_CHARS
    assert rows[1][6] == "short review"


def test_values_are_plain_python_types_for_postgres():
    first, second = rows_for_copy(make_reviews(), ["a", "b"], np.zeros((2, 2)))
    assert first[3] == 1 and type(first[3]) is int
    assert first[4] == dt.datetime(2024, 1, 2, 3, 4, 5)
    assert first[5] == "8.9.1"
    assert second[5] is None


def test_review_with_no_vector_fails_instead_of_loading_bad_data():
    with pytest.raises(KeyError):
        list(rows_for_copy(make_reviews(), ["a", "z"], np.zeros((2, 2))))
