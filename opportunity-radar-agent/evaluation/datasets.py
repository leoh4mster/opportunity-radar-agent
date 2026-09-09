"""Versioned JSONL datasets for human-labeled extraction and ranking evaluation."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from app.services.article_identity import compute_content_hash
from app.services.llm_service import CATEGORIES


SCHEMA_VERSION = "1.0"
LABELED_STATUSES = {"labeled", "reviewed"}
ANNOTATION_STATUSES = {"unlabeled", *LABELED_STATUSES}
EXTRACTION_FIELDS = {"deadline", "location", "link", "organizer", "event_time", "requirements"}


class DatasetError(ValueError):
    pass


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.is_file():
        raise DatasetError(f"数据集不存在：{source}")
    records = []
    for line_number, line in enumerate(source.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"第 {line_number} 行不是合法 JSON：{exc.msg}") from exc
        if not isinstance(value, dict):
            raise DatasetError(f"第 {line_number} 行必须是 JSON 对象")
        records.append(value)
    if not records:
        raise DatasetError("数据集不能为空")
    return records


def write_jsonl(path: str | Path, records: Iterable[dict[str, Any]]) -> None:
    """Atomic replacement prevents a stopped annotation UI from truncating data."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = list(records)
    content = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def dataset_fingerprint(records: list[dict[str, Any]]) -> str:
    stable = []
    for record in records:
        copy = dict(record)
        copy.pop("model_suggestions", None)
        copy.pop("model_order", None)
        stable.append(copy)
    encoded = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def dataset_kind(records: list[dict[str, Any]]) -> str:
    kinds = {str(record.get("kind") or "") for record in records}
    if len(kinds) != 1 or next(iter(kinds)) not in {"extraction", "ranking"}:
        raise DatasetError("一个 JSONL 文件只能包含同一种 kind：extraction 或 ranking")
    return next(iter(kinds))


def validate_records(records: list[dict[str, Any]], require_complete: bool = False) -> dict[str, Any]:
    kind = dataset_kind(records)
    errors: list[str] = []
    identifiers: set[str] = set()
    labeled = reviewed = 0
    for index, record in enumerate(records, 1):
        prefix = f"第 {index} 行"
        identifier = str(record.get("id") or "").strip()
        if not identifier:
            errors.append(f"{prefix}：id 不能为空")
        elif identifier in identifiers:
            errors.append(f"{prefix}：id 重复：{identifier}")
        identifiers.add(identifier)
        if record.get("schema_version") != SCHEMA_VERSION:
            errors.append(f"{prefix}：schema_version 必须是 {SCHEMA_VERSION}")
        annotation = record.get("annotation")
        if not isinstance(annotation, dict):
            errors.append(f"{prefix}：annotation 必须是对象")
            continue
        status = annotation.get("status")
        if status not in ANNOTATION_STATUSES:
            errors.append(f"{prefix}：annotation.status 不合法")
            continue
        labeled += int(status in LABELED_STATUSES)
        reviewed += int(status == "reviewed")
        if require_complete and status not in LABELED_STATUSES:
            errors.append(f"{prefix}：仍未完成标注")
        if kind == "extraction":
            errors.extend(_validate_extraction(record, annotation, prefix))
        else:
            errors.extend(_validate_ranking(record, annotation, prefix))
    return {
        "valid": not errors,
        "kind": kind,
        "records": len(records),
        "labeled": labeled,
        "reviewed": reviewed,
        "unlabeled": len(records) - labeled,
        "fingerprint": dataset_fingerprint(records),
        "errors": errors,
    }


def require_valid(records: list[dict[str, Any]], require_complete: bool = False) -> dict[str, Any]:
    report = validate_records(records, require_complete=require_complete)
    if report["errors"]:
        preview = "；".join(report["errors"][:10])
        suffix = f"（另有 {len(report['errors']) - 10} 条）" if len(report["errors"]) > 10 else ""
        raise DatasetError(preview + suffix)
    return report


