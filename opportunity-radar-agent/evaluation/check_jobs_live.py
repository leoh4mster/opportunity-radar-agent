"""Opt-in synthetic HTTP + lifespan-worker acceptance. Search transport is fake."""
from datetime import datetime, timedelta, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit
from unittest.mock import patch


def run_check(allow_network=False, max_requests=16):
    if not allow_network:
        raise ValueError("真实 API 检查可能计费，请显式添加 --allow-network")
    if not 1 <= max_requests <= 16:
        raise ValueError("请求上限必须为 1 到 16")
    if "app.core.database" in sys.modules or "app.core.config" in sys.modules:
        raise ValueError("必须在独立进程中运行")
    project = Path(__file__).resolve().parents[1]
    report = {"ok": False, "scope": "synthetic_http_durable_worker_real_deepseek_fake_search",
              "max_requests": max_requests, "requests": [], "jobs": [],
              "source_sha256": {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted((project / "app").rglob("*.py"))},
              "limitations": ["虚构数据，不代表真实语料效果", "搜索 transport 为测试替身，不是实际联网搜索", "浏览器验收单独记录"]}
    directory = project / "evaluation/private/jobs-live"
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="radar-jobs-live-") as temp:
        os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(temp) / "test.db")
        from fastapi.testclient import TestClient
        from app.core.config import get_settings
        from app.core.database import engine
        from app.main import app
        from app.services.llm_gateway import LLMGateway
        from app.services.external_search_provider import ExternalSearchResponse, ExternalSearchResult
        settings = get_settings()
        endpoint = urlsplit(settings.deepseek_base_url)
        if endpoint.scheme != "https" or endpoint.hostname != "api.deepseek.com" or endpoint.port not in (None, 443) or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
            raise ValueError("只允许 DeepSeek 官方 HTTPS 端点")
        if not LLMGateway().is_configured():
            raise ValueError("未配置 DeepSeek Key")
        report["model"] = settings.llm_model
        original = LLMGateway._post_json
        guard = threading.Lock()
        def tracked(gateway, url, key, payload):
            with guard:
                if len(report["requests"]) >= max_requests:
                    raise RuntimeError("request budget exhausted")
                record = {"status": "started"}
                report["requests"].append(record)
            before = time.monotonic()
            try:
                value = original(gateway, url, key, payload)
                record.update(status="success", usage=value.get("usage") or {})
                return value
            except Exception:
                record["status"] = "failed"
                raise
            finally:
                record["duration_ms"] = round((time.monotonic() - before) * 1000)
        def wait_job(client, job):
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                row = client.get(job["status_url"]).json()
                if row["status"] not in {"queued", "running"}:
                    report["jobs"].append(row)
                    assert row["status"] == "succeeded", f"{row['kind']}: {row['error_code']}"
                    assert row["mode"] == "deepseek"
                    return row
                time.sleep(0.2)
            raise AssertionError("job timed out")
        fake_sources = ExternalSearchResponse(status="success", provider="fixture", query="虚构测试",
            results=[ExternalSearchResult(title="虚构验收资料（不是真实网站）", url="https://example.invalid/synthetic",
                                          snippet="虚构 RAG 项目，线上参与，需 Python 基础，仅用于软件验收。")])
        try:
            with patch.object(LLMGateway, "_post_json", tracked), \
                 patch("app.services.job_handlers.BochaSearchProvider.search", return_value=fake_sources), \
                 TestClient(app) as client:
                uid = client.post("/profiles", json={"name": "虚构可靠任务验收用户", "major_direction": "计算机",
                    "current_goals": ["找实习"], "skills": ["Python"], "interested_fields": ["RAG"],
                    "detailed_needs": "希望每周用四小时完成线上 RAG 项目。"}).json()["id"]
                cutoff = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
                article = {"title": "虚构大学 RAG 实习招募（软件验收用）", "content":
                    f"虚构大学智能系统实验室发布 RAG 实习招募，欢迎本科生报名。地点：线上。报名截止：{cutoff}。"
                    "项目目标是用 Python 构建文档检索、问答和评测程序。每周投入四小时，周期六周。"
                    "需要 Python 和基础机器学习知识。参与者将先整理文档，再实现检索与回答，最后完成评测报告。"
                    "没有真实报名链接，此通知及机构均为软件验收虚构数据，不代表真实招聘。"}
                accepted = client.post("/articles/ingest-clean", json=article)
                assert accepted.status_code == 202
                job = accepted.json()["job"]
                duplicate = client.post("/articles/ingest-clean", json=article).json()
                assert duplicate["duplicate"] and duplicate["job"]["id"] == job["id"]
                wait_job(client, job)
                opportunities = client.get("/opportunities").json()
                assert len(opportunities) == 1, "expected one fictional opportunity"
                oid = opportunities[0]["id"]
                wait_job(client, client.post(f"/recommendations/generate/{uid}").json()["job"])
                assert client.get(f"/recommendations/{uid}").json()
                analysis = client.post(f"/tools/opportunity-progress/{uid}/{oid}/analyze").json()
                wait_job(client, analysis["job"])
                check = client.post(f"/tools/opportunity-progress/tasks/{analysis['task']['id']}/web-check").json()
                wait_job(client, check["job"])
                report["ok"] = True
        except Exception as exc:
            report["error_type"] = type(exc).__name__
            report["error"] = str(exc) if isinstance(exc, AssertionError) else "检查失败；未输出异常原文"
        finally:
            report["duration_ms"] = round((time.monotonic() - started) * 1000)
            report["tokens"] = sum(int(r.get("usage", {}).get("total_tokens") or 0) for r in report["requests"])
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            engine.dispose()
    return report, output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--max-requests", type=int, default=16)
    args = parser.parse_args()
    report, output = run_check(args.allow_network, args.max_requests)
    print(json.dumps({"ok": report["ok"], "requests": len(report["requests"]), "tokens": report["tokens"],
                      "duration_ms": report["duration_ms"], "report": str(output), "error": report.get("error")}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
