from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree

from .hierarchy import NEEDS_REVIEW, chapter_for_page, infer_printed_page_offset, parse_toc, stable_node_id, subtopic_from_page


class ConversionError(ValueError):
    pass


def safe_name(name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._ -]+", "", Path(name).name).strip(" .")
    return clean[:160] or "uploaded-document"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _clean(text: str) -> str:
    text = text.replace("\x00", " ").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _chunks(text: str, limit: int = 3600, overlap: int = 240) -> list[str]:
    text = _clean(text)
    if not text:
        return []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n", start + limit // 2, end), text.rfind(". ", start + limit // 2, end))
            if boundary > start:
                end = boundary + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _likely_heading(line: str) -> bool:
    line = re.sub(r"\s+", " ", line).strip(" :-")
    if not 4 <= len(line) <= 90 or len(line.split()) > 12:
        return False
    if re.match(r"^(chapter|unit|part|section)\s+[0-9ivxlcdm]+\b", line, re.I):
        return True
    if re.match(r"^\d{1,3}[.)-]\s+[A-Za-z]", line):
        return True
    letters = [c for c in line if c.isalpha()]
    return len(letters) >= 4 and line == line.upper()


def _record(meta: dict[str, str], source_id: str, concept: str, section: str, text: str, hierarchy: dict | None = None) -> dict[str, str | int]:
    item: dict[str, str | int] = {
        "source_id": source_id,
        "title": meta["title"],
        "publisher": meta["publisher"],
        "authority_tier": "B",
        "license_note": meta["license_note"],
        "edition": meta["edition"],
        "effective_date": date.today().isoformat(),
        "subject": meta["subject"],
        "concept": concept,
        "section": section,
        "text": text,
    }
    item.update(hierarchy or {
        "document_id": int(meta.get("document_id", "0") or 0), "section_name": "", "chapter": section,
        "topic_id": stable_node_id(source_id, "topic", "", concept), "topic": concept,
        "subtopic_id": "", "subtopic": "", "page_start": 0, "page_end": 0,
        "name_origin": "manual" if meta.get("default_topic") else "extracted",
        "approval_status": "APPROVED", "name_locked": 0,
    })
    return item


