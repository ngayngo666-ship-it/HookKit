import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sk_cloud_ai.cli import main


class CliTests(unittest.TestCase):
    def test_config_prints_redacted_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "skai.env"
            env_file.write_text(
                "SK_CLOUD_AI_API_KEY=sk-live-key-1234\n"
                "SK_CLOUD_AI_BASE_URL=https://gw.example/v1\n"
                "SK_CLOUD_AI_MODEL=demo\n",
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {}, clear=True):
                with mock.patch("sys.stdout") as stdout:
                    code = main(["--env-file", str(env_file), "config"])
        self.assertEqual(code, 0)
        printed = "".join(call.args[0] for call in stdout.write.call_args_list)
        self.assertIn("https://gw.example/v1", printed)
        self.assertIn("sk-…1234", printed)
        self.assertNotIn("sk-live-key-1234", printed)

    def test_missing_key_exits_2(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("sys.stderr"):
                code = main(["--env-file", "/tmp/does-not-exist-skai.env", "config"])
        self.assertEqual(code, 2)

    def test_cursor_run_does_not_need_cloud_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "skai.env"
            env_file.write_text(
                "CURSOR_API_KEY=crsr-live-key-9876\nGITHUB_TOKEN=ghp_live_token_abcd\n",
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {}, clear=True):
                with mock.patch("sk_cloud_ai.cli.CursorClient") as cursor_cls:
                    cursor_cls.return_value.create_agent.return_value = {
                        "agent": {
                            "id": "bc-1",
                            "status": "ACTIVE",
                            "url": "https://cursor.com/agents/bc-1",
                            "repos": [{"url": "https://github.com/acme/demo"}],
                        },
                        "run": {"id": "run-1", "status": "CREATING"},
                    }
                    with mock.patch("sys.stdout"):
                        code = main(
                            [
                                "--env-file",
                                str(env_file),
                                "cursor",
                                "run",
                                "sửa",
                                "readme",
                                "--repo",
                                "acme/demo",
                                "--no-auto-pr",
                            ]
                        )
        self.assertEqual(code, 0)
        cursor_cls.assert_called_once()
        self.assertEqual(cursor_cls.call_args.args[0], "crsr-live-key-9876")
        sent = cursor_cls.return_value.create_agent.call_args.kwargs
        self.assertEqual(sent["repo"], "acme/demo")
        self.assertFalse(sent["auto_create_pr"])
        self.assertNotIn("ghp_live_token_abcd", str(sent))

    def test_connect_reports_missing_cursor_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "skai.env"
            env_file.write_text(
                "CURSOR_API_KEY=crsr-live-key-9876\nGITHUB_TOKEN=ghp_live_token_abcd\n",
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {}, clear=True):
                with mock.patch("sk_cloud_ai.cli.CursorClient") as cursor_cls:
                    with mock.patch("sk_cloud_ai.cli.GitHubClient") as github_cls:
                        cursor_cls.return_value.me.return_value = {
                            "userEmail": "dev@example.com",
                            "apiKeyName": "local",
                        }
                        cursor_cls.return_value.repositories.return_value = [
                            {"url": "https://github.com/acme/other"}
                        ]
                        github_cls.return_value.whoami.return_value = {"login": "octo"}
                        github_cls.return_value.repo.return_value = {
                            "full_name": "acme/demo",
                            "default_branch": "master",
                            "private": False,
                        }
                        with mock.patch("sys.stdout") as stdout:
                            code = main(
                                ["--env-file", str(env_file), "connect", "--repo", "acme/demo"]
                            )
        self.assertEqual(code, 1)
        printed = "".join(call.args[0] for call in stdout.write.call_args_list)
        self.assertIn("chưa thấy", printed)
        self.assertIn("octo", printed)
        self.assertNotIn("ghp_live_token_abcd", printed)
        self.assertNotIn("crsr-live-key-9876", printed)


if __name__ == "__main__":
    unittest.main()
