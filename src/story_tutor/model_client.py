from __future__ import annotations

from abc import ABC, abstractmethod
import json
import time
import urllib.error
import urllib.request
from typing import Any
import threading

from .config import Settings


class ModelError(RuntimeError):
    pass


class ModelHTTPError(ModelError):
    def __init__(self, status: int, detail: str, error_code: str = "", retry_after: str = ""):
        super().__init__(f"Model service returned HTTP {status}{': ' + detail if detail else ''}")
        self.status, self.detail, self.error_code, self.retry_after = status, detail, error_code, retry_after


def public_model_error(error: ModelError, provider: str) -> str:
    """Return a user-safe model error without provider payloads, URLs, or stack details."""
    if isinstance(error, ModelHTTPError):
        if error.status in {401, 403}:
            return "The configured model credentials were rejected. Review the model setup and try again."
        if error.status == 429:
            return "The model service has reached a rate or usage limit. Wait for capacity to reset and try again."
        if error.status == 400:
            return "The model rejected this request. Shorten the question or try a narrower topic."
        if 500 <= error.status <= 599:
            return "The model service is temporarily unavailable. Please try again shortly."
        return "The model service could not complete the request. Review Setup & health and try again."
    message = str(error)
    if message.startswith("No user-owned OpenAI API key is configured"):
        return "No OpenAI API key is configured. Review Setup & health before generating a lesson."
    if "rejected every configured API key" in message:
        return "The configured OpenAI credentials were rejected. Replace them and restart the Dell service."
    if "rate or quota capacity is unavailable" in message:
        return "OpenAI rate or usage capacity is unavailable. Wait for the limit to reset and try again."
    if "invalid structured JSON" in message or "JSON response must be an object" in message:
        return "The model returned an invalid response. Retry the request; no unverified content was shown."
    label = "OpenAI" if provider == "openai" else "The local model"
    return f"{label} is unavailable. Review Setup & health and try again."


