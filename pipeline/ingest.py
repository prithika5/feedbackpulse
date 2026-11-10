"""Stage 1: read a raw dataset and normalize it to the project's column names and types."""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class AppSource:
    app_id: str
    name: str
    category: str
    path: Path


APPS = {
    "spotify": AppSource(
        app_id="spotify",
        name="Spotify",
        category="Music & Audio",
        path=Path("data/raw/spotify_reviews/spotify_reviews.csv"),
    ),
}

# Only these columns are read. userName is left out on purpose, so reviewer identities
# can never reach BigQuery, Postgres, or the UI.
RAW_TO_CLEAN_COLUMNS = {
    "reviewId": "review_id",
    "content": "text",
    "score": "rating",
    "thumbsUpCount": "thumbs_up",
    "reviewCreatedVersion": "app_version",
    "at": "review_date",
}


def ingest(source: AppSource) -> pd.DataFrame:
    """Read one app's CSV. Bad values become nulls here; the clean stage decides what to drop."""
    # Versions must stay strings: as numbers, "8.10" would turn into 8.1.
    raw = pd.read_csv(
        source.path,
        usecols=list(RAW_TO_CLEAN_COLUMNS),
        dtype={"reviewId": "string", "content": "string", "reviewCreatedVersion": "string"},
    )
    df = raw.rename(columns=RAW_TO_CLEAN_COLUMNS)
    df["app_id"] = source.app_id
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce")
    df["review_date"] = pd.to_datetime(df["review_date"], errors="coerce")
    df["thumbs_up"] = pd.to_numeric(df["thumbs_up"], errors="coerce").fillna(0).astype(int)
    return df
