import tempfile
import unittest
from pathlib import Path

from story_tutor.db import Database


class DatabaseHierarchyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(Path(self.temp.name) / "test.db")
        self.db.initialize()

    def tearDown(self): self.temp.cleanup()

    def test_manual_topic_deduplication_and_admin_lock(self):
        first = self.db.create_manual_topic("Maths", " Profit   and Loss ")
        second = self.db.create_manual_topic("Maths", "profit and loss")
        self.assertEqual(first["id"], second["id"])
        renamed = self.db.update_topic(first["id"], "rename", {"display_name": "Profit, Loss and Discount"})
        self.assertEqual(renamed["name_origin"], "admin_corrected")
        self.assertEqual(renamed["name_locked"], 1)

    def test_migration_preserves_legacy_chunk_and_approval(self):
        record = {"source_id":"s","title":"B","publisher":"P","authority_tier":"B","license_note":"ok",
          "edition":"1","effective_date":"2026-01-01","subject":"Maths","concept":"Percentage","section":"p1","text":"evidence"}
        self.db.ingest([record])
        rows = self.db.chunks("Maths")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["approval_status"], "APPROVED")

    def test_search_and_subject_filter(self):
        self.db.create_manual_topic("Maths", "Number System")
        self.db.create_manual_topic("Polity", "Article 21")
        result = self.db.library_hierarchy(search="number", subject="Maths")
        self.assertEqual([x["display_name"] for x in result["nodes"]], ["Number System"])


if __name__ == "__main__": unittest.main()
