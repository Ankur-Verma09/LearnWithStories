from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from .config import Settings
from .db import Database
from .learning_profiles import LearningProfileEngine, validate_generation_preferences
from .memory import ContextMemoryManager, approximate_tokens
from .model_client import create_model_client
from .prompt_builder import StoryPromptBuilder
from .prompts import (
    FOLLOW_UP_REPAIR_SYSTEM, FOLLOW_UP_SYSTEM, FOLLOW_UP_VERIFY_SYSTEM,
    PLAN_SYSTEM, REPAIR_SYSTEM, VERIFY_SYSTEM, WRITE_SYSTEM,
)
from .retrieval import Retriever
from .schemas import apply_server_metadata, followup_shape_issues, lesson_shape_issues


def stable_cache_key(material: dict[str, Any]) -> str:
    serialized = json.dumps(material, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class StoryTutorAgent:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.database = Database(settings.database_path)
        self.database.initialize()
        self.model = create_model_client(settings)
        self.retriever = Retriever(self.database, settings.max_evidence_chunks)
        self.memory = ContextMemoryManager(self.database, settings.max_memory_tokens)
        self.profiles = LearningProfileEngine(settings.learning_profiles_path)
        self.prompts = StoryPromptBuilder()

    def _model_call(
        self, stage: str, request_id: str, system: str, user: str,
        *, temperature: float, max_tokens: int,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            result = self.model.chat_json(system, user, temperature=temperature, max_tokens=max_tokens)
        except Exception:
            self.database.record_event("model_call", {
                "request_id": request_id, "stage": stage, "provider": self.settings.model_provider,
                "model": self.settings.model_name, "duration_ms": round((time.perf_counter() - started) * 1000),
                "success": False,
            })
            raise
        metrics = dict(getattr(self.model, "last_call_metrics", {}))
        self.database.record_event("model_call", {
            "request_id": request_id, "stage": stage, "provider": self.settings.model_provider,
            "model": self.settings.model_name,
            "duration_ms": metrics.get("duration_ms", round((time.perf_counter() - started) * 1000)),
            "prompt_tokens": metrics.get("prompt_tokens", max(1, len(system + user) // 4)),
            "output_tokens": metrics.get("output_tokens", max(1, len(json.dumps(result, ensure_ascii=False)) // 4)),
            "retry_count": metrics.get("retry_count", 0), "success": True,
        })
        return result

    def _verify(
        self, request_id: str, subject: str, concept: str,
        evidence: list[dict[str, Any]], lesson: dict[str, Any],
    ) -> dict[str, Any]:
        return self._model_call(
            "verify", request_id, VERIFY_SYSTEM,
            self.prompts.verify(subject, concept, evidence, lesson),
            temperature=0.0, max_tokens=1000,
        )

    def create_lesson(
        self, subject: str, concept: str, level: int, language: str, minutes: int,
        refresh: bool = False, question: str = "", *, age: int | None = None,
        knowledge_level: str = "", story_style: str = "", difficulty: str = "",
        profile_override: str = "", learner_id: int = 1, owner_user_id: int | None = None,
    ) -> dict[str, Any]:
        learner_age = int(age if age is not None else level)
        knowledge_level = knowledge_level or self.settings.default_knowledge_level
        story_style = story_style or self.settings.default_story_style
        difficulty = difficulty or self.settings.default_difficulty
        profile = self.profiles.build(learner_age, knowledge_level, profile_override)
        story_style, difficulty = validate_generation_preferences(story_style, difficulty)
        if minutes not in {2, 5, 10}:
            raise ValueError("Lesson minutes must be 2, 5, or 10")
        subject = " ".join(subject.split())
        concept = " ".join(concept.split())
        question = " ".join(question.split())
        language = " ".join(language.split())
        if not subject:
            raise ValueError("Select a subject with approved learning material")
        if not question:
            raise ValueError("Enter the specific question you want to learn")
        evidence = self.retriever.search(subject, concept, question)
        if not evidence:
            scope = f" within {concept}" if concept else ""
            return {"status": "NEEDS_EVIDENCE", "message": f"No approved source material matched this question{scope}."}

        lesson_focus = concept or question
        context = self.memory.build(subject, lesson_focus, learner_age, language, owner_user_id)
        context["progression"] = self.database.progression_context(subject, lesson_focus, learner_id)
        cache_context = {
            "facts": list(context.get("facts", [])),
            "memories": [item for item in context.get("memories", []) if item.get("kind") != "model_preference"],
        }
        cache_material = {
            "subject": subject, "concept": concept, "question": question,
            "age": learner_age, "age_profile": profile.age_band,
            "knowledge_level": profile.knowledge_level, "profile_override": profile_override,
            "story_style": story_style, "difficulty": difficulty,
            "language": language, "minutes": minutes,
            "provider": self.settings.model_provider, "model": self.settings.model_name,
            "learner_id": learner_id,
            "evidence": evidence, "context": cache_context,
        }
        cache_key = stable_cache_key(cache_material)
        request_id = cache_key[:16]
        if not refresh and (cached := self.database.cached_lesson(cache_key)):
            return {
                "status": "PASS", "cached": True, "lesson_id": cached["id"],
                "lesson": json.loads(cached["lesson_json"]),
                "verification": json.loads(cached["verification_json"]),
                "sources": json.loads(cached["evidence_json"]),
            }

        while evidence and approximate_tokens(json.dumps(evidence, ensure_ascii=False)) > self.settings.max_evidence_tokens:
            evidence.pop()
        if not evidence:
            return {"status": "NEEDS_EVIDENCE", "message": "Approved evidence exceeded the configured context budget."}

        common = self.prompts.common(
            subject=subject, concept=concept, question=question, language=language, minutes=minutes,
            profile=profile, story_style=story_style, difficulty=difficulty,
            learner_context=context, evidence=evidence,
        )
        generation_started = time.perf_counter()
        plan = self._model_call(
            "plan", request_id, PLAN_SYSTEM, self.prompts.plan(common),
            temperature=min(0.25, self.settings.model_temperature), max_tokens=900,
        )
        generated_preference = " ".join(str(plan.get("recommended_learning_preference", "")).split())[:300]
        if generated_preference:
            self.database.add_memory_if_absent(
                "model_preference", generated_preference, subject, lesson_focus, 0.65,
                owner_user_id=owner_user_id, created_by="MODEL",
            )
        output_budget = {2: 900, 5: 1600, 10: 2600}[minutes]
        lesson = self._model_call(
            "write", request_id, WRITE_SYSTEM, self.prompts.write(common, plan),
            temperature=self.settings.model_temperature, max_tokens=output_budget,
        )
        lesson = apply_server_metadata(
            lesson, subject=subject, topic=lesson_focus, age=learner_age,
            age_profile=profile.age_band, knowledge_level=profile.knowledge_level,
            story_style=story_style, difficulty=difficulty,
        )
        valid_ids = {item["evidence_id"] for item in evidence}
        format_issues = lesson_shape_issues(lesson, valid_ids)
        verification = self._verify(request_id, subject, lesson_focus, evidence, lesson)
        verdict = str(verification.get("verdict", "FAIL")).upper()
        repaired = False
        if verdict != "PASS" or format_issues:
            lesson = self._model_call(
                "repair", request_id, REPAIR_SYSTEM,
                self.prompts.repair(
                    subject=subject, concept=lesson_focus, question=question, evidence=evidence,
                    lesson=lesson, verification=verification, format_issues=format_issues,
                ),
                temperature=min(0.2, self.settings.model_temperature), max_tokens=output_budget,
            )
            lesson = apply_server_metadata(
                lesson, subject=subject, topic=lesson_focus, age=learner_age,
                age_profile=profile.age_band, knowledge_level=profile.knowledge_level,
                story_style=story_style, difficulty=difficulty,
            )
            format_issues = lesson_shape_issues(lesson, valid_ids)
            verification = self._verify(request_id, subject, lesson_focus, evidence, lesson)
            verdict = str(verification.get("verdict", "FAIL")).upper()
            repaired = True
        status = "PASS" if verdict == "PASS" and not format_issues else "FAIL"
        if format_issues:
            verification.setdefault("repair_instructions", []).extend(format_issues)
            verification["verdict"] = "FAIL"

        generation_ms = round((time.perf_counter() - generation_started) * 1000)
        lesson_id = self.database.save_lesson({
            "cache_key": cache_key, "subject": subject, "concept": lesson_focus, "question": question,
            "understanding_level": learner_age, "learner_age": learner_age,
            "knowledge_level": profile.knowledge_level, "learning_profile": profile.age_band,
            "story_style": story_style, "difficulty": difficulty, "language": language,
            "model_provider": self.settings.model_provider, "model_name": self.settings.model_name,
            "generation_ms": generation_ms,
            "evidence_json": json.dumps(evidence, ensure_ascii=False),
            "context_json": json.dumps(context, ensure_ascii=False),
            "lesson_json": json.dumps(lesson, ensure_ascii=False),
            "verification_json": json.dumps(verification, ensure_ascii=False), "status": status,
            "learner_id": learner_id,
        })
        self.database.record_event("lesson_generation", {
            "request_id": request_id, "lesson_id": lesson_id, "status": status,
            "subject": subject, "topic": lesson_focus, "age_profile": profile.age_band,
            "knowledge_level": profile.knowledge_level, "provider": self.settings.model_provider,
            "model": self.settings.model_name, "generation_ms": generation_ms,
            "evidence_count": len(evidence), "repaired": repaired,
        })
        if status != "PASS":
            return {
                "status": "LESSON_WITHHELD", "cached": False, "repaired": repaired,
                "lesson_id": lesson_id, "lesson": None, "verification": None, "sources": [],
                "message": "The generated lesson was withheld because it did not pass the factual review. Try again or narrow the question.",
            }
        return {
            "status": status, "cached": False, "repaired": repaired,
            "lesson_id": lesson_id, "lesson": lesson,
            "verification": verification, "sources": evidence,
        }

    def ask_followup(
        self, lesson_id: int, question: str, conversation_id: int | None = None,
        learner_id: int = 1,
    ) -> dict[str, Any]:
        question = " ".join(str(question).split())
        if len(question) < 3:
            raise ValueError("Enter a follow-up question")
        if len(question) > 500:
            raise ValueError("Follow-up questions must be 500 characters or fewer")
        lesson_row = self.database.lesson_detail(lesson_id)
        if lesson_row is None or lesson_row["status"] != "PASS" or int(lesson_row["learner_id"]) != learner_id:
            raise ValueError("Verified lesson not found")

        conversation_id = self.database.get_or_create_conversation(lesson_id, conversation_id, learner_id)
        conversation = self.database.conversation_context(conversation_id, max_messages=6)
        while conversation["recent_messages"] and approximate_tokens(json.dumps(conversation, ensure_ascii=False)) > self.settings.max_session_summary_tokens:
            conversation["recent_messages"].pop(0)

        lesson = json.loads(lesson_row["lesson_json"])
        lesson_snapshot = {
            "subject": lesson_row["subject"], "topic": lesson_row["concept"],
            "original_question": lesson_row["question"], "title": lesson.get("title", ""),
            "concept_summary": lesson.get("concept_summary", ""), "key_points": lesson.get("key_points", []),
            "exam_truth": lesson.get("exam_truth", []), "story": str(lesson.get("story", ""))[:6000],
        }
        evidence = json.loads(lesson_row["evidence_json"])
        while evidence and approximate_tokens(json.dumps(evidence, ensure_ascii=False)) > self.settings.max_evidence_tokens:
            evidence.pop()
        if not evidence:
            return {"status": "NEEDS_EVIDENCE", "message": "The verified source evidence for this lesson is unavailable."}

        learner = {
            "age": int(lesson_row["learner_age"]), "knowledge_level": lesson_row["knowledge_level"],
            "learning_profile": lesson_row["learning_profile"],
            "progression": self.database.progression_context(lesson_row["subject"], lesson_row["concept"], learner_id),
        }
        request_material = {"lesson_id": lesson_id, "question": question, "conversation": conversation}
        request_id = stable_cache_key(request_material)[:16]
        candidate = self._model_call(
            "followup", request_id, FOLLOW_UP_SYSTEM,
            self.prompts.followup(lesson=lesson_snapshot, question=question, evidence=evidence,
                                  conversation=conversation, learner=learner),
            temperature=min(0.35, self.settings.model_temperature), max_tokens=900,
        )
        if str(candidate.get("scope_status", "")).upper() == "OUT_OF_SCOPE":
            safe_answer = "That question is outside this lesson's subject or topic. Start a new lesson so the tutor can retrieve the correct approved evidence."
            saved = self.database.save_followup_exchange(
                conversation_id, question, safe_answer, [],
                str(candidate.get("conversation_summary", "")), learner_id=learner_id,
            )
            return {"status": "OUT_OF_SCOPE", **saved, "suggested_questions": []}

        valid_ids = {item["evidence_id"] for item in evidence}
        issues = followup_shape_issues(candidate, valid_ids)
        verification = self._model_call(
            "followup_verify", request_id, FOLLOW_UP_VERIFY_SYSTEM,
            self.prompts.verify_followup(question=question, evidence=evidence, answer=candidate),
            temperature=0.0, max_tokens=600,
        )
        if str(verification.get("verdict", "FAIL")).upper() != "PASS" or issues:
            candidate = self._model_call(
                "followup_repair", request_id, FOLLOW_UP_REPAIR_SYSTEM,
                self.prompts.repair_followup(
                    question=question, evidence=evidence, conversation=conversation, answer=candidate,
                    verification=verification, format_issues=issues,
                ),
                temperature=min(0.2, self.settings.model_temperature), max_tokens=900,
            )
            issues = followup_shape_issues(candidate, valid_ids)
            verification = self._model_call(
                "followup_verify", request_id, FOLLOW_UP_VERIFY_SYSTEM,
                self.prompts.verify_followup(question=question, evidence=evidence, answer=candidate),
                temperature=0.0, max_tokens=600,
            )
        if issues or str(verification.get("verdict", "FAIL")).upper() != "PASS":
            return {"status": "FOLLOWUP_WITHHELD", "conversation_id": conversation_id,
                    "message": "The follow-up answer was withheld because it could not be verified against the approved sources."}

        markers = set(candidate.get("source_markers", []))
        sources = [{"evidence_id": item["evidence_id"], "title": item.get("title", ""),
                    "section": item.get("section", ""), "page_start": item.get("page_start", 0),
                    "page_end": item.get("page_end", 0)} for item in evidence if item["evidence_id"] in markers]
        saved = self.database.save_followup_exchange(
            conversation_id, question, " ".join(str(candidate["answer"]).split()), sources,
            str(candidate.get("conversation_summary", "")),
            str(candidate.get("possible_misconception", "")), learner_id,
        )
        return {"status": "PASS", **saved, "suggested_questions": candidate.get("suggested_questions", [])[:3],
                "verification": {"verdict": "PASS"}}
