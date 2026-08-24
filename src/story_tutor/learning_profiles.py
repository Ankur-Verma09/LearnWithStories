from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


ALLOWED_KNOWLEDGE_LEVELS = ("beginner", "intermediate", "advanced")
ALLOWED_STORY_STYLES = ("realistic_funny", "realistic", "conversational")
ALLOWED_DIFFICULTIES = ("easy", "standard", "challenging")


@dataclass(frozen=True)
class LearningProfile:
    age: int
    age_band: str
    knowledge_level: str
    vocabulary: str
    sentence_style: str
    examples: tuple[str, ...]
    humor: str
    analogy_frequency: str
    technical_depth: str
    prerequisites: str
    terminology: str
    reasoning: str

    def as_prompt_data(self) -> dict[str, Any]:
        return {
            "age": self.age,
            "age_band": self.age_band,
            "knowledge_level": self.knowledge_level,
            "age_adaptation": {
                "vocabulary": self.vocabulary,
                "sentence_style": self.sentence_style,
                "relatable_examples": list(self.examples),
                "humor": self.humor,
                "analogy_frequency": self.analogy_frequency,
            },
            "knowledge_adaptation": {
                "technical_depth": self.technical_depth,
                "prerequisites": self.prerequisites,
                "terminology": self.terminology,
                "reasoning": self.reasoning,
            },
        }


class LearningProfileEngine:
    def __init__(self, config_path: str | Path):
        path = Path(config_path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Learning profile configuration could not be loaded: {path}") from error
        self.age_bands = tuple(raw.get("age_bands", ()))
        self.knowledge_levels = dict(raw.get("knowledge_levels", {}))
        self._validate_configuration()

    def _validate_configuration(self) -> None:
        if not self.age_bands:
            raise ValueError("At least one age band must be configured")
        previous_max: int | None = None
        ids: set[str] = set()
        for band in self.age_bands:
            band_id = str(band.get("id", "")).strip()
            minimum, maximum = int(band.get("min_age", -1)), int(band.get("max_age", -1))
            if not band_id or band_id in ids or minimum < 0 or maximum < minimum:
                raise ValueError("Learning age bands contain an invalid or duplicate definition")
            if previous_max is not None and minimum != previous_max + 1:
                raise ValueError("Learning age bands must be contiguous and ordered")
            ids.add(band_id)
            previous_max = maximum
        if not set(ALLOWED_KNOWLEDGE_LEVELS) <= self.knowledge_levels.keys():
            raise ValueError("Learning profiles must define beginner, intermediate, and advanced knowledge levels")

    def build(self, age: int, knowledge_level: str, profile_override: str = "") -> LearningProfile:
        if isinstance(age, bool):
            raise ValueError("Learner age must be a whole number")
        age = int(age)
        if not 5 <= age <= 100:
            raise ValueError("Learner age must be between 5 and 100")
        knowledge_level = " ".join(str(knowledge_level).lower().split())
        if knowledge_level not in ALLOWED_KNOWLEDGE_LEVELS:
            raise ValueError("Knowledge level must be beginner, intermediate, or advanced")
        selected = None
        override = " ".join(str(profile_override).lower().split())
        if override:
            selected = next((band for band in self.age_bands if band["id"] == override), None)
            if selected is None:
                raise ValueError("The selected learning profile override is not configured")
        else:
            selected = next((band for band in self.age_bands if int(band["min_age"]) <= age <= int(band["max_age"])), None)
        if selected is None:
            raise ValueError("No learning profile is configured for this age")
        knowledge = self.knowledge_levels[knowledge_level]
        return LearningProfile(
            age=age,
            age_band=str(selected["id"]),
            knowledge_level=knowledge_level,
            vocabulary=str(selected["vocabulary"]),
            sentence_style=str(selected["sentence_style"]),
            examples=tuple(str(item) for item in selected.get("examples", ())),
            humor=str(selected["humor"]),
            analogy_frequency=str(selected["analogy_frequency"]),
            technical_depth=str(knowledge["technical_depth"]),
            prerequisites=str(knowledge["prerequisites"]),
            terminology=str(knowledge["terminology"]),
            reasoning=str(knowledge["reasoning"]),
        )


def validate_generation_preferences(story_style: str, difficulty: str) -> tuple[str, str]:
    story_style = " ".join(str(story_style).lower().split())
    difficulty = " ".join(str(difficulty).lower().split())
    if story_style not in ALLOWED_STORY_STYLES:
        raise ValueError("Story style must be realistic_funny, realistic, or conversational")
    if difficulty not in ALLOWED_DIFFICULTIES:
        raise ValueError("Difficulty must be easy, standard, or challenging")
    return story_style, difficulty
