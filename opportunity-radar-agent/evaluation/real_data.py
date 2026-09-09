"""Build, validate and evaluate private human-labeled corpora.

No command calls a remote model unless --mode deepseek and --allow-network are
both present. Run `python -m evaluation.real_data --help` for workflows.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.observability import runtime_metrics
from app.models.entities import Article, Opportunity, Recommendation, UserProfile
from app.services.article_identity import compute_content_hash
from app.services.json_utils import dumps
from app.services.llm_gateway import LLMGateway, LLMGatewayError
from app.services.llm_service import LLMService
from app.services.matching_service import MatchingService
from evaluation.datasets import (
    DatasetError, SCHEMA_VERSION, dataset_fingerprint, load_jsonl,
    merge_human_annotations, require_valid, validate_records, write_jsonl,
)
from evaluation.metrics import evaluate_extraction, evaluate_ranking
from evaluation.run import OfflineGateway


DEFAULT_EXTRACTION_PATH = Path("evaluation/private/extraction.jsonl")
DEFAULT_RANKING_PATH = Path("evaluation/private/ranking.jsonl")


def export_extraction_queue(db: Session, output: str | Path, limit: int = 200) -> dict[str, Any]:
    target = Path(output)
    old = load_jsonl(target) if target.is_file() else []
    articles = db.query(Article).order_by(Article.id.asc()).limit(limit).all()
    records = []
    for article in articles:
        digest = compute_content_hash(article.content)
        suggestions = []
        for opportunity in sorted(article.opportunities, key=lambda item: item.id):
            suggestions.append({
                "name": opportunity.name,
                "category": opportunity.category,
                "deadline": opportunity.deadline or "",
                "location": opportunity.location or "",
                "link": opportunity.link or "",
                "organizer": opportunity.organizer or "",
            })
        records.append({
            "schema_version": SCHEMA_VERSION,
            "kind": "extraction",
            "id": f"article-{digest[:16]}",
            "content_hash": digest,
            "provenance": {
                "source": article.source or "",
                "published_at": article.published_at or "",
                "source_url": article.url or "",
                "local_article_id": article.id,
            },
            "title": article.title,
            "content": article.content,
            # Suggestions are explicitly excluded from the dataset fingerprint
            # and metrics. They are never promoted to gold automatically.
            "model_suggestions": suggestions,
            "annotation": {"status": "unlabeled", "has_opportunity": None,
                           "opportunities": [], "notes": ""},
        })
    preserved = merge_human_annotations(records, old)
    require_valid(records)
    write_jsonl(target, records)
    return {"kind": "extraction", "records": len(records), "preserved_labels": preserved,
            "output": str(target), "fingerprint": dataset_fingerprint(records)}


def export_ranking_queue(db: Session, output: str | Path, profile_id: int | None = None,
                         as_of: str | None = None) -> dict[str, Any]:
    target = Path(output)
    old = load_jsonl(target) if target.is_file() else []
    profile = db.get(UserProfile, profile_id) if profile_id is not None else db.query(UserProfile).order_by(UserProfile.id).first()
    if profile is None:
        raise DatasetError("没有可导出的用户画像，请先在页面中创建画像")
    opportunities = db.query(Opportunity).order_by(Opportunity.id).all()
    if len(opportunities) < 2:
        raise DatasetError("推荐评测至少需要两个候选机会")
    candidates = [
        {
            "id": f"opportunity-{item.id}", "name": item.name, "category": item.category,
            "organizer": item.organizer or "", "event_time": item.event_time or "",
            "deadline": item.deadline or "", "location": item.location or "",
            "target_audience": item.target_audience or "", "requirements": item.requirements or "",
            "summary": item.summary or "", "link": item.link or "",
            "benefit": item.benefit, "cost": item.cost, "credibility": item.credibility,
            "verification_status": item.verification_status or "",
            "credibility_score": item.credibility_score, "risk_level": item.risk_level or "",
        }
        for item in opportunities
    ]
    recommendation_ids = [row[0] for row in (
        db.query(Recommendation.opportunity_id)
        .filter(Recommendation.user_id == profile.id)
        .order_by(Recommendation.total_score.desc()).all()
    )]
    candidate_digest = compute_content_hash("\n".join(item["id"] for item in candidates))[:12]
    record = {
        "schema_version": SCHEMA_VERSION,
        "kind": "ranking",
        "id": f"profile-{profile.id}-{candidate_digest}",
        "as_of": as_of or date.today().isoformat(),
        "profile": {
            # Name is intentionally omitted; ranking only needs preferences.
            "major_direction": profile.major_direction or "",
            "grade_identity": profile.grade_identity or "",
            "current_goals": _json_list(profile.current_goals),
            "skills": _json_list(profile.skills),
            "interested_fields": _json_list(profile.interested_fields),
            "disliked_contents": _json_list(profile.disliked_contents),
            "detailed_needs": profile.detailed_needs or "",
            "time_preference": profile.time_preference or "",
            "location_preference": profile.location_preference or "",
        },
        "candidates": candidates,
        "model_order": [f"opportunity-{item_id}" for item_id in recommendation_ids],
        "annotation": {"status": "unlabeled",
                       "relevance": {item["id"]: None for item in candidates}, "notes": ""},
    }
    records = [record]
    preserved = merge_human_annotations(records, old)
    require_valid(records)
    write_jsonl(target, records)
    return {"kind": "ranking", "records": 1, "candidates": len(candidates),
            "preserved_labels": preserved, "output": str(target),
            "fingerprint": dataset_fingerprint(records)}


def _json_list(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def evaluator_for_mode(mode: str, allow_network: bool) -> LLMService:
    if mode == "rules":
        return LLMService(gateway=OfflineGateway())
    if not allow_network:
        raise DatasetError("DeepSeek 评测会发送标注集正文并可能产生费用；请确认后显式添加 --allow-network")
    gateway = LLMGateway()
    if not gateway.is_configured():
        raise DatasetError("未配置你自己的 DEEPSEEK_API_KEY，无法运行 deepseek 模式")
    return LLMService(gateway=gateway, allow_local_fallback=False)


def rank_record(record: dict[str, Any], llm: LLMService) -> list[str]:
    """Exercise the production ranking service in an isolated in-memory DB."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        profile_data = record["profile"]
        profile = UserProfile(
            name="evaluation-user",
            major_direction=str(profile_data.get("major_direction") or ""),
            grade_identity=str(profile_data.get("grade_identity") or ""),
            current_goals=dumps(profile_data.get("current_goals") or []),
            skills=dumps(profile_data.get("skills") or []),
            interested_fields=dumps(profile_data.get("interested_fields") or []),
            disliked_contents=dumps(profile_data.get("disliked_contents") or []),
            detailed_needs=str(profile_data.get("detailed_needs") or ""),
            time_preference=str(profile_data.get("time_preference") or ""),
            location_preference=str(profile_data.get("location_preference") or ""),
        )
        session.add(profile)
        session.flush()
        id_map = {}
        for candidate in record["candidates"]:
            article = Article(title=candidate["name"], content=f"{candidate['id']}\n{candidate.get('summary', '')}")
            session.add(article)
            session.flush()
            opportunity = Opportunity(
                article_id=article.id,
                name=candidate["name"], category=candidate["category"],
                organizer=str(candidate.get("organizer") or ""),
                event_time=str(candidate.get("event_time") or ""),
                deadline=str(candidate.get("deadline") or ""),
                location=str(candidate.get("location") or ""),
                target_audience=str(candidate.get("target_audience") or ""),
                requirements=str(candidate.get("requirements") or ""),
                summary=str(candidate.get("summary") or ""),
                link=str(candidate.get("link") or ""),
                benefit=float(candidate.get("benefit", 0.6)),
                cost=float(candidate.get("cost", 0.4)),
                credibility=float(candidate.get("credibility", 0.7)),
                verification_status=str(candidate.get("verification_status") or ""),
                credibility_score=candidate.get("credibility_score"),
                risk_level=str(candidate.get("risk_level") or ""),
            )
            session.add(opportunity)
            session.flush()
            id_map[opportunity.id] = candidate["id"]
        session.commit()
        service = MatchingService(llm=llm, today=date.fromisoformat(record["as_of"]), strict_llm=True)
        recommendations = service.generate_for_user(session, profile.id, force=True)
        return [id_map[row.opportunity_id] for row in recommendations]
    finally:
        session.close()
        engine.dispose()


