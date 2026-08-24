from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

from .agent import StoryTutorAgent
from .config import Settings
from .db import Database
from .model_client import ModelError, create_model_client


def load_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8") as source:
        for number, line in enumerate(source, 1):
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as error:
                    raise ValueError(f"Invalid JSON on line {number}: {error}") from error
    return records


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="story-tutor", description="Backend-only AI Story Tutor agent")
    root.add_argument("--config", default="config/settings.json")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Create local configuration and database")
    sub.add_parser("health", help="Check the RTX model service")
    ingest = sub.add_parser("ingest", help="Ingest approved JSONL source chunks")
    ingest.add_argument("path", type=Path)
    lesson = sub.add_parser("lesson", help="Generate and verify one teaching story")
    lesson.add_argument("concept")
    lesson.add_argument("--subject", default="Polity")
    lesson.add_argument("--level", type=int)
    lesson.add_argument("--age", type=int, help="Learner age; --level remains a backward-compatible alias")
    lesson.add_argument("--knowledge-level", choices=["beginner", "intermediate", "advanced"])
    lesson.add_argument("--story-style", choices=["realistic_funny", "realistic", "conversational"])
    lesson.add_argument("--difficulty", choices=["easy", "standard", "challenging"])
    lesson.add_argument("--language")
    lesson.add_argument("--minutes", type=int, default=5, choices=[2, 5, 10])
    lesson.add_argument("--refresh", action="store_true")
    remember = sub.add_parser("remember", help="Store an explicit learner preference or context item")
    remember.add_argument("content")
    remember.add_argument("--kind", default="preference", choices=["preference", "profile", "misconception", "goal"])
    remember.add_argument("--subject", default="")
    remember.add_argument("--concept", default="")
    history = sub.add_parser("history", help="Show recent lesson attempts")
    history.add_argument("--limit", type=int, default=10)
    sub.add_parser("progress", help="Show recall and concept-mastery progress")
    sub.add_parser("content", help="Show approved concept coverage")
    return root


def main() -> None:
    args = parser().parse_args()
    config_path = Path(args.config)
    if args.command == "init":
        if not config_path.exists():
            config_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile("config/settings.example.json", config_path)
            print(f"Created {config_path}. Edit model_base_url and model_name before testing.")
        settings = Settings.load(config_path)
        Database(settings.database_path).initialize()
        print(f"Initialized database at {settings.database_path}")
        return
    try:
        settings = Settings.load(config_path)
        database = Database(settings.database_path); database.initialize()
        if args.command == "health":
            response = create_model_client(settings).health()
            names = [item.get("name", "") for item in response.get("models", [])]
            print(json.dumps({"status": "reachable", "configured_model": settings.model_name, "available_models": names}, indent=2))
        elif args.command == "ingest":
            inserted, skipped = database.ingest(load_jsonl(args.path))
            print(json.dumps({"inserted": inserted, "skipped_duplicates": skipped}, indent=2))
        elif args.command == "remember":
            memory_id = database.add_memory(args.kind, args.content, args.subject, args.concept, 0.8)
            print(json.dumps({"memory_id": memory_id, "status": "stored"}, indent=2))
        elif args.command == "history":
            print(json.dumps([dict(row) for row in database.lesson_history(args.limit)], indent=2))
        elif args.command == "progress":
            print(json.dumps(database.progress(), indent=2))
        elif args.command == "content":
            print(json.dumps(database.content_inventory(), indent=2))
        elif args.command == "lesson":
            level = args.age or args.level or settings.default_learner_age
            language = args.language or settings.default_language
            result = StoryTutorAgent(settings).create_lesson(
                args.subject, args.concept, level, language, args.minutes, args.refresh,
                question=args.concept, age=level,
                knowledge_level=args.knowledge_level or settings.default_knowledge_level,
                story_style=args.story_style or settings.default_story_style,
                difficulty=args.difficulty or settings.default_difficulty,
            )
            print(json.dumps(result, indent=2, ensure_ascii=False))
            if result["status"] != "PASS":
                raise SystemExit(2)
    except (FileNotFoundError, ValueError, ModelError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
