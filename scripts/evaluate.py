"""Run every generated document through the pipeline (no database) and compare with ground truth.

Usage: uv run python scripts/evaluate.py      (about 42 LLM calls, roughly $0.01)
"""

import json

from common import DATA, RECEIVED_ON, build_pipeline, generated_documents, supplier_from_filename

from quote_pipeline.config import get_settings

FIELDS = ["supplier", "part_number", "unit_price", "currency", "moq", "lead_time_days", "valid_until"]


def main() -> None:
    pipeline = build_pipeline(get_settings())
    truth = {(t["source_file"], t["row"]): t
             for t in map(json.loads, (DATA / "ground_truth.jsonl").read_text(encoding="utf-8").splitlines())}

    outcomes = []
    for path, source_file in generated_documents():
        outcomes += pipeline.process_file(path, source_file, RECEIVED_ON, supplier_from_filename(source_file))

    print(f"{'document':32} {'status':13} {'expected':13} reasons")
    correct_status = 0
    field_hits = dict.fromkeys(FIELDS, 0)
    for o in outcomes:
        t = truth[(o.source_file, o.row)]
        expected = "valid" if t["expected_valid"] else "needs_review"
        correct_status += o.status == expected
        mark = "" if o.status == expected else "  <-- MISMATCH"
        name = o.source_file + (f" #{o.row}" if o.row else "")
        print(f"{name:32} {o.status:13} {expected:13} {'; '.join(o.issues)}{mark}")
        if o.quote:
            got = o.quote.model_dump(mode="json")  # dates -> "YYYY-MM-DD", same as ground truth
            for f in FIELDS:
                field_hits[f] += got[f] == t[f]

    n = len(outcomes)
    total_cost = sum(o.extraction.cost_usd for o in outcomes if o.extraction)
    print(f"\nRouting: {correct_status}/{n} quotes routed as expected")
    print("Field accuracy: " + ", ".join(f"{f} {field_hits[f]}/{n}" for f in FIELDS))
    print(f"Cost: ${total_cost:.4f} for {n} quotes")


if __name__ == "__main__":
    main()
