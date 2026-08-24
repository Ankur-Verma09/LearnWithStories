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
    request_timeout_seconds: int
    database_path: Path
    max_evidence_chunks: int
    max_evidence_tokens: int
    max_memory_tokens: int
    max_session_summary_tokens: int
    default_understanding_level: int
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
        required = {
            "model_base_url", "model_name", "database_path",
            "max_evidence_chunks", "max_evidence_tokens", "max_memory_tokens",
            "max_session_summary_tokens", "default_understanding_level", "default_language"
        }
        missing = sorted(required - raw.keys())
        if missing:
            raise ValueError(f"Missing settings: {', '.join(missing)}")
        level = int(raw["default_understanding_level"])
        if not 10 <= level <= 28:
            raise ValueError("default_understanding_level must be between 10 and 28")
        provider = str(raw.get("model_provider", "ollama")).strip().lower()
        if provider not in {"ollama", "openai"}:
            raise ValueError("model_provider must be 'ollama' or 'openai'")
        configured_key = str(raw.get("model_api_key", "")).strip()
        if provider == "openai":
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
            model_base_url=str(raw["model_base_url"]).rstrip("/"),
            model_name=str(raw["model_name"]),
            model_api_key=api_key,
            model_api_keys=api_keys,
            request_timeout_seconds=int(raw.get("request_timeout_seconds", 180)),
            database_path=Path(raw["database_path"]),
            max_evidence_chunks=int(raw["max_evidence_chunks"]),
            max_evidence_tokens=int(raw["max_evidence_tokens"]),
            max_memory_tokens=int(raw["max_memory_tokens"]),
            max_session_summary_tokens=int(raw["max_session_summary_tokens"]),
            default_understanding_level=level,
            default_language=str(raw["default_language"]),
            max_upload_bytes=int(raw.get("max_upload_bytes", 157286400)),
        )
