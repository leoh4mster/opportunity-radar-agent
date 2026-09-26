"""Local-only Streamlit workbench for human gold-label creation."""
from __future__ import annotations

import json
import copy
import os
from pathlib import Path

import streamlit as st

from evaluation.datasets import DatasetError, load_jsonl, require_valid, validate_records, write_jsonl


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRIVATE_ROOT = (PROJECT_ROOT / "evaluation" / "private").resolve()
DEFAULT_DATASET = PRIVATE_ROOT / "extraction.jsonl"


def safe_dataset_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    resolved = path.resolve()
    try:
        resolved.relative_to(PRIVATE_ROOT)
    except ValueError as exc:
        raise DatasetError(f"标注工具只允许写入 {PRIVATE_ROOT}") from exc
    return resolved


st.set_page_config(page_title="机会雷达人工标注", layout="wide")
st.title("机会雷达 · 人工标注工作台")
st.caption("这里只创建人工真值。模型建议仅作参考，保存文件位于 Git 忽略的 evaluation/private。")

configured_path = os.environ.get("EVALUATION_DATASET", str(DEFAULT_DATASET))
path_text = st.sidebar.text_input("本地数据集", value=configured_path)
try:
    dataset_path = safe_dataset_path(path_text)
    records = load_jsonl(dataset_path)
    summary = validate_records(records)
    if summary["errors"]:
        raise DatasetError("；".join(summary["errors"][:5]))
except DatasetError as exc:
    st.error(str(exc))
    st.stop()

st.sidebar.metric("标注进度", f"{summary['labeled']} / {summary['records']}")
st.sidebar.progress(summary["labeled"] / summary["records"])
st.sidebar.caption(f"数据指纹：{summary['fingerprint'][:16]}…")
unlabeled_indices = [index for index, row in enumerate(records)
                     if row["annotation"]["status"] == "unlabeled"]
default_index = unlabeled_indices[0] if unlabeled_indices else 0
index = st.sidebar.number_input("记录序号", min_value=1, max_value=len(records),
                                value=default_index + 1, step=1) - 1
record = records[index]
annotation = record["annotation"]
widget_key = f"{dataset_path}:{record['id']}"
st.write(f"第 {index + 1} / {len(records)} 条 · `{record['id']}` · 状态：`{annotation['status']}`")

if record["kind"] == "extraction":
    st.subheader(record["title"])
    provenance = record.get("provenance") or {}
    st.caption(f"来源：{provenance.get('source') or '未注明'} · 发布时间：{provenance.get('published_at') or '未注明'}")
    st.text_area("文章正文（只读）", value=record["content"], height=320, disabled=True, key=f"body-{widget_key}")
    suggestions = record.get("model_suggestions") or []
    with st.expander(f"查看模型建议（{len(suggestions)} 条，不计入真值）"):
        st.json(suggestions)

    current_has = annotation.get("has_opportunity")
    choice_index = 0 if current_has is None else (1 if current_has else 2)
    choice = st.radio("这篇文章是否发布了可报名、申请或参与的具体机会？",
                      ["尚未判断", "有机会", "没有机会"], index=choice_index, horizontal=True, key=f"choice-{widget_key}")
    initial_gold = annotation.get("opportunities") or []
    st.caption('请独立填写机会列表；每项包含 name、category、match_keywords 和 fields。模型建议不会预填。')
    gold_text = st.text_area(
        "人工机会列表（JSON）",
        value=json.dumps(initial_gold, ensure_ascii=False, indent=2),
        height=280,
        key=f"gold-{widget_key}",
        disabled=choice == "没有机会",
        help="每项填写 name、category、match_keywords，以及需要严格评测的 fields。空值也可作为明确真值。",
    )
    notes = st.text_area("标注备注", value=str(annotation.get("notes") or ""), key=f"notes-{widget_key}")
    reviewed = st.checkbox("已由第二次检查确认，可标记为 reviewed", value=annotation["status"] == "reviewed", key=f"reviewed-{widget_key}")
    if st.button("保存本条人工标注", type="primary"):
        try:
            if choice == "尚未判断":
                raise DatasetError("请先判断是否包含机会")
            opportunities = [] if choice == "没有机会" else json.loads(gold_text)
            if not isinstance(opportunities, list):
                raise DatasetError("人工机会列表必须是 JSON 数组")
            updated_records = copy.deepcopy(records)
            updated_records[index]["annotation"] = {
                "status": "reviewed" if reviewed else "labeled",
                "has_opportunity": choice == "有机会",
                "opportunities": opportunities,
                "notes": notes.strip(),
            }
            require_valid(updated_records)
            write_jsonl(dataset_path, updated_records)
            st.success("已原子保存。模型建议没有被自动当作标签。")
            st.rerun()
        except (DatasetError, json.JSONDecodeError) as exc:
            st.error(f"无法保存：{exc}")
else:
    st.subheader("推荐排序相关性标注")
    st.caption(f"评测日期固定为 {record['as_of']}；0=无关，1=弱相关，2=相关，3=高度相关。")
    st.json(record["profile"], expanded=False)
    st.info("请先按用户画像独立判断，再展开模型当前排序，避免被系统答案锚定。")
    with st.expander("查看模型当前排序（不计入真值）"):
        st.write(record.get("model_order") or [])
    relevance = annotation.get("relevance") or {}
    grades = {}
    for candidate in record["candidates"]:
        candidate_id = candidate["id"]
        with st.container(border=True):
            st.markdown(f"**{candidate['name']}** · {candidate['category']} · {candidate.get('location') or '地点未注明'}")
            st.caption(candidate.get("summary") or candidate.get("requirements") or "无摘要")
            current = relevance.get(candidate_id)
            choices = [None, 0, 1, 2, 3]
            grades[candidate_id] = st.selectbox(
                "相关性", options=choices, index=choices.index(current),
                format_func=lambda value: "尚未判断" if value is None else str(value),
                key=f"grade-{widget_key}-{candidate_id}",
            )
            with st.expander("候选详情（日期、资格、地点等）"):
                st.json(candidate)
    notes = st.text_area("标注备注", value=str(annotation.get("notes") or ""), key=f"notes-{widget_key}")
    reviewed = st.checkbox("已由第二次检查确认，可标记为 reviewed", value=annotation["status"] == "reviewed", key=f"reviewed-{widget_key}")
    if st.button("保存本组排序标注", type="primary"):
        updated_records = copy.deepcopy(records)
        updated_records[index]["annotation"] = {"status": "reviewed" if reviewed else "labeled",
                                                "relevance": grades, "notes": notes.strip()}
        try:
            require_valid(updated_records)
            write_jsonl(dataset_path, updated_records)
            st.success("已原子保存。")
            st.rerun()
        except DatasetError as exc:
            st.error(f"无法保存：{exc}")
