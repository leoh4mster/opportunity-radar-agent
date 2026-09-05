from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.entities import Article
from app.services.import_service import ImportService


class ImportServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine)()

    def tearDown(self) -> None:
        self.session.close()

    def test_repeated_import_is_idempotent(self) -> None:
        payload = {
            "articles": [
                {"title": "实习招募", "content": "报名截止：2030-12-31\n地点：上海"},
                {"title": "空白不同但正文相同", "content": "报名截止： 2030-12-31\n\n地点：上海"},
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "articles.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            first_articles, first_skipped = ImportService().import_file(self.session, str(path))
            second_articles, second_skipped = ImportService().import_file(self.session, str(path))

        self.assertEqual(len(first_articles), 1)
        self.assertEqual(first_skipped, 1)
        self.assertEqual(second_articles, [])
        self.assertEqual(second_skipped, 2)
        self.assertEqual(self.session.query(Article).count(), 1)


if __name__ == "__main__":
    unittest.main()
