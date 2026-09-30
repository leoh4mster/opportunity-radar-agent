"""Task controls with Streamlit's real widget runtime, no server or private DB."""
from pathlib import Path
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
