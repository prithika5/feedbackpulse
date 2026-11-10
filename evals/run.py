"""Run the eval questions against a live API and write a JSON result and a report."""

import datetime as dt
import json
import os
import re
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv
from google.cloud import bigquery

QUESTIONS = Path("evals/questions.yaml")
RESULTS_DIR = Path("evals/results")
REPORT = Path("evals/REPORT.md")
SECONDS_BETWEEN_QUESTIONS = 12  # Keeps a full run inside free-tier requests-per-minute.
REQUEST_TIMEOUT = 150


def compute_truth(client: bigquery.Client, dataset: str, sql: str) -> list:
    config = bigquery.QueryJobConfig(
        default_dataset=bigquery.DatasetReference(client.project, dataset)
    )
    row = next(iter(client.query(sql, job_config=config).result(timeout=60)))
    return list(row.values())


def numbers_in(text: str) -> list[float]:
    # Citation markers like [1] are removed first so they can't count as answers.
    without_citations = re.sub(r"\[\d+\]", "", text)
    return [float(n.replace(",", "")) for n in re.findall(r"-?\d[\d,]*\.?\d*", without_citations)]


def value_matches(expected, answer: str, tolerance: float) -> bool:
    if isinstance(expected, str):
        return expected.lower() in answer.lower()
    return any(abs(found - float(expected)) <= tolerance for found in numbers_in(answer))


def tools_match(used: set[str], acceptable: list[list[str]]) -> bool:
    return any(set(option) <= used for option in acceptable)


def ask(base_url: str, question: str) -> dict:
    """Send one question and collect its event stream."""
    started = time.perf_counter()
    result = {"answer": "", "citations": 0, "tools": [], "tokens": 0, "insufficient": False}
    event = None
    with httpx.stream(
        "POST", f"{base_url}/ask", json={"question": question}, timeout=REQUEST_TIMEOUT
    ) as response:
        if response.status_code != 200:
            result["error"] = f"HTTP {response.status_code}"
            return result | {"latency_s": time.perf_counter() - started}
        for line in response.iter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1])
                if event == "answer_delta":
                    result["answer"] += data["text"]
                elif event == "citation":
                    result["citations"] += 1
                elif event == "done":
                    result["tools"] = data["tools"]
                    result["tokens"] = data["tokens"]
                    result["insufficient"] = data["insufficient_data"]
                elif event == "error":
                    result["error"] = data["message"]
    return result | {"latency_s": time.perf_counter() - started}


def grade(question: dict, result: dict, truth: list | None) -> dict:
    """Mark the answer. A check is None when it doesn't apply to this question."""
    used = set(result["tools"])
    answered = bool(result["answer"]) and "error" not in result
    correct = answered
    if truth is not None:
        tolerance = question.get("tolerance", 0)
        correct = answered and all(value_matches(v, result["answer"], tolerance) for v in truth)
    if question.get("must_refuse"):
        correct = answered and result["insufficient"]
    if question.get("needs_citation"):
        correct = correct and result["citations"] >= 1
    router = tools_match(used, question["expected_tools"]) if "expected_tools" in question else None
    return {"correct": correct, "router_correct": router}


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))]


def summarize(rows: list[dict]) -> dict:
    by_category = defaultdict(list)
    for row in rows:
        by_category[row["category"]].append(row["correct"])
    routed = [row["router_correct"] for row in rows if row["router_correct"] is not None]
    # Failed requests are left out of latency and tokens so errors don't flatter the numbers.
    completed = [row for row in rows if "error" not in row]
    latencies = [row["latency_s"] for row in completed]
    return {
        "questions": len(rows),
        "errors": len(rows) - len(completed),
        "accuracy_overall": sum(row["correct"] for row in rows) / len(rows),
        "accuracy_by_category": {
            name: {"correct": sum(items), "total": len(items)}
            for name, items in by_category.items()
        },
        "router_accuracy": sum(routed) / len(routed) if routed else None,
        "router_questions": len(routed),
        "latency_p50_s": round(statistics.median(latencies), 2) if latencies else None,
        "latency_p95_s": round(percentile(latencies, 0.95), 2) if latencies else None,
        "avg_tokens": round(statistics.mean(r["tokens"] for r in completed)) if completed else None,
    }


def write_report(summary: dict, rows: list[dict], stamp: str, base_url: str) -> None:
    overall = summary["accuracy_overall"]
    lines = [
        "# Eval report",
        "",
        f"Run `{stamp}` against the deployed API. Ground truth comes from SQL at eval time.",
        "",
        f"- Overall accuracy: {overall:.0%} of {summary['questions']} questions",
    ]
    if summary["router_accuracy"] is not None:
        router = summary["router_accuracy"]
        lines.append(f"- Router accuracy: {router:.0%} of {summary['router_questions']} questions")
    lines += [
        f"- Latency p50 / p95: {summary['latency_p50_s']} s / {summary['latency_p95_s']} s",
        f"- Average tokens per answer: {summary['avg_tokens']}",
        f"- Failed requests: {summary['errors']}",
        "",
        "| Category | Correct |",
        "|---|---|",
    ]
    for name, score in summary["accuracy_by_category"].items():
        lines.append(f"| {name} | {score['correct']}/{score['total']} |")
    lines += ["", "| Question | Correct | Router | Tools | Latency (s) |", "|---|---|---|---|---|"]
    for row in rows:
        tools = ", ".join(row["tools"]) or "none"
        latency = round(row["latency_s"], 1)
        router = "n/a" if row["router_correct"] is None else row["router_correct"]
        lines.append(f"| {row['id']} | {row['correct']} | {router} | {tools} | {latency} |")
    REPORT.write_text("\n".join(lines) + "\n")


def main() -> None:
    load_dotenv()
    base_url = sys.argv[1].rstrip("/")
    client = bigquery.Client(project=os.environ["GCP_PROJECT_ID"], location="US")
    dataset = os.environ.get("BQ_DATASET", "feedbackpulse")
    questions = yaml.safe_load(QUESTIONS.read_text())

    rows = []
    for index, question in enumerate(questions, start=1):
        truth = None
        if "truth_sql" in question:
            truth = compute_truth(client, dataset, question["truth_sql"])
        result = ask(base_url, question["question"])
        graded = grade(question, result, truth)
        rows.append(
            {
                "id": question["id"],
                "category": question["category"],
                "question": question["question"],
                "truth": [str(value) for value in truth] if truth is not None else None,
                **result,
                **graded,
            }
        )
        print(f"{index}/{len(questions)} {question['id']}: {graded}", flush=True)
        time.sleep(SECONDS_BETWEEN_QUESTIONS)

    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    summary = summarize(rows)
    RESULTS_DIR.mkdir(exist_ok=True)
    payload = {"timestamp": stamp, "summary": summary, "results": rows}
    (RESULTS_DIR / f"{stamp}.json").write_text(json.dumps(payload, indent=2, default=str) + "\n")
    write_report(summary, rows, stamp, base_url)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
