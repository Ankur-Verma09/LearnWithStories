from __future__ import annotations

import re
from typing import Any

from .db import Database


STOP_WORDS = {"the", "a", "an", "of", "to", "and", "or", "in", "is", "what", "explain", "tell", "me", "about"}


def terms(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) > 1 and word not in STOP_WORDS}


class Retriever:
    def __init__(self, database: Database, max_chunks: int):
        self.database = database
        self.max_chunks = max_chunks

    def search(self, subject: str, concept: str, question: str = "") -> list[dict[str, Any]]:
        query_terms = terms(f"{subject} {concept} {question}")
        scored: list[tuple[float, Any]] = []
        candidates = self.database.chunks(subject)
        selected_topic = " ".join(concept.split()).casefold()
        exact = [row for row in candidates if selected_topic and selected_topic in {
            " ".join(str(row[field] or "").split()).casefold() for field in ("concept", "topic", "subtopic", "chapter")
        }]
        # For the first agent slice, exact concept boundaries are safer than
        # silently mixing related concepts. Prerequisites will later be linked
        # through an explicit syllabus graph rather than lexical coincidence.
        if selected_topic:
            candidates = exact
        for row in candidates:
            title_terms = terms(f"{row['concept']} {row['section']} {row['title']}")
            body_terms = terms(row["text"])
            score = 3.0 * len(query_terms & title_terms) + 1.0 * len(query_terms & body_terms)
            if selected_topic and selected_topic in {str(row["concept"]).casefold(), str(row["topic"]).casefold(), str(row["subtopic"]).casefold(), str(row["chapter"]).casefold()}:
                score += 8.0
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda item: (-item[0], item[1]["id"]))
        results = []
        for score, row in scored[: self.max_chunks]:
            results.append({
                "evidence_id": f"E{row['id']}", "score": score, "source_id": row["source_id"],
                "title": row["title"], "publisher": row["publisher"], "section": row["section"],
                "subject": row["subject"], "concept": row["concept"], "text": row["text"],
            })
        return results
