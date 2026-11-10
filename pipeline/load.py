"""Write the cleaned data to BigQuery with batch load jobs, which are free (streaming isn't)."""

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from google.cloud import bigquery

from pipeline.ingest import APPS
from pipeline.releases import derive_releases

SCHEMA_SQL = Path("infra/bigquery_schema.sql")
LOAD_TIMEOUT_SECONDS = 300


def build_tables(cleaned_by_app: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Combine every processed app into the rows for each BigQuery table."""
    reviews = pd.concat(cleaned_by_app.values(), ignore_index=True)
    apps = pd.DataFrame(
        [
            {
                "app_id": app_id,
                "name": APPS[app_id].name,
                "category": APPS[app_id].category,
                "review_count": len(frame),
            }
            for app_id, frame in cleaned_by_app.items()
        ]
    )
    return {"apps": apps, "reviews": reviews, "releases": derive_releases(reviews)}


def load_all(processed_dir: Path) -> dict[str, int]:
    """Replace the tables with every app processed so far. Returns rows loaded per table.

    Loading all apps together means a run for one app can't erase another app's rows,
    and replacing whole tables makes re-runs safe.
    """
    load_dotenv()
    dataset = os.environ.get("BQ_DATASET", "feedbackpulse")
    client = bigquery.Client(project=os.environ["GCP_PROJECT_ID"], location="US")
    client.query(SCHEMA_SQL.read_text().replace("__DATASET__", dataset)).result(timeout=120)

    cleaned_by_app = {
        path.parent.name: pd.read_parquet(path)
        for path in sorted(processed_dir.glob("*/reviews_clean.parquet"))
    }
    if not cleaned_by_app:
        raise FileNotFoundError(f"No cleaned reviews found under {processed_dir}")

    return {
        table: _replace_table(client, dataset, table, frame, processed_dir)
        for table, frame in build_tables(cleaned_by_app).items()
    }


def load_themes(
    themes: pd.DataFrame, review_themes: pd.DataFrame, processed_dir: Path
) -> dict[str, int]:
    """Replace the themes and review_themes tables."""
    dataset = os.environ.get("BQ_DATASET", "feedbackpulse")
    client = bigquery.Client(project=os.environ["GCP_PROJECT_ID"], location="US")
    tables = {"themes": themes, "review_themes": review_themes}
    return {
        table: _replace_table(client, dataset, table, frame, processed_dir)
        for table, frame in tables.items()
    }


def _replace_table(
    client: bigquery.Client, dataset: str, table: str, frame: pd.DataFrame, processed_dir: Path
) -> int:
    load_dir = processed_dir / "_load"
    load_dir.mkdir(exist_ok=True)
    path = load_dir / f"{table}.parquet"
    frame.to_parquet(path, index=False)
    table_id = f"{client.project}.{dataset}.{table}"
    parquet_options = bigquery.ParquetOptions()
    parquet_options.enable_list_inference = True  # Needed to load keywords as ARRAY<STRING>.
    config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        parquet_options=parquet_options,
        # Without this, the load would replace our declared schema with Parquet's guess.
        schema=client.get_table(table_id).schema,
    )
    with path.open("rb") as file:
        job = client.load_table_from_file(file, table_id, job_config=config)
    return job.result(timeout=LOAD_TIMEOUT_SECONDS).output_rows
