import tempfile
import unittest
from pathlib import Path

from story_tutor.db import Database
from story_tutor.retrieval import Retriever


def record(concept, text):
    return {"source_id":"book","title":"Maths","publisher":"Author","authority_tier":"B","license_note":"ok",
      "edition":"1","effective_date":"2026-01-01","subject":"Maths","concept":concept,"section":concept,"text":text,
      "document_id":1,"section_name":"Arithmetic","chapter":concept,"topic_id":"topic-"+concept,"topic":concept,
      "subtopic_id":"","subtopic":"","page_start":1,"page_end":2,"name_origin":"extracted","approval_status":"APPROVED","name_locked":0}


class QuestionAndPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(Path(self.temp.name) / "test.db")
        self.db.initialize()
        self.db.ingest([record("Percentage", "Percentage compares a part per hundred and solves percentage change."),
                        record("Profit and Loss", "Profit is selling price minus cost price.")])

    def tearDown(self): self.temp.cleanup()

    def test_selected_topic_strictly_filters_question_retrieval(self):
        results = Retriever(self.db, 5).search("Maths", "Percentage", "How is percentage change calculated?")
        self.assertTrue(results)
        self.assertEqual({item["concept"] for item in results}, {"Percentage"})

    def test_blank_topic_searches_question_across_subject(self):
        results = Retriever(self.db, 5).search("Maths", "", "What is selling price and cost price?")
        self.assertEqual(results[0]["concept"], "Profit and Loss")

    def test_preferences_can_be_deduplicated_and_deleted(self):
        first = self.db.add_memory_if_absent("model_preference", "Use a visual comparison", "Maths", "Percentage")
        second = self.db.add_memory_if_absent("model_preference", " use a visual comparison ", "Maths", "Percentage")
        self.assertEqual(first, second)
        self.assertTrue(self.db.delete_memory(first))
        self.assertFalse(self.db.delete_memory(first))


if __name__ == "__main__": unittest.main()
