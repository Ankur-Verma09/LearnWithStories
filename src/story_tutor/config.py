from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    model_provider: str
    model_base_url: str
    model_name: str
    model_api_key: str
    model_api_keys: tuple[str, ...]
    model_temperature: float
    model_max_retries: int
    ollama_keep_alive: str
    request_timeout_seconds: int
    database_path: Path
    max_evidence_chunks: int
    max_evidence_tokens: int
    max_memory_tokens: int
    max_session_summary_tokens: int
    default_understanding_level: int
    default_learner_age: int
    default_knowledge_level: str
    default_story_style: str
    default_difficulty: str
    learning_profiles_path: Path
    default_language: str
    max_upload_bytes: int

    @classmethod
    def load(cls, path: str | Path) -> "Settings":
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(
                f"Configuration not found: {config_path}. Copy config/settings.example.json to config/settings.json and edit it."
            )
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        def env_or(name: str, fallback: object) -> str:
            value = os.environ.get(name, "").strip()
            return value or str(fallback)
        required = {
            "model_base_url", "model_name", "database_path",
            "max_evidence_chunks", "max_evidence_tokens", "max_memory_tokens",
            "max_session_summary_tokens", "default_understanding_level", "default_language"
        }
        missing = sorted(required - raw.keys())
        if missing:
            raise ValueError(f"Missing settings: {', '.join(missing)}")
        level = int(raw["default_understanding_level"])
        if not 5 <= level <= 100:
            raise ValueError("default_understanding_level must be between 5 and 100")
        learner_age = int(raw.get("default_learner_age", level))
        if not 5 <= learner_age <= 100:
            raise ValueError("default_learner_age must be between 5 and 100")
        # provider = env_or("LLM_PROVIDER", raw.get("model_provider", "ollama")).lower()
        # if provider not in {"ollama", "openai"}:
        #     raise ValueError("model_provider must be 'ollama' or 'openai'")
        provider = env_or("LLM_PROVIDER", raw.get("model_provider", "ollama")).lower()
        if provider not in {"ollama", "openai", "openai_compat"}:
            raise ValueError("model_provider must be 'ollama', 'openai', or 'openai_compat'")
        knowledge_level = str(raw.get("default_knowledge_level", "beginner")).strip().lower()
        if knowledge_level not in {"beginner", "intermediate", "advanced"}:
            raise ValueError("default_knowledge_level must be beginner, intermediate, or advanced")
        story_style = str(raw.get("default_story_style", "realistic_funny")).strip().lower()
        if story_style not in {"realistic_funny", "realistic", "conversational"}:
            raise ValueError("default_story_style is invalid")
        difficulty = str(raw.get("default_difficulty", "standard")).strip().lower()
        if difficulty not in {"easy", "standard", "challenging"}:
            raise ValueError("default_difficulty is invalid")
        temperature = float(env_or("LLM_TEMPERATURE", raw.get("model_temperature", 0.65)))
        if not 0 <= temperature <= 2:
            raise ValueError("model_temperature must be between 0 and 2")
        retries = int(env_or("LLM_MAX_RETRIES", raw.get("model_max_retries", 1)))
        if not 0 <= retries <= 3:
            raise ValueError("model_max_retries must be between 0 and 3")
        # configured_key = str(raw.get("model_api_key", "")).strip()
        # if provider == "openai":
        configured_key = str(raw.get("model_api_key", "")).strip()
        if provider in {"openai", "openai_compat"}:
            candidates = [os.environ.get("OPENAI_API_KEY", "").strip()]
            candidates.extend(part.strip() for part in os.environ.get("OPENAI_API_KEYS", "").replace("\r", "\n").replace(";", "\n").replace(",", "\n").split("\n"))
            keys_file = os.environ.get("OPENAI_API_KEYS_FILE", "").strip()
            if keys_file and Path(keys_file).is_file():
                candidates.extend(line.strip() for line in Path(keys_file).read_text(encoding="utf-8").splitlines())
            api_keys = tuple(dict.fromkeys(key for key in candidates if key))
        else:
            api_keys = (configured_key,) if configured_key else ()
        api_key = api_keys[0] if api_keys else ""
        return cls(
            model_provider=provider,
            model_base_url=env_or("LLM_BASE_URL", raw["model_base_url"]).rstrip("/"),
            model_name=env_or("LLM_MODEL", raw["model_name"]),
            model_api_key=api_key,
            model_api_keys=api_keys,
            model_temperature=temperature,
            model_max_retries=retries,
            ollama_keep_alive=str(raw.get("ollama_keep_alive", "30m")),
            request_timeout_seconds=int(env_or("LLM_TIMEOUT", raw.get("request_timeout_seconds", 180))),
            database_path=Path(raw["database_path"]),
            max_evidence_chunks=int(raw["max_evidence_chunks"]),
            max_evidence_tokens=int(raw["max_evidence_tokens"]),
            max_memory_tokens=int(raw["max_memory_tokens"]),
            max_session_summary_tokens=int(raw["max_session_summary_tokens"]),
            default_understanding_level=level,
            default_learner_age=learner_age,
            default_knowledge_level=knowledge_level,
            default_story_style=story_style,
            default_difficulty=difficulty,
            learning_profiles_path=Path(raw.get("learning_profiles_path", "config/learning_profiles.json")),
            default_language=str(raw["default_language"]),
            max_upload_bytes=int(raw.get("max_upload_bytes", 157286400)),
        )
