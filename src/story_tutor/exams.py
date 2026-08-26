from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from .config import Settings
from .db import Database
from .memory import approximate_tokens
from .model_client import create_model_client
from .prompts import EXAM_GENERATE_SYSTEM, EXAM_VERIFY_SYSTEM


EXAM_TYPES = {"SUBJECT", "TOPIC", "OVERALL"}
DIFFICULTIES = {"EASY", "MEDIUM", "HARD", "MIXED"}
EXAM_PATTERNS = {
    "GENERAL": {"label": "General practice", "questions": None, "minutes": None, "negative_mark": 0.0,
                "sections": []},
    "IBPS_PO_PRELIMS": {"label": "Bank IBPS PO Prelims", "questions": 100, "minutes": 60,
                        "negative_mark": 0.25,
                        "sections": ["English Language: 30", "Quantitative Aptitude: 35", "Reasoning Ability: 35"]},
    "SBI_PO_PRELIMS": {"label": "SBI PO Prelims", "questions": 100, "minutes": 60,
                       "negative_mark": 0.25,
                       "sections": ["English Language: 30", "Quantitative Aptitude: 35", "Reasoning Ability: 35"]},
    "SSC_CGL_TIER1": {"label": "SSC CGL Tier-I", "questions": 100, "minutes": 60,
                      "negative_mark": 0.50,
                      "sections": ["General Intelligence & Reasoning: 25", "General Awareness: 25",
                                   "Quantitative Aptitude: 25", "English Comprehension: 25"]},
}


def clean_text(value: Any, limit: int = 160) -> str:
    return " ".join(str(value or "").split())[:limit]


