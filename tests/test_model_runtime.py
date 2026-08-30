import os
import unittest
from unittest.mock import MagicMock, patch


os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from backend.services import model_runtime  # noqa: E402


class ModelRuntimeTests(unittest.TestCase):
    def test_402_is_reported_as_balance_insufficient(self):
        status = model_runtime.classify_model_error(
            RuntimeError("Error code: 402 - Insufficient Balance")
        )
        self.assertEqual(status["availability"], "balance_insufficient")
        self.assertEqual(status["last_error_code"], "402")
        self.assertIn("余额不足", status["message"])

    def test_timeout_is_reported_as_degraded(self):
        status = model_runtime.classify_model_error(TimeoutError("request timed out"))
        self.assertEqual(status["availability"], "unavailable")
        self.assertIn("降级", status["message"])

    def test_connection_failure_points_to_network_or_proxy(self):
        status = model_runtime.classify_model_error(
            RuntimeError("APIConnectionError: Connection error. WinError 10061")
        )
        self.assertEqual(status["availability"], "unavailable")
        self.assertEqual(status["last_error_code"], "connection_failed")
        self.assertIn("代理", status["message"])

    def test_probe_records_success_without_exposing_key(self):
        fake_client = MagicMock()
        with patch.object(model_runtime, "LLM_API_KEY", "test-key"), \
             patch("openai.OpenAI", return_value=fake_client):
            result = model_runtime.probe_model(force=True)
        self.assertEqual(result["availability"], "available")
        self.assertNotIn("test-key", str(result))

    def test_probe_rejects_an_empty_model_response(self):
        fake_client = MagicMock()
        fake_choice = MagicMock()
        fake_choice.message.content = ""
        fake_client.chat.completions.create.return_value.choices = [fake_choice]
        with patch.object(model_runtime, "LLM_API_KEY", "test-key"), \
             patch("openai.OpenAI", return_value=fake_client):
            result = model_runtime.probe_model(force=True)
        self.assertEqual(result["availability"], "degraded")
        self.assertEqual(result["last_error_code"], "empty_response")


if __name__ == "__main__":
    unittest.main()
