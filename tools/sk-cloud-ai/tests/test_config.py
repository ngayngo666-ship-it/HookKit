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

    def test_openai_key_is_separate_from_gateway(self):
        settings = load_settings(
            environ={
                "SK_CLOUD_AI_API_KEY": "sk-gateway-key-1234",
                "SK_CLOUD_AI_BASE_URL": "https://gw.example/v1",
                "OPENAI_API_KEY": "sk-openai-key-9876",
                "OPENAI_ORG_ID": "org-unit",
                "OPENAI_PROJECT_ID": "proj_unit",
                "OPENAI_MODEL": "gpt-4o-mini",
            }
        )
        cloud = settings.require_cloud()
        openai = settings.require_openai()
        self.assertEqual(cloud.api_key, "sk-gateway-key-1234")
        self.assertEqual(cloud.base_url, "https://gw.example/v1")
        self.assertEqual(cloud.organization, "")
        self.assertEqual(openai.api_key, "sk-openai-key-9876")
        self.assertEqual(openai.base_url, "https://api.openai.com/v1")
        self.assertEqual(openai.model, "gpt-4o-mini")
        self.assertEqual(openai.organization, "org-unit")
        self.assertEqual(openai.project, "proj_unit")
        self.assertNotIn("sk-openai-key-9876", settings.status_text())

    def test_placeholder_cloud_key_uses_openai(self):
        config = load_config(
            environ={
                "SK_CLOUD_AI_API_KEY": "sk-your-api-key",
                "OPENAI_API_KEY": "sk-real-openai-1234",
            }
        )
        self.assertEqual(config.api_key, "sk-real-openai-1234")
        self.assertEqual(config.key_source, "OPENAI_API_KEY")

    def test_anthropic_key_selects_anthropic_endpoint(self):
        config = load_config(
            environ={"SK_CLOUD_AI_API_KEY": "sk-ant-usr-example-key-1234"}
        )
        self.assertEqual(config.base_url, "https://api.anthropic.com")
        self.assertEqual(config.model, "claude-haiku-4-5-20251001")

    def test_explicit_base_overrides_anthropic_key(self):
        config = load_config(
            environ={
                "SK_CLOUD_AI_API_KEY": "sk-ant-usr-example-key-1234",
                "SK_CLOUD_AI_BASE_URL": "https://gw.example/v1",
                "SK_CLOUD_AI_MODEL": "custom-model",
            }
        )
        self.assertEqual(config.base_url, "https://gw.example/v1")
        self.assertEqual(config.model, "custom-model")

    def test_gateway_does_not_satisfy_openai_command(self):
        settings = load_settings(
            environ={
                "SK_CLOUD_AI_API_KEY": "sk-gateway-key-1234",
                "SK_CLOUD_AI_BASE_URL": "https://gw.example/v1",
            }
        )
        with self.assertRaises(ConfigError):
            settings.require_openai()


if __name__ == "__main__":
    unittest.main()
