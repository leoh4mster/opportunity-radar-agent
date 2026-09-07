"""Run with python -m evaluation.run. Never reads API credentials or calls an LLM."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.llm_service import LLMService


class OfflineGateway:
    def is_configured(self):
        return False

    def chat(self, *args, **kwargs):
        raise AssertionError("Offline evaluation must never call a remote model")


def evaluate(cases, extractor):
    # Each fixture contains zero or one annotated opportunity. Multi-opportunity
    # extraction needs a separate matching metric, not an assumed item order.
    tp = fp = fn = correct_fields = total_fields = 0
    failures = []
    for case in cases:
        predicted = extractor(case["title"], case["content"])
        expected = case["expected"]
        tp += int(expected is not None and bool(predicted))
        fp += max(0, len(predicted) - int(expected is not None))
        fn += int(expected is not None and not predicted)
        errors = []
        if len(predicted) != int(expected is not None):
            errors.append("opportunity_count")
        if expected is not None:
            actual = predicted[0] if predicted else {}
            for field, value in expected.items():
                total_fields += 1
                # Missing prediction never receives credit for an expected blank.
                if predicted and str(actual.get(field, "")).strip() == value:
                    correct_fields += 1
                else:
                    errors.append(field)
        if errors:
            failures.append({"id": case["id"], "errors": errors})
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "mode": "offline_rules", "dataset": "synthetic-v1", "cases": len(cases),
        "true_positives": tp, "false_positives": fp, "false_negatives": fn,
        "precision": round(precision, 4), "recall": round(recall, 4),
        "f1": round(f1, 4), "field_exact_match": round(correct_fields / total_fields, 4) if total_fields else 0.0,
        "correct_fields": correct_fields, "total_fields": total_fields,
        "failures": failures,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if below the committed baseline floors")
    args = parser.parse_args()
    root = Path(__file__).parent
    cases = json.loads((root / "cases.json").read_text(encoding="utf-8"))
    report = evaluate(cases, LLMService(gateway=OfflineGateway()).extract_opportunities)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.check:
        baseline = json.loads((root / "baseline.json").read_text(encoding="utf-8"))
        return int(any(report[key] < floor for key, floor in baseline["minimum_metrics"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
