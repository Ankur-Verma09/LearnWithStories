import json
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from story_tutor.agent import StoryTutorAgent, stable_cache_key
from story_tutor.config import Settings
from story_tutor.db import Database
from story_tutor.learning_profiles import LearningProfileEngine
from story_tutor.model_client import LLMProvider, PROVIDERS
from story_tutor.prompt_builder import StoryPromptBuilder
from story_tutor.prompts import PLAN_SYSTEM, VERIFY_SYSTEM, WRITE_SYSTEM
from story_tutor.schemas import apply_server_metadata, lesson_shape_issues


ROOT = Path(__file__).parents[1]
PROFILES = ROOT / "config/learning_profiles.json"


def valid_lesson(evidence_id="E1"):
    questions = [
        {"question": f"Question {index}?", "options": ["A", "B", "C", "D"],
         "correct_index": 0, "explanation": "Because the approved fact supports A.", "evidence_id": evidence_id}
        for index in range(1, 4)
    ]
    return {
        "title": "The Chair That Pushed Back", "story": "A realistic story about equal and opposite forces.",
        "concept_summary": "Forces occur in equal and opposite pairs.",
        "key_points": ["Forces act on different objects.", "The forces are equal and opposite."],
        "real_world_example": "A person pushes a chair and the chair pushes back.",
        "fun_fact": "Walking depends on an action-reaction pair.",
        "exam_truth": ["Every action has an equal and opposite reaction."],
        "memory_hook": "Push back pair", "source_markers": [evidence_id],
        "check_questions": questions,
    }


class FakeModel:
    def __init__(self):
        self.calls = []
        self.last_call_metrics = {"duration_ms": 4, "prompt_tokens": 20, "output_tokens": 30, "retry_count": 0}

    def chat_json(self, system, user, temperature, max_tokens):
        self.calls.append((system, json.loads(user), temperature, max_tokens))
        if system == PLAN_SYSTEM:
            return {"learning_points": ["Force pairs"], "setting": "office", "characters": ["learner"],
                    "scenes": ["chair rolls"], "analogy_limits": [], "recall_hook": "pair",
                    "evidence_ids": ["E1"], "recommended_learning_preference": "Use realistic demonstrations."}
        if system == WRITE_SYSTEM:
            return valid_lesson()
        if system == VERIFY_SYSTEM:
            return {"verdict": "PASS", "supported_claims": ["Force pairs"], "unsupported_claims": [],
                    "contradictions": [], "invalid_source_markers": [], "objective_coverage": 1.0,
                    "repair_instructions": []}
        raise AssertionError("Unexpected model stage")


def agent_settings(database_path):
    return SimpleNamespace(
        database_path=database_path, model_provider="ollama", model_name="gemma3:12b",
        model_base_url="http://127.0.0.1:11434", model_api_key="", model_api_keys=(),
        model_temperature=0.65, model_max_retries=1, ollama_keep_alive="30m",
        request_timeout_seconds=120, max_evidence_chunks=5, max_evidence_tokens=3000,
        max_memory_tokens=600, learning_profiles_path=PROFILES,
        default_knowledge_level="beginner", default_story_style="realistic_funny",
        default_difficulty="standard",
    )


class LearningProfileTests(unittest.TestCase):
    def setUp(self):
        self.engine = LearningProfileEngine(PROFILES)

    def test_age_and_knowledge_level_are_independent(self):
        adult_beginner = self.engine.build(28, "beginner")
        adult_advanced = self.engine.build(28, "advanced")
        teen_advanced = self.engine.build(16, "advanced")
        self.assertEqual(adult_beginner.age_band, adult_advanced.age_band)
        self.assertEqual(adult_beginner.vocabulary, adult_advanced.vocabulary)
        self.assertNotEqual(adult_beginner.technical_depth, adult_advanced.technical_depth)
        self.assertEqual(teen_advanced.technical_depth, adult_advanced.technical_depth)
        self.assertNotEqual(teen_advanced.vocabulary, adult_advanced.vocabulary)

    def test_profile_override_does_not_override_knowledge(self):
        profile = self.engine.build(28, "beginner", "teenager")
        self.assertEqual(profile.age_band, "teenager")
        self.assertEqual(profile.knowledge_level, "beginner")

    def test_invalid_values_are_rejected(self):
        for age in (4, 101):
            with self.assertRaises(ValueError):
                self.engine.build(age, "beginner")
        with self.assertRaises(ValueError):
            self.engine.build(28, "expert")


class PromptAndSchemaTests(unittest.TestCase):
    def test_prompt_keeps_age_adaptation_separate_from_knowledge_adaptation(self):
        profile = LearningProfileEngine(PROFILES).build(28, "beginner")
        common = StoryPromptBuilder.common(
            subject="Physics", concept="Newton's Third Law", question="Why does a chair push back?",
            language="English", minutes=5, profile=profile, story_style="realistic_funny",
            difficulty="standard", learner_context=[], evidence=[{"evidence_id": "E1"}],
        )
        learner = common["learner"]
        self.assertEqual(learner["age"], 28)
        self.assertEqual(learner["knowledge_level"], "beginner")
        self.assertIn("age_adaptation", learner)
        self.assertIn("knowledge_adaptation", learner)

    def test_schema_accepts_complete_story_and_rejects_duplicate_options(self):
        lesson = valid_lesson()
        self.assertEqual(lesson_shape_issues(lesson, {"E1"}), [])
        lesson["check_questions"][0]["options"] = ["A", "A", "B", "C"]
        self.assertTrue(any("distinct options" in issue for issue in lesson_shape_issues(lesson, {"E1"})))

    def test_server_metadata_cannot_be_overridden_by_model_output(self):
        lesson = apply_server_metadata(
            {**valid_lesson(), "subject": "Injected"}, subject="Physics", topic="Forces", age=28,
            age_profile="adult", knowledge_level="beginner", story_style="realistic_funny", difficulty="standard")
        self.assertEqual(lesson["subject"], "Physics")
        self.assertEqual(lesson["learning_level"]["knowledge_level"], "beginner")

    def test_cache_key_changes_for_knowledge_level(self):
        first = stable_cache_key({"age": 28, "knowledge_level": "beginner"})
        second = stable_cache_key({"age": 28, "knowledge_level": "advanced"})
        self.assertNotEqual(first, second)


