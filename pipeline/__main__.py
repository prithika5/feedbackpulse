"""Pipeline entry point: python -m pipeline run --app <app_id|all>."""

import argparse
import json
import logging
import os
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from pipeline import store
from pipeline.clean import clean_reviews
from pipeline.cluster import (
    cluster_reviews,
    merge_similar_clusters,
    reduce_dimensions,
    score_labels,
)
from pipeline.embed import cache_path, embed_reviews, read_vectors
from pipeline.ingest import APPS, AppSource, ingest
from pipeline.label import label_cluster
from pipeline.load import load_all, load_themes
from pipeline.themes import build_theme_tables

PROCESSED_DIR = Path("data/processed")
log = logging.getLogger("pipeline")


def run_app(source: AppSource) -> dict:
    started = time.perf_counter()
    raw = ingest(source)
    log.info("%s: ingested %s rows", source.app_id, f"{len(raw):,}")
    cleaned, report = clean_reviews(raw)

    # Each run overwrites the same files, so re-running is always safe.
    out_dir = PROCESSED_DIR / source.app_id
    out_dir.mkdir(parents=True, exist_ok=True)
    cleaned.to_parquet(out_dir / "reviews_clean.parquet", index=False)
    report["app_id"] = source.app_id
    report["seconds"] = round(time.perf_counter() - started, 1)
    (out_dir / "clean_report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def run_themes(source: AppSource, model_name: str) -> None:
    app_dir = PROCESSED_DIR / source.app_id
    columns = ["review_id", "app_id", "rating", "text", "review_date", "app_version"]
    reviews = pd.read_parquet(app_dir / "reviews_clean.parquet", columns=columns)
    ids, vectors = read_vectors(cache_path(PROCESSED_DIR, source.app_id, model_name))
    if ids != reviews["review_id"].tolist():
        raise ValueError("Embeddings are out of step with the cleaned reviews")

    reduced = reduce_dimensions(vectors, app_dir / "umap5.npy")
    size, labels, scores = cluster_reviews(reduced)
    themes_found, noise = scores[size]
    print(f"  {source.app_id}: min_cluster_size={size}, {themes_found} themes, {noise:.1%} noise")
    labels = merge_similar_clusters(vectors, labels)
    print(f"  after merging overlapping clusters: {score_labels(labels)[0]} themes")

    themes, review_themes = build_theme_tables(
        source.app_id, reviews, vectors, labels, label_cluster
    )
    print(f"  BigQuery: {load_themes(themes, review_themes, PROCESSED_DIR)}")
    theme_by_review = dict(zip(review_themes["review_id"], review_themes["theme_id"], strict=True))
    with store.connect() as conn:
        store.apply_schema(conn)
        print(f"  Postgres: {store.write_themes(conn, reviews, ids, vectors, theme_by_review)}")


def print_summary(report: dict) -> None:
    print(f"\nCleaning summary: {report['app_id']}")
    print(f"  {'rows in':<28}{report['rows_in']:>10,}")
    for rule, count in report["removed"].items():
        print(f"  {'- ' + rule:<28}{count:>10,}")
    print(f"  {'rows out':<28}{report['rows_out']:>10,}")
    replaced = ", ".join(f"{count:,} {kind}" for kind, count in report["pii_replaced"].items())
    print(f"  PII replaced: {replaced}")
    print(f"  Took {report['seconds']}s")


def main() -> None:
    parser = argparse.ArgumentParser(prog="pipeline")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run the pipeline stages built so far")
    run.add_argument("--app", required=True, choices=[*APPS, "all"])
    run.add_argument(
        "--reuse-clean",
        action="store_true",
        help="Skip ingest and cleaning for apps that already have cleaned output",
    )
    args = parser.parse_args()

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sources = APPS.values() if args.app == "all" else [APPS[args.app]]
    for source in sources:
        if args.reuse_clean and (PROCESSED_DIR / source.app_id / "reviews_clean.parquet").exists():
            log.info("%s: reusing existing cleaned output", source.app_id)
            continue
        print_summary(run_app(source))

    print("\nBigQuery load")
    for table, rows in load_all(PROCESSED_DIR).items():
        print(f"  {table:<28}{rows:>10,}")

    print("\nEmbeddings")
    model_name = os.environ["EMBEDDING_MODEL"]
    for source in sources:
        reviews = pd.read_parquet(PROCESSED_DIR / source.app_id / "reviews_clean.parquet")
        path = cache_path(PROCESSED_DIR, source.app_id, model_name)
        started = time.perf_counter()
        result = embed_reviews(reviews[["review_id", "text"]], path)
        seconds = round(time.perf_counter() - started, 1)
        print(f"  {source.app_id}: {result} in {seconds}s")

    print("\nPostgres (pgvector)")
    columns = ["review_id", "app_id", "rating", "text", "review_date", "app_version"]
    with store.connect() as conn:
        store.apply_schema(conn)
        for source in sources:
            reviews = pd.read_parquet(
                PROCESSED_DIR / source.app_id / "reviews_clean.parquet", columns=columns
            )
            ids, vectors = read_vectors(cache_path(PROCESSED_DIR, source.app_id, model_name))
            result = store.upsert_embeddings(conn, reviews, ids, vectors)
            print(f"  {source.app_id}: {result}")
        store.build_hnsw_index(conn)
        print("  HNSW index ready")

    print("\nThemes")
    for source in sources:
        run_themes(source, model_name)


if __name__ == "__main__":
    main()
