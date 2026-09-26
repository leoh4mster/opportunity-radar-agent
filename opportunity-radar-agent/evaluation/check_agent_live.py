"""Opt-in real-model service-chain acceptance using synthetic data and a disposable DB.

Run in a fresh process: python -m evaluation.check_agent_live --allow-network
No personal corpus, application database, web search or external action is used.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from unittest.mock import patch


def run_check(allow_network: bool, max_requests: int = 16) -> tuple[dict, Path]:
    if not allow_network:
        raise ValueError('真实 API 检查可能计费，请显式添加 --allow-network。')
    if 'app.core.database' in sys.modules or 'app.core.config' in sys.modules:
        raise ValueError('请用独立进程运行，以保证临时数据库隔离。')
    if not 1 <= max_requests <= 20:
        raise ValueError('max-requests 必须在 1 到 20 之间。')
    report_dir = Path(__file__).resolve().parent / 'private' / 'agent-live'
    report_dir.mkdir(parents=True, exist_ok=True)
    output = report_dir / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    project = Path(__file__).resolve().parents[1]
    report = {'ok': False, 'scope': 'synthetic_service_chain_real_deepseek',
              'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'code_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              'source_sha256': {str(path.relative_to(project)): hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in [Path(__file__).resolve(), *sorted((project / 'app').rglob('*.py'))]},
              'max_http_requests': max_requests, 'steps': [], 'requests': [],
              'limitations': ['服务层集成测试；后台 worker 同步运行，未测试浏览器或重启恢复。',
                              '所有场景数据均虚构，不能替代真实语料效果评测。',
                              '不包含博查搜索、微信采集、邮件或外部报名。']}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='opportunity-live-') as directory:
        # This must precede every application import. Background worker sessions
        # then point to the same disposable database without replacing services.
        os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(directory) / 'test.db')
        from app.core.config import get_settings
        from app.core.database import Base, engine, SessionLocal
        from app.core.observability import runtime_metrics
        from app.models import entities as m
        from app.services.extraction_service import ExtractionService
        from app.services.feedback_service import FeedbackService
        from app.services.growth_memory.memory_manager import GrowthMemoryManager
        from app.services.growth_memory.snapshot_service import GrowthMemorySnapshotService
        from app.services.json_utils import dumps, loads_dict, loads_list
        from app.services.llm_gateway import LLMGateway
        from app.services.llm_service import LLMService
        from app.services.matching_service import MatchingService
        from app.services.opportunity_agent import OpportunityAgent
        from app.services.opportunity_assistant_service import OpportunityAssistantService
        from app.services.opportunity_progress_service import OpportunityProgressService

        settings = get_settings()
        endpoint = urlsplit(settings.deepseek_base_url)
        if not (endpoint.scheme == 'https' and endpoint.hostname == 'api.deepseek.com'
                and endpoint.port in (None, 443) and not endpoint.username
                and not endpoint.password and not endpoint.query and not endpoint.fragment):
            raise ValueError('此验收只允许 DeepSeek 官方 HTTPS 端点。')
        if not LLMGateway().is_configured():
            raise ValueError('未配置 DeepSeek Key。')
        report['model'] = settings.llm_model
        report['thinking'] = settings.llm_thinking
        report['max_output_tokens_per_request'] = settings.llm_max_tokens
        Base.metadata.create_all(engine)
        runtime_metrics.reset()
        stage = 'setup'
        original_post = LLMGateway._post_json

        def tracked_post(gateway, url, key, payload):
            if len(report['requests']) >= max_requests:
                raise RuntimeError('Live check request budget exhausted')
            entry = {'stage': stage, 'requested_model': payload['model'], 'status': 'started'}
            report['requests'].append(entry)
            tick = time.monotonic()
            try:
                data = original_post(gateway, url, key, payload)
                entry.update(status='success', served_model=data.get('model'), usage=data.get('usage', {}))
                # Inputs are created below and are synthetic. No auth headers,
                # settings, API key, personal data or reasoning trace is saved.
                entry['output'] = (data.get('choices') or [{}])[0].get('message', {}).get('content')
                entry['finish_reason'] = (data.get('choices') or [{}])[0].get('finish_reason')
                entry['includes_growth_memory'] = any('"snapshot_id"' in msg.get('content', '') for msg in payload['messages'])
                return data
            except Exception as exc:
                entry.update(status='failed', error_type=type(exc).__name__)
                raise
            finally:
                entry['duration_ms'] = round((time.monotonic() - tick) * 1000)

        @contextmanager
        def step(name):
            nonlocal stage
            stage = name
            row = {'name': name, 'status': 'running'}
            report['steps'].append(row)
            print(json.dumps({'stage': name, 'status': 'running'}, ensure_ascii=False), flush=True)
            tick = time.monotonic()
            try:
                yield row
                row['status'] = 'passed'
            except Exception:
                row['status'] = 'failed'
                raise
            finally:
                row['duration_ms'] = round((time.monotonic() - tick) * 1000)
                print(json.dumps({'stage': name, 'status': row['status'], 'duration_ms': row['duration_ms']}, ensure_ascii=False), flush=True)

        try:
            with patch.object(LLMGateway, '_post_json', tracked_post), SessionLocal() as db:
                cutoff = (date.today() + timedelta(days=30)).isoformat()
                article = m.Article(title='星河实验室 RAG 项目实习生招募', content=(
                    '以下是软件验收的虚构场景，请按给定条件分析，不需访问外部网站。\n'
                    '星河实验室现招募 RAG 项目实习生，面向大三本科生，熟悉 Python 和机器学习即可申请。\n'
                    '主办方：星河实验室\n地点：线上\n报名截止：' + cutoff + '\n'
                    '职责：实现检索增强问答原型，完成评测报告。每周投入八小时。\n'
                    '申请材料：一页简历和一个 RAG 演示项目。无需论文发表经历。\n'
                    '报名链接：https://example.com/synthetic-rag\n'
                    '此链接仅作测试，不要访问或实际投递。'))
                user = m.UserProfile(name='虚构验收用户', major_direction='人工智能', grade_identity='大三本科生',
                    current_goals=dumps(['找实习', '科研入门']), skills=dumps(['Python', '机器学习']),
                    interested_fields=dumps(['RAG', 'AI Agent']), disliked_contents=dumps(['纯营销']),
                    location_preference='线上', time_preference='周末', detailed_needs='每周可投入八小时，希望完成可展示的 RAG 项目。')
                other = m.UserProfile(name='隔离验证用户')
                db.add_all([article, user, other]); db.commit()
                uid, other_id = user.id, other.id
                strict_llm = LLMService(allow_local_fallback=False)
                extraction = ExtractionService(); extraction.llm = strict_llm
                with step('remote_extraction_and_storage') as row:
                    assert extraction.process_article(db, article) == 1, '虚构通知应只生成一个机会'
                    opportunity = db.query(m.Opportunity).one()
                    oid = opportunity.id
                    assert opportunity.category == '实习', '机会类别不正确'
                    assert '线上' in opportunity.location and cutoff in opportunity.deadline, '关键字段与原文不一致'
                    row.update(opportunity_id=oid, category=opportunity.category)
                with step('remote_negative_extraction'):
                    assert strict_llm.extract_opportunities('实习准备经验随笔', '本文仅总结过去准备简历的经验，不发布岗位，不接受报名。') == [], '经验文章被误报为机会'
                with step('remote_matching_and_summary') as row:
                    matcher = MatchingService(llm=strict_llm, strict_llm=True)
                    rec = matcher.generate_for_user(db, uid)[0]
                    rid = rec.id
                    assert len(rec.content_overview) >= 80
                    summary = strict_llm.summarize_recommendations({'current_goals': ['找实习']},
                        [{'name': opportunity.name, 'reason': rec.reason, 'deadline': opportunity.deadline,
                          'requirements': opportunity.requirements, 'verification_status': opportunity.verification_status}])
                    assert summary.strip()
                    row.update(recommendation_id=rid, overview_length=len(rec.content_overview), summary=summary)
                with step('remote_assistant') as row:
                    answer = OpportunityAssistantService().chat(db, uid, oid, '根据当前资料，我应该如何准备作品集？请仅使用已提供信息。')
                    assert answer['answer'].strip() and not answer['used_search'] and answer['search_status'] == 'none'
                    row['answer'] = answer['answer']
                progress = OpportunityProgressService()
                with step('remote_progress_analysis') as row:
                    task = progress.start_analysis_task(db, uid, oid)
                    task_id = task.id
                    with patch.object(progress, '_fallback_final_from_rounds', wraps=progress._fallback_final_from_rounds) as fallback:
                        progress.execute_analysis_task(task_id)
                        db.expire_all()
                        task = db.get(m.OpportunityProgressTask, task_id)
                        assert task.status in {'waiting_confirmation', 'stopped'}, '推进分析未成功完成'
                        assert not fallback.called, '最终结论走了部分结果回退'
                    assert loads_list(task.rounds), '未保存真实模型分析轮次'
                    assert loads_list(task.suggested_todos), '未生成可执行的任务建议'
                    row.update(task_id=task_id, rounds=len(loads_list(task.rounds)), status_in_product=task.status,
                               final=loads_dict(task.final_result))
                with step('plan_and_real_todo_execution') as row:
                    plan = progress.create_plan_from_task(db, task_id)
                    row['confirmation_source'] = 'explicit simulated user choice; not autonomous model authorization'
                    plan_id = plan.id
                    items = db.query(m.OpportunityProgressItem).filter_by(plan_id=plan_id).all()
                    selected = [item.id for item in items[:2]]
                    assert len(selected) == 2, '模型没有提出至少两个独立任务'
                    first = progress.sync_plan_items_to_todos(db, plan_id, selected)
                    second = progress.sync_plan_items_to_todos(db, plan_id, selected)
                    assert len(first['created']) == 2 and len(second['existing']) == 2
                    assert db.query(m.Todo).count() == 2
                    assert len({item['todo_id'] for item in first['created']}) == 2
                    row.update(plan_id=plan_id, task_count=len(items), created_todos=2, duplicate_todos=0)
                with step('real_calendar_execution') as row:
                    agent = OpportunityAgent()
                    agent.run_opportunity_action(db, uid, oid, 'calendar')
                    agent.run_opportunity_action(db, uid, oid, 'calendar')
                    assert db.query(m.CalendarEvent).count() == 1, '日历未保存或重复创建'
                    row['calendar_events'] = 1
                with step('remote_replan_and_confirmation') as row:
                    item = db.get(m.OpportunityProgressItem, selected[0])
                    completed_title = item.title
                    update = progress.replan(db, plan_id,
                        f'我已完成任务 ID {item.id}「{completed_title}」，请标为完成。其余任务尚未完成。每周可用时间降为四小时，请按此调整。')
                    assert db.get(m.OpportunityProgressItem, item.id).status == 'pending', '确认前正式计划已被修改'
                    proposed = loads_dict(update.proposed_changes_json)
                    assert any(c['task_id'] == item.id and c['change_type'] == 'complete' for c in proposed['task_changes']), '模型未识别明确的完成反馈'
                    updated_plan = progress.confirm_plan_update(db, plan_id, update.id)
                    assert updated_plan.version_number == 2
                    assert db.get(m.OpportunityProgressItem, item.id).status == 'completed'
                    assert db.get(m.Todo, item.todo_id).status == 'completed', '计划已完成，但关联待办未同步完成'
                    row.update(version=2, confirmed_update_id=update.id, proposed=proposed,
                               linked_todo_status=db.get(m.Todo, item.todo_id).status)
                with step('remote_growth_memory_and_reuse') as row:
                    FeedbackService().record_recommendation_feedback(db, uid, rid, 'mark_useful', oid,
                        {'feedback_text': '我更偏好线上 RAG 项目，每周只能投入四小时，暂不考虑线下岗位。'})
                    memory = GrowthMemorySnapshotService().generate(db, uid)
                    assert memory['updated']
                    snapshot = memory['data']
                    before = len(report['requests'])
                    cached = GrowthMemorySnapshotService().generate(db, uid)
                    assert not cached['updated'] and len(report['requests']) == before
                    assert GrowthMemoryManager().recommendation_context(db, other_id) == {}, '用户间记忆发生泄漏'
                    matcher.generate_for_user(db, uid)
                    assert any(req.get('includes_growth_memory') for req in report['requests'][before:]), '新推荐未携带成长记忆'
                    row.update(snapshot_id=snapshot.id, behavior_count=snapshot.behavior_count,
                               preference_changes=snapshot.preference_changes, next_stage_advice=snapshot.next_stage_advice,
                               repeated_generation_calls=0, other_user_isolated=True)
                assert runtime_metrics.snapshot()['llm']['fallbacks_total'] == 0, '链路使用了本地模型回退'
                assert all(req['status'] == 'success' for req in report['requests']), '链路存在请求失败'
                report['ok'] = True
        except Exception as exc:
            report['error_type'] = type(exc).__name__
            report['error'] = str(exc) if isinstance(exc, AssertionError) else '该步骤失败，详见阶段及请求状态；未输出异常正文。'
        finally:
            report['llm_execution'] = runtime_metrics.snapshot()['llm']
            report['duration_ms'] = round((time.monotonic() - started) * 1000)
            report['tokens'] = {key: sum(int(req.get('usage', {}).get(key) or 0) for req in report['requests'])
                                for key in ['prompt_tokens', 'completion_tokens', 'total_tokens']}
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            engine.dispose()
    return report, output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-network', action='store_true')
    parser.add_argument('--max-requests', type=int, default=16)
    args = parser.parse_args()
    try:
        report, output = run_check(args.allow_network, args.max_requests)
    except ValueError as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({'ok': report['ok'], 'report': str(output), 'requests': len(report['requests']),
                      'duration_ms': report['duration_ms'], 'tokens': report['tokens'],
                      'error': report.get('error')}, ensure_ascii=False), flush=True)
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
