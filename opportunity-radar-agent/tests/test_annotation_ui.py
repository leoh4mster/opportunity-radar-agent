"""Exercise annotation controls without a browser or access to real labels."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.services.article_identity import compute_content_hash
from evaluation.datasets import load_jsonl, write_jsonl


ROOT = Path(__file__).resolve().parents[1]


class AnnotationUITest(unittest.TestCase):
    def setUp(self):
        private = ROOT / "evaluation" / "private"
        private.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="ui-test-", dir=private)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "labels.jsonl"
        self.env = patch.dict(os.environ, {"EVALUATION_DATASET": str(self.path)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def app(self):
        app = AppTest.from_file(str(ROOT / "evaluation" / "annotation_app.py")).run()
        self.assertFalse(app.exception)
        return app

    def test_extraction_starts_blank_and_switching_records_does_not_copy_judgment(self):
        records = []
        for i in range(2):
            content = f"独立人工判断案例 {i}"
            records.append({"schema_version": "1.0", "kind": "extraction", "id": str(i),
                            "title": f"案例 {i}", "content": content, "content_hash": compute_content_hash(content),
                            "model_suggestions": [{"name": "模型建议", "category": "实习"}],
                            "annotation": {"status": "unlabeled", "has_opportunity": None, "opportunities": [], "notes": ""}})
        write_jsonl(self.path, records)
        app = self.app()
        self.assertEqual(json.loads(app.text_area[1].value), [])
        app.radio[0].set_value("没有机会").run()
        app.sidebar.number_input[0].set_value(2).run()
        self.assertEqual(app.radio[0].value, "尚未判断")
        self.assertEqual(load_jsonl(self.path), records)

    def test_ranking_cannot_save_unjudged_candidates_as_zero(self):
        record = copy.deepcopy(load_jsonl(ROOT / "evaluation" / "ranking_cases.jsonl")[0])
        record["annotation"] = {"status": "unlabeled", "relevance": {item["id"]: None for item in record["candidates"]}, "notes": ""}
        write_jsonl(self.path, [record])
        app = self.app()
        self.assertTrue(all(widget.value is None for widget in app.selectbox))
        app.button[0].click().run()
        self.assertTrue(app.error)
        self.assertEqual(load_jsonl(self.path), [record])
        for widget in app.selectbox:
            widget.set_value(0)
        app.button[0].click().run()
        self.assertFalse(app.exception)
        saved = load_jsonl(self.path)[0]["annotation"]
        self.assertEqual(saved["status"], "labeled")
        self.assertTrue(all(value == 0 for value in saved["relevance"].values()))