class ProviderConfigurationTests(unittest.TestCase):
    def test_provider_registry_uses_common_contract(self):
        self.assertEqual(set(PROVIDERS), {"ollama", "openai"})
        self.assertTrue(all(issubclass(provider, LLMProvider) for provider in PROVIDERS.values()))

    def test_environment_can_override_local_model_without_code_changes(self):
        with patch.dict("os.environ", {
            "LLM_PROVIDER": "ollama", "LLM_MODEL": "gemma3:12b",
            "LLM_BASE_URL": "http://192.168.1.50:11434", "LLM_TEMPERATURE": "0.7",
            "LLM_TIMEOUT": "120", "LLM_MAX_RETRIES": "2",
        }, clear=False):
            settings = Settings.load(ROOT / "config/settings.example.json")
        self.assertEqual(settings.model_name, "gemma3:12b")
        self.assertEqual(settings.model_base_url, "http://192.168.1.50:11434")
        self.assertEqual(settings.model_max_retries, 2)


class AgentPipelineTests(unittest.TestCase):
    def test_grounded_pipeline_and_cache_without_real_model(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = agent_settings(Path(folder) / "story.db")
            fake = FakeModel()
            with patch("story_tutor.agent.create_model_client", return_value=fake):
                agent = StoryTutorAgent(settings)
                agent.database.ingest([{
                    "source_id": "physics-source", "title": "Verified Physics", "publisher": "Teacher",
                    "authority_tier": "approved", "license_note": "test", "edition": "1",
                    "effective_date": "2026-01-01", "subject": "Physics", "concept": "Newton's Third Law",
                    "section": "Forces", "text": "Every action force has an equal and opposite reaction force on another object."
                }])
                first = agent.create_lesson(
                    "Physics", "Newton's Third Law", 28, "English", 5, question="Why does a chair push back?",
                    age=28, knowledge_level="beginner", story_style="realistic_funny", difficulty="standard")
                self.assertEqual(first["status"], "PASS")
                self.assertEqual(first["lesson"]["learning_level"]["age"], 28)
                self.assertEqual(first["lesson"]["learning_level"]["knowledge_level"], "beginner")
                calls_after_first = len(fake.calls)
                cached = agent.create_lesson(
                    "Physics", "Newton's Third Law", 28, "English", 5, question="Why does a chair push back?",
                    age=28, knowledge_level="beginner", story_style="realistic_funny", difficulty="standard")
                self.assertTrue(cached["cached"])
                self.assertEqual(len(fake.calls), calls_after_first)
                different_level = agent.create_lesson(
                    "Physics", "Newton's Third Law", 28, "English", 5, question="Why does a chair push back?",
                    age=28, knowledge_level="advanced", story_style="realistic_funny", difficulty="standard")
                self.assertFalse(different_level["cached"])
                self.assertGreater(len(fake.calls), calls_after_first)


class MigrationAndQualityFixtureTests(unittest.TestCase):
    def test_existing_lesson_age_is_preserved_during_migration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("""CREATE TABLE lessons (
                  id INTEGER PRIMARY KEY,cache_key TEXT NOT NULL UNIQUE,subject TEXT NOT NULL,concept TEXT NOT NULL,
                  question TEXT NOT NULL DEFAULT '',understanding_level INTEGER NOT NULL,language TEXT NOT NULL,
                  model_name TEXT NOT NULL,evidence_json TEXT NOT NULL,context_json TEXT NOT NULL,
                  lesson_json TEXT NOT NULL,verification_json TEXT NOT NULL,status TEXT NOT NULL,
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
                connection.execute("""INSERT INTO lessons
                  (cache_key,subject,concept,question,understanding_level,language,model_name,evidence_json,context_json,lesson_json,verification_json,status)
                  VALUES ('legacy','Physics','Forces','Why?',28,'English','old','[]','{}','{}','{}','PASS')""")
                connection.commit()
            database = Database(path)
            database.initialize()
            row = database.lesson_detail(1)
            self.assertEqual(row["learner_age"], 28)
            self.assertEqual(row["knowledge_level"], "beginner")

    def test_golden_dataset_covers_requested_subjects_and_ages(self):
        cases = json.loads((ROOT / "tests/fixtures/story_quality_cases.json").read_text(encoding="utf-8"))
        self.assertEqual({case["age"] for case in cases}, {8, 12, 16, 22, 28, 40})
        self.assertEqual(len({case["subject"] for case in cases}), 6)


if __name__ == "__main__":
    unittest.main()
