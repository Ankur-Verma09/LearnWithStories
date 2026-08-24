from __future__ import annotations

import hashlib
import json
from typing import Any

from .config import Settings
from .db import Database
from .memory import ContextMemoryManager, approximate_tokens
from .model_client import create_model_client
from .prompts import PLAN_SYSTEM, REPAIR_SYSTEM, VERIFY_SYSTEM, WRITE_SYSTEM
from .retrieval import Retriever


LEVEL_GUIDES = {
    10: "very common words, short sentences, concrete objects, one idea at a time, frequent recap",
    15: "high-school vocabulary, short paragraphs, simple cause and effect, define exam terms",
    18: "general adult vocabulary, moderate complexity, realistic linked causes, standard exam terms",
    28: "precise educated-adult language, nuanced realistic analogy, compact pace, preserve qualifiers",
}


def level_guide(level: int) -> str:
    nearest = min(LEVEL_GUIDES, key=lambda candidate: abs(candidate - level))
    return LEVEL_GUIDES[nearest]


class StoryTutorAgent:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.database = Database(settings.database_path)
        self.database.initialize()
        self.model = create_model_client(settings)
        self.retriever = Retriever(self.database, settings.max_evidence_chunks)
        self.memory = ContextMemoryManager(self.database, settings.max_memory_tokens)

    @staticmethod
    def _lesson_shape_ok(lesson: dict[str, Any], valid_ids: set[str]) -> bool:
        markers = set(lesson.get("source_markers", [])) if isinstance(lesson.get("source_markers"), list) else set()
        questions = lesson.get("check_questions")
        if not markers or not markers <= valid_ids or not isinstance(questions, list) or len(questions) != 3:
            return False
        for item in questions:
            if not isinstance(item, dict) or not isinstance(item.get("options"), list) or len(item["options"]) != 4:
                return False
            if not isinstance(item.get("correct_index"), int) or not 0 <= item["correct_index"] <= 3:
                return False
            if item.get("evidence_id") not in valid_ids or not item.get("question") or not item.get("explanation"):
                return False
        return True

    def _verify(self, subject: str, concept: str, evidence: list[dict[str, Any]], lesson: dict[str, Any]) -> dict[str, Any]:
        return self.model.chat_json(
            VERIFY_SYSTEM,
            json.dumps({"subject": subject, "concept": concept, "evidence": evidence, "candidate_lesson": lesson}, ensure_ascii=False),
            temperature=0.0,
            max_tokens=1000,
        )

    def create_lesson(self, subject: str, concept: str, level: int, language: str, minutes: int, refresh: bool = False, question: str = "") -> dict[str, Any]:
        if not 10 <= level <= 28:
            raise ValueError("Understanding level must be between 10 and 28")
        if minutes not in {2, 5, 10}:
            raise ValueError("Lesson minutes must be 2, 5, or 10")
        concept = " ".join(concept.split())
        question = " ".join(question.split())
        if not question:
            raise ValueError("Enter the specific question you want to learn")
        evidence = self.retriever.search(subject, concept, question)
        if not evidence:
            scope = f" within {concept}" if concept else ""
            return {"status": "NEEDS_EVIDENCE", "message": f"No approved source material matched this question{scope}."}

        lesson_focus = concept or question
        context = self.memory.build(subject, lesson_focus, level, language)
        cache_material = json.dumps({
            "subject": subject, "concept": concept, "question": question, "level": level, "language": language, "minutes": minutes,
            "model": self.settings.model_name, "evidence": evidence, "context": context,
        }, sort_keys=True, ensure_ascii=False)
        cache_key = hashlib.sha256(cache_material.encode("utf-8")).hexdigest()
        if not refresh and (cached := self.database.cached_lesson(cache_key)):
            return {"status": "PASS", "cached": True, "lesson_id": cached["id"], "lesson": json.loads(cached["lesson_json"]), "verification": json.loads(cached["verification_json"]), "sources": json.loads(cached["evidence_json"])}

        evidence_text = json.dumps(evidence, ensure_ascii=False)
        if approximate_tokens(evidence_text) > self.settings.max_evidence_tokens:
            while evidence and approximate_tokens(json.dumps(evidence, ensure_ascii=False)) > self.settings.max_evidence_tokens:
                evidence.pop()
        common = {
            "subject": subject, "topic_filter": concept or None, "specific_question": question, "concept": lesson_focus, "language": language, "understanding_level": level,
            "level_guide": level_guide(level), "lesson_minutes": minutes, "learner_context": context,
            "evidence": evidence,
        }
        plan = self.model.chat_json(PLAN_SYSTEM, json.dumps(common, ensure_ascii=False), temperature=0.2, max_tokens=900)
        generated_preference = " ".join(str(plan.get("recommended_learning_preference", "")).split())[:300]
        if generated_preference:
            self.database.add_memory_if_absent("model_preference", generated_preference, subject, lesson_focus, 0.65)
        draft_input = dict(common); draft_input["approved_plan"] = plan
        lesson = self.model.chat_json(WRITE_SYSTEM, json.dumps(draft_input, ensure_ascii=False), temperature=0.65, max_tokens={2: 700, 5: 1300, 10: 2200}[minutes])
        valid_ids = {item["evidence_id"] for item in evidence}
        verification = self._verify(subject, lesson_focus, evidence, lesson)
        verdict = str(verification.get("verdict", "FAIL")).upper()
        deterministic_ok = self._lesson_shape_ok(lesson, valid_ids)
        repaired = False
        if verdict != "PASS" or not deterministic_ok:
            repair_payload = {
                "subject": subject, "concept": lesson_focus, "question": question, "evidence": evidence,
                "rejected_lesson": lesson, "verifier_findings": verification,
                "deterministic_format_problem": not deterministic_ok,
            }
            lesson = self.model.chat_json(REPAIR_SYSTEM, json.dumps(repair_payload, ensure_ascii=False), temperature=0.2, max_tokens={2: 700, 5: 1300, 10: 2200}[minutes])
            verification = self._verify(subject, lesson_focus, evidence, lesson)
            verdict = str(verification.get("verdict", "FAIL")).upper()
            deterministic_ok = self._lesson_shape_ok(lesson, valid_ids)
            repaired = True
        status = "PASS" if verdict == "PASS" and deterministic_ok else "FAIL"
        if not deterministic_ok:
            verification.setdefault("repair_instructions", []).append("Use at least one valid evidence marker and provide exactly three check questions.")
            verification["verdict"] = "FAIL"

        lesson_id = self.database.save_lesson({
            "cache_key": cache_key, "subject": subject, "concept": lesson_focus, "question": question, "understanding_level": level,
            "language": language, "model_name": self.settings.model_name,
            "evidence_json": json.dumps(evidence, ensure_ascii=False), "context_json": json.dumps(context, ensure_ascii=False),
            "lesson_json": json.dumps(lesson, ensure_ascii=False), "verification_json": json.dumps(verification, ensure_ascii=False),
            "status": status,
        })
        self.database.record_event("lesson_generation", {"lesson_id": lesson_id, "status": status, "concept": lesson_focus, "question": question, "repaired": repaired})
        return {"status": status, "cached": False, "repaired": repaired, "lesson_id": lesson_id, "lesson": lesson if status == "PASS" else None, "verification": verification, "sources": evidence if status == "PASS" else []}
