"""Durable task polling, shared by article, recommendation and progress views."""
from urllib.parse import urlencode
import streamlit as st

ACTIVE = {"queued", "running"}
LABELS = {"queued": "排队中", "running": "执行中", "succeeded": "已完成", "failed": "失败"}


def latest_jobs(jobs):
    latest = {}
    for job in sorted(jobs, key=lambda item: item["id"], reverse=True):
        latest.setdefault((job["kind"], job["object_id"]), job)
    return list(latest.values())


def render_jobs(api_get, api_post, *, kind, key, object_id=None, user_id=None, on_refresh=None):
    params = {"kind": kind}
    if object_id is not None:
        params["object_id"] = object_id
    if user_id is not None:
        params["user_id"] = user_id
    path = "/jobs?" + urlencode(params)
    try:
        initial = latest_jobs(api_get(path))
    except Exception:
        st.warning("任务状态暂时不可用，请稍后刷新页面")
        return True
    active = any(job["status"] in ACTIVE for job in initial)

    @st.fragment(run_every=2 if active else None)
    def panel():
        try:
            jobs = latest_jobs(api_get(path))
        except Exception:
            st.warning("无法读取任务状态，将继续尝试")
            return
        if on_refresh:
            try:
                on_refresh()
            except Exception:
                st.warning("业务结果暂时不可用，请稍后刷新页面")
                return
        if len(jobs) > 1:
            st.caption(f"任务完成 {sum(j['status'] == 'succeeded' for j in jobs)}/{len(jobs)}，"
                       f"失败 {sum(j['status'] == 'failed' for j in jobs)}")
        for job in jobs:
            label = LABELS.get(job["status"], job["status"])
            if job["stage"] in {"recovering", "retrying"}:
                label += " · 正在恢复"
            mode = {"rules": "本地规则", "deepseek": "DeepSeek"}.get(job["mode"], "待确定模式")
            st.caption(f"#{job['id']} · {label} · {job['completed']}/{job['total']} 阶段"
                       f" · 执行 {job['attempts']}/2 次 · {mode}")
            if job["status"] == "failed":
                st.error(job["error_message"] or "处理失败")
                st.caption(f"请求 ID：{job['request_id'] or '无'}")
                if st.button("重试任务", key=f"{key}-retry-{job['id']}"):
                    try:
                        api_post(f"/jobs/{job['id']}/retry")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
        signature = [(j["id"], j["status"]) for j in jobs]
        previous = st.session_state.get(key + "-signature")
        st.session_state[key + "-signature"] = signature
        if active and not any(j["status"] in ACTIVE for j in jobs):
            st.rerun()  # Full redraw updates business results and stops the timer.
        elif previous is not None and previous != signature and not active:
            st.rerun()
    panel()
    return active
