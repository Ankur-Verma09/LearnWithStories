import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from story_tutor.agent import StoryTutorAgent
from story_tutor.db import Database
from story_tutor.progression import progression_update
from story_tutor.prompts import FOLLOW_UP_SYSTEM, FOLLOW_UP_VERIFY_SYSTEM


ROOT = Path(__file__).parents[1]


def settings(database_path):
    return SimpleNamespace(
        database_path=database_path, model_provider="ollama", model_name="gemma3:12b",
        model_base_url="http://127.0.0.1:11434", model_api_key="", model_api_keys=(),
        model_temperature=0.65, model_max_retries=1, ollama_keep_alive="30m",
        request_timeout_seconds=120, max_evidence_chunks=5, max_evidence_tokens=3000,
        max_memory_tokens=600, max_session_summary_tokens=300,
        learning_profiles_path=ROOT / "config/learning_profiles.json",
        default_knowledge_level="beginner", default_story_style="realistic_funny",
        default_difficulty="standard",
    )


def lesson_values():
    evidence = [{"evidence_id": "E1", "title": "Math Book", "publisher": "Teacher",
                 "section": "Interest", "subject": "Maths", "concept": "Compound Interest",
                 "text": "Compound interest is calculated on principal plus accumulated interest.",
                 "page_start": 10, "page_end": 11}]
    questions = [{"question": f"Recall {index}?", "options": ["A", "B", "C", "D"],
                  "correct_index": 0, "explanation": "A is supported.", "evidence_id": "E1"}
                 for index in range(3)]
    lesson = {"title": "Interest Story", "story": "A balance grows after interest is added.",
              "concept_summary": "Interest can accumulate.", "key_points": ["Interest is added."],
              "exam_truth": ["Later interest can include accumulated interest."],
              "check_questions": questions}
    return {
        "cache_key": "lesson-one", "subject": "Maths", "concept": "Compound Interest",
        "question": "Why does it grow faster?", "understanding_level": 28, "learner_age": 28,
        "knowledge_level": "beginner", "learning_profile": "adult",
        "story_style": "realistic", "difficulty": "standard", "language": "English",
        "model_provider": "ollama", "model_name": "gemma3:12b", "generation_ms": 10,
        "evidence_json": json.dumps(evidence), "context_json": "{}",
        "lesson_json": json.dumps(lesson), "verification_json": '{"verdict":"PASS"}', "status": "PASS",
    }


class ProgressiveLearningTests(unittest.TestCase):
    def test_progression_is_deterministic_and_age_independent(self):
        first = progression_update(
            current_score=0, attempt_count=0, success_streak=0, incorrect_streak=0,
            score=2, total=3, now=datetime(2026, 8, 24, tzinfo=timezone.utc),
        )
        self.assertEqual(first.progression_stage, "developing")
        self.assertEqual(first.recommended_knowledge_level, "beginner")
        self.assertEqual(first.next_review_at, "2026-08-27T00:00:00Z")

    def test_recall_updates_progress_misconceptions_and_review(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Database(Path(folder) / "story.db")
            database.initialize()
            lesson_id = database.save_lesson(lesson_values())
            questions = json.loads(lesson_values()["lesson_json"])["check_questions"]
            result = database.save_comprehension(lesson_id, 2, 3, [0, 1, 0], "right", questions)
            self.assertEqual(result["stage"], "developing")
            context = database.progression_context("Maths", "Compound Interest")
            self.assertEqual(context["attempt_count"], 1)
            self.assertEqual(len(context["open_misconceptions"]), 1)
            progress = database.progress()
            self.assertEqual(progress["mastery"][0]["progression_stage"], "developing")


class FakeFollowupModel:
    def __init__(self):
        self.calls = []
        self.last_call_metrics = {}

    def chat_json(self, system, user, temperature, max_tokens):
        payload = json.loads(user)
        self.calls.append((system, payload))
        if system == FOLLOW_UP_SYSTEM:
            return {"scope_status": "IN_SCOPE", "answer": "Year two uses principal plus earlier interest.",
                    "source_markers": ["E1"], "suggested_questions": ["How is simple interest different?"],
                    "possible_misconception": "The learner may think only principal earns interest.",
                    "conversation_summary": "The learner asked why later compound interest grows faster."}
        if system == FOLLOW_UP_VERIFY_SYSTEM:
            return {"verdict": "PASS", "unsupported_claims": [], "contradictions": [],
                    "invalid_source_markers": [], "repair_instructions": []}
        raise AssertionError("Unexpected model stage")


class FollowupConversationTests(unittest.TestCase):
    def test_grounded_followup_is_saved_bounded_and_clearable(self):
        with tempfile.TemporaryDirectory() as folder:
            fake = FakeFollowupModel()
            with patch("story_tutor.agent.create_model_client", return_value=fake):
                agent = StoryTutorAgent(settings(Path(folder) / "story.db"))
                lesson_id = agent.database.save_lesson(lesson_values())
                result = agent.ask_followup(lesson_id, "Why is year two larger?")
                self.assertEqual(result["status"], "PASS")
                self.assertEqual(result["sources"][0]["evidence_id"], "E1")
                conversation = agent.database.conversation_for_lesson(lesson_id)
                self.assertEqual([item["role"] for item in conversation["messages"]], ["user", "assistant"])
                self.assertLessEqual(len(agent.database.conversation_context(result["conversation_id"])["recent_messages"]), 6)
                self.assertTrue(agent.database.clear_conversation(lesson_id))
                self.assertEqual(agent.database.conversation_for_lesson(lesson_id)["messages"], [])


class ProgressiveUiAndApiContractTests(unittest.TestCase):
    def test_followup_routes_and_responsive_ui_are_present(self):
        server = (ROOT / "src/story_tutor/web_server.py").read_text(encoding="utf-8")
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        js = (ROOT / "web/app.js").read_text(encoding="utf-8")
        css = (ROOT / "web/question-preferences.css").read_text(encoding="utf-8")
        self.assertIn('/follow-ups', server)
        self.assertIn('id="followupQuestion"', html)
        self.assertIn("loadFollowups", js)
        self.assertIn(".followup-form{grid-template-columns:1fr}", css)


if __name__ == "__main__":
    unittest.main()
