import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sk_cloud_ai.client import CloudAIClient, CloudAIError, endpoint
from sk_cloud_ai.config import Config


def _config() -> Config:
    return Config(
        api_key="sk-secret-key-abcd",
        base_url="https://gw.example/v1",
        model="demo",
        timeout=5,
        key_source="test",
    )


class ClientTests(unittest.TestCase):
    def test_endpoint_strips_method_suffix(self):
        self.assertEqual(
            endpoint("https://gw.example/v1/chat/completions", "/models"),
            "https://gw.example/v1/models",
        )

    def test_chat_sends_bearer_and_parses_tool_call(self):
        seen = {}

        def transport(method, url, headers, body, timeout):
            seen["method"] = method
            seen["url"] = url
            seen["headers"] = headers
            seen["body"] = json.loads(body.decode())
            seen["timeout"] = timeout
            payload = {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": "{\"path\": \"a.c\"}",
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
            return 200, json.dumps(payload).encode()

        reply = CloudAIClient(_config(), transport).chat(
            [{"role": "user", "content": "đọc"}],
            tools=[{"type": "function"}],
        )
        self.assertEqual(seen["url"], "https://gw.example/v1/chat/completions")
        self.assertEqual(seen["headers"]["Authorization"], "Bearer sk-secret-key-abcd")
        self.assertEqual(seen["headers"]["User-Agent"], "skai-cloud-ai")
        self.assertNotIn("OpenAI-Organization", seen["headers"])
        self.assertEqual(seen["body"]["model"], "demo")
        self.assertEqual(seen["body"]["messages"][0]["content"], "đọc")
        self.assertEqual(reply["tool_calls"][0]["function"]["name"], "read_file")
        self.assertEqual(reply["content"], "")

    def test_http_error_redacts_key(self):
        def transport(method, url, headers, body, timeout):
            raw = json.dumps(
                {"error": {"message": "bad key sk-secret-key-abcd"}}
            ).encode()
            return 401, raw

        with self.assertRaises(CloudAIError) as caught:
            CloudAIClient(_config(), transport).list_models()
        self.assertEqual(caught.exception.status, 401)
        self.assertNotIn("sk-secret-key-abcd", str(caught.exception))
        self.assertIn("bad key", str(caught.exception))

    def test_list_models(self):
        def transport(method, url, headers, body, timeout):
            self.assertEqual(url, "https://gw.example/v1/models")
            self.assertIsNone(body)
            return 200, json.dumps({"data": [{"id": "a"}, {"id": "b"}]}).encode()

        names = CloudAIClient(_config(), transport).list_models()
        self.assertEqual(names, ["a", "b"])

    def test_openai_org_and_project_headers(self):
        seen = {}

        def transport(method, url, headers, body, timeout):
            seen["headers"] = headers
            seen["url"] = url
            return 200, json.dumps({"data": [{"id": "gpt-4o-mini"}]}).encode()

        config = _config()
        config = type(config)(
            api_key=config.api_key,
            base_url="https://api.openai.com/v1",
            model=config.model,
            timeout=config.timeout,
            key_source=config.key_source,
            organization="org-unit",
            project="proj_unit",
        )
        CloudAIClient(config, transport).list_models()
        self.assertEqual(seen["url"], "https://api.openai.com/v1/models")
        self.assertEqual(seen["headers"]["OpenAI-Organization"], "org-unit")
        self.assertEqual(seen["headers"]["OpenAI-Project"], "proj_unit")

    def test_anthropic_chat_uses_messages_api(self):
        seen = {}

        def transport(method, url, headers, body, timeout):
            seen["url"] = url
            seen["headers"] = headers
            seen["body"] = json.loads(body.decode())
            payload = {
                "content": [
                    {"type": "text", "text": "pong"},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "read_file",
                        "input": {"path": "a.c"},
                    },
                ]
            }
            return 200, json.dumps(payload).encode()

        config = Config(
            api_key="sk-ant-usr-example-key-1234",
            base_url="https://api.anthropic.com",
            model="claude-haiku-4-5-20251001",
            timeout=5,
            key_source="test",
        )
        reply = CloudAIClient(config, transport).chat(
            [
                {"role": "system", "content": "ngắn"},
                {"role": "user", "content": "đọc"},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Đọc file",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        )
        self.assertEqual(seen["url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(seen["headers"]["x-api-key"], "sk-ant-usr-example-key-1234")
        self.assertEqual(seen["headers"]["anthropic-version"], "2023-06-01")
        self.assertNotIn("Authorization", seen["headers"])
        self.assertEqual(seen["body"]["system"], "ngắn")
        self.assertEqual(seen["body"]["messages"][0]["content"], "đọc")
        self.assertEqual(seen["body"]["tools"][0]["name"], "read_file")
        self.assertEqual(reply["content"], "pong")
        self.assertEqual(reply["tool_calls"][0]["id"], "toolu_1")
        self.assertEqual(reply["tool_calls"][0]["function"]["name"], "read_file")
        self.assertEqual(
            json.loads(reply["tool_calls"][0]["function"]["arguments"]),
            {"path": "a.c"},
        )


if __name__ == "__main__":
    unittest.main()