def evaluate_task(task: str, records: list[dict[str, Any]], mode: str,
                  allow_network: bool, k: int = 3) -> dict[str, Any]:
    validation = require_valid(records, require_complete=True)
    if validation["kind"] != task:
        raise DatasetError(f"数据集 kind={validation['kind']}，不能执行 {task} 评测")
    runtime_metrics.reset()
    llm = evaluator_for_mode(mode, allow_network)
    if task == "extraction":
        metrics = evaluate_extraction(records, llm.extract_opportunities)
    else:
        metrics = evaluate_ranking(records, lambda record: rank_record(record, llm), k=k)
    return {"task": task, "mode": mode, "schema_version": SCHEMA_VERSION,
            "dataset_fingerprint": validation["fingerprint"], **metrics,
            "llm_execution": runtime_metrics.snapshot()["llm"]}


def check_baseline(report: dict[str, Any], baseline_path: str | Path) -> list[dict[str, Any]]:
    try:
        baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetError("baseline 文件无法读取或不是有效 JSON") from exc
    if not isinstance(baseline, dict):
        raise DatasetError("baseline 顶层必须是 JSON 对象")
    if baseline.get("task") != report.get("task"):
        raise DatasetError("baseline task 与评测任务不一致")
    expected_fingerprint = baseline.get("dataset_fingerprint")
    if expected_fingerprint and expected_fingerprint != report.get("dataset_fingerprint"):
        raise DatasetError("baseline 对应的数据指纹不同；请审阅数据变更后重新建立基线")
    regressions = []
    for path, minimum in (baseline.get("minimum_metrics") or {}).items():
        value: Any = report
        try:
            for part in path.split("."):
                value = value[part]
            passed = value is not None and float(value) >= float(minimum)
        except (KeyError, TypeError, ValueError):
            passed = False
            value = None
        if not passed:
            regressions.append({"metric": path, "actual": value, "minimum": minimum})
    return regressions


