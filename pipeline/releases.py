"""Derive one row per (app, version) from the reviews themselves."""

import pandas as pd

# Below this, a version's average rating is too noisy to compare with another release.
MIN_RELEASE_REVIEWS = 50


def derive_releases(reviews: pd.DataFrame) -> pd.DataFrame:
    """first_seen_date is the earliest review of a version, so it estimates the release date."""
    releases = (
        reviews.dropna(subset=["app_version"])
        .groupby(["app_id", "app_version"], as_index=False)
        .agg(first_seen=("review_date", "min"), review_count=("review_id", "size"))
        .rename(columns={"app_version": "version"})
    )
    releases["first_seen_date"] = releases["first_seen"].dt.date
    releases["low_volume"] = releases["review_count"] < MIN_RELEASE_REVIEWS
    columns = ["app_id", "version", "first_seen_date", "review_count", "low_volume"]
    return releases[columns].sort_values(
        ["app_id", "first_seen_date", "version"], ignore_index=True
    )
