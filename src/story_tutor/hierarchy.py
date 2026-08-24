from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Iterable


NEEDS_REVIEW = "Needs review"


def clean_name(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" .:-–—\t")


def normalized_name(value: str) -> str:
    return clean_name(value).casefold()


def stable_node_id(source_id: str, node_type: str, parent_id: str, name: str) -> str:
    identity = "|".join((source_id, node_type, parent_id, normalized_name(name)))
    return "node-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class TocChapter:
    number: int
    section: str
    title: str
    page_start: int
    page_end: int


def parse_toc(page_texts: Iterable[str]) -> list[TocChapter]:
    section = ""
    chapters: list[TocChapter] = []
    section_pattern = re.compile(r"SECTION\s*[–—-]?\s*[IVX]+\s*:\s*([^\n]+)", re.I)
    chapter_pattern = re.compile(r"^\s*(\d{1,3})\.\s+(.+?)\s+(\d{1,4})\s*[–—-]\s*(\d{1,4})\s*$")
    for text in page_texts:
        for raw in text.splitlines():
            line = clean_name(raw)
            found_section = section_pattern.search(line)
            if found_section:
                section = clean_name(found_section.group(1)).title()
                continue
            match = chapter_pattern.match(line)
            if not match:
                continue
            title = clean_name(match.group(2))
            if title and normalized_name(title) not in {normalized_name(item.title) for item in chapters}:
                chapters.append(TocChapter(int(match.group(1)), section or NEEDS_REVIEW, title, int(match.group(3)), int(match.group(4))))
    return sorted(chapters, key=lambda item: item.number)


def chapter_for_page(chapters: list[TocChapter], printed_page: int) -> TocChapter | None:
    return next((item for item in chapters if item.page_start <= printed_page <= item.page_end), None)


def infer_printed_page_offset(page_texts: list[str], chapters: list[TocChapter]) -> int | None:
    for chapter in chapters[:8]:
        expected = normalized_name(chapter.title)
        for index, text in enumerate(page_texts):
            first = [clean_name(line) for line in text.splitlines()[:8] if clean_name(line)]
            if any(normalized_name(re.sub(r"^\d+\s+", "", line)) == expected for line in first):
                return (index + 1) - chapter.page_start
    return None


GENERIC_HEADINGS = {
    "quantitative aptitude", "fundamental concepts", "solved examples", "exercise",
    "answers", "explanatory answers", "data sufficiency", "directions",
}


def subtopic_from_page(text: str, chapter: TocChapter | None) -> str:
    chapter_name = normalized_name(chapter.title) if chapter else ""
    candidates: list[str] = []
    for raw in text.splitlines()[:28]:
        line = clean_name(raw)
        if not 3 <= len(line) <= 100:
            continue
        normalized = normalized_name(re.sub(r"^\d+\s+", "", line))
        if normalized == chapter_name or normalized in GENERIC_HEADINGS:
            continue
        if re.fullmatch(r"\d+", line) or re.match(r"^\d+\s+QUANTITATIVE APTITUDE$", line, re.I):
            continue
        if chapter and re.match(rf"^{re.escape(chapter.title)}\s+\d+$", line, re.I):
            continue
        uppercase = line == line.upper() and any(char.isalpha() for char in line) and len(line.split()) <= 10
        if uppercase:
            candidates.append(clean_name(re.sub(r"^[IVXLC]+\.\s+", "", line)).title())
    return candidates[0] if candidates else ""
