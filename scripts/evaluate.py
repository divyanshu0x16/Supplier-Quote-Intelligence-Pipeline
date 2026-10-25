"""Measure the pipeline against ground truth and save a report (M8). No database involved.

Usage: uv run python scripts/evaluate.py [--workers 8]      (42 LLM calls, about $0.01)
Writes eval_reports/<timestamp>_<model>.json (for comparing runs) and .md (for reading), and prints the change
in each field's accuracy since the previous report.
"""

import argparse
import json
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from common import DATA, RECEIVED_ON, build_pipeline, generated_documents, supplier_from_filename

from quote_pipeline.config import get_settings
from quote_pipeline.domain.models import Outcome

FIELDS = ["supplier", "part_number", "unit_price", "currency", "moq", "lead_time_days", "valid_until"]
REPORTS = Path("eval_reports")


def run(workers: int) -> list[Outcome]:
    pipeline = build_pipeline(get_settings())

    def process(doc: tuple[Path, str]) -> list[Outcome]:
        path, source_file = doc
        return pipeline.process_file(path, source_file, RECEIVED_ON, supplier_from_filename(source_file))

    # The LLM calls spend nearly all their time waiting on the network, so threads run them in parallel well.
    # pool.map keeps the results in the same order as the input.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return [o for outcomes in pool.map(process, generated_documents()) for o in outcomes]


def field_matches(field: str, got, expected) -> bool:
    if field == "unit_price" and got is not None and expected is not None:
        return abs(got - expected) < 1e-6  # floats: compare with a tolerance, never with ==
    return got == expected


def score(outcomes: list[Outcome], truth: dict) -> dict:
    rows = []
    for o in outcomes:
        t = truth[(o.source_file, o.row)]
        got = o.quote.model_dump(mode="json") if o.quote else {}  # no quote at all = every field wrong
        matches = {f: field_matches(f, got.get(f), t[f]) for f in FIELDS}
        rows.append({
            "doc": o.source_file + (f" #{o.row}" if o.row else ""),
            "format": o.source_file.split("/")[0],
            "expected": "valid" if t["expected_valid"] else "needs_review",
            "status": o.status,
            "issues": o.issues,
            "planted": t["issues"],
            "fields": matches,
            "wrong": {f: {"expected": t[f], "got": got.get(f)} for f in FIELDS if not matches[f]},
            "cost_usd": o.extraction.cost_usd if o.extraction else 0.0,
            "latency_ms": o.extraction.latency_ms if o.extraction else None,
        })

    formats = sorted({r["format"] for r in rows})

    def accuracy(subset: list[dict], f: str) -> float:
        return sum(r["fields"][f] for r in subset) / len(subset)

    field_accuracy = {f: {"all": accuracy(rows, f),
                          **{fmt: accuracy([r for r in rows if r["format"] == fmt], f) for fmt in formats}}
                      for f in FIELDS}

    def count(expected: str, status: str) -> int:
        return sum(r["expected"] == expected and r["status"] == status for r in rows)

    routing = {
        "faults_caught": count("needs_review", "needs_review"),
        "faults_missed": count("needs_review", "valid"),  # the dangerous kind: a bad quote marked valid
        "false_alarms": count("valid", "needs_review"),  # the cheap kind: a reviewer spends a few seconds
        "valid_passed": count("valid", "valid"),
    }
    fault_types = sorted({p for r in rows for p in r["planted"]})
    faults = {ft: {"caught": sum(ft in r["planted"] and r["status"] == "needs_review" for r in rows),
                   "total": sum(ft in r["planted"] for r in rows)} for ft in fault_types}

    latencies = sorted(r["latency_ms"] for r in rows if r["latency_ms"] is not None)
    return {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "model": get_settings().llm_model,
        "quotes": len(rows),
        "cost_usd": round(sum(r["cost_usd"] for r in rows), 6),
        "latency_ms": {"p50": round(statistics.median(latencies)),
                       "p95": round(statistics.quantiles(latencies, n=20)[-1])},  # slowest 1 in 20 calls
        "field_accuracy": field_accuracy,
        "routing": routing,
        "faults": faults,
        "rows": rows,
    }


def to_markdown(r: dict) -> str:
    formats = [k for k in next(iter(r["field_accuracy"].values())) if k != "all"]
    pct = lambda x: f"{x:.0%}"  # noqa: E731
    lines = [
        f"# Eval report: {r['model']}, {r['run_at']}",
        "",
        f"{r['quotes']} quotes · cost ${r['cost_usd']:.4f} · latency p50 {r['latency_ms']['p50']} ms, "
        f"p95 {r['latency_ms']['p95']} ms",
        "",
        "## Field accuracy",
        "",
        "| field | all | " + " | ".join(formats) + " |",
        "|---|---|" + "---|" * len(formats),
        *[f"| {f} | {pct(a['all'])} | " + " | ".join(pct(a[fmt]) for fmt in formats) + " |"
          for f, a in r["field_accuracy"].items()],
        "",
        "Note: CSV rows don't name the supplier; it's filled from ingestion metadata, not read by the model.",
        "",
        "## Routing",
        "",
        "| | count |",
        "|---|---|",
        f"| faults caught | {r['routing']['faults_caught']} |",
        f"| **faults missed** (bad quote marked valid) | **{r['routing']['faults_missed']}** |",
        f"| false alarms (good quote sent to review) | {r['routing']['false_alarms']} |",
        f"| valid quotes passed | {r['routing']['valid_passed']} |",
        "",
        "## Planted faults",
        "",
        "| fault | caught |",
        "|---|---|",
        *[f"| {ft} | {v['caught']}/{v['total']} |" for ft, v in r["faults"].items()],
        "",
        "## Wrong fields",
        "",
    ]
    wrong = [(row["doc"], f, v) for row in r["rows"] for f, v in row["wrong"].items()]
    if wrong:
        lines += ["| document | field | expected | got |", "|---|---|---|---|",
                  *[f"| {d} | {f} | {v['expected']} | {v['got']} |" for d, f, v in wrong]]
    else:
        lines.append("None.")
    misrouted = [row for row in r["rows"] if row["status"] != row["expected"]]
    lines += ["", "## Misrouted quotes", ""]
    if misrouted:
        lines += ["| document | expected | got | reasons |", "|---|---|---|---|",
                  *[f"| {m['doc']} | {m['expected']} | {m['status']} | {'; '.join(m['issues'])} |" for m in misrouted]]
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def print_change_since(previous: Path, report: dict) -> None:
    before = json.loads(previous.read_text())["field_accuracy"]
    print(f"\nChange since {previous.name}:")
    for f, a in report["field_accuracy"].items():
        old = before.get(f, {}).get("all")
        delta = "" if old is None else f"  ({(a['all'] - old) * 100:+.1f} points)"
        print(f"  {f:15} {a['all']:.0%}{delta}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    truth = {(t["source_file"], t["row"]): t
             for t in map(json.loads, (DATA / "ground_truth.jsonl").read_text(encoding="utf-8").splitlines())}
    report = score(run(args.workers), truth)

    REPORTS.mkdir(exist_ok=True)
    previous = sorted(REPORTS.glob("*.json"))[-1:]  # the latest earlier report, if any
    stem = REPORTS / f"{datetime.now():%Y%m%d-%H%M%S}_{report['model']}"
    stem.with_suffix(".json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    stem.with_suffix(".md").write_text(to_markdown(report))

    print(to_markdown(report))
    if previous:
        print_change_since(previous[0], report)
    print(f"\nSaved {stem}.md and .json")


if __name__ == "__main__":
    main()