class LLMProvider(ABC):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.last_call_metrics: dict[str, Any] = {}
        self._last_transport_retries = 0

    def _request(self, path: str, payload: dict[str, Any] | None = None, method: str = "POST", api_key: str = "") -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        selected_key = api_key or self.settings.model_api_key
        if selected_key:
            headers["Authorization"] = f"Bearer {selected_key}"
        request = urllib.request.Request(
            f"{self.settings.model_base_url}{path}", data=body, headers=headers, method=method
        )
        self._last_transport_retries = 0
        for attempt in range(self.settings.model_max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.settings.request_timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                try:
                    error_body = json.loads(error.read().decode("utf-8")).get("error", {})
                    detail = error_body.get("message", "")
                    error_code = error_body.get("code", "") or error_body.get("type", "")
                except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                    detail, error_code = "", ""
                if 500 <= error.code <= 599 and attempt < self.settings.model_max_retries:
                    self._last_transport_retries += 1
                    continue
                raise ModelHTTPError(error.code, detail, str(error_code), error.headers.get("Retry-After", "")) from error
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt < self.settings.model_max_retries:
                    self._last_transport_retries += 1
                    continue
                raise ModelError(f"Model service request failed: {type(error).__name__}") from error
            except json.JSONDecodeError as error:
                raise ModelError("Model service returned an unreadable response") from error
        raise ModelError("Model service request failed after retry")

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """Return provider health/model metadata without exposing credentials."""

    @abstractmethod
    def chat_json(self, system: str, user: str, temperature: float, max_tokens: int) -> dict[str, Any]:
        """Return one parsed JSON object or raise ModelError."""


# Backward-compatible name retained for existing integrations and tests.
BaseModelClient = LLMProvider


class OllamaClient(LLMProvider):

    def health(self) -> dict[str, Any]:
        return self._request("/api/tags", payload=None, method="GET")

    def chat_json(self, system: str, user: str, temperature: float, max_tokens: int) -> dict[str, Any]:
        started = time.perf_counter()
        result = self._request("/api/chat", {
            "model": self.settings.model_name,
            "stream": False,
            "format": "json",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "keep_alive": self.settings.ollama_keep_alive,
        })
        try:
            content = result["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ModelError("Model returned invalid structured JSON") from error
        if not isinstance(parsed, dict):
            raise ModelError("Model JSON response must be an object")
        self.last_call_metrics = {
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "prompt_tokens": int(result.get("prompt_eval_count", max(1, len(system + user) // 4))),
            "output_tokens": int(result.get("eval_count", max(1, len(content) // 4))),
            "load_duration_ns": int(result.get("load_duration", 0) or 0),
            "total_duration_ns": int(result.get("total_duration", 0) or 0),
            "retry_count": self._last_transport_retries,
        }
        return parsed


class OpenAIClient(LLMProvider):
    def __init__(self, settings: Settings):
        super().__init__(settings)
        self._keys = list(settings.model_api_keys)
        self._key_index = 0
        self._key_lock = threading.Lock()

    def _request(self, path: str, payload: dict[str, Any] | None = None, method: str = "POST") -> dict[str, Any]:
        if not self._keys:
            raise ModelError(
                "No user-owned OpenAI API key is configured. Set OPENAI_API_KEY or OPENAI_API_KEYS, then restart the app."
            )
        attempted: list[int] = []
        for _ in range(len(self._keys)):
            with self._key_lock:
                index = self._key_index
            if index in attempted:
                index = next(i for i in range(len(self._keys)) if i not in attempted)
            attempted.append(index)
            try:
                return super()._request(path, payload, method, api_key=self._keys[index])
            except ModelHTTPError as error:
                quota_failure = error.status == 429 and error.error_code in {"insufficient_quota", "billing_hard_limit_reached"}
                if (error.status in {401, 403} or quota_failure) and len(attempted) < len(self._keys):
                    with self._key_lock:
                        self._key_index = (index + 1) % len(self._keys)
                    continue
                if error.status in {401, 403}:
                    raise ModelError("OpenAI rejected every configured API key. Replace invalid keys and restart the application.") from error
                if error.status == 429:
                    raise ModelError("OpenAI rate or quota capacity is unavailable. Wait for the limit to reset or check billing; the application will not rotate keys to bypass rate limits.") from error
                raise

    def health(self) -> dict[str, Any]:
        self._request(f"/models/{self.settings.model_name}", payload=None, method="GET")
        return {"models": [{"name": self.settings.model_name}]}

    def chat_json(self, system: str, user: str, temperature: float, max_tokens: int) -> dict[str, Any]:
        started = time.perf_counter()
        logical_retries = 0
        payload = {
            "model": self.settings.model_name,
            "instructions": system,
            "input": "Return only one valid JSON object.\n\n" + user,
            "max_output_tokens": max_tokens,
            "store": False,
            "truncation": "auto",
            "text": {"format": {"type": "json_object"}},
        }
        try:
            result = self._request("/responses", payload)
        except ModelHTTPError as error:
            context_error = error.status == 400 and any(term in (error.detail + " " + error.error_code).lower() for term in ("context", "maximum", "too many tokens"))
            if not context_error:
                raise
            payload["input"] = payload["input"][:max(4000, len(payload["input"]) // 2)]
            payload["max_output_tokens"] = max(512, max_tokens // 2)
            result = self._request("/responses", payload)
            logical_retries += 1
        incomplete = result.get("incomplete_details", {}) or {}
        if result.get("status") == "incomplete" and incomplete.get("reason") == "max_output_tokens":
            payload["max_output_tokens"] = min(8192, max(max_tokens + 512, max_tokens * 2))
            result = self._request("/responses", payload)
            logical_retries += 1
        content = result.get("output_text", "")
        if not content:
            for item in result.get("output", []):
                if item.get("type") == "message":
                    content = "".join(
                        part.get("text", "") for part in item.get("content", []) if part.get("type") == "output_text"
                    )
                    if content:
                        break
        try:
            parsed = json.loads(content)
        except (TypeError, json.JSONDecodeError) as error:
            raise ModelError("OpenAI returned invalid structured JSON") from error
        if not isinstance(parsed, dict):
            raise ModelError("OpenAI JSON response must be an object")
        usage = result.get("usage", {}) or {}
        self.last_call_metrics = {
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "prompt_tokens": int(usage.get("input_tokens", max(1, len(system + user) // 4))),
            "output_tokens": int(usage.get("output_tokens", max(1, len(content) // 4))),
            "retry_count": logical_retries + self._last_transport_retries,
        }
        return parsed

class OpenAICompatClient(OpenAIClient):
    """OpenAI Chat-Completions-compatible dialect: DeepSeek, HF Inference, local vLLM/TGI, etc."""

    def health(self) -> dict[str, Any]:
        self._request("/models", payload=None, method="GET")
        return {"models": [{"name": self.settings.model_name}]}

    def chat_json(self, system: str, user: str, temperature: float, max_tokens: int) -> dict[str, Any]:
        started = time.perf_counter()
        payload = {
            "model": self.settings.model_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user + "\n\nReturn only one valid JSON object."},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        result = self._request("/chat/completions", payload)
        try:
            content = result["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise ModelError("Model returned invalid structured JSON") from error
        if not isinstance(parsed, dict):
            raise ModelError("Model JSON response must be an object")
        usage = result.get("usage", {}) or {}
        self.last_call_metrics = {
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "prompt_tokens": int(usage.get("prompt_tokens", max(1, len(system + user) // 4))),
            "output_tokens": int(usage.get("completion_tokens", max(1, len(content) // 4))),
            "retry_count": self._last_transport_retries,
        }
        return parsed


# PROVIDERS: dict[str, type[LLMProvider]] = {"ollama": OllamaClient, "openai": OpenAIClient}
PROVIDERS: dict[str, type[LLMProvider]] = {"ollama": OllamaClient, "openai": OpenAIClient, "openai_compat": OpenAICompatClient}


def create_model_client(settings: Settings) -> LLMProvider:
    try:
        provider = PROVIDERS[settings.model_provider]
    except KeyError as error:
        raise ValueError(f"Unsupported LLM provider: {settings.model_provider}") from error
    return provider(settings)