def write_report(path: str | Path, report: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    export_extraction = subparsers.add_parser("export-extraction", help="Export DB articles as an unlabeled private queue")
    export_extraction.add_argument("--output", default=str(DEFAULT_EXTRACTION_PATH))
    export_extraction.add_argument("--limit", type=int, default=200)
    export_ranking = subparsers.add_parser("export-ranking", help="Export one profile and candidate set")
    export_ranking.add_argument("--output", default=str(DEFAULT_RANKING_PATH))
    export_ranking.add_argument("--profile-id", type=int)
    export_ranking.add_argument("--as-of")
    validate = subparsers.add_parser("validate", help="Validate schema and annotation progress")
    validate.add_argument("dataset")
    validate.add_argument("--require-complete", action="store_true")
    evaluate = subparsers.add_parser("evaluate", help="Evaluate a complete extraction or ranking set")
    evaluate.add_argument("task", choices=["extraction", "ranking"])
    evaluate.add_argument("dataset")
    evaluate.add_argument("--mode", choices=["rules", "deepseek"], default="rules")
    evaluate.add_argument("--allow-network", action="store_true")
    evaluate.add_argument("--k", type=int, default=3)
    evaluate.add_argument("--output")
    evaluate.add_argument("--baseline")
    compare = subparsers.add_parser("compare", help="Compare rules with DeepSeek on the same fingerprint")
    compare.add_argument("task", choices=["extraction", "ranking"])
    compare.add_argument("dataset")
    compare.add_argument("--allow-network", action="store_true")
    compare.add_argument("--k", type=int, default=3)
    compare.add_argument("--output")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command.startswith("export-"):
            from app.core.database import SessionLocal
            with SessionLocal() as db:
                if args.command == "export-extraction":
                    report = export_extraction_queue(db, args.output, args.limit)
                else:
                    report = export_ranking_queue(db, args.output, args.profile_id, args.as_of)
        elif args.command == "validate":
            report = validate_records(load_jsonl(args.dataset), require_complete=args.require_complete)
            if report["errors"]:
                print(json.dumps(report, ensure_ascii=False, indent=2))
                return 1
        elif args.command == "evaluate":
            report = evaluate_task(args.task, load_jsonl(args.dataset), args.mode,
                                   args.allow_network, args.k)
            if args.baseline:
                report["regressions"] = check_baseline(report, args.baseline)
        else:
            records = load_jsonl(args.dataset)
            rules = evaluate_task(args.task, records, "rules", False, args.k)
            deepseek = evaluate_task(args.task, records, "deepseek", args.allow_network, args.k)
            report = {"task": args.task, "dataset_fingerprint": rules["dataset_fingerprint"],
                      "rules": rules, "deepseek": deepseek}
        if getattr(args, "output", None) and not args.command.startswith("export-"):
            write_report(args.output, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return int(bool(report.get("regressions")))
    except DatasetError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    except LLMGatewayError as exc:
        print(json.dumps({
            "ok": False,
            "error": "DeepSeek 评测失败；未生成或保存评测成绩",
            "error_type": type(exc).__name__,
        }, ensure_ascii=False, indent=2))
        return 3
    except RuntimeError as exc:
        print(json.dumps({
            "ok": False,
            "error": "模型输出校验失败；未生成或保存评测成绩",
            "error_type": type(exc).__name__,
        }, ensure_ascii=False, indent=2))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
