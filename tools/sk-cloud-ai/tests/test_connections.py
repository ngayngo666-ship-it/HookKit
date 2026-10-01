import base64
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sk_cloud_ai.cursor_api import CursorClient, format_created
from sk_cloud_ai.github_api import GitHubClient, normalize_repo, resolve_repo_and_pr
from sk_cloud_ai.httputil import ApiError
from sk_cloud_ai.link import render_link


class GitHubTests(unittest.TestCase):
    def test_normalize_and_pr(self):
        self.assertEqual(normalize_repo("acme/demo.git"), "https://github.com/acme/demo")
        repo, pr = resolve_repo_and_pr("", "https://github.com/acme/demo/pull/12")
        self.assertEqual(repo, "https://github.com/acme/demo")
        self.assertEqual(pr, "https://github.com/acme/demo/pull/12")
        with self.assertRaises(ValueError):
            resolve_repo_and_pr("other/repo", "https://github.com/acme/demo/pull/12")

    def test_whoami_uses_bearer_and_redacts(self):
        seen = {}

        def transport(method, url, headers, body, timeout):
            seen["url"] = url
            seen["headers"] = headers
            return 401, b'{"message":"bad token ghp_live_token_abcd"}'

        with self.assertRaises(ApiError) as caught:
            GitHubClient("ghp_live_token_abcd", transport=transport).whoami()
        self.assertEqual(seen["url"], "https://api.github.com/user")
        self.assertEqual(seen["headers"]["Authorization"], "Bearer ghp_live_token_abcd")
        self.assertEqual(seen["headers"]["User-Agent"], "skai-cloud-ai")
        self.assertNotIn("ghp_live_token_abcd", str(caught.exception))


class CursorTests(unittest.TestCase):
    def test_create_agent_posts_repo_without_github_token(self):
        seen = {}

        def transport(method, url, headers, body, timeout):
            seen["method"] = method
            seen["url"] = url
            seen["headers"] = headers
            seen["body"] = json.loads(body.decode())
            payload = {
                "agent": {
                    "id": "bc-1",
                    "status": "ACTIVE",
                    "url": "https://cursor.com/agents/bc-1",
                    "repos": [{"url": "https://github.com/acme/demo"}],
                },
                "run": {"id": "run-1", "status": "CREATING"},
            }
            return 200, json.dumps(payload).encode()

        created = CursorClient("crsr-secret-key-abcd", transport=transport).create_agent(
            prompt="Thêm README",
            repo="acme/demo",
            ref="master",
            auto_create_pr=True,
        )
        decoded = base64.b64decode(
            seen["headers"]["Authorization"].split(" ", 1)[1]
        ).decode()
        self.assertEqual(decoded, "crsr-secret-key-abcd:")
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["url"], "https://api.cursor.com/v1/agents")
        self.assertEqual(
            seen["body"]["repos"],
            [{"url": "https://github.com/acme/demo", "startingRef": "master"}],
        )
        self.assertTrue(seen["body"]["autoCreatePR"])
        self.assertNotIn("mcpServers", seen["body"])
        self.assertNotIn("envVars", seen["body"])
        self.assertIn("bc-1", format_created(created))
        self.assertIn("https://github.com/acme/demo", format_created(created))

    def test_error_redacts_key_and_basic_token(self):
        basic = base64.b64encode(b"crsr-secret-key-abcd:").decode()

        def transport(method, url, headers, body, timeout):
            raw = json.dumps(
                {"error": {"message": f"nope crsr-secret-key-abcd {basic}"}}
            ).encode()
            return 401, raw

        with self.assertRaises(ApiError) as caught:
            CursorClient("crsr-secret-key-abcd", transport=transport).me()
        message = str(caught.exception)
        self.assertNotIn("crsr-secret-key-abcd", message)
        self.assertNotIn(basic, message)

    def test_rejects_agent_id_with_slash(self):
        def transport(method, url, headers, body, timeout):
            raise AssertionError("không được gọi mạng khi id sai")

        with self.assertRaises(ApiError):
            CursorClient("crsr-secret-key-abcd", transport=transport).get_agent("a/b")

    def test_pr_omits_starting_ref(self):
        seen = {}

        def transport(method, url, headers, body, timeout):
            seen["body"] = json.loads(body.decode())
            return 200, b'{"agent":{"id":"bc-2"},"run":{"id":"run-2","status":"CREATING"}}'

        CursorClient("crsr-secret-key-abcd", transport=transport).create_agent(
            prompt="xem diff",
            pr="https://github.com/acme/demo/pull/9",
            ref="master",
        )
        self.assertEqual(
            seen["body"]["repos"][0],
            {
                "url": "https://github.com/acme/demo",
                "prUrl": "https://github.com/acme/demo/pull/9",
            },
        )


class LinkTests(unittest.TestCase):
    def test_render_says_when_cursor_cannot_see_repo(self):
        text = render_link(
            cursor_me={"userEmail": "dev@example.com", "apiKeyName": "local"},
            cursor_repos=[{"url": "https://github.com/acme/other"}],
            repo_error="",
            github_user={"login": "octo"},
            github_repo={"full_name": "acme/demo", "default_branch": "master", "private": False},
            repo="acme/demo",
        )
        self.assertIn("dev@example.com", text)
        self.assertIn("GitHub: octo", text)
        self.assertIn("chưa thấy", text)
        self.assertIn("acme/demo", text)


if __name__ == "__main__":
    unittest.main()
