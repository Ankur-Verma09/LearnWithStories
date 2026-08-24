import tempfile
import unittest
from pathlib import Path

from story_tutor.db import Database
from story_tutor.exams import ExamRequest, balanced_allocations, normalized_question


CATALOG = [{"subject": "History", "topics": ["Ancient India"]},
           {"subject": "Polity", "topics": ["Article 21"]},
           {"subject": "Geography", "topics": ["Rivers"]}]


class ExamDomainTests(unittest.TestCase):
    def test_overall_allocation_is_balanced_and_preserves_totals(self):
        rows = balanced_allocations(["History", "Polity", "Geography"], 61, 3601)
        self.assertEqual(sum(row["question_count"] for row in rows), 61)
        self.assertEqual(sum(row["time_seconds"] for row in rows), 3601)
        self.assertLessEqual(max(row["question_count"] for row in rows)-min(row["question_count"] for row in rows), 1)
        self.assertLessEqual(max(row["time_seconds"] for row in rows)-min(row["time_seconds"] for row in rows), 1)

    def test_topic_exam_requires_topic_and_one_subject(self):
        with self.assertRaisesRegex(ValueError, "topic"):
            ExamRequest.from_payload({"exam_name":"Test","exam_type":"TOPIC","subjects":["Polity"],
              "difficulty":"MEDIUM","question_count":10,"total_time_minutes":10}, CATALOG)

    def test_duplicate_normalization_ignores_case_and_punctuation(self):
        self.assertEqual(normalized_question("What is Article 21?"), normalized_question("WHAT is Article-21"))

    def test_exam_answers_are_locked_and_evaluated_once(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            database = Database(Path(folder) / "exam.db"); database.initialize()
            exam_id = database.create_exam({"exam_name":"Static fixture","exam_type":"SUBJECT","difficulty":"EASY",
              "topic":"","total_questions":1,"total_time_minutes":1,"model_name":"fixture","config_json":"{}"},
              [{"subject":"Polity","question_count":1,"time_seconds":60}],
              [{"subject":"Polity","topic":"Article 21","question":"Which right is protected?","question_hash":"unique",
                "options":["Life and liberty","Trade","Religion only","Property"],"correct_index":0,
                "explanation":"Article 21 protects life and personal liberty.","evidence_id":"E1","source_title":"Constitution",
                "source_page_start":1,"source_page_end":1,"allotted_seconds":60}])
            started = database.start_exam(exam_id)
            completed = database.submit_exam_answer(exam_id, started["current_question"]["id"], 0, "one")
            duplicate = database.submit_exam_answer(exam_id, started["current_question"]["id"], 1, "two")
            self.assertEqual(completed["correct_count"], 1)
            self.assertEqual(duplicate["correct_count"], 1)
            self.assertEqual(duplicate["analysis"][0]["selected_index"], 0)


if __name__ == "__main__": unittest.main()
