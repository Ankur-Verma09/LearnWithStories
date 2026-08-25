from __future__ import annotations

import argparse
from collections import OrderedDict
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import socket
import sqlite3
import threading
import time
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse
import uuid

from .agent import StoryTutorAgent
from .auth import (
    AuthenticatedUser, hash_password, new_session_values, normalize_email,
    session_cookie, session_hash_from_cookie, verify_password,
)
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


class LibraryReadCache:
    """Small process-local read cache invalidated by every library write."""

    def __init__(self, max_entries: int = 32, ttl_seconds: float = 60.0) -> None:
        self._lock = threading.RLock()
        self._values: OrderedDict[object, tuple[float, Any]] = OrderedDict()
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds

    def get(self, key: object, loader: Callable[[], Any]) -> Any:
        with self._lock:
            cached = self._values.get(key)
            now = time.monotonic()
            if cached is not None and now - cached[0] < self._ttl_seconds:
                self._values.move_to_end(key)
                return cached[1]
            value = loader()
            self._values[key] = (now, value)
            self._values.move_to_end(key)
            while len(self._values) > self._max_entries:
                self._values.popitem(last=False)
            return value

    def invalidate(self) -> None:
        with self._lock:
            self._values.clear()


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
        self.library_cache = LibraryReadCache()

    def _document_inventory(self) -> list[dict[str, Any]]:
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

    def document_inventory(self) -> list[dict[str, Any]]:
        return self.library_cache.get("documents", self._document_inventory)

    def catalog(self) -> list[dict[str, Any]]:
        return self.library_cache.get("catalog", self.database.catalog)

    def library_hierarchy(self, search: str = "", subject: str = "", document_id: int = 0) -> dict[str, Any]:
        key = ("hierarchy", search.casefold(), subject.casefold(), document_id)
        return self.library_cache.get(
            key, lambda: self.database.library_hierarchy(search=search, subject=subject, document_id=document_id),
        )

    def library_snapshot(self) -> dict[str, Any]:
        return {
            "documents": self.document_inventory(),
            "hierarchy": self.library_hierarchy(),
        }

    def invalidate_library_cache(self) -> None:
        self.library_cache.invalidate()

    def handler(self):
        application = self

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(application.static_dir), **kwargs)

            def log_message(self, format: str, *args: Any) -> None:
                print(f"WEB {self.address_string()} {format % args}")

            def send_json(self, status: HTTPStatus, payload: Any, extra_headers: dict[str, str] | None = None) -> None:
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                for name, value in (extra_headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(data)

            def current_user(self, required: bool = True) -> AuthenticatedUser | None:
                token_hash = session_hash_from_cookie(self.headers.get("Cookie", ""))
                payload = application.database.session_user(token_hash)
                if payload is None:
                    if required:
                        self.send_json(HTTPStatus.UNAUTHORIZED, {
                            "status": "AUTH_REQUIRED", "message": "Sign in to continue.",
                        })
                    return None
                return AuthenticatedUser(
                    id=int(payload["id"]), email=payload["email"], display_name=payload["display_name"],
                    learner_id=int(payload["learner_id"]), roles=frozenset(payload["roles"]),
                    csrf_token=payload["csrf_token"],
                )

            def require_admin(self, user: AuthenticatedUser) -> bool:
                if user.is_admin:
                    return True
                self.send_json(HTTPStatus.FORBIDDEN, {
                    "status": "FORBIDDEN", "message": "Administrator access is required.",
                })
                return False

            def valid_csrf(self, user: AuthenticatedUser) -> bool:
                if self.headers.get("X-LWS-CSRF", "") == user.csrf_token:
                    return True
                self.send_json(HTTPStatus.FORBIDDEN, {
                    "status": "CSRF_REJECTED", "message": "Your secure session could not be verified. Sign in again.",
                })
                return False

            def is_local_request(self) -> bool:
                host = self.headers.get("Host", "").strip().casefold()
                return host.startswith("127.0.0.1:") or host == "127.0.0.1" \
                    or host.startswith("localhost:") or host == "localhost" \
                    or host.startswith("[::1]:") or host == "[::1]"

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
                if path == "/.well-known/appspecific/com.chrome.devtools.json":
                    # Chrome DevTools probes localhost for optional workspace metadata.
                    # Returning an empty response keeps this browser-generated request
                    # out of the server's 404/error output.
                    self.send_response(HTTPStatus.NO_CONTENT)
                    self.send_header("Content-Length", "0")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    return
                if path == "/api/auth/status":
                    self.send_json(HTTPStatus.OK, {"bootstrap_required": application.database.bootstrap_required()})
                    return
                if path == "/api/auth/me":
                    user = self.current_user()
                    if user:
                        self.send_json(HTTPStatus.OK, {"user": user.public()})
                    return
                user = self.current_user(required=path.startswith("/api/")) if path.startswith("/api/") else None
                if path.startswith("/api/") and user is None:
                    return
                if path == "/api/users":
                    if self.require_admin(user):
                        self.send_json(HTTPStatus.OK, application.database.users())
                    return
                if path == "/api/config":
                    payload = {
                        "api_version": 7,
                        "features": ["online_examinations", "adaptive_learning_profiles", "progressive_mastery", "lesson_followups", "role_based_access"],
                        "default_level": application.settings.default_learner_age,
                        "default_learner_age": application.settings.default_learner_age,
                        "default_knowledge_level": application.settings.default_knowledge_level,
                        "default_story_style": application.settings.default_story_style,
                        "default_difficulty": application.settings.default_difficulty,
                        "default_language": application.settings.default_language,
                        "user": user.public(),
                    }
                    if user.is_admin:
                        payload.update({
                            "features": payload["features"] + ["document_upload", "pdf_conversion", "docx_conversion", "library_management", "user_management"],
                            "model_provider": application.settings.model_provider,
                            "model_name": application.settings.model_name,
                            "configured_api_keys": len(application.settings.model_api_keys) if application.settings.model_provider == "openai" else 0,
                        })
                    self.send_json(HTTPStatus.OK, payload)
                    return
                if path == "/api/history":
                    self.send_json(HTTPStatus.OK, [dict(row) for row in application.database.lesson_history(12, user.learner_id)])
                    return
                if path.startswith("/api/lessons/"):
                    parts = path.strip("/").split("/")
                    if len(parts) == 4 and parts[:2] == ["api", "lessons"] and parts[3] == "follow-ups":
                        try:
                            lesson_id = int(parts[2])
                        except ValueError:
                            self.send_json(HTTPStatus.BAD_REQUEST, {"message": "Invalid lesson id"})
                            return
                        row = application.database.lesson_detail(lesson_id)
                        if row is None or int(row["learner_id"]) != user.learner_id:
                            self.send_json(HTTPStatus.NOT_FOUND, {"message": "Verified lesson not found"})
                            return
                        conversation = application.database.conversation_for_lesson(lesson_id, user.learner_id)
                        if conversation is None:
                            self.send_json(HTTPStatus.NOT_FOUND, {"message": "Verified lesson not found"})
                        else:
                            self.send_json(HTTPStatus.OK, conversation)
                        return
                    if len(parts) != 3:
                        self.send_json(HTTPStatus.NOT_FOUND, {"message": "Lesson endpoint not found"})
                        return
                    try:
                        lesson_id = int(parts[2])
                    except ValueError:
                        self.send_json(HTTPStatus.BAD_REQUEST, {"message": "Invalid lesson id"})
                        return
                    row = application.database.lesson_detail(lesson_id)
                    if row is None or int(row["learner_id"]) != user.learner_id:
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
                        "level": row["learner_age"], "age": row["learner_age"],
                        "knowledge_level": row["knowledge_level"], "learning_profile": row["learning_profile"],
                        "story_style": row["story_style"], "difficulty": row["difficulty"],
                        "language": row["language"], "status": row["status"],
                        "created_at": row["created_at"], "lesson": json.loads(row["lesson_json"]),
                        "verification": json.loads(row["verification_json"]), "sources": json.loads(row["evidence_json"]),
                    })
                    return
                if path == "/api/progress":
                    self.send_json(HTTPStatus.OK, application.database.progress(user.learner_id))
                    return
                if path == "/api/content":
                    if not self.require_admin(user): return
                    self.send_json(HTTPStatus.OK, application.database.content_inventory())
                    return
                if path == "/api/catalog":
                    self.send_json(HTTPStatus.OK, application.catalog())
                    return
                if path == "/api/documents":
                    if not self.require_admin(user): return
                    self.send_json(HTTPStatus.OK, application.document_inventory())
                    return
                if path == "/api/library/hierarchy":
                    if not self.require_admin(user): return
                    query = parse_qs(parsed_url.query)
                    self.send_json(HTTPStatus.OK, application.library_hierarchy(
                        search=query.get("search", [""])[0], subject=query.get("subject", [""])[0],
                        document_id=int(query.get("document_id", ["0"])[0] or 0)))
                    return
                if path == "/api/library/snapshot":
                    if not self.require_admin(user): return
                    self.send_json(HTTPStatus.OK, application.library_snapshot())
                    return
                if path == "/api/memories":
                    self.send_json(HTTPStatus.OK, application.database.memory_inventory(
                        owner_user_id=user.id, is_admin=user.is_admin,
                    ))
                    return
                if path == "/api/exams/history":
                    query = parse_qs(parsed_url.query)
                    self.send_json(HTTPStatus.OK, application.database.exam_history(
                        int(query.get("limit", ["50"])[0]), user.id,
                    ))
                    return
                if path.startswith("/api/exams/"):
                    parts = path.strip("/").split("/")
                    if len(parts) == 3:
                        if not application.database.exam_owned_by(int(parts[2]), user.id):
                            self.send_json(HTTPStatus.NOT_FOUND, {"message": "Exam not found"})
                            return
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
                        payload = {"status": "online"}
                        if user.is_admin:
                            payload.update({"provider": application.settings.model_provider, "models": models,
                                            "configured_model": application.settings.model_name})
                        self.send_json(HTTPStatus.OK, payload)
                    except ModelError as error:
                        self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {
                            "status": "MODEL_OFFLINE",
                            "message": public_model_error(error, application.settings.model_provider) if user.is_admin
                            else "The service is currently unavailable. Previously verified lessons are still available.",
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
                    if path in {"/api/auth/bootstrap", "/api/auth/login"}:
                        payload = self.read_json()
                        email = normalize_email(payload.get("email", ""))
                        password = str(payload.get("password", ""))
                        if "@" not in email or email.startswith("@") or email.endswith("@"):
                            raise ValueError("Enter a valid email address")
                        if path.endswith("/bootstrap"):
                            if not self.is_local_request():
                                self.send_json(HTTPStatus.FORBIDDEN, {
                                    "status": "LOCAL_SETUP_REQUIRED",
                                    "message": "Create the first administrator from the Dell's local portal.",
                                })
                                return
                            display_name = " ".join(str(payload.get("display_name", "")).split())[:100]
                            if len(display_name) < 2:
                                raise ValueError("Enter the administrator's display name")
                            account = application.database.create_user(
                                email, display_name, hash_password(password), ["ADMIN", "STUDENT"], bootstrap=True,
                            )
                        else:
                            account = application.database.user_by_email(email)
                            if account is None or not verify_password(password, account.pop("password_hash", "")):
                                self.send_json(HTTPStatus.UNAUTHORIZED, {
                                    "status": "LOGIN_FAILED", "message": "The email or password is incorrect.",
                                })
                                return
                        token, token_hash, csrf, expires = new_session_values()
                        application.database.create_session(int(account["id"]), token_hash, csrf, expires)
                        account["csrf_token"] = csrf
                        account["is_admin"] = "ADMIN" in account["roles"]
                        secure = self.headers.get("X-Forwarded-Proto", "").casefold() == "https"
                        self.send_json(HTTPStatus.CREATED if path.endswith("/bootstrap") else HTTPStatus.OK,
                                       {"user": account}, {"Set-Cookie": session_cookie(token, secure=secure)})
                        return
                    user = self.current_user()
                    if user is None or not self.valid_csrf(user):
                        return
                    if path == "/api/auth/logout":
                        application.database.revoke_session(session_hash_from_cookie(self.headers.get("Cookie", "")))
                        secure = self.headers.get("X-Forwarded-Proto", "").casefold() == "https"
                        self.send_json(HTTPStatus.OK, {"status": "SIGNED_OUT"},
                                       {"Set-Cookie": session_cookie("", secure=secure, delete=True)})
                        return
                    if path == "/api/upload":
                        if not self.require_admin(user): return
                        self.handle_upload()
                        return
                    payload = self.read_json()
                    if path == "/api/users":
                        if not self.require_admin(user): return
                        email = normalize_email(payload.get("email", ""))
                        display_name = " ".join(str(payload.get("display_name", "")).split())[:100]
                        if "@" not in email or len(display_name) < 2:
                            raise ValueError("Enter a valid name and email address")
                        roles = payload.get("roles", [])
                        if not isinstance(roles, list):
                            raise ValueError("Roles must be a list")
                        created = application.database.create_user(
                            email, display_name, hash_password(str(payload.get("password", ""))),
                            [str(role).upper() for role in roles],
                        )
                        self.send_json(HTTPStatus.CREATED, created)
                        return
                    if path == "/api/exams/generate":
                        if not application.generation_lock.acquire(blocking=False):
                            self.send_json(HTTPStatus.CONFLICT, {"status": "BUSY", "message": "Another AI generation task is currently running."})
                            return
                        try:
                            result = application.exams.generate(payload, owner_user_id=user.id)
                        finally:
                            application.generation_lock.release()
                        self.send_json(HTTPStatus.CREATED, result)
                        return
                    if path.startswith("/api/exams/"):
                        parts = path.strip("/").split("/")
                        exam_id = int(parts[2]) if len(parts) >= 3 else 0
                        if not application.database.exam_owned_by(exam_id, user.id):
                            self.send_json(HTTPStatus.NOT_FOUND, {"message": "Exam not found"})
                            return
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
                        if not self.require_admin(user): return
                        topic = application.database.create_manual_topic(
                            str(payload.get("subject", "")), str(payload.get("name", "")),
                            int(payload.get("document_id", 0) or 0), str(payload.get("parent_id", "")))
                        application.invalidate_library_cache()
                        self.send_json(HTTPStatus.CREATED, topic)
                        return
                    if path.startswith("/api/documents/") and path.endswith("/reprocess"):
                        if not self.require_admin(user): return
                        document_id = int(path.strip("/").split("/")[2])
                        document = application.database.document(document_id)
                        if document is None:
                            self.send_json(HTTPStatus.NOT_FOUND, {"message": "Book not found"}); return
                        source_path = Path(document["stored_path"])
                        if not source_path.exists(): raise ValueError("The original book file is no longer available")
                        application.invalidate_library_cache()
                        application.database.update_document(document_id, status="PROCESSING")
                        application.database.prepare_reprocess(document_id)
                        output, records = convert_document(source_path, Path("data/sources/generated"), {
                            "document_id": str(document_id), "subject": document["subject"], "title": document["title"],
                            "default_topic": "", "publisher": document["publisher"], "edition": document["edition"],
                            "license_note": "User confirms authorization for private educational use.",
                        }, source_id=document["source_id"])
                        inserted, skipped = application.database.ingest(records)
                        application.database.update_document(document_id, status="READY", jsonl_path=str(output), records=len(records))
                        application.invalidate_library_cache()
                        self.send_json(HTTPStatus.OK, {"status":"READY","records":len(records),"inserted":inserted,"preserved":skipped})
                        return
                    if path == "/api/lesson":
                        if not application.generation_lock.acquire(blocking=False):
                            self.send_json(HTTPStatus.CONFLICT, {"status": "BUSY", "message": "Another lesson is currently being prepared."})
                            return
                        try:
                            learner_age = int(payload.get("age", payload.get("level", application.settings.default_learner_age)))
                            result = application.agent.create_lesson(
                                subject=str(payload.get("subject", "")).strip(),
                                concept=" ".join(str(payload.get("concept", "")).split()),
                                question=" ".join(str(payload.get("question", "")).split()),
                                level=learner_age,
                                language=str(payload.get("language", application.settings.default_language)).strip(),
                                minutes=int(payload.get("minutes", 5)),
                                refresh=bool(payload.get("refresh", False)),
                                age=learner_age,
                                knowledge_level=str(payload.get("knowledge_level", application.settings.default_knowledge_level)),
                                story_style=str(payload.get("story_style", application.settings.default_story_style)),
                                difficulty=str(payload.get("difficulty", application.settings.default_difficulty)),
                                profile_override=str(payload.get("profile_override", "")),
                                learner_id=user.learner_id, owner_user_id=user.id,
                            )
                        finally:
                            application.generation_lock.release()
                        status = HTTPStatus.OK if result.get("status") == "PASS" else HTTPStatus.UNPROCESSABLE_ENTITY
                        self.send_json(status, result)
                        return
                    if path.startswith("/api/lessons/") and path.endswith("/follow-ups"):
                        parts = path.strip("/").split("/")
                        if len(parts) != 4:
                            raise ValueError("Invalid follow-up endpoint")
                        if not application.generation_lock.acquire(blocking=False):
                            self.send_json(HTTPStatus.CONFLICT, {"status": "BUSY", "message": "Another AI response is currently being prepared."})
                            return
                        try:
                            conversation_value = payload.get("conversation_id")
                            conversation_id = int(conversation_value) if conversation_value not in {None, ""} else None
                            result = application.agent.ask_followup(
                                int(parts[2]), str(payload.get("question", "")), conversation_id, user.learner_id,
                            )
                        finally:
                            application.generation_lock.release()
                        status = HTTPStatus.CREATED if result.get("status") in {"PASS", "OUT_OF_SCOPE"} else HTTPStatus.UNPROCESSABLE_ENTITY
                        self.send_json(status, result)
                        return
                    if path == "/api/memory":
                        content = str(payload.get("content", "")).strip()
                        if not content:
                            raise ValueError("Memory content is required")
                        memory_id = application.database.add_memory(
                            kind=str(payload.get("kind", "preference")), content=content,
                            subject=str(payload.get("subject", "")), concept=str(payload.get("concept", "")), salience=0.8,
                            owner_user_id=user.id, created_by="USER",
                        )
                        self.send_json(HTTPStatus.CREATED, {"status": "stored", "memory_id": memory_id})
                        return
                    if path.startswith("/api/lessons/") and path.endswith("/check"):
                        parts = path.strip("/").split("/")
                        if len(parts) != 4:
                            raise ValueError("Invalid lesson check endpoint")
                        lesson_id = int(parts[2])
                        lesson_row = application.database.lesson_detail(lesson_id)
                        if lesson_row is None or lesson_row["status"] != "PASS" or int(lesson_row["learner_id"]) != user.learner_id:
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
                        mastery = application.database.save_comprehension(
                            lesson_id, score, len(questions), answers, difficulty, questions, user.learner_id,
                        )
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
                        "message": public_model_error(error, application.settings.model_provider)
                        if user.is_admin
                        else "The service is currently unavailable. Previously verified lessons are still available.",
                    })
                except Exception as error:
                    print(f"WEB ERROR {type(error).__name__}: {error}")
                    self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"status": "INTERNAL_ERROR", "message": "The application could not complete this request. Check the server window for details."})

            def do_PATCH(self) -> None:
                path = urlparse(self.path).path
                try:
                    user = self.current_user()
                    if user is None or not self.valid_csrf(user): return
                    parts = path.strip("/").split("/")
                    if len(parts) == 3 and parts[:2] == ["api", "memories"]:
                        payload = self.read_json()
                        content = " ".join(str(payload.get("content", "")).split())[:300]
                        if not content: raise ValueError("Context cannot be empty")
                        if not application.database.update_memory(int(parts[2]), content, user.id, user.is_admin):
                            self.send_json(HTTPStatus.NOT_FOUND, {"message": "Context item not found"}); return
                        self.send_json(HTTPStatus.OK, {"status": "UPDATED", "message": "Context updated."})
                        return
                    if len(parts) == 3 and parts[:2] == ["api", "users"]:
                        if not self.require_admin(user): return
                        payload = self.read_json()
                        roles = payload.get("roles", [])
                        if not isinstance(roles, list): raise ValueError("Roles must be a list")
                        display_name = " ".join(str(payload.get("display_name", "")).split())[:100]
                        password = str(payload.get("password", ""))
                        updated = application.database.update_user(
                            int(parts[2]), display_name=display_name,
                            roles=[str(role).upper() for role in roles],
                            is_active=bool(payload.get("is_active", True)),
                            password_hash=hash_password(password) if password else "",
                        )
                        if updated is None:
                            self.send_json(HTTPStatus.NOT_FOUND, {"message": "User not found"}); return
                        self.send_json(HTTPStatus.OK, updated)
                        return
                    if len(parts) != 3 or parts[:2] != ["api", "topics"]:
                        self.send_json(HTTPStatus.NOT_FOUND, {"message":"Endpoint not found"}); return
                    if not self.require_admin(user): return
                    payload = self.read_json()
                    updated = application.database.update_topic(parts[2], str(payload.get("action", "")), payload)
                    if updated is None: self.send_json(HTTPStatus.NOT_FOUND, {"message":"Topic not found"}); return
                    application.invalidate_library_cache()
                    self.send_json(HTTPStatus.OK, updated)
                except json.JSONDecodeError:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"status":"INVALID_REQUEST","message":"The request contained invalid JSON."})
                except ValueError as error:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"status":"INVALID_REQUEST","message":public_validation_error(error)})
                except PermissionError as error:
                    self.send_json(HTTPStatus.FORBIDDEN, {"status":"FORBIDDEN","message":public_validation_error(error)})
                except (TypeError, sqlite3.IntegrityError):
                    self.send_json(HTTPStatus.BAD_REQUEST, {"status":"INVALID_REQUEST","message":"The topic change could not be applied. Review the selected values and try again."})

            def do_DELETE(self) -> None:
                path = urlparse(self.path).path
                try:
                    user = self.current_user()
                    if user is None or not self.valid_csrf(user): return
                    parts = path.strip("/").split("/")
                    if len(parts) == 3 and parts[:2] == ["api", "memories"]:
                        if not application.database.delete_memory(int(parts[2]), user.id, user.is_admin):
                            self.send_json(HTTPStatus.NOT_FOUND, {"message": "Preference not found"}); return
                        self.send_json(HTTPStatus.OK, {"status": "DELETED", "message": "Preference deleted."})
                        return
                    if len(parts) == 4 and parts[:2] == ["api", "lessons"] and parts[3] == "follow-ups":
                        lesson = application.database.lesson_detail(int(parts[2]))
                        if lesson is None or int(lesson["learner_id"]) != user.learner_id:
                            self.send_json(HTTPStatus.NOT_FOUND, {"message": "Follow-up conversation not found"}); return
                        if not application.database.clear_conversation(int(parts[2]), user.learner_id):
                            self.send_json(HTTPStatus.NOT_FOUND, {"message": "Follow-up conversation not found"})
                            return
                        self.send_json(HTTPStatus.OK, {"status": "CLEARED", "message": "Follow-up conversation cleared."})
                        return
                    if len(parts) < 3 or parts[:2] != ["api", "documents"]:
                        self.send_json(HTTPStatus.NOT_FOUND, {"message": "Endpoint not found"})
                        return
                    if not self.require_admin(user): return
                    document_id = int(parts[2])
                    if len(parts) == 3:
                        document = application.database.delete_document(document_id)
                        if document is None:
                            self.send_json(HTTPStatus.NOT_FOUND, {"message": "Book not found"})
                            return
                        application.invalidate_library_cache()
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
                        application.invalidate_library_cache()
                        self.send_json(HTTPStatus.OK, {"status": "DELETED", "message": f"{concept} was removed from this book only."})
                        return
                    self.send_json(HTTPStatus.NOT_FOUND, {"message": "Endpoint not found"})
                except json.JSONDecodeError:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"status": "INVALID_REQUEST", "message": "The request contained invalid JSON."})
                except ValueError as error:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"status": "INVALID_REQUEST", "message": public_validation_error(error)})
                except TypeError:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"status": "INVALID_REQUEST", "message": "The selected item has an invalid identifier."})
                except PermissionError as error:
                    self.send_json(HTTPStatus.FORBIDDEN, {"status": "FORBIDDEN", "message": public_validation_error(error)})
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
                    if document_id is not None:
                        application.invalidate_library_cache()
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
