from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import re


@dataclass(frozen=True)
class ProgressDecision:
    mastery_score: float
    attempt_count: int
    success_streak: int
    incorrect_streak: int
    progression_stage: str
    recommended_knowledge_level: str
    next_review_at: str
    review_interval_days: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def normalize_signal(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value).casefold()))


def misconception_key(value: str) -> str:
    normalized = normalize_signal(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def progression_update(
    *, current_score: float, attempt_count: int, success_streak: int,
    incorrect_streak: int, score: int, total: int,
    difficulty_feedback: str = "right", now: datetime | None = None,
) -> ProgressDecision:
    if total < 1 or score < 0 or score > total:
        raise ValueError("Progress scores must be between zero and the question total")
    if difficulty_feedback not in {"too_easy", "right", "too_hard"}:
        raise ValueError("Invalid difficulty feedback")

    observed = score / total
    current = min(1.0, max(0.0, float(current_score)))
    attempts = max(0, int(attempt_count)) + 1
    learning_rate = 0.40 if attempts <= 3 else 0.25
    mastery = observed if attempt_count < 1 else current + learning_rate * (observed - current)
    mastery = round(min(1.0, max(0.0, mastery)), 4)

    successful = observed >= (2 / 3)
    success_streak = max(0, int(success_streak)) + 1 if successful else 0
    incorrect_streak = 0 if successful else max(0, int(incorrect_streak)) + 1

    if mastery >= 0.85 and attempts >= 4:
        stage, level, interval = "mastered", "advanced", 14
    elif mastery >= 0.65 and attempts >= 2:
        stage, level, interval = "proficient", "intermediate", 7
    elif mastery >= 0.35:
        stage, level, interval = "developing", "beginner", 3
    else:
        stage, level, interval = "foundation", "beginner", 1
    if not successful:
        interval = 1

    current_time = now or datetime.now(timezone.utc)
    next_review = current_time + timedelta(days=interval)
    return ProgressDecision(
        mastery_score=mastery,
        attempt_count=attempts,
        success_streak=success_streak,
        incorrect_streak=incorrect_streak,
        progression_stage=stage,
        recommended_knowledge_level=level,
        next_review_at=next_review.strftime("%Y-%m-%dT%H:%M:%SZ"),
        review_interval_days=interval,
    )
