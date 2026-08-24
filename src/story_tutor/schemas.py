from __future__ import annotations

from typing import Any


def lesson_shape_issues(lesson: dict[str, Any], valid_evidence_ids: set[str]) -> list[str]:
    issues: list[str] = []
    for field in ("title", "story", "concept_summary", "real_world_example", "fun_fact", "memory_hook"):
        if not isinstance(lesson.get(field), str) or not lesson[field].strip():
            issues.append(f"{field} must be a non-empty string")
    for field in ("exam_truth", "key_points"):
        values = lesson.get(field)
        if not isinstance(values, list) or not values or not all(isinstance(item, str) and item.strip() for item in values):
            issues.append(f"{field} must be a non-empty array of strings")
    markers = lesson.get("source_markers")
    if not isinstance(markers, list) or not markers:
        issues.append("source_markers must contain at least one evidence ID")
    elif not set(markers) <= valid_evidence_ids:
        issues.append("source_markers contains an unknown evidence ID")
    questions = lesson.get("check_questions")
    if not isinstance(questions, list) or len(questions) != 3:
        issues.append("check_questions must contain exactly three questions")
        return issues
    for index, item in enumerate(questions):
        prefix = f"check_questions[{index}]"
        if not isinstance(item, dict):
            issues.append(f"{prefix} must be an object")
            continue
        options = item.get("options")
        if not isinstance(options, list) or len(options) != 4 or len({str(option).strip().casefold() for option in options}) != 4:
            issues.append(f"{prefix}.options must contain exactly four distinct options")
        if isinstance(item.get("correct_index"), bool) or not isinstance(item.get("correct_index"), int) or not 0 <= item["correct_index"] <= 3:
            issues.append(f"{prefix}.correct_index must be an integer from 0 to 3")
        if item.get("evidence_id") not in valid_evidence_ids:
            issues.append(f"{prefix}.evidence_id must identify supplied evidence")
        if not isinstance(item.get("question"), str) or not item["question"].strip():
            issues.append(f"{prefix}.question is required")
        if not isinstance(item.get("explanation"), str) or not item["explanation"].strip():
            issues.append(f"{prefix}.explanation is required")
    return issues


def apply_server_metadata(
    lesson: dict[str, Any], *, subject: str, topic: str, age: int,
    age_profile: str, knowledge_level: str, story_style: str, difficulty: str,
) -> dict[str, Any]:
    enriched = dict(lesson)
    enriched["subject"] = subject
    enriched["topic"] = topic
    enriched["learning_level"] = {
        "age": age,
        "profile": age_profile,
        "knowledge_level": knowledge_level,
    }
    enriched["story_style"] = story_style
    enriched["difficulty"] = difficulty
    return enriched
