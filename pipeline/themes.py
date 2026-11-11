"""Turn cluster assignments into the themes and review_themes tables."""

from collections.abc import Callable

import numpy as np
import pandas as pd

from pipeline.cluster import (
    NOISE_LABEL,
    assign_noise,
    centroid_distances,
    representative_indices,
)
from pipeline.label import REPRESENTATIVE_REVIEWS, ThemeLabel


def theme_id_for(app_id: str, label: int) -> str:
    return f"{app_id}_other" if label == NOISE_LABEL else f"{app_id}_{label:03d}"


def build_theme_tables(
    app_id: str,
    reviews: pd.DataFrame,
    vectors: np.ndarray,
    labels: np.ndarray,
    labeler: Callable[[list[str]], ThemeLabel],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Label each cluster with the LLM. Noise becomes "Other" without spending an LLM call.

    Labels are written from each cluster's core reviews, before noise reviews join it, so
    the name reflects the clearest examples of the theme.
    """
    created_at = pd.Timestamp.now(tz="UTC")
    texts = reviews["text"].to_numpy()
    distances = np.zeros(len(reviews))
    themes = []
    core_labels, labels = labels, assign_noise(vectors, labels)
    first_label_by_name: dict[str, int] = {}

    for label in sorted(set(labels.tolist())):
        members = np.flatnonzero(labels == label)
        distances[members] = centroid_distances(vectors[members])
        if label == NOISE_LABEL:
            theme = ThemeLabel(
                name="Other Topics",
                description="Reviews that did not fit a clear theme.",
                sentiment="neutral",
                keywords=["other"],
            )
            name = "Other"
        else:
            closest = representative_indices(vectors, core_labels, label, REPRESENTATIVE_REVIEWS)
            theme = labeler([str(texts[i]) for i in closest])
            name = theme.name
            first_with_name = first_label_by_name.setdefault(name.casefold(), label)
            if first_with_name != label:  # Two clusters given one name are one theme.
                labels[members] = first_with_name
                continue
        themes.append(
            {
                "theme_id": theme_id_for(app_id, label),
                "app_id": app_id,
                "name": name,
                "description": theme.description,
                "sentiment": theme.sentiment,
                "keywords": theme.keywords,
                "created_at": created_at,
            }
        )

    review_themes = pd.DataFrame(
        {
            "review_id": reviews["review_id"].astype(str).to_numpy(),
            "theme_id": [theme_id_for(app_id, int(label)) for label in labels],
            "distance": distances,
        }
    )
    return pd.DataFrame(themes), review_themes
