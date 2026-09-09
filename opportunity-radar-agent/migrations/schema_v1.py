"""Frozen schema at revision 0001; do not import evolving application models."""
import sqlalchemy as sa

metadata = sa.MetaData()

sa.Table(
    'articles', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('title', sa.String(length=255), primary_key=False, nullable=False),
    sa.Column('source', sa.String(length=120), primary_key=False, nullable=False),
    sa.Column('author', sa.String(length=120), primary_key=False, nullable=False),
    sa.Column('published_at', sa.String(length=64), primary_key=False, nullable=False),
    sa.Column('content', sa.Text(), primary_key=False, nullable=False),
    sa.Column('url', sa.String(length=500), primary_key=False, nullable=False),
    sa.Column('imported_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.Column('processed', sa.Boolean(), primary_key=False, nullable=False),
)
sa.Index('ix_articles_id', metadata.tables['articles'].c['id'], unique=False)
sa.Index('ix_articles_title', metadata.tables['articles'].c['title'], unique=False)

sa.Table(
    'search_cache', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('provider', sa.String(length=120), primary_key=False, nullable=False),
    sa.Column('query', sa.Text(), primary_key=False, nullable=False),
    sa.Column('results', sa.Text(), primary_key=False, nullable=False),
    sa.Column('status', sa.String(length=80), primary_key=False, nullable=False),
    sa.Column('error_message', sa.Text(), primary_key=False, nullable=False),
    sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.Column('expires_at', sa.DateTime(), primary_key=False, nullable=False),
)
sa.Index('ix_search_cache_created_at', metadata.tables['search_cache'].c['created_at'], unique=False)
sa.Index('ix_search_cache_expires_at', metadata.tables['search_cache'].c['expires_at'], unique=False)
sa.Index('ix_search_cache_id', metadata.tables['search_cache'].c['id'], unique=False)
sa.Index('ix_search_cache_provider', metadata.tables['search_cache'].c['provider'], unique=False)
sa.Index('ix_search_cache_query', metadata.tables['search_cache'].c['query'], unique=False)
sa.Index('ix_search_cache_status', metadata.tables['search_cache'].c['status'], unique=False)

sa.Table(
    'user_profiles', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('name', sa.String(length=120), primary_key=False, nullable=False),
    sa.Column('major_direction', sa.String(length=255), primary_key=False, nullable=False),
    sa.Column('grade_identity', sa.String(length=120), primary_key=False, nullable=False),
    sa.Column('current_goals', sa.Text(), primary_key=False, nullable=False),
    sa.Column('skills', sa.Text(), primary_key=False, nullable=False),
    sa.Column('interested_fields', sa.Text(), primary_key=False, nullable=False),
    sa.Column('disliked_contents', sa.Text(), primary_key=False, nullable=False),
    sa.Column('detailed_needs', sa.Text(), primary_key=False, nullable=False),
    sa.Column('time_preference', sa.String(length=255), primary_key=False, nullable=False),
    sa.Column('location_preference', sa.String(length=255), primary_key=False, nullable=False),
    sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.Column('updated_at', sa.DateTime(), primary_key=False, nullable=False),
)
sa.Index('ix_user_profiles_id', metadata.tables['user_profiles'].c['id'], unique=False)

sa.Table(
    'growth_memory_snapshots', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('user_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('current_stage', sa.Text(), primary_key=False, nullable=False),
    sa.Column('recent_focus', sa.Text(), primary_key=False, nullable=False),
    sa.Column('preference_changes', sa.Text(), primary_key=False, nullable=False),
    sa.Column('overall_observation', sa.Text(), primary_key=False, nullable=False),
    sa.Column('next_stage_advice', sa.Text(), primary_key=False, nullable=False),
    sa.Column('behavior_count', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('behavior_start_time', sa.DateTime(), primary_key=False, nullable=True),
    sa.Column('behavior_end_time', sa.DateTime(), primary_key=False, nullable=True),
    sa.Column('analyzed_event_ids', sa.Text(), primary_key=False, nullable=False),
    sa.Column('referenced_memory_ids', sa.Text(), primary_key=False, nullable=False),
    sa.Column('model_name', sa.String(length=120), primary_key=False, nullable=False),
    sa.Column('prompt_version', sa.String(length=80), primary_key=False, nullable=False),
    sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user_profiles.id']),
)
sa.Index('ix_growth_memory_snapshots_created_at', metadata.tables['growth_memory_snapshots'].c['created_at'], unique=False)
sa.Index('ix_growth_memory_snapshots_id', metadata.tables['growth_memory_snapshots'].c['id'], unique=False)
sa.Index('ix_growth_memory_snapshots_user_id', metadata.tables['growth_memory_snapshots'].c['user_id'], unique=False)

sa.Table(
    'memory_reflections', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('user_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('reflection_type', sa.String(length=120), primary_key=False, nullable=False),
    sa.Column('summary', sa.Text(), primary_key=False, nullable=False),
    sa.Column('confidence', sa.Float(), primary_key=False, nullable=False),
    sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.Column('updated_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user_profiles.id']),
)
sa.Index('ix_memory_reflections_id', metadata.tables['memory_reflections'].c['id'], unique=False)
sa.Index('ix_memory_reflections_reflection_type', metadata.tables['memory_reflections'].c['reflection_type'], unique=False)
sa.Index('ix_memory_reflections_user_id', metadata.tables['memory_reflections'].c['user_id'], unique=False)

sa.Table(
    'opportunities', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('article_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('name', sa.String(length=255), primary_key=False, nullable=False),
    sa.Column('category', sa.String(length=80), primary_key=False, nullable=False),
    sa.Column('organizer', sa.String(length=255), primary_key=False, nullable=False),
    sa.Column('event_time', sa.String(length=120), primary_key=False, nullable=False),
    sa.Column('deadline', sa.String(length=120), primary_key=False, nullable=False),
    sa.Column('location', sa.String(length=255), primary_key=False, nullable=False),
    sa.Column('target_audience', sa.Text(), primary_key=False, nullable=False),
    sa.Column('link', sa.String(length=500), primary_key=False, nullable=False),
    sa.Column('requirements', sa.Text(), primary_key=False, nullable=False),
    sa.Column('summary', sa.Text(), primary_key=False, nullable=False),
    sa.Column('benefit', sa.Float(), primary_key=False, nullable=False),
    sa.Column('cost', sa.Float(), primary_key=False, nullable=False),
    sa.Column('credibility', sa.Float(), primary_key=False, nullable=False),
    sa.Column('raw_payload', sa.Text(), primary_key=False, nullable=False),
    sa.Column('official_url', sa.String(length=500), primary_key=False, nullable=False),
    sa.Column('registration_url', sa.String(length=500), primary_key=False, nullable=False),
    sa.Column('verification_status', sa.String(length=40), primary_key=False, nullable=False),
    sa.Column('credibility_score', sa.Float(), primary_key=False, nullable=True),
    sa.Column('risk_level', sa.String(length=40), primary_key=False, nullable=False),
    sa.Column('risk_flags', sa.Text(), primary_key=False, nullable=False),
    sa.Column('verification_summary', sa.Text(), primary_key=False, nullable=False),
    sa.Column('evidence_sources', sa.Text(), primary_key=False, nullable=False),
    sa.Column('enriched_at', sa.DateTime(), primary_key=False, nullable=True),
    sa.Column('verified_at', sa.DateTime(), primary_key=False, nullable=True),
    sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.ForeignKeyConstraint(['article_id'], ['articles.id']),
)
sa.Index('ix_opportunities_article_id', metadata.tables['opportunities'].c['article_id'], unique=False)
sa.Index('ix_opportunities_category', metadata.tables['opportunities'].c['category'], unique=False)
sa.Index('ix_opportunities_id', metadata.tables['opportunities'].c['id'], unique=False)
sa.Index('ix_opportunities_name', metadata.tables['opportunities'].c['name'], unique=False)

sa.Table(
    'user_events', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('user_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('event_type', sa.String(length=80), primary_key=False, nullable=False),
    sa.Column('event_target', sa.String(length=120), primary_key=False, nullable=False),
    sa.Column('event_metadata', sa.Text(), primary_key=False, nullable=False),
    sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user_profiles.id']),
)
sa.Index('ix_user_events_event_type', metadata.tables['user_events'].c['event_type'], unique=False)
sa.Index('ix_user_events_id', metadata.tables['user_events'].c['id'], unique=False)
sa.Index('ix_user_events_user_id', metadata.tables['user_events'].c['user_id'], unique=False)

sa.Table(
    'calendar_events', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('user_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('opportunity_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('title', sa.String(length=255), primary_key=False, nullable=False),
    sa.Column('start_time', sa.DateTime(), primary_key=False, nullable=True),
    sa.Column('end_time', sa.DateTime(), primary_key=False, nullable=True),
    sa.Column('status', sa.String(length=40), primary_key=False, nullable=False),
    sa.Column('source', sa.String(length=120), primary_key=False, nullable=False),
    sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.Column('updated_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.ForeignKeyConstraint(['opportunity_id'], ['opportunities.id']),
    sa.ForeignKeyConstraint(['user_id'], ['user_profiles.id']),
    sa.UniqueConstraint('user_id', 'opportunity_id', name='uq_calendar_event_user_opportunity'),
)
sa.Index('ix_calendar_events_id', metadata.tables['calendar_events'].c['id'], unique=False)
sa.Index('ix_calendar_events_opportunity_id', metadata.tables['calendar_events'].c['opportunity_id'], unique=False)
sa.Index('ix_calendar_events_start_time', metadata.tables['calendar_events'].c['start_time'], unique=False)
sa.Index('ix_calendar_events_status', metadata.tables['calendar_events'].c['status'], unique=False)
sa.Index('ix_calendar_events_title', metadata.tables['calendar_events'].c['title'], unique=False)
sa.Index('ix_calendar_events_user_id', metadata.tables['calendar_events'].c['user_id'], unique=False)

sa.Table(
    'enrichment_results', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('user_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('opportunity_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('query', sa.Text(), primary_key=False, nullable=False),
    sa.Column('summary', sa.Text(), primary_key=False, nullable=False),
    sa.Column('key_findings', sa.Text(), primary_key=False, nullable=False),
    sa.Column('official_links', sa.Text(), primary_key=False, nullable=False),
    sa.Column('registration_links', sa.Text(), primary_key=False, nullable=False),
    sa.Column('deadline_notes', sa.Text(), primary_key=False, nullable=False),
    sa.Column('eligibility_notes', sa.Text(), primary_key=False, nullable=False),
    sa.Column('risk_flags', sa.Text(), primary_key=False, nullable=False),
    sa.Column('credibility_score', sa.Float(), primary_key=False, nullable=True),
    sa.Column('action_suggestion', sa.Text(), primary_key=False, nullable=False),
    sa.Column('sources', sa.Text(), primary_key=False, nullable=False),
    sa.Column('status', sa.String(length=40), primary_key=False, nullable=False),
    sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.Column('updated_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.ForeignKeyConstraint(['opportunity_id'], ['opportunities.id']),
    sa.ForeignKeyConstraint(['user_id'], ['user_profiles.id']),
)
sa.Index('ix_enrichment_results_id', metadata.tables['enrichment_results'].c['id'], unique=False)
sa.Index('ix_enrichment_results_opportunity_id', metadata.tables['enrichment_results'].c['opportunity_id'], unique=False)
sa.Index('ix_enrichment_results_status', metadata.tables['enrichment_results'].c['status'], unique=False)
sa.Index('ix_enrichment_results_user_id', metadata.tables['enrichment_results'].c['user_id'], unique=False)

sa.Table(
    'opportunity_progress_tasks', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('user_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('opportunity_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('current_stage', sa.String(length=80), primary_key=False, nullable=False),
    sa.Column('rounds', sa.Text(), primary_key=False, nullable=False),
    sa.Column('final_result', sa.Text(), primary_key=False, nullable=False),
    sa.Column('suggested_todos', sa.Text(), primary_key=False, nullable=False),
    sa.Column('confirmed', sa.Boolean(), primary_key=False, nullable=False),
    sa.Column('created_todo_ids', sa.Text(), primary_key=False, nullable=False),
    sa.Column('status', sa.String(length=40), primary_key=False, nullable=False),
    sa.Column('error_message', sa.Text(), primary_key=False, nullable=False),
    sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.Column('updated_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.ForeignKeyConstraint(['opportunity_id'], ['opportunities.id']),
    sa.ForeignKeyConstraint(['user_id'], ['user_profiles.id']),
)
sa.Index('ix_opportunity_progress_tasks_current_stage', metadata.tables['opportunity_progress_tasks'].c['current_stage'], unique=False)
sa.Index('ix_opportunity_progress_tasks_id', metadata.tables['opportunity_progress_tasks'].c['id'], unique=False)
sa.Index('ix_opportunity_progress_tasks_opportunity_id', metadata.tables['opportunity_progress_tasks'].c['opportunity_id'], unique=False)
sa.Index('ix_opportunity_progress_tasks_status', metadata.tables['opportunity_progress_tasks'].c['status'], unique=False)
sa.Index('ix_opportunity_progress_tasks_user_id', metadata.tables['opportunity_progress_tasks'].c['user_id'], unique=False)

sa.Table(
    'opportunity_states', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('user_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('opportunity_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('state', sa.String(length=40), primary_key=False, nullable=False),
    sa.Column('updated_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.ForeignKeyConstraint(['opportunity_id'], ['opportunities.id']),
    sa.ForeignKeyConstraint(['user_id'], ['user_profiles.id']),
    sa.UniqueConstraint('user_id', 'opportunity_id', name='uq_opportunity_state_user_opp'),
)
sa.Index('ix_opportunity_states_id', metadata.tables['opportunity_states'].c['id'], unique=False)
sa.Index('ix_opportunity_states_opportunity_id', metadata.tables['opportunity_states'].c['opportunity_id'], unique=False)
sa.Index('ix_opportunity_states_state', metadata.tables['opportunity_states'].c['state'], unique=False)
sa.Index('ix_opportunity_states_user_id', metadata.tables['opportunity_states'].c['user_id'], unique=False)

sa.Table(
    'recommendations', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('user_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('opportunity_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('relevance_score', sa.Float(), primary_key=False, nullable=False),
    sa.Column('urgency_score', sa.Float(), primary_key=False, nullable=False),
    sa.Column('benefit_score', sa.Float(), primary_key=False, nullable=False),
    sa.Column('cost_score', sa.Float(), primary_key=False, nullable=False),
    sa.Column('credibility_score', sa.Float(), primary_key=False, nullable=False),
    sa.Column('total_score', sa.Float(), primary_key=False, nullable=False),
    sa.Column('reason', sa.Text(), primary_key=False, nullable=False),
    sa.Column('content_overview', sa.Text(), primary_key=False, nullable=False),
    sa.Column('relevance_explanation', sa.Text(), primary_key=False, nullable=False),
    sa.Column('risk_notes', sa.Text(), primary_key=False, nullable=False),
    sa.Column('anti_recommendation_reason', sa.Text(), primary_key=False, nullable=False),
    sa.Column('action_suggestion', sa.Text(), primary_key=False, nullable=False),
    sa.Column('opportunity_state', sa.String(length=40), primary_key=False, nullable=False),
    sa.Column('deadline', sa.String(length=120), primary_key=False, nullable=False),
    sa.Column('deadline_urgency', sa.String(length=40), primary_key=False, nullable=False),
    sa.Column('deadline_note', sa.Text(), primary_key=False, nullable=False),
    sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.ForeignKeyConstraint(['opportunity_id'], ['opportunities.id']),
    sa.ForeignKeyConstraint(['user_id'], ['user_profiles.id']),
)
sa.Index('ix_recommendations_id', metadata.tables['recommendations'].c['id'], unique=False)
sa.Index('ix_recommendations_opportunity_id', metadata.tables['recommendations'].c['opportunity_id'], unique=False)
sa.Index('ix_recommendations_user_id', metadata.tables['recommendations'].c['user_id'], unique=False)

sa.Table(
    'similar_opportunity_results', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('user_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('opportunity_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('query', sa.Text(), primary_key=False, nullable=False),
    sa.Column('results', sa.Text(), primary_key=False, nullable=False),
    sa.Column('comparison_summary', sa.Text(), primary_key=False, nullable=False),
    sa.Column('status', sa.String(length=40), primary_key=False, nullable=False),
    sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.Column('updated_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.ForeignKeyConstraint(['opportunity_id'], ['opportunities.id']),
    sa.ForeignKeyConstraint(['user_id'], ['user_profiles.id']),
)
sa.Index('ix_similar_opportunity_results_id', metadata.tables['similar_opportunity_results'].c['id'], unique=False)
sa.Index('ix_similar_opportunity_results_opportunity_id', metadata.tables['similar_opportunity_results'].c['opportunity_id'], unique=False)
sa.Index('ix_similar_opportunity_results_status', metadata.tables['similar_opportunity_results'].c['status'], unique=False)
sa.Index('ix_similar_opportunity_results_user_id', metadata.tables['similar_opportunity_results'].c['user_id'], unique=False)

sa.Table(
    'todos', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('user_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('opportunity_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('title', sa.String(length=255), primary_key=False, nullable=False),
    sa.Column('description', sa.Text(), primary_key=False, nullable=False),
    sa.Column('deadline', sa.String(length=120), primary_key=False, nullable=True),
    sa.Column('deadline_note', sa.Text(), primary_key=False, nullable=False),
    sa.Column('status', sa.String(length=40), primary_key=False, nullable=False),
    sa.Column('priority', sa.String(length=40), primary_key=False, nullable=False),
    sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.Column('updated_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.ForeignKeyConstraint(['opportunity_id'], ['opportunities.id']),
    sa.ForeignKeyConstraint(['user_id'], ['user_profiles.id']),
    sa.UniqueConstraint('user_id', 'opportunity_id', name='uq_todo_user_opportunity'),
)
sa.Index('ix_todos_id', metadata.tables['todos'].c['id'], unique=False)
sa.Index('ix_todos_opportunity_id', metadata.tables['todos'].c['opportunity_id'], unique=False)
sa.Index('ix_todos_priority', metadata.tables['todos'].c['priority'], unique=False)
sa.Index('ix_todos_status', metadata.tables['todos'].c['status'], unique=False)
sa.Index('ix_todos_title', metadata.tables['todos'].c['title'], unique=False)
sa.Index('ix_todos_user_id', metadata.tables['todos'].c['user_id'], unique=False)

sa.Table(
    'tool_call_logs', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('user_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('opportunity_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('action', sa.String(length=80), primary_key=False, nullable=False),
    sa.Column('tool_name', sa.String(length=120), primary_key=False, nullable=False),
    sa.Column('query', sa.Text(), primary_key=False, nullable=False),
    sa.Column('provider', sa.String(length=120), primary_key=False, nullable=False),
    sa.Column('input_json', sa.Text(), primary_key=False, nullable=False),
    sa.Column('output_json', sa.Text(), primary_key=False, nullable=False),
    sa.Column('status', sa.String(length=40), primary_key=False, nullable=False),
    sa.Column('result_summary', sa.Text(), primary_key=False, nullable=False),
    sa.Column('error_message', sa.Text(), primary_key=False, nullable=False),
    sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.ForeignKeyConstraint(['opportunity_id'], ['opportunities.id']),
    sa.ForeignKeyConstraint(['user_id'], ['user_profiles.id']),
)
sa.Index('ix_tool_call_logs_action', metadata.tables['tool_call_logs'].c['action'], unique=False)
sa.Index('ix_tool_call_logs_id', metadata.tables['tool_call_logs'].c['id'], unique=False)
sa.Index('ix_tool_call_logs_opportunity_id', metadata.tables['tool_call_logs'].c['opportunity_id'], unique=False)
sa.Index('ix_tool_call_logs_tool_name', metadata.tables['tool_call_logs'].c['tool_name'], unique=False)
sa.Index('ix_tool_call_logs_user_id', metadata.tables['tool_call_logs'].c['user_id'], unique=False)

sa.Table(
    'tool_calls', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('user_id', sa.Integer(), primary_key=False, nullable=True),
    sa.Column('opportunity_id', sa.Integer(), primary_key=False, nullable=True),
    sa.Column('tool_name', sa.String(length=80), primary_key=False, nullable=False),
    sa.Column('payload', sa.Text(), primary_key=False, nullable=False),
    sa.Column('query', sa.Text(), primary_key=False, nullable=False),
    sa.Column('provider', sa.String(length=120), primary_key=False, nullable=False),
    sa.Column('status', sa.String(length=40), primary_key=False, nullable=False),
    sa.Column('result_summary', sa.Text(), primary_key=False, nullable=False),
    sa.Column('error_message', sa.Text(), primary_key=False, nullable=False),
    sa.Column('result', sa.Text(), primary_key=False, nullable=False),
    sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.ForeignKeyConstraint(['opportunity_id'], ['opportunities.id']),
    sa.ForeignKeyConstraint(['user_id'], ['user_profiles.id']),
)
sa.Index('ix_tool_calls_id', metadata.tables['tool_calls'].c['id'], unique=False)
sa.Index('ix_tool_calls_tool_name', metadata.tables['tool_calls'].c['tool_name'], unique=False)

sa.Table(
    'opportunity_progress_plans', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('user_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('opportunity_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('source_task_id', sa.Integer(), primary_key=False, nullable=True),
    sa.Column('goal', sa.Text(), primary_key=False, nullable=False),
    sa.Column('overall_judgment', sa.Text(), primary_key=False, nullable=False),
    sa.Column('current_stage', sa.Text(), primary_key=False, nullable=False),
    sa.Column('plan_summary', sa.Text(), primary_key=False, nullable=False),
    sa.Column('next_focus', sa.Text(), primary_key=False, nullable=False),
    sa.Column('risks_json', sa.Text(), primary_key=False, nullable=False),
    sa.Column('system_status', sa.String(length=40), primary_key=False, nullable=False),
    sa.Column('version_number', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.Column('updated_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.Column('completed_at', sa.DateTime(), primary_key=False, nullable=True),
    sa.ForeignKeyConstraint(['opportunity_id'], ['opportunities.id']),
    sa.ForeignKeyConstraint(['source_task_id'], ['opportunity_progress_tasks.id']),
    sa.ForeignKeyConstraint(['user_id'], ['user_profiles.id']),
)
sa.Index('ix_opportunity_progress_plans_id', metadata.tables['opportunity_progress_plans'].c['id'], unique=False)
sa.Index('ix_opportunity_progress_plans_opportunity_id', metadata.tables['opportunity_progress_plans'].c['opportunity_id'], unique=False)
sa.Index('ix_opportunity_progress_plans_source_task_id', metadata.tables['opportunity_progress_plans'].c['source_task_id'], unique=False)
sa.Index('ix_opportunity_progress_plans_system_status', metadata.tables['opportunity_progress_plans'].c['system_status'], unique=False)
sa.Index('ix_opportunity_progress_plans_user_id', metadata.tables['opportunity_progress_plans'].c['user_id'], unique=False)

sa.Table(
    'opportunity_progress_items', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('plan_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('title', sa.String(length=255), primary_key=False, nullable=False),
    sa.Column('description', sa.Text(), primary_key=False, nullable=False),
    sa.Column('priority', sa.String(length=40), primary_key=False, nullable=False),
    sa.Column('status', sa.String(length=40), primary_key=False, nullable=False),
    sa.Column('source', sa.String(length=80), primary_key=False, nullable=False),
    sa.Column('synced_to_todo', sa.Boolean(), primary_key=False, nullable=False),
    sa.Column('todo_id', sa.Integer(), primary_key=False, nullable=True),
    sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.Column('updated_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.ForeignKeyConstraint(['plan_id'], ['opportunity_progress_plans.id']),
    sa.ForeignKeyConstraint(['todo_id'], ['todos.id']),
)
sa.Index('ix_opportunity_progress_items_id', metadata.tables['opportunity_progress_items'].c['id'], unique=False)
sa.Index('ix_opportunity_progress_items_plan_id', metadata.tables['opportunity_progress_items'].c['plan_id'], unique=False)
sa.Index('ix_opportunity_progress_items_priority', metadata.tables['opportunity_progress_items'].c['priority'], unique=False)
sa.Index('ix_opportunity_progress_items_status', metadata.tables['opportunity_progress_items'].c['status'], unique=False)
sa.Index('ix_opportunity_progress_items_title', metadata.tables['opportunity_progress_items'].c['title'], unique=False)
sa.Index('ix_opportunity_progress_items_todo_id', metadata.tables['opportunity_progress_items'].c['todo_id'], unique=False)

sa.Table(
    'opportunity_progress_updates', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('plan_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('user_progress_text', sa.Text(), primary_key=False, nullable=False),
    sa.Column('ai_assessment_json', sa.Text(), primary_key=False, nullable=False),
    sa.Column('proposed_changes_json', sa.Text(), primary_key=False, nullable=False),
    sa.Column('confirmation_status', sa.String(length=40), primary_key=False, nullable=False),
    sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.Column('confirmed_at', sa.DateTime(), primary_key=False, nullable=True),
    sa.ForeignKeyConstraint(['plan_id'], ['opportunity_progress_plans.id']),
)
sa.Index('ix_opportunity_progress_updates_confirmation_status', metadata.tables['opportunity_progress_updates'].c['confirmation_status'], unique=False)
sa.Index('ix_opportunity_progress_updates_id', metadata.tables['opportunity_progress_updates'].c['id'], unique=False)
sa.Index('ix_opportunity_progress_updates_plan_id', metadata.tables['opportunity_progress_updates'].c['plan_id'], unique=False)

sa.Table(
    'opportunity_progress_web_checks', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('user_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('opportunity_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('task_id', sa.Integer(), primary_key=False, nullable=True),
    sa.Column('plan_id', sa.Integer(), primary_key=False, nullable=True),
    sa.Column('query', sa.Text(), primary_key=False, nullable=False),
    sa.Column('status', sa.String(length=40), primary_key=False, nullable=False),
    sa.Column('sources_json', sa.Text(), primary_key=False, nullable=False),
    sa.Column('analysis_json', sa.Text(), primary_key=False, nullable=False),
    sa.Column('error_message', sa.Text(), primary_key=False, nullable=False),
    sa.Column('request_id', sa.String(length=80), primary_key=False, nullable=False),
    sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.Column('updated_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.ForeignKeyConstraint(['opportunity_id'], ['opportunities.id']),
    sa.ForeignKeyConstraint(['plan_id'], ['opportunity_progress_plans.id']),
    sa.ForeignKeyConstraint(['task_id'], ['opportunity_progress_tasks.id']),
    sa.ForeignKeyConstraint(['user_id'], ['user_profiles.id']),
)
sa.Index('ix_opportunity_progress_web_checks_id', metadata.tables['opportunity_progress_web_checks'].c['id'], unique=False)
sa.Index('ix_opportunity_progress_web_checks_opportunity_id', metadata.tables['opportunity_progress_web_checks'].c['opportunity_id'], unique=False)
sa.Index('ix_opportunity_progress_web_checks_plan_id', metadata.tables['opportunity_progress_web_checks'].c['plan_id'], unique=False)
sa.Index('ix_opportunity_progress_web_checks_request_id', metadata.tables['opportunity_progress_web_checks'].c['request_id'], unique=False)
sa.Index('ix_opportunity_progress_web_checks_status', metadata.tables['opportunity_progress_web_checks'].c['status'], unique=False)
sa.Index('ix_opportunity_progress_web_checks_task_id', metadata.tables['opportunity_progress_web_checks'].c['task_id'], unique=False)
sa.Index('ix_opportunity_progress_web_checks_user_id', metadata.tables['opportunity_progress_web_checks'].c['user_id'], unique=False)

sa.Table(
    'opportunity_progress_versions', metadata,
    sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
    sa.Column('plan_id', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('version_number', sa.Integer(), primary_key=False, nullable=False),
    sa.Column('snapshot_json', sa.Text(), primary_key=False, nullable=False),
    sa.Column('update_id', sa.Integer(), primary_key=False, nullable=True),
    sa.Column('created_at', sa.DateTime(), primary_key=False, nullable=False),
    sa.ForeignKeyConstraint(['plan_id'], ['opportunity_progress_plans.id']),
    sa.ForeignKeyConstraint(['update_id'], ['opportunity_progress_updates.id']),
)
sa.Index('ix_opportunity_progress_versions_id', metadata.tables['opportunity_progress_versions'].c['id'], unique=False)
sa.Index('ix_opportunity_progress_versions_plan_id', metadata.tables['opportunity_progress_versions'].c['plan_id'], unique=False)
sa.Index('ix_opportunity_progress_versions_update_id', metadata.tables['opportunity_progress_versions'].c['update_id'], unique=False)
sa.Index('ix_opportunity_progress_versions_version_number', metadata.tables['opportunity_progress_versions'].c['version_number'], unique=False)