def _pdf_records(path: Path, meta: dict[str, str], source_id: str) -> list[dict[str, str]]:
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise ConversionError("PDF support is not installed. Run setup-learn-with-stories.cmd once, then restart the application.") from error
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise ConversionError("This PDF is password-protected. Upload an unlocked copy.")
        pages = [(index + 1, _clean(page.extract_text() or "")) for index, page in enumerate(reader.pages)]
    except ConversionError:
        raise
    except Exception as error:
        raise ConversionError("The PDF could not be read. Confirm that it is a valid, uncorrupted PDF and try again.") from error
    usable = [(number, text) for number, text in pages if len(text) >= 80]
    if not usable or len(usable) < max(1, len(pages) // 10):
        raise ConversionError("This appears to be a scanned PDF without searchable text. Convert it with OCR, then upload the searchable PDF.")
    chapters = parse_toc(text for _, text in pages[:20])
    offset = infer_printed_page_offset([text for _, text in pages], chapters)
    current_subtopics: dict[int, str] = {}
    records: list[dict[str, str]] = []
    for page_number, text in usable:
        printed_page = page_number - offset if offset is not None else page_number
        chapter = chapter_for_page(chapters, printed_page)
        chapter_name = chapter.title if chapter else NEEDS_REVIEW
        section_name = chapter.section if chapter else NEEDS_REVIEW
        # PDF exercise layouts frequently format questions like headings. Use the
        # TOC chapter as the authoritative topic and leave sub-topic blank unless
        # a future book-specific extractor can identify it reliably.
        detected = ""
        if chapter and detected:
            current_subtopics[chapter.number] = detected
        subtopic = current_subtopics.get(chapter.number, "") if chapter else ""
        topic = chapter_name
        concept = subtopic or topic
        origin = "extracted" if chapter else "needs_review"
        chapter_id = stable_node_id(source_id, "chapter", "", f"{section_name}|{chapter_name}")
        topic_id = stable_node_id(source_id, "topic", chapter_id, topic)
        subtopic_id = stable_node_id(source_id, "subtopic", topic_id, subtopic) if subtopic else ""
        hierarchy = {
            "document_id": int(meta.get("document_id", "0") or 0), "chapter": chapter_name,
            "section_name": section_name, "topic_id": topic_id, "topic": topic,
            "subtopic_id": subtopic_id, "subtopic": subtopic, "page_start": printed_page,
            "page_end": printed_page, "name_origin": origin,
            "approval_status": "APPROVED" if chapter else "NEEDS_REVIEW", "name_locked": 0,
        }
        for index, chunk in enumerate(_chunks(text), 1):
            records.append(_record(meta, source_id, concept, f"PDF page {page_number}, chunk {index}", chunk, hierarchy))
    return records


def _docx_records(path: Path, meta: dict[str, str], source_id: str) -> list[dict[str, str]]:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as error:
        raise ConversionError("The Word file is not a valid DOCX document. Legacy .doc files must first be saved as .docx.") from error
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as error:
        raise ConversionError("The Word document structure is damaged. Open and save it as a new DOCX file, then try again.") from error
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    current = meta["default_topic"] or meta["title"]
    blocks: list[tuple[str, str]] = []
    buffer: list[str] = []
    for paragraph in root.iter(ns + "p"):
        text = _clean("".join(node.text or "" for node in paragraph.iter(ns + "t")))
        if not text:
            continue
        style_node = paragraph.find(f"{ns}pPr/{ns}pStyle")
        style = style_node.attrib.get(ns + "val", "") if style_node is not None else ""
        is_heading = style.lower().startswith("heading") or _likely_heading(text)
        if is_heading:
            if buffer:
                blocks.append((current, "\n\n".join(buffer)))
                buffer = []
            current = text[:120]
        else:
            buffer.append(text)
    if buffer:
        blocks.append((current, "\n\n".join(buffer)))
    records: list[dict[str, str]] = []
    for block_index, (concept, text) in enumerate(blocks, 1):
        for chunk_index, chunk in enumerate(_chunks(text), 1):
            records.append(_record(meta, source_id, concept, f"DOCX section {block_index}, chunk {chunk_index}", chunk))
    if not records:
        raise ConversionError("No readable text was found in this DOCX file.")
    return records


def _text_records(path: Path, meta: dict[str, str], source_id: str) -> list[dict[str, str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ConversionError("The text file must use UTF-8 encoding.") from error
    records = [_record(meta, source_id, meta["default_topic"] or meta["title"], f"Text chunk {i}", chunk) for i, chunk in enumerate(_chunks(text), 1)]
    if not records:
        raise ConversionError("No readable text was found in this file.")
    return records


def validate_jsonl(path: Path, expected_subject: str) -> list[dict[str, str]]:
    required = {"source_id", "title", "publisher", "authority_tier", "license_note", "edition", "effective_date", "subject", "concept", "section", "text"}
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as error:
            raise ConversionError(f"Invalid JSON on line {number}: {error.msg}") from error
        missing = required - item.keys()
        if missing:
            raise ConversionError(f"JSONL line {number} is missing: {', '.join(sorted(missing))}")
        if expected_subject and item["subject"].strip().lower() != expected_subject.lower():
            raise ConversionError(f"JSONL line {number} uses subject '{item['subject']}', not '{expected_subject}'.")
        if not str(item["text"]).strip() or not str(item["concept"]).strip():
            raise ConversionError(f"JSONL line {number} has an empty topic or text value.")
        records.append(item)
    if not records:
        raise ConversionError("The JSONL file contains no records.")
    return records


def convert_document(path: Path, output_dir: Path, metadata: dict[str, str], source_id: str = "") -> tuple[Path, list[dict[str, str]]]:
    meta = {key: str(value).strip() for key, value in metadata.items()}
    meta.setdefault("publisher", "User-provided source")
    meta.setdefault("edition", "Uploaded edition")
    meta.setdefault("license_note", "User confirms authorization for private educational use.")
    meta.setdefault("default_topic", "")
    if not meta.get("subject"):
        raise ConversionError("Subject is required.")
    meta["title"] = meta.get("title") or path.stem
    digest = file_sha256(path)
    source_id = source_id or f"upload-{digest[:16]}"
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        records = _pdf_records(path, meta, source_id)
    elif suffix == ".docx":
        records = _docx_records(path, meta, source_id)
    elif suffix == ".txt":
        records = _text_records(path, meta, source_id)
    elif suffix == ".jsonl":
        records = validate_jsonl(path, meta["subject"])
        records = [{**record, "source_id": source_id} for record in records]
    else:
        raise ConversionError("Unsupported file type. Upload PDF, DOCX, TXT, or JSONL.")
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{safe_name(path.stem)}-{safe_name(source_id)[-12:]}.jsonl"
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return output, records