def _validate_extraction(record: dict[str, Any], annotation: dict[str, Any], prefix: str) -> list[str]:
    errors = []
    title = record.get("title")
    content = record.get("content")
    if not isinstance(title, str) or not title.strip():
        errors.append(f"{prefix}：title 不能为空")
    if not isinstance(content, str) or not content.strip():
        errors.append(f"{prefix}：content 不能为空")
    elif record.get("content_hash") != compute_content_hash(content):
        errors.append(f"{prefix}：content_hash 与正文不一致")
    opportunities = annotation.get("opportunities")
    if not isinstance(opportunities, list):
        errors.append(f"{prefix}：annotation.opportunities 必须是数组")
        return errors
    has_opportunity = annotation.get("has_opportunity")
    status = annotation.get("status")
    if status in LABELED_STATUSES:
        if not isinstance(has_opportunity, bool):
            errors.append(f"{prefix}：完成标注后 has_opportunity 必须是布尔值")
        elif has_opportunity != bool(opportunities):
            errors.append(f"{prefix}：has_opportunity 与 opportunities 是否为空不一致")
    for item_index, item in enumerate(opportunities, 1):
        item_prefix = f"{prefix}机会 {item_index}"
        if not isinstance(item, dict):
            errors.append(f"{item_prefix}：必须是对象")
            continue
        if not str(item.get("name") or "").strip():
            errors.append(f"{item_prefix}：name 不能为空")
        if item.get("category") not in CATEGORIES:
            errors.append(f"{item_prefix}：category 不在允许列表")
        keywords = item.get("match_keywords", [])
        if not isinstance(keywords, list) or any(not isinstance(value, str) for value in keywords):
            errors.append(f"{item_prefix}：match_keywords 必须是字符串数组")
        fields = item.get("fields", {})
        if not isinstance(fields, dict):
            errors.append(f"{item_prefix}：fields 必须是对象")
        else:
            unknown = set(fields) - EXTRACTION_FIELDS
            if unknown:
                errors.append(f"{item_prefix}：未知评测字段 {sorted(unknown)}")
            if any(not isinstance(value, str) for value in fields.values()):
                errors.append(f"{item_prefix}：fields 的值必须是字符串")
    return errors


def _validate_ranking(record: dict[str, Any], annotation: dict[str, Any], prefix: str) -> list[str]:
    errors = []
    profile = record.get("profile")
    if not isinstance(profile, dict):
        errors.append(f"{prefix}：profile 必须是对象")
    else:
        for field in ("current_goals", "skills", "interested_fields", "disliked_contents"):
            value = profile.get(field, [])
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                errors.append(f"{prefix}：profile.{field} 必须是字符串数组")
    try:
        date.fromisoformat(str(record.get("as_of") or ""))
    except ValueError:
        errors.append(f"{prefix}：as_of 必须是 YYYY-MM-DD")
    candidates = record.get("candidates")
    if not isinstance(candidates, list) or len(candidates) < 2:
        errors.append(f"{prefix}：至少需要两个候选机会")
        return errors
    candidate_ids = [str(item.get("id") or "") for item in candidates if isinstance(item, dict)]
    if len(candidate_ids) != len(candidates) or any(not value for value in candidate_ids):
        errors.append(f"{prefix}：每个候选机会都必须有 id")
    if len(set(candidate_ids)) != len(candidate_ids):
        errors.append(f"{prefix}：候选机会 id 重复")
    for candidate_index, candidate in enumerate(candidates, 1):
        if not isinstance(candidate, dict):
            continue
        if not str(candidate.get("name") or "").strip():
            errors.append(f"{prefix}候选 {candidate_index}：name 不能为空")
        if candidate.get("category") not in CATEGORIES:
            errors.append(f"{prefix}候选 {candidate_index}：category 不在允许列表")
        for field in ("benefit", "cost", "credibility"):
            try:
                value = float(candidate.get(field, 0.6))
                if not 0 <= value <= 1:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append(f"{prefix}候选 {candidate_index}：{field} 必须是 0-1 数字")
    relevance = annotation.get("relevance")
    if not isinstance(relevance, dict):
        errors.append(f"{prefix}：annotation.relevance 必须是对象")
        return errors
    if set(relevance) != set(candidate_ids):
        errors.append(f"{prefix}：relevance 的候选 id 必须与 candidates 完全一致")
    status = annotation.get("status")
    for candidate_id, grade in relevance.items():
        if grade is None and status == "unlabeled":
            continue
        if type(grade) is not int or not 0 <= grade <= 3:
            errors.append(f"{prefix}：{candidate_id} 的相关性必须是 0-3 整数")
    return errors


def merge_human_annotations(new_records: list[dict[str, Any]], old_records: list[dict[str, Any]]) -> int:
    """Preserve labels only when the immutable content/candidate identity matches."""
    old_by_key = {_merge_key(record): record for record in old_records}
    preserved = 0
    for record in new_records:
        previous = old_by_key.get(_merge_key(record))
        if previous and isinstance(previous.get("annotation"), dict):
            record["annotation"] = previous["annotation"]
            preserved += int(previous["annotation"].get("status") in LABELED_STATUSES)
    return preserved


def _merge_key(record: dict[str, Any]) -> tuple[str, str]:
    if record.get("kind") == "extraction":
        return "extraction", str(record.get("content_hash") or "")
    identity = {
        "profile": record.get("profile") or {},
        "as_of": record.get("as_of"),
        "candidates": sorted(record.get("candidates") or [], key=lambda item: str(item.get("id") or "")),
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "ranking", hashlib.sha256(encoded).hexdigest()


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()
