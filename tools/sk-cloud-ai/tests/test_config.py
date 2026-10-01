import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sk_cloud_ai.config import ConfigError, load_config, load_settings


class ConfigTests(unittest.TestCase):
    def test_env_overrides_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "skai.env"
            path.write_text(
                'SK_CLOUD_AI_API_KEY="sk-from-file-1234"\n'
                "SK_CLOUD_AI_BASE_URL=https://files.example/v1\n"
                "SK_CLOUD_AI_MODEL=file-model\n",
                encoding="utf-8",
            )
            config = load_config(
                env_file=path,
                environ={
                    "SK_CLOUD_AI_API_KEY": "sk-from-env-5678",
                    "OPENAI_MODEL": "env-model",
                },
            )
        self.assertEqual(config.api_key, "sk-from-env-5678")
        self.assertEqual(config.base_url, "https://files.example/v1")
        self.assertEqual(config.model, "env-model")
        self.assertEqual(config.key_source, "SK_CLOUD_AI_API_KEY")
        self.assertEqual(config.redacted_key(), "sk-…5678")

    def test_missing_key(self):
        with self.assertRaises(ConfigError):
            load_config(environ={})

    def test_rejects_placeholder(self):
        with self.assertRaises(ConfigError):
            load_config(environ={"SK_CLOUD_AI_API_KEY": "sk-your-api-key"})

    def test_rejects_bad_url(self):
        with self.assertRaises(ConfigError):
            load_config(
                environ={
                    "SK_CLOUD_AI_API_KEY": "sk-real-key-1234",
                    "SK_CLOUD_AI_BASE_URL": "ftp://nope",
                }
            )

    def test_strips_trailing_slash_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "local.env"
            path.write_text(
                "export SK_CLOUD_AI_API_KEY=sk-export-key-9999\n"
                "SK_CLOUD_AI_BASE_URL=https://gw.example/v1/\n",
                encoding="utf-8",
            )
            config = load_config(env_file=path, environ={})
        self.assertEqual(config.api_key, "sk-export-key-9999")
        self.assertEqual(config.base_url, "https://gw.example/v1")
        self.assertEqual(config.key_source, str(path))

    def test_placeholder_keys_stay_hidden(self):
        settings = load_settings(
            environ={
                "CURSOR_API_KEY": "cursor_your-api-key",
                "GITHUB_TOKEN": "github_pat_your-token",
            }
        )
        text = settings.status_text()
        self.assertIn("giá trị mẫu", text)
        self.assertNotIn("cursor_your-api-key", text)
        self.assertNotIn("github_pat_your-token", text)
        with self.assertRaises(ConfigError):
            settings.require_cursor()
        with self.assertRaises(ConfigError):
            settings.require_github()


if __name__ == "__main__":
    unittest.main()
