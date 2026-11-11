"""Stage 5: group reviews into themes with UMAP + HDBSCAN. No LLM, so results are repeatable."""

from pathlib import Path

import numpy as np
from sklearn.cluster import HDBSCAN

NOISE_LABEL = -1
MIN_THEMES = 8
MAX_THEMES = 25
RANDOM_STATE = 42
# Tuned on the Spotify reviews. The default "eom" selection produced one cluster holding a
# third of all reviews, while "leaf" with 300 gave 24 specific themes, the largest at 7%.
CANDIDATE_MIN_CLUSTER_SIZES = (300,)
CLUSTER_SELECTION_METHOD = "leaf"
# Leaf clustering leaves most reviews unassigned. A noise review joins its closest theme only
# at this cosine similarity or above. Reading borderline examples showed they still fit.
NOISE_ASSIGNMENT_THRESHOLD = 0.55
# Clusters this similar are one topic split in two. Tuned by reading ranked pairs on Spotify:
# pairs at 0.855 and above were true overlaps, and the next pair (0.850) was unrelated.
# The cutoff sits midway between them. That gap is narrow, so re-check it for any new data.
MERGE_SIMILARITY_THRESHOLD = 0.8525


def reduce_dimensions(vectors: np.ndarray, cache_file: Path | None = None) -> np.ndarray:
    """Compress 384 dimensions to 5, because density clustering fails in very high dimensions."""
    if cache_file and cache_file.exists():
        return np.load(cache_file)
    # Imported here because umap-learn is slow to import and only this stage needs it.
    import umap

    reduced = umap.UMAP(
        n_components=5,
        n_neighbors=30,
        min_dist=0.0,  # Packs similar reviews tightly, which helps density clustering.
        metric="cosine",
        random_state=RANDOM_STATE,  # Makes UMAP slower, but re-runs give the same themes.
    ).fit_transform(vectors)
    if cache_file:
        np.save(cache_file, reduced)
    return reduced


def score_labels(labels: np.ndarray) -> tuple[int, float]:
    """Return (number of themes, share of reviews left as noise)."""
    themes = len(set(labels.tolist()) - {NOISE_LABEL})
    return themes, float((labels == NOISE_LABEL).mean())


def choose_labels(candidates: dict[int, np.ndarray]) -> tuple[int, np.ndarray]:
    """Pick the candidate with the least noise among those with a usable number of themes."""
    in_range = [
        (score_labels(labels)[1], size)
        for size, labels in candidates.items()
        if MIN_THEMES <= score_labels(labels)[0] <= MAX_THEMES
    ]
    if not in_range:
        counts = {size: score_labels(labels)[0] for size, labels in candidates.items()}
        raise ValueError(f"No candidate produced {MIN_THEMES}-{MAX_THEMES} themes: {counts}")
    _, best_size = min(in_range)
    return best_size, candidates[best_size]


def cluster_reviews(reduced: np.ndarray) -> tuple[int, np.ndarray, dict[int, tuple[int, float]]]:
    """Try each cluster size. Returns the chosen size, its labels, and every candidate's score."""
    candidates = {
        size: HDBSCAN(
            min_cluster_size=size, cluster_selection_method=CLUSTER_SELECTION_METHOD, copy=True
        ).fit_predict(reduced)
        for size in CANDIDATE_MIN_CLUSTER_SIZES
    }
    best_size, labels = choose_labels(candidates)
    return best_size, labels, {size: score_labels(found) for size, found in candidates.items()}


def merge_similar_clusters(
    vectors: np.ndarray, labels: np.ndarray, threshold: float = MERGE_SIMILARITY_THRESHOLD
) -> np.ndarray:
    """Combine clusters whose centres nearly coincide. Each group takes its lowest label."""
    themes = sorted(set(labels.tolist()) - {NOISE_LABEL})
    if len(themes) < 2:
        return labels.copy()
    centroids = np.stack([vectors[labels == theme].mean(axis=0) for theme in themes])
    centroids = centroids / np.linalg.norm(centroids, axis=1, keepdims=True)
    similarities = centroids @ centroids.T

    group = {theme: theme for theme in themes}

    def root(theme: int) -> int:
        while group[theme] != theme:
            theme = group[theme]
        return theme

    for i, first in enumerate(themes):
        for j in range(i + 1, len(themes)):
            if similarities[i, j] >= threshold:
                low, high = sorted((root(first), root(themes[j])))
                group[high] = low

    merged = labels.copy()
    for theme in themes:
        merged[labels == theme] = root(theme)
    return merged


def assign_noise(
    vectors: np.ndarray, labels: np.ndarray, threshold: float = NOISE_ASSIGNMENT_THRESHOLD
) -> np.ndarray:
    """Give noise reviews to their closest theme when similar enough. The rest stay noise."""
    themes = sorted(set(labels.tolist()) - {NOISE_LABEL})
    noise = np.flatnonzero(labels == NOISE_LABEL)
    if not themes or noise.size == 0:
        return labels.copy()
    centroids = np.stack([vectors[labels == theme].mean(axis=0) for theme in themes])
    centroids = centroids / np.linalg.norm(centroids, axis=1, keepdims=True)
    similarities = vectors[noise] @ centroids.T
    best = similarities.argmax(axis=1)
    close_enough = similarities.max(axis=1) >= threshold
    assigned = labels.copy()
    assigned[noise[close_enough]] = np.array(themes)[best[close_enough]]
    return assigned


def representative_indices(
    vectors: np.ndarray, labels: np.ndarray, label: int, n: int
) -> np.ndarray:
    """Positions of the n reviews closest to a cluster's centre, most typical first."""
    members = np.flatnonzero(labels == label)
    distances = centroid_distances(vectors[members])
    return members[np.argsort(distances, kind="stable")[:n]]


def centroid_distances(vectors: np.ndarray) -> np.ndarray:
    """Cosine distance from each (unit-length) vector to the group's centre."""
    centroid = vectors.mean(axis=0)
    centroid = centroid / np.linalg.norm(centroid)
    return 1 - vectors @ centroid
