from __future__ import annotations

import json
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


class BaseModelClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _request(self, path: str, payload: dict[str, Any] | None = None, method: str = "POST", api_key: str = "") -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        selected_key = api_key or self.settings.model_api_key
        if selected_key:
            headers["Authorization"] = f"Bearer {selected_key}"
        request = urllib.request.Request(
            f"{self.settings.model_base_url}{path}", data=body, headers=headers, method=method
        )
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
            raise ModelHTTPError(error.code, detail, str(error_code), error.headers.get("Retry-After", "")) from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ModelError(f"Model service request failed: {error}") from error


class OllamaClient(BaseModelClient):

    def health(self) -> dict[str, Any]:
        return self._request("/api/tags", payload=None, method="GET")

    def chat_json(self, system: str, user: str, temperature: float, max_tokens: int) -> dict[str, Any]:
        result = self._request("/api/chat", {
            "model": self.settings.model_name,
            "stream": False,
            "format": "json",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": temperature, "num_predict": max_tokens},
        })
        try:
            content = result["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ModelError("Model returned invalid structured JSON") from error
        if not isinstance(parsed, dict):
            raise ModelError("Model JSON response must be an object")
        return parsed


class OpenAIClient(BaseModelClient):
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
        incomplete = result.get("incomplete_details", {}) or {}
        if result.get("status") == "incomplete" and incomplete.get("reason") == "max_output_tokens":
            payload["max_output_tokens"] = min(8192, max(max_tokens + 512, max_tokens * 2))
            result = self._request("/responses", payload)
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
        return parsed


def create_model_client(settings: Settings) -> BaseModelClient:
    if settings.model_provider == "openai":
        return OpenAIClient(settings)
    return OllamaClient(settings)
