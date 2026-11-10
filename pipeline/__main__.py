"""Pipeline entry point: python -m pipeline run --app <app_id|all>."""

import argparse
import json
import logging
import time
from pathlib import Path

from pipeline.clean import clean_reviews
from pipeline.ingest import APPS, AppSource, ingest
from pipeline.load import load_all

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


if __name__ == "__main__":
    main()
