import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SERVER = (ROOT / "src/story_tutor/web_server.py").read_text(encoding="utf-8")
DATABASE = (ROOT / "src/story_tutor/db.py").read_text(encoding="utf-8")
EXAMS = (ROOT / "src/story_tutor/exams.py").read_text(encoding="utf-8")


class ExamContractTests(unittest.TestCase):
    def test_exam_routes_cover_generation_lifecycle_and_history(self):
        for marker in ('/api/exams/generate', '/api/exams/history', 'parts[3] == "start"',
                       'parts[3] == "finish"', 'parts[5] == "answer"'):
            self.assertIn(marker, SERVER)

    def test_active_exam_payload_does_not_reveal_answer_key(self):
        active_branch = DATABASE[DATABASE.index('elif exam["status"] == "IN_PROGRESS"'):DATABASE.index('def exam_detail')]
        self.assertNotIn("correct_index", active_branch)
        self.assertNotIn("explanation", active_branch)

    def test_generation_has_deduplication_and_factual_gate(self):
        self.assertIn("normalized_question", EXAMS)
        self.assertIn("EXAM_VERIFY_SYSTEM", EXAMS)
        self.assertIn('len(options) != 4', EXAMS)

    def test_database_enforces_duplicate_submission_and_question_guards(self):
        self.assertIn("UNIQUE(exam_id, question_id)", DATABASE)
        self.assertIn("UNIQUE(exam_id, submission_key)", DATABASE)
        self.assertIn("UNIQUE(exam_id, question_hash)", DATABASE)


if __name__ == "__main__": unittest.main()
