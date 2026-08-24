from __future__ import annotations

from typing import Any

from .db import Database


def approximate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


class ContextMemoryManager:
    def __init__(self, database: Database, max_tokens: int):
        self.database = database
        self.max_tokens = max_tokens

    def build(self, subject: str, concept: str, level: int, language: str) -> dict[str, Any]:
        fixed = [
            f"preferred_language={language}",
            f"understanding_level={level}",
        ]
        selected: list[dict[str, Any]] = []
        used = approximate_tokens("\n".join(fixed))
        for row in self.database.memories(subject, concept):
            cost = approximate_tokens(row["content"])
            if used + cost > self.max_tokens:
                continue
            selected.append({"id": row["id"], "kind": row["kind"], "content": row["content"]})
            used += cost
        return {"facts": fixed, "memories": selected, "approximate_tokens": used}

