import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from pipeline.cluster import (
    MAX_THEMES,
    MIN_THEMES,
    assign_noise,
    choose_labels,
    merge_similar_clusters,
    representative_indices,
)
from pipeline.label import ThemeLabel
from pipeline.themes import build_theme_tables, theme_id_for


def valid_label(**overrides) -> dict:
    return {
        "name": "Too Many Ads",
        "description": "Users dislike ad frequency.",
        "sentiment": "neg",
        "keywords": ["ads"],
    } | overrides


def test_valid_theme_json_is_accepted():
    label = ThemeLabel.model_validate_json(
        '{"name":"Too Many Ads","description":"d","sentiment":"neg","keywords":["ads"]}'
    )
    assert label.sentiment == "neg"


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "Ads"},
        {"name": "A Very Long Theme Name Here"},
        {"sentiment": "angry"},
        {"keywords": []},
    ],
)
def test_invalid_theme_json_is_rejected(bad):
    with pytest.raises(ValidationError):
        ThemeLabel(**valid_label(**bad))


def labels_with(themes: int, noise: int) -> np.ndarray:
    return np.array([*range(themes), *([-1] * noise)])


def test_choose_labels_picks_least_noise_within_the_theme_range():
    candidates = {
        1: labels_with(MAX_THEMES + 1, 0),
        2: labels_with(MIN_THEMES, 10),
        3: labels_with(MIN_THEMES + 1, 2),
    }
    assert choose_labels(candidates)[0] == 3


def test_choose_labels_fails_loudly_when_nothing_fits():
    with pytest.raises(ValueError):
        choose_labels({1: labels_with(MIN_THEMES - 1, 0)})


def unit_vectors() -> np.ndarray:
    return np.array([[1.0, 0.0], [0.9, 0.436], [0.0, 1.0], [0.6, 0.8]])


def test_representatives_are_closest_to_the_centre():
    vectors = np.array([[1.0, 0.0], [0.995, 0.0999], [0.0, 1.0]])
    labels = np.array([0, 0, 0])
    assert representative_indices(vectors, labels, 0, 1).tolist() == [1]


def test_noise_becomes_other_without_calling_the_llm():
    reviews = pd.DataFrame({"review_id": list("abcd"), "text": list("wxyz")})
    labels = np.array([0, 0, -1, -1])
    calls = []

    def labeler(texts):
        calls.append(texts)
        return ThemeLabel(**valid_label())

    themes, review_themes = build_theme_tables("spotify", reviews, unit_vectors(), labels, labeler)
    assert len(calls) == 1
    assert set(themes["name"]) == {"Too Many Ads", "Other"}
    # The last review is close enough to join the theme. The third one is not.
    assert review_themes["theme_id"].tolist() == [
        theme_id_for("spotify", 0),
        theme_id_for("spotify", 0),
        "spotify_other",
        theme_id_for("spotify", 0),
    ]


def test_theme_label_is_written_from_core_reviews_only():
    reviews = pd.DataFrame({"review_id": list("abcd"), "text": list("wxyz")})
    seen = []

    def labeler(texts):
        seen.extend(texts)
        return ThemeLabel(**valid_label())

    build_theme_tables("spotify", reviews, unit_vectors(), np.array([0, 0, -1, -1]), labeler)
    assert sorted(seen) == ["w", "x"]


def test_assign_noise_respects_the_threshold():
    labels = np.array([0, 0, -1, -1])
    assert assign_noise(unit_vectors(), labels, threshold=0.99).tolist() == [0, 0, -1, -1]
    assert assign_noise(unit_vectors(), labels, threshold=0.5).tolist() == [0, 0, -1, 0]


def test_assign_noise_with_no_themes_changes_nothing():
    labels = np.array([-1, -1, -1, -1])
    assert assign_noise(unit_vectors(), labels).tolist() == labels.tolist()


def test_merge_combines_only_clusters_above_the_threshold():
    vectors = np.array([[1.0, 0.0], [0.999, 0.045], [0.0, 1.0], [0.1, 0.995]])
    labels = np.array([3, 5, 8, 8])
    assert merge_similar_clusters(vectors, labels, threshold=0.9).tolist() == [3, 3, 8, 8]
    assert merge_similar_clusters(vectors, labels, threshold=0.9999).tolist() == [3, 5, 8, 8]


def test_merge_follows_chains_and_leaves_noise_alone():
    angles = np.radians([0, 20, 40, 90])
    vectors = np.column_stack([np.cos(angles), np.sin(angles)])
    labels = np.array([1, 2, 3, -1])
    assert merge_similar_clusters(vectors, labels, threshold=0.9).tolist() == [1, 1, 1, -1]


def test_clusters_given_the_same_name_become_one_theme():
    vectors = np.array([[1.0, 0.0], [0.99, 0.141], [0.0, 1.0], [0.141, 0.99]])
    reviews = pd.DataFrame({"review_id": list("abcd"), "text": list("wxyz")})
    labels = np.array([0, 0, 1, 1])
    themes, review_themes = build_theme_tables(
        "spotify", reviews, vectors, labels, lambda _: ThemeLabel(**valid_label())
    )
    assert len(themes) == 1
    assert set(review_themes["theme_id"]) == {theme_id_for("spotify", 0)}
