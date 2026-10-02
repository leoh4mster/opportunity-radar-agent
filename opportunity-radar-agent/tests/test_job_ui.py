"""Task controls with Streamlit's real widget runtime, no server or private DB."""
from pathlib import Path
import ast
import unittest
from streamlit.testing.v1 import AppTest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
SCRIPT = '''
import sys
sys.path.insert(0, FRONTEND_PATH)
import streamlit as st
from job_components import render_jobs
st.session_state.setdefault("jobs", [])
st.session_state.setdefault("submitted", [])
def get(path):
    return st.session_state.jobs
def post(path):
    st.session_state.submitted.append(path)
    for job in st.session_state.jobs:
        job["status"] = "queued"
        job["id"] += 1
    return {}
active = render_jobs(get, post, kind="recommendation", object_id=1, key="test")
st.button("刷新推荐", disabled=active)
'''.replace("FRONTEND_PATH", repr(str(FRONTEND)))


def job(status, ident=1):
    return dict(id=ident, kind="recommendation", object_id=1, status=status,
                stage="queued", completed=0, total=1, attempts=1, mode="deepseek",
                error_message="暂时失败", request_id="test-request")


class JobUITest(unittest.TestCase):
    def test_actions_refresh_backend_state_instead_of_cached_recommendation(self):
        source = (FRONTEND / "streamlit_app.py").read_text()
        function = next(node for node in ast.parse(source).body
                        if isinstance(node, ast.FunctionDef) and node.name == "render_opportunity_actions")
        script = '''
from __future__ import annotations
import streamlit as st
APIClientError = RuntimeError
def api_get(path):
    assert path == "/opportunities/5/state?user_id=1"
    return {"state": st.session_state.get("backend_state", "")}
def get_current_progress_plan(*args):
    return {"plan": None}
def get_latest_opportunity_progress_task(*args):
    return {"task": None}
def render_opportunity_assistant(*args, **kwargs):
    pass
''' + ast.get_source_segment(source, function) + '''
render_opportunity_actions(1, {"id": 5}, {"id": 3, "opportunity_state": ""})
'''
        app = AppTest.from_string(script).run()
        self.assertFalse(app.exception)
        self.assertFalse(next(b for b in app.button if b.label == "待办加入日历").disabled)
        app.session_state["backend_state"] = "calendar_created"
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(next(b for b in app.button if b.label == "已加入日历").disabled)
        app.session_state["backend_state"] = "applied"
        app.run()
        self.assertTrue(next(b for b in app.button if b.label == "已申请").disabled)

    def test_recommendation_profile_survives_hidden_widget_and_return(self):
        source = (FRONTEND / "streamlit_app.py").read_text()
        function = next(node for node in ast.parse(source).body
                        if isinstance(node, ast.FunctionDef) and node.name == "render_recommendations_page")
        script = '''
import streamlit as st
profiles = [{"id": 2, "name": "second"}, {"id": 1, "name": "first"}]
def api_get(path):
    st.session_state["last_read"] = path
    return profiles if path == "/profiles" else []
def render_jobs(*args, **kwargs):
    return False
def api_post(*args, **kwargs):
    raise AssertionError("Navigation must not submit a task")
''' + ast.get_source_segment(source, function) + '''
if st.toggle("Detail"):
    st.write("The profile widget is absent on this page")
else:
    render_recommendations_page()
'''
        app = AppTest.from_string(script).run()
        app.selectbox[0].set_value({"id": 1, "name": "first"}).run()
        app.toggle[0].set_value(True).run()
        self.assertEqual(len(app.selectbox), 0)
        app.toggle[0].set_value(False).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox[0].value["id"], 1)
        self.assertEqual(app.session_state["last_read"], "/recommendations/1")

    def test_active_disables_refresh_and_terminal_enables_it(self):
        app = AppTest.from_string(SCRIPT)
        app.session_state["jobs"] = [job("running")]
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(next(b for b in app.button if b.label == "刷新推荐").disabled)
        app.session_state["jobs"] = [job("succeeded")]
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.button[0].disabled)

    def test_failure_displays_trace_and_retries_once(self):
        app = AppTest.from_string(SCRIPT)
        app.session_state["jobs"] = [job("failed")]
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(app.error)
        self.assertTrue(any("test-request" in item.value for item in app.caption))
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["submitted"], ["/jobs/1/retry"])
        self.assertTrue(next(b for b in app.button if b.label == "刷新推荐").disabled)

    def test_switching_profiles_uses_separate_task_state(self):
        script = SCRIPT.replace('st.session_state.setdefault("jobs", [])', '''st.session_state.setdefault("jobs", [])
profile = st.selectbox("画像", [1, 2])''').replace('return st.session_state.jobs', 'return [job for job in st.session_state.jobs if job["object_id"] == profile]').replace('object_id=1, key="test"', 'object_id=profile, key=f"test-{profile}"')
        app = AppTest.from_string(script)
        app.session_state["jobs"] = [job("running")]
        app.run()
        self.assertTrue(next(b for b in app.button if b.label == "刷新推荐").disabled)
        app.selectbox[0].set_value(2).run()
        self.assertFalse(app.exception)
        self.assertFalse(next(b for b in app.button if b.label == "刷新推荐").disabled)
        self.assertFalse(any("#1" in item.value for item in app.caption))