def normalized_question(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def balanced_allocations(subjects: list[str], total_questions: int, total_seconds: int) -> list[dict[str, Any]]:
    """Distribute both questions and time deterministically with a maximum difference of one."""
    if not subjects:
        raise ValueError("Choose at least one subject")
    if total_questions < len(subjects):
        raise ValueError("Question count must be at least the number of selected subjects")
    base_q, extra_q = divmod(total_questions, len(subjects))
    base_t, extra_t = divmod(total_seconds, len(subjects))
    return [
        {
            "subject": subject,
            "question_count": base_q + (1 if index < extra_q else 0),
            "time_seconds": base_t + (1 if index < extra_t else 0),
        }
        for index, subject in enumerate(subjects)
    ]


@dataclass(frozen=True)
class ExamRequest:
    exam_name: str
    exam_type: str
    subjects: list[str]
    topic: str
    difficulty: str
    question_count: int
    total_time_minutes: int
    exam_pattern: str
    negative_mark_per_wrong: float

    @classmethod
    def from_payload(cls, payload: dict[str, Any], catalog: list[dict[str, Any]]) -> "ExamRequest":
        name = clean_text(payload.get("exam_name"), 120)
        exam_type = clean_text(payload.get("exam_type"), 20).upper()
        difficulty = clean_text(payload.get("difficulty"), 20).upper()
        exam_pattern = clean_text(payload.get("exam_pattern", "GENERAL"), 40).upper()
        if exam_pattern not in EXAM_PATTERNS:
            raise ValueError("Choose a supported target examination")
        raw_subjects = payload.get("subjects", [])
        if isinstance(raw_subjects, str):
            raw_subjects = [raw_subjects]
        if not isinstance(raw_subjects, list):
            raise ValueError("Subjects must be a list")
        subjects = list(dict.fromkeys(clean_text(value, 80) for value in raw_subjects if clean_text(value, 80)))
        topic = clean_text(payload.get("topic"), 120)
        try:
            count = int(payload.get("question_count", 0))
            minutes = int(payload.get("total_time_minutes", 0))
        except (TypeError, ValueError) as error:
            raise ValueError("Question count and total time must be whole numbers") from error
        if not name:
            raise ValueError("Enter an exam name")
        if exam_type not in EXAM_TYPES:
            raise ValueError("Choose Subject, Topic, or Overall exam type")
        if difficulty not in DIFFICULTIES:
            raise ValueError("Choose Easy, Medium, Hard, or Mixed difficulty")
        pattern = EXAM_PATTERNS[exam_pattern]
        count = int(pattern["questions"] or count)
        minutes = int(pattern["minutes"] or minutes)
        if not 1 <= count <= 100:
            raise ValueError("Question count must be between 1 and 100")
        if not 1 <= minutes <= 300:
            raise ValueError("Total time must be between 1 and 300 minutes")
        available = {clean_text(item.get("subject"), 80).casefold(): clean_text(item.get("subject"), 80) for item in catalog}
        unknown = [subject for subject in subjects if subject.casefold() not in available]
        if unknown:
            raise ValueError(f"No approved content is available for: {', '.join(unknown)}")
        subjects = [available[subject.casefold()] for subject in subjects]
        if exam_type in {"SUBJECT", "TOPIC"} and len(subjects) != 1:
            raise ValueError("Choose exactly one subject for this exam type")
        if exam_type == "OVERALL" and len(subjects) < 2:
            raise ValueError("Choose at least two subjects for an Overall exam")
        if exam_type == "TOPIC" and not topic:
            raise ValueError("Choose or enter a topic")
        if exam_type != "TOPIC":
            topic = ""
        if count < len(subjects):
            raise ValueError("Question count must be at least the number of selected subjects")
        if count > minutes * 60:
            raise ValueError("Total time must allow at least one second per question")
        return cls(name, exam_type, subjects, topic, difficulty, count, minutes,
                   exam_pattern, float(pattern["negative_mark"]))


class ExamService:
    def __init__(self, settings: Settings, database: Database | None = None):
        self.settings = settings
        self.database = database or Database(settings.database_path)
        self.database.initialize()
        self.model = create_model_client(settings)

    def _evidence(self, subject: str, topic: str, limit: int) -> list[dict[str, Any]]:
        rows = [row for row in self.database.chunks(subject) if str(row["approval_status"]).upper() == "APPROVED"]
        normalized_topic = clean_text(topic).casefold()
        if normalized_topic:
            rows = [row for row in rows if normalized_topic in {
                clean_text(row[field]).casefold() for field in ("concept", "topic", "subtopic", "chapter")
            }]
        # Prefer topic diversity for full-subject and overall exams.
        selected: list[Any] = []
        seen: set[str] = set()
        for row in rows:
            key = clean_text(row["subtopic"] or row["topic"] or row["concept"]).casefold()
            if key not in seen:
                selected.append(row); seen.add(key)
        for row in rows:
            if row not in selected:
                selected.append(row)
        evidence = []
        for row in selected[: max(limit, self.settings.max_evidence_chunks)]:
            candidate = {
                "evidence_id": f"E{row['id']}", "subject": row["subject"],
                "topic": row["subtopic"] or row["topic"] or row["concept"],
                "chapter": row["chapter"], "title": row["title"], "publisher": row["publisher"],
                "page_start": row["page_start"], "page_end": row["page_end"], "text": row["text"],
            }
            if evidence and approximate_tokens(json.dumps(evidence + [candidate], ensure_ascii=False)) > self.settings.max_evidence_tokens:
                break
            evidence.append(candidate)
        return evidence

    @staticmethod
    def _validate_questions(raw: Any, valid_ids: set[str], expected: int, existing: set[str]) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or len(raw) != expected:
            raise ValueError(f"The model must return exactly {expected} questions")
        accepted: list[dict[str, Any]] = []
        local_seen: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("Every generated question must be an object")
            question = clean_text(item.get("question"), 1000)
            key = normalized_question(question)
            options = item.get("options")
            correct = item.get("correct_index")
            evidence_id = clean_text(item.get("evidence_id"), 40)
            explanation = clean_text(item.get("explanation"), 2000)
            topic = clean_text(item.get("topic"), 160)
            if len(key) < 12 or key in existing or key in local_seen:
                raise ValueError("Generated questions contain a duplicate or invalid question")
            if not isinstance(options, list) or len(options) != 4:
                raise ValueError("Every question must have exactly four options")
            options = [clean_text(option, 500) for option in options]
            if any(not option for option in options) or len({option.casefold() for option in options}) != 4:
                raise ValueError("Every question must have four distinct non-empty options")
            if not isinstance(correct, int) or not 0 <= correct <= 3:
                raise ValueError("Every question must have one valid correct answer")
            if evidence_id not in valid_ids or not explanation:
                raise ValueError("Every question must contain a valid evidence reference and explanation")
            accepted.append({"question": question, "options": options, "correct_index": correct,
                             "explanation": explanation, "evidence_id": evidence_id, "topic": topic})
            local_seen.add(key)
        return accepted

    def generate(self, payload: dict[str, Any], owner_user_id: int | None = None) -> dict[str, Any]:
        request = ExamRequest.from_payload(payload, self.database.catalog())
        allocations = balanced_allocations(request.subjects, request.question_count, request.total_time_minutes * 60)
        all_questions: list[dict[str, Any]] = []
        seen: set[str] = set()
        for allocation in allocations:
            evidence = self._evidence(allocation["subject"], request.topic, allocation["question_count"] * 2)
            if not evidence:
                focus = f" for topic '{request.topic}'" if request.topic else ""
                raise ValueError(f"No approved evidence is available in {allocation['subject']}{focus}")
            valid_ids = {item["evidence_id"] for item in evidence}
            questions: list[dict[str, Any]] = []
                        stall_attempts = 0
            while len(questions) < allocation["question_count"]:
                batch_count = min(10, allocation["question_count"] - len(questions))
                generation_input = {
                    "exam_name": request.exam_name, "exam_type": request.exam_type,
                    "target_exam_pattern": EXAM_PATTERNS[request.exam_pattern],
                    "subject": allocation["subject"], "topic_filter": request.topic or None,
                    "difficulty": request.difficulty, "requested_count": batch_count,
                    "existing_question_texts": [item["question"] for item in all_questions + questions],
                    "evidence": evidence,
                }
                draft = self.model.chat_json(EXAM_GENERATE_SYSTEM, json.dumps(generation_input, ensure_ascii=False),
                                             temperature=0.25, max_tokens=min(4600, 700 + batch_count * 350))
                batch = self._validate_questions(draft.get("questions"), valid_ids,
                                                 seen | {normalized_question(item["question"]) for item in questions})
                if not batch:
                    stall_attempts += 1
                    if stall_attempts >= 5:
                        raise ValueError("The model could not produce enough unique questions from the supplied evidence")
                    continue
                stall_attempts = 0
                verification = self.model.chat_json(
                    EXAM_VERIFY_SYSTEM,
                    json.dumps({"evidence": evidence, "candidate_questions": batch}, ensure_ascii=False),
                    temperature=0.0, max_tokens=min(1800, 500 + len(batch) * 100),
                )
                if clean_text(verification.get("verdict"), 10).upper() != "PASS":
                    issues = verification.get("issues", [])
                    detail = "; ".join(clean_text(item, 200) for item in issues[:3]) if isinstance(issues, list) else "verification failed"
                    raise ValueError(f"Generated questions were withheld by the factual review gate: {detail}")
                questions.extend(batch[: allocation["question_count"] - len(questions)])
            base_seconds, extra_seconds = divmod(allocation["time_seconds"], allocation["question_count"])
            for question_index, question in enumerate(questions):
                evidence_row = next(item for item in evidence if item["evidence_id"] == question["evidence_id"])
                question.update({
                    "subject": allocation["subject"], "topic": question["topic"] or evidence_row["topic"],
                    "source_title": evidence_row["title"], "source_page_start": evidence_row["page_start"],
                    "source_page_end": evidence_row["page_end"],
                    "allotted_seconds": max(1, base_seconds + (1 if question_index < extra_seconds else 0)),
                    "question_hash": hashlib.sha256(normalized_question(question["question"]).encode("utf-8")).hexdigest(),
                })
                seen.add(normalized_question(question["question"]))
                all_questions.append(question)
        exam_id = self.database.create_exam({
            "exam_name": request.exam_name, "exam_type": request.exam_type, "difficulty": request.difficulty,
            "topic": request.topic, "total_questions": request.question_count,
            "total_time_minutes": request.total_time_minutes, "model_name": self.settings.model_name,
            "config_json": json.dumps(payload, ensure_ascii=False), "owner_user_id": owner_user_id,
            "exam_pattern": request.exam_pattern,
            "negative_mark_per_wrong": request.negative_mark_per_wrong,
        }, allocations, all_questions)
        return self.database.exam_detail(exam_id, reveal_answers=False)
