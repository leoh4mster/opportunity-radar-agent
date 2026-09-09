"""Metrics for multi-opportunity extraction and graded recommendation ranking."""
from __future__ import annotations

import math
from difflib import SequenceMatcher
from typing import Any, Callable

from evaluation.datasets import LABELED_STATUSES, normalize_text


def evaluate_extraction(records: list[dict[str, Any]], predictor: Callable[[str, str], list[dict]]) -> dict:
    tp = fp = fn = article_tp = article_fp = article_fn = 0
    correct_fields = total_fields = 0
    field_stats: dict[str, dict[str, int]] = {}
    failures = []
    evaluated = 0
    for record in records:
        annotation = record["annotation"]
        if annotation["status"] not in LABELED_STATUSES:
            continue
        evaluated += 1
        predicted = predictor(record["title"], record["content"])
        predicted = [item for item in predicted if isinstance(item, dict)]
        gold = annotation["opportunities"]
        expected_positive = bool(gold)
        predicted_positive = bool(predicted)
        article_tp += int(expected_positive and predicted_positive)
        article_fp += int(not expected_positive and predicted_positive)
        article_fn += int(expected_positive and not predicted_positive)

        matches = _match_opportunities(gold, predicted)
        tp += len(matches)
        fp += len(predicted) - len(matches)
        fn += len(gold) - len(matches)
        errors = []
        if len(predicted) != len(gold):
            errors.append({"type": "opportunity_count", "expected": len(gold), "actual": len(predicted)})
        matched_gold = {gold_index for gold_index, _ in matches}
        for gold_index in range(len(gold)):
            if gold_index not in matched_gold:
                errors.append({"type": "missed_opportunity", "name": gold[gold_index]["name"]})
        for gold_index, predicted_index in matches:
            expected_fields = gold[gold_index].get("fields") or {}
            actual = predicted[predicted_index]
            for field, expected in expected_fields.items():
                total_fields += 1
                stats = field_stats.setdefault(field, {"correct": 0, "total": 0})
                stats["total"] += 1
                if normalize_text(actual.get(field, "")) == normalize_text(expected):
                    correct_fields += 1
                    stats["correct"] += 1
                else:
                    errors.append({"type": "field", "opportunity": gold[gold_index]["name"],
                                   "field": field, "expected": expected,
                                   "actual": str(actual.get(field, ""))})
        if errors:
            failures.append({"id": record["id"], "errors": errors})

    precision, recall, f1 = _classification(tp, fp, fn)
    article_precision, article_recall, article_f1 = _classification(article_tp, article_fp, article_fn)
    return {
        "evaluated_cases": evaluated,
        "opportunity": {"true_positives": tp, "false_positives": fp, "false_negatives": fn,
                        "precision": precision, "recall": recall, "f1": f1},
        "article_detection": {"true_positives": article_tp, "false_positives": article_fp,
                              "false_negatives": article_fn, "precision": article_precision,
                              "recall": article_recall, "f1": article_f1},
        "field_exact_match": round(correct_fields / total_fields, 4) if total_fields else None,
        "field_stats": {field: {**stats, "exact_match": round(stats["correct"] / stats["total"], 4)}
                        for field, stats in sorted(field_stats.items())},
        "correct_fields": correct_fields,
        "total_fields": total_fields,
        "failures": failures,
    }


def _match_opportunities(gold: list[dict], predicted: list[dict]) -> list[tuple[int, int]]:
    """Deterministic score-first one-to-one matching; article lists are normally small."""
    candidates = []
    for gold_index, expected in enumerate(gold):
        for predicted_index, actual in enumerate(predicted):
            score = _match_score(expected, actual)
            if score > 0:
                candidates.append((score, gold_index, predicted_index))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    used_gold = set()
    used_predicted = set()
    matches = []
    for score, gold_index, predicted_index in candidates:
        if gold_index in used_gold or predicted_index in used_predicted:
            continue
        used_gold.add(gold_index)
        used_predicted.add(predicted_index)
        matches.append((gold_index, predicted_index))
    return matches


