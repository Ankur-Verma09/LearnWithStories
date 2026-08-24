import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from story_tutor.config import Settings
from story_tutor.model_client import BaseModelClient, ModelHTTPError, OpenAIClient


def client_settings(keys=("sk-owned-a", "sk-owned-b")):
    return SimpleNamespace(model_api_keys=keys, model_api_key=keys[0] if keys else "", model_base_url="https://api.openai.com/v1",
        request_timeout_seconds=3, model_name="gpt-test")


class OpenAIKeyPoolTests(unittest.TestCase):
    def test_settings_deduplicate_environment_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps({"model_provider":"openai","model_base_url":"https://api.openai.com/v1","model_name":"gpt-test",
              "database_path":"data/test.db","max_evidence_chunks":1,"max_evidence_tokens":100,"max_memory_tokens":50,
              "max_session_summary_tokens":50,"default_understanding_level":18,"default_language":"English"}), encoding="utf-8")
            with patch.dict(os.environ, {"OPENAI_API_KEY":"sk-owned-a","OPENAI_API_KEYS":"sk-owned-a; sk-owned-b"}, clear=False):
                settings = Settings.load(path)
            self.assertEqual(settings.model_api_keys, ("sk-owned-a", "sk-owned-b"))

    def test_authentication_failure_switches_to_next_owned_key(self):
        client = OpenAIClient(client_settings())
        used = []
        def request(_self, path, payload=None, method="POST", api_key=""):
            used.append(api_key)
            if api_key == "sk-owned-a": raise ModelHTTPError(401, "invalid key", "invalid_api_key")
            return {"ok": True}
        with patch.object(BaseModelClient, "_request", request):
            self.assertTrue(client._request("/models")["ok"])
        self.assertEqual(used, ["sk-owned-a", "sk-owned-b"])

    def test_context_error_reduces_request_without_switching_key(self):
        client = OpenAIClient(client_settings(("sk-owned-a",)))
        payloads = []
        def request(path, payload=None, method="POST"):
            payloads.append(dict(payload))
            if len(payloads) == 1: raise ModelHTTPError(400, "maximum context length exceeded", "context_length_exceeded")
            return {"output_text": "{}"}
        client._request = request
        self.assertEqual(client.chat_json("system", "x" * 12000, 0, 2000), {})
        self.assertLess(len(payloads[1]["input"]), len(payloads[0]["input"]))
        self.assertEqual(payloads[1]["max_output_tokens"], 1000)

    def test_output_limit_retries_with_larger_output_budget(self):
        client = OpenAIClient(client_settings(("sk-owned-a",)))
        payloads = []
        def request(path, payload=None, method="POST"):
            payloads.append(dict(payload))
            if len(payloads) == 1: return {"status":"incomplete","incomplete_details":{"reason":"max_output_tokens"}}
            return {"output_text":"{}"}
        client._request = request
        self.assertEqual(client.chat_json("system", "user", 0, 1000), {})
        self.assertEqual(payloads[1]["max_output_tokens"], 2000)


if __name__ == "__main__": unittest.main()
