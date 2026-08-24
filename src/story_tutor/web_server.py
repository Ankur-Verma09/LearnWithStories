from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import socket
import sqlite3
import threading
from typing import Any
from urllib.parse import parse_qs, urlparse
import uuid

from .agent import StoryTutorAgent
from .config import Settings
from .converter import ConversionError, convert_document, file_sha256, safe_name
from .db import Database
from .exams import ExamService
from .model_client import ModelError, create_model_client, public_model_error


def public_validation_error(error: Exception, fallback: str = "Review the submitted values and try again.") -> str:
    message = " ".join(str(error).split())
    technical = re.compile(
        r"traceback|stack trace|syntaxerror|typeerror|referenceerror|sqlite|urllib|"
        r"<!doctype|<html|<script|```|\bfunction\s*\(|\bselect\s+.+\bfrom\b|"
        r"\binsert\s+into\b|(?:[a-z]:\\|/(?:app|usr|home|var)/)|\bat\s+[\w$.]+\s*\(",
        re.IGNORECASE,
    )
    if not message or len(message) > 300 or technical.search(message):
        return fallback
    return message


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    """Prevent multiple app instances from sharing the same Windows port."""

    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class TutorWebApplication:
    def __init__(self, settings: Settings, static_dir: Path):
        self.settings = settings
        self.static_dir = static_dir
        self.agent = StoryTutorAgent(settings)
        self.database = Database(settings.database_path)
        self.database.initialize()
        self.exams = ExamService(settings, self.database)
        self.generation_lock = threading.Lock()
        self.upload_lock = threading.Lock()

    def document_inventory(self) -> list[dict[str, Any]]:
        registered = self.database.documents()
        known = {
            Path(item[key]).resolve()
            for item in registered
            for key in ("stored_path", "jsonl_path")
            if item.get(key)
        }
        discovered = []
        source_root = Path("data/sources")
        if source_root.exists():
            for path in sorted(source_root.rglob("*"), key=lambda item: item.stat().st_mtime if item.is_file() else 0, reverse=True):
                if not path.is_file() or path.suffix.lower() not in {".pdf", ".docx", ".txt", ".jsonl"} or path.resolve() in known:
                    continue
                discovered.append({
                    "id": f"disk:{path.as_posix()}", "file_name": path.name, "subject": "Not assigned",
                    "title": path.stem, "file_type": path.suffix.lstrip("."), "status": "ON_DISK", "records": 0,
                    "error_message": "Use Add a document to assign a subject and index this file." if path.suffix.lower() != ".jsonl" else "Existing source file on disk.",
                    "created_at": "", "jsonl_path": str(path) if path.suffix.lower() == ".jsonl" else "",
                })
        for item in registered:
            item.pop("stored_path", None)
            if item.get("error_message"):
                item["error_message"] = public_validation_error(
                    ValueError(str(item["error_message"])),
                    "This document could not be processed. Review it and try again.",
                )
        return registered + discovered

    def handler(self):
        application = self

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(application.static_dir), **kwargs)

            def log_message(self, format: str, *args: Any) -> None:
                print(f"WEB {self.address_string()} {format % args}")

            def send_json(self, status: HTTPStatus, payload: Any) -> None:
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.end_headers()
                self.wfile.write(data)

            def read_json(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 32768:
                    raise ValueError("Request body must be between 1 byte and 32 KB")
                parsed = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(parsed, dict):
                    raise ValueError("JSON body must be an object")
                return parsed

            def header_text(self, name: str, default: str = "") -> str:
                value = self.headers.get(name, default).strip()
                if "\r" in value or "\n" in value:
                    raise ValueError(f"Invalid {name} header")
                return value[:500]

            def save_upload(self, destination: Path, length: int) -> None:
                destination.parent.mkdir(parents=True, exist_ok=True)
                remaining = length
                with destination.open("wb") as stream:
                    while remaining:
                        block = self.rfile.read(min(1024 * 1024, remaining))
                        if not block:
                            raise ValueError("The upload ended before the full file was received.")
                        stream.write(block)
                        remaining -= len(block)

            def do_GET(self) -> None:
                parsed_url = urlparse(self.path)
                path = parsed_url.path
                if path == "/api/config":
                    self.send_json(HTTPStatus.OK, {
                        "api_version": 4,
                        "features": ["document_upload", "pdf_conversion", "docx_conversion", "library_management", "online_examinations"],
                        "default_level": application.settings.default_understanding_level,
                        "default_language": application.settings.default_language,
                        "model_provider": application.settings.model_provider,
                        "model_name": application.settings.model_name,
                        "configured_api_keys": len(application.settings.model_api_keys) if application.settings.model_provider == "openai" else 0,
                    })
                    return
                if path == "/api/history":
                    self.send_json(HTTPStatus.OK, [dict(row) for row in application.database.lesson_history(12)])
                    return
                if path.startswith("/api/lessons/"):
                    try:
                        lesson_id = int(path.rsplit("/", 1)[-1])
                    except ValueError:
                        self.send_json(HTTPStatus.BAD_REQUEST, {"message": "Invalid lesson id"})
                        return
                    row = application.database.lesson_detail(lesson_id)
                    if row is None:
                        self.send_json(HTTPStatus.NOT_FOUND, {"message": "Lesson not found"})
                        return
                    if row["status"] != "PASS":
                        self.send_json(HTTPStatus.CONFLICT, {
                            "status": "LESSON_WITHHELD",
                            "message": "This lesson was withheld because it did not pass the factual review.",
                        })
                        return
                    self.send_json(HTTPStatus.OK, {
                        "lesson_id": row["id"], "subject": row["subject"], "concept": row["concept"],
                        "question": row["question"],
                        "level": row["understanding_level"], "language": row["language"], "status": row["status"],
                        "created_at": row["created_at"], "lesson": json.loads(row["lesson_json"]),
                        "verification": json.loads(row["verification_json"]), "sources": json.loads(row["evidence_json"]),
                    })
                    return
                if path == "/api/progress":
                    self.send_json(HTTPStatus.OK, application.database.progress())
                    return
                if path == "/api/content":
                    self.send_json(HTTPStatus.OK, application.database.content_inventory())
                    return
                if path == "/api/catalog":
                    self.send_json(HTTPStatus.OK, application.database.catalog())
                    return
                if path == "/api/documents":
                    self.send_json(HTTPStatus.OK, application.document_inventory())
                    return
                if path == "/api/library/hierarchy":
                    query = parse_qs(parsed_url.query)
                    self.send_json(HTTPStatus.OK, application.database.library_hierarchy(
                        search=query.get("search", [""])[0], subject=query.get("subject", [""])[0],
                        document_id=int(query.get("document_id", ["0"])[0] or 0)))
                    return
                if path == "/api/memories":
                    self.send_json(HTTPStatus.OK, application.database.memory_inventory())
                    return
                if path == "/api/exams/history":
                    query = parse_qs(parsed_url.query)
                    self.send_json(HTTPStatus.OK, application.database.exam_history(int(query.get("limit", ["50"])[0])))
                    return
                if path.startswith("/api/exams/"):
                    parts = path.strip("/").split("/")
                    if len(parts) == 3:
                        exam = application.database.exam_detail(int(parts[2]))
                        if exam is None:
                            self.send_json(HTTPStatus.NOT_FOUND, {"message": "Exam not found"})
                        else:
                            self.send_json(HTTPStatus.OK, exam)
                        return
                if path == "/api/health":
                    try:
                        response = create_model_client(application.settings).health()
                        models = [item.get("name", "") for item in response.get("models", [])]
                        self.send_json(HTTPStatus.OK, {"status": "online", "provider": application.settings.model_provider, "models": models, "configured_model": application.settings.model_name})
                    except ModelError as error:
                        self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {
                            "status": "MODEL_OFFLINE",
                            "message": public_model_error(error, application.settings.model_provider),
                        })
                    return
                if path.startswith("/api/"):
                    self.send_json(HTTPStatus.NOT_FOUND, {"status": "NOT_FOUND", "message": "API endpoint not found"})
                    return
                if path == "/":
                    self.path = "/index.html"
                super().do_GET()

            def do_POST(self) -> None:
                path = urlparse(self.path).path
                try:
                    if path == "/api/upload":
                        self.handle_upload()
                        return
                    payload = self.read_json()
                    if path == "/api/exams/generate":
                        if not application.generation_lock.acquire(blocking=False):
                            self.send_json(HTTPStatus.CONFLICT, {"status": "BUSY", "message": "Another AI generation task is currently running."})
                            return
                        try:
                            result = application.exams.generate(payload)
                        finally:
                            application.generation_lock.release()
                        self.send_json(HTTPStatus.CREATED, result)
                        return
                    if path.startswith("/api/exams/"):
                        parts = path.strip("/").split("/")
                        exam_id = int(parts[2]) if len(parts) >= 3 else 0
                        result = None
                        if len(parts) == 4 and parts[3] == "start":
                            result = application.database.start_exam(exam_id)
                        elif len(parts) == 4 and parts[3] == "finish":
                            result = application.database.finish_exam(exam_id)
                        elif len(parts) == 6 and parts[3] == "questions" and parts[5] == "answer":
                            selected = payload.get("selected_index")
                            if selected is not None:
                                if isinstance(selected, bool):
                                    raise ValueError("Selected option must be a number from 0 to 3")
                                selected = int(selected)
                            timed_out = payload.get("timed_out", False)
                            if not isinstance(timed_out, bool):
                                raise ValueError("timed_out must be true or false")
                            result = application.database.submit_exam_answer(
                                exam_id, int(parts[4]), selected, str(payload.get("submission_key", "")),
                                timed_out)
                        else:
                            self.send_json(HTTPStatus.NOT_FOUND, {"message": "Exam endpoint not found"}); return
                        if result is None:
                            self.send_json(HTTPStatus.NOT_FOUND, {"message": "Exam not found"})
                        else:
                            self.send_json(HTTPStatus.OK, result)
                        return
                    if path == "/api/topics/manual":
                        topic = application.database.create_manual_topic(
                            str(payload.get("subject", "")), str(payload.get("name", "")),
                            int(payload.get("document_id", 0) or 0), str(payload.get("parent_id", "")))
                        self.send_json(HTTPStatus.CREATED, topic)
                        return
                    if path.startswith("/api/documents/") and path.endswith("/reprocess"):
                        document_id = int(path.strip("/").split("/")[2])
                        document = application.database.document(document_id)
                        if document is None:
                            self.send_json(HTTPStatus.NOT_FOUND, {"message": "Book not found"}); return
                        source_path = Path(document["stored_path"])
                        if not source_path.exists(): raise ValueError("The original book file is no longer available")
                        application.database.update_document(document_id, status="PROCESSING")
                        application.database.prepare_reprocess(document_id)
                        output, records = convert_document(source_path, Path("data/sources/generated"), {
                            "document_id": str(document_id), "subject": document["subject"], "title": document["title"],
                            "default_topic": "", "publisher": document["publisher"], "edition": document["edition"],
                            "license_note": "User confirms authorization for private educational use.",
                        }, source_id=document["source_id"])
                        inserted, skipped = application.database.ingest(records)
                        application.database.update_document(document_id, status="READY", jsonl_path=str(output), records=len(records))
                        self.send_json(HTTPStatus.OK, {"status":"READY","records":len(records),"inserted":inserted,"preserved":skipped})
                        return
                    if path == "/api/lesson":
                        if not application.generation_lock.acquire(blocking=False):
                            self.send_json(HTTPStatus.CONFLICT, {"status": "BUSY", "message": "Another lesson is currently being prepared."})
                            return
                        try:
                            result = application.agent.create_lesson(
                                subject=str(payload.get("subject", "")).strip(),
                                concept=" ".join(str(payload.get("concept", "")).split()),
                                question=" ".join(str(payload.get("question", "")).split()),
                                level=int(payload.get("level", application.settings.default_understanding_level)),
                                language=str(payload.get("language", application.settings.default_language)).strip(),
                                minutes=int(payload.get("minutes", 5)),
                                refresh=bool(payload.get("refresh", False)),
                            )
                        finally:
                            application.generation_lock.release()
                        status = HTTPStatus.OK if result.get("status") == "PASS" else HTTPStatus.UNPROCESSABLE_ENTITY
                        self.send_json(status, result)
                        return
                    if path == "/api/memory":
                        content = str(payload.get("content", "")).strip()
                        if not content:
                            raise ValueError("Memory content is required")
                        memory_id = application.database.add_memory(
                            kind=str(payload.get("kind", "preference")), content=content,
                            subject=str(payload.get("subject", "")), concept=str(payload.get("concept", "")), salience=0.8,
                        )
                        self.send_json(HTTPStatus.CREATED, {"status": "stored", "memory_id": memory_id})
                        return
                    if path.startswith("/api/lessons/") and path.endswith("/check"):
                        parts = path.strip("/").split("/")
                        if len(parts) != 4:
                            raise ValueError("Invalid lesson check endpoint")
                        lesson_id = int(parts[2])
                        lesson_row = application.database.lesson_detail(lesson_id)
                        if lesson_row is None or lesson_row["status"] != "PASS":
                            raise ValueError("Verified lesson not found")
                        lesson = json.loads(lesson_row["lesson_json"])
                        questions = lesson.get("check_questions", [])
                        answers = payload.get("answers", [])
                        if not isinstance(answers, list) or len(answers) != len(questions):
                            raise ValueError("Answer every question before submitting")
                        score = sum(1 for index, item in enumerate(questions) if answers[index] == item.get("correct_index"))
                        difficulty = str(payload.get("difficulty", "right"))
                        if difficulty not in {"too_easy", "right", "too_hard"}:
                            raise ValueError("Invalid difficulty feedback")
                        mastery = application.database.save_comprehension(lesson_id, score, len(questions), answers, difficulty)
                        review = [{"correct_index": item.get("correct_index"), "explanation": item.get("explanation", "")} for item in questions]
                        self.send_json(HTTPStatus.CREATED, {"score": score, "total": len(questions), "review": review, "mastery": mastery})
                        return
                    self.send_json(HTTPStatus.NOT_FOUND, {"message": "Endpoint not found"})
                except json.JSONDecodeError:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"status": "INVALID_REQUEST", "message": "The request contained invalid JSON."})
                except ValueError as error:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"status": "INVALID_REQUEST", "message": public_validation_error(error)})
                except TypeError:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"status": "INVALID_REQUEST", "message": "One or more request fields have invalid values."})
                except ModelError as error:
                    self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {
                        "status": "MODEL_OFFLINE",
                        "message": public_model_error(error, application.settings.model_provider),
                    })
                except Exception as error:
                    print(f"WEB ERROR {type(error).__name__}: {error}")
                    self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"status": "INTERNAL_ERROR", "message": "The application could not complete this request. Check the server window for details."})

            def do_PATCH(self) -> None:
                path = urlparse(self.path).path
                try:
                    parts = path.strip("/").split("/")
                    if len(parts) != 3 or parts[:2] != ["api", "topics"]:
                        self.send_json(HTTPStatus.NOT_FOUND, {"message":"Endpoint not found"}); return
                    payload = self.read_json()
                    updated = application.database.update_topic(parts[2], str(payload.get("action", "")), payload)
                    if updated is None: self.send_json(HTTPStatus.NOT_FOUND, {"message":"Topic not found"}); return
                    self.send_json(HTTPStatus.OK, updated)
                except json.JSONDecodeError:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"status":"INVALID_REQUEST","message":"The request contained invalid JSON."})
                except ValueError as error:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"status":"INVALID_REQUEST","message":public_validation_error(error)})
                except (TypeError, sqlite3.IntegrityError):
                    self.send_json(HTTPStatus.BAD_REQUEST, {"status":"INVALID_REQUEST","message":"The topic change could not be applied. Review the selected values and try again."})

            def do_DELETE(self) -> None:
                path = urlparse(self.path).path
                try:
                    parts = path.strip("/").split("/")
                    if len(parts) == 3 and parts[:2] == ["api", "memories"]:
                        if not application.database.delete_memory(int(parts[2])):
                            self.send_json(HTTPStatus.NOT_FOUND, {"message": "Preference not found"}); return
                        self.send_json(HTTPStatus.OK, {"status": "DELETED", "message": "Preference deleted."})
                        return
                    if len(parts) < 3 or parts[:2] != ["api", "documents"]:
                        self.send_json(HTTPStatus.NOT_FOUND, {"message": "Endpoint not found"})
                        return
                    document_id = int(parts[2])
                    if len(parts) == 3:
                        document = application.database.delete_document(document_id)
                        if document is None:
                            self.send_json(HTTPStatus.NOT_FOUND, {"message": "Book not found"})
                            return
                        allowed_root = Path("data/sources").resolve()
                        for key in ("stored_path", "jsonl_path"):
                            candidate = Path(document.get(key, ""))
                            if candidate and candidate.exists():
                                resolved = candidate.resolve()
                                if resolved.is_relative_to(allowed_root):
                                    resolved.unlink()
                        self.send_json(HTTPStatus.OK, {"status": "DELETED", "message": f"{document['title']} and its topics were deleted."})
                        return
                    if len(parts) == 4 and parts[3] == "topics":
                        concept = str(self.read_json().get("concept", "")).strip()
                        if not concept:
                            raise ValueError("Choose a topic to delete")
                        deleted = application.database.delete_document_topic(document_id, concept)
                        if deleted is None:
                            self.send_json(HTTPStatus.NOT_FOUND, {"message": "Book not found"})
                            return
                        if deleted == 0:
                            self.send_json(HTTPStatus.NOT_FOUND, {"message": "Topic not found in this book"})
                            return
                        self.send_json(HTTPStatus.OK, {"status": "DELETED", "message": f"{concept} was removed from this book only."})
                        return
                    self.send_json(HTTPStatus.NOT_FOUND, {"message": "Endpoint not found"})
                except json.JSONDecodeError:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"status": "INVALID_REQUEST", "message": "The request contained invalid JSON."})
                except ValueError as error:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"status": "INVALID_REQUEST", "message": public_validation_error(error)})
                except TypeError:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"status": "INVALID_REQUEST", "message": "The selected item has an invalid identifier."})
                except Exception as error:
                    print(f"DELETE ERROR {type(error).__name__}: {error}")
                    self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"status": "DELETE_FAILED", "message": "The selected library item could not be deleted."})

            def handle_upload(self) -> None:
                if not application.upload_lock.acquire(blocking=False):
                    self.send_json(HTTPStatus.CONFLICT, {"status": "UPLOAD_BUSY", "message": "Another document is being processed. Please wait and try again."})
                    return
                stored_path: Path | None = None
                document_id: int | None = None
                try:
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                    except ValueError as error:
                        raise ConversionError("The upload size is invalid.") from error
                    if length < 1:
                        raise ConversionError("Choose a non-empty file to upload.")
                    if length > application.settings.max_upload_bytes:
                        limit = application.settings.max_upload_bytes // (1024 * 1024)
                        raise ConversionError(f"The file is too large. The current upload limit is {limit} MB.")
                    file_name = safe_name(self.header_text("X-File-Name"))
                    suffix = Path(file_name).suffix.lower()
                    if suffix not in {".pdf", ".docx", ".txt", ".jsonl"}:
                        raise ConversionError("Unsupported file type. Upload PDF, DOCX, TXT, or JSONL. Save legacy Word .doc files as .docx first.")
                    subject = self.header_text("X-Subject")
                    if not subject:
                        raise ConversionError("Enter the subject before uploading.")
                    uploads = Path("data/sources/uploads")
                    stored_path = uploads / file_name
                    if stored_path.exists():
                        stored_path = uploads / f"{stored_path.stem}-{uuid.uuid4().hex[:8]}{suffix}"
                    self.save_upload(stored_path, length)
                    digest = file_sha256(stored_path)
                    title = self.header_text("X-Title") or Path(file_name).stem
                    publisher = self.header_text("X-Publisher") or "User-provided source"
                    edition = self.header_text("X-Edition") or "Uploaded edition"
                    source_id = f"upload-{uuid.uuid4().hex}"
                    values = {
                        "file_name": file_name, "stored_path": str(stored_path), "jsonl_path": "", "sha256": digest,
                        "source_id": source_id, "subject": subject, "title": title, "publisher": publisher,
                        "edition": edition, "file_type": suffix.lstrip("."), "status": "PROCESSING",
                        "records": 0, "error_message": "",
                    }
                    document_id = application.database.register_document(values)
                    output, records = convert_document(stored_path, Path("data/sources/generated"), {
                        "document_id": str(document_id),
                        "subject": subject,
                        "title": title,
                        "default_topic": self.header_text("X-Default-Topic"),
                        "publisher": publisher,
                        "edition": edition,
                        "license_note": self.header_text("X-License-Note") or "User confirms authorization for private educational use.",
                    }, source_id=source_id)
                    inserted, skipped = application.database.ingest(records)
                    application.database.update_document(document_id, status="READY", jsonl_path=str(output), records=inserted + skipped)
                    self.send_json(HTTPStatus.CREATED, {
                        "status": "READY", "document_id": document_id, "file_name": file_name,
                        "jsonl_file": output.name, "records": len(records), "inserted": inserted, "skipped": skipped,
                        "message": f"{file_name} is ready. {inserted} new evidence chunks were added.",
                    })
                except (ConversionError, ValueError) as error:
                    public_message = public_validation_error(error, "The document could not be processed. Confirm the file is valid and try again.")
                    if document_id is not None:
                        application.database.update_document(document_id, status="FAILED", error_message=public_message)
                    self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"status": "UPLOAD_FAILED", "message": public_message})
                except Exception as error:
                    if document_id is not None:
                        application.database.update_document(document_id, status="FAILED", error_message="Unexpected conversion error")
                    print(f"UPLOAD ERROR {type(error).__name__}: {error}")
                    self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"status": "UPLOAD_FAILED", "message": "The document could not be processed. Check the server window for details."})
                finally:
                    application.upload_lock.release()

        return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local AI Story Tutor web interface")
    parser.add_argument("--config", default="config/settings.json")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--static", default="web")
    args = parser.parse_args()
    settings = Settings.load(args.config)
    static_dir = Path(args.static).resolve()
    if not (static_dir / "index.html").exists():
        raise FileNotFoundError(f"UI files were not found in {static_dir}")
    application = TutorWebApplication(settings, static_dir)
    try:
        server = ExclusiveThreadingHTTPServer((args.host, args.port), application.handler())
    except OSError as error:
        raise SystemExit(
            f"Learn With Stories is already running at http://{args.host}:{args.port}. "
            "Use the existing window, or close it before starting again."
        ) from error
    print(f"Learn With Stories is available at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Learn With Stories")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