def _match_score(expected: dict, actual: dict) -> float:
    if normalize_text(expected.get("category")) != normalize_text(actual.get("category")):
        return 0
    haystack = normalize_text(" ".join(str(actual.get(field) or "")
                                      for field in ("name", "summary", "requirements")))
    keywords = [normalize_text(value) for value in expected.get("match_keywords") or [] if value]
    if keywords and any(value in haystack for value in keywords):
        return 3
    expected_name = normalize_text(expected.get("name"))
    actual_name = normalize_text(actual.get("name"))
    if expected_name and actual_name:
        if expected_name in actual_name or actual_name in expected_name:
            return 2.5
        similarity = SequenceMatcher(None, expected_name, actual_name).ratio()
        if similarity >= 0.45:
            return 1 + similarity
    return 0


def evaluate_ranking(records: list[dict[str, Any]], ranker: Callable[[dict], list[str]], k: int = 3) -> dict:
    rows = []
    failures = []
    for record in records:
        annotation = record["annotation"]
        if annotation["status"] not in LABELED_STATUSES:
            continue
        relevance = {str(key): int(value) for key, value in annotation["relevance"].items()}
        predicted = ranker(record)
        expected_ids = set(relevance)
        filtered = [candidate_id for candidate_id in predicted if candidate_id in expected_ids]
        missing = sorted(expected_ids - set(filtered))
        duplicates = len(filtered) != len(set(filtered))
        if missing or duplicates:
            failures.append({"id": record["id"], "errors": {
                "missing_candidate_ids": missing, "duplicate_predictions": duplicates,
            }})
        # Append missing candidates as worst-ranked so a broken ranker is penalized.
        ranking = list(dict.fromkeys(filtered)) + missing
        positive_count = sum(grade > 0 for grade in relevance.values())
        top = ranking[:k]
        top_positive = sum(relevance[candidate_id] > 0 for candidate_id in top)
        first_positive = next((index for index, candidate_id in enumerate(ranking, 1)
                               if relevance[candidate_id] > 0), None)
        dcg = _dcg([relevance[candidate_id] for candidate_id in ranking[:k]])
        ideal = _dcg(sorted(relevance.values(), reverse=True)[:k])
        pairs = correct_pairs = 0
        positions = {candidate_id: index for index, candidate_id in enumerate(ranking)}
        ids = list(relevance)
        for left_index, left in enumerate(ids):
            for right in ids[left_index + 1:]:
                if relevance[left] == relevance[right]:
                    continue
                pairs += 1
                preferred, other = (left, right) if relevance[left] > relevance[right] else (right, left)
                correct_pairs += int(positions[preferred] < positions[other])
        rows.append({
            "id": record["id"],
            f"ndcg@{k}": round(dcg / ideal, 4) if ideal else 1.0,
            "mrr": round(1 / first_positive, 4) if first_positive else 0.0,
            f"hit_rate@{k}": float(top_positive > 0) if positive_count else 1.0,
            f"precision@{k}": round(top_positive / min(k, len(ranking)), 4) if ranking else 0.0,
            "pairwise_accuracy": round(correct_pairs / pairs, 4) if pairs else 1.0,
            "predicted_order": ranking,
        })
    metric_names = [f"ndcg@{k}", "mrr", f"hit_rate@{k}", f"precision@{k}", "pairwise_accuracy"]
    aggregate = {name: round(sum(row[name] for row in rows) / len(rows), 4) if rows else None
                 for name in metric_names}
    return {"evaluated_cases": len(rows), "k": k, "metrics": aggregate,
            "cases": rows, "failures": failures}


def _dcg(grades: list[int]) -> float:
    return sum((2 ** grade - 1) / math.log2(index + 2) for index, grade in enumerate(grades))


def _classification(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return round(precision, 4), round(recall, 4), round(f1, 4)
