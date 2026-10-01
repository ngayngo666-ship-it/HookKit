import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sk_cloud_ai.agent import run
from sk_cloud_ai.client import CloudAIError
from sk_cloud_ai.sandbox import Sandbox


class ScriptedClient:
    def __init__(self, replies, fail_tools=False):
        self.replies = list(replies)
        self.fail_tools = fail_tools
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append(
            {"messages": [dict(message) for message in messages], "tools": tools}
        )
        if self.fail_tools and tools:
            raise CloudAIError("tools unsupported", status=400)
        if not self.replies:
            raise AssertionError("hết kịch bản")
        return self.replies.pop(0)


class AgentTests(unittest.TestCase):
    def test_reads_then_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.c").write_text("int answer = 7;\n", encoding="utf-8")
            client = ScriptedClient(
                [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path": "a.c"}',
                                },
                            }
                        ],
                    },
                    {
                        "role": "assistant",
                        "content": "Biến answer bằng 7.",
                        "tool_calls": [],
                    },
                ]
            )
            result = run(client, Sandbox(root), "answer là gì?", mode="chat")
        self.assertEqual(result.text, "Biến answer bằng 7.")
        self.assertEqual(result.writes, [])
        tool_msg = client.calls[1]["messages"][-1]
        self.assertIn("int answer = 7;", tool_msg["content"])

    def test_edit_applies_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.c").write_text("int answer = 7;\n", encoding="utf-8")
            client = ScriptedClient(
                [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {
                                    "name": "apply_diff",
                                    "arguments": (
                                        '{"path": "a.c", "diff": '
                                        '"@@ -1 +1 @@\\n-int answer = 7;\\n+int answer = 8;\\n"}'
                                    ),
                                },
                            }
                        ],
                    },
                    {"role": "assistant", "content": "Đã tăng answer.", "tool_calls": []},
                ]
            )
            result = run(client, Sandbox(root), "tăng answer", mode="edit")
            self.assertEqual((root / "a.c").read_text(encoding="utf-8"), "int answer = 8;\n")
            self.assertEqual(result.writes, ["a.c"])

    def test_chat_refuses_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.c").write_text("old\n", encoding="utf-8")
            client = ScriptedClient(
                [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {
                                    "name": "write_file",
                                    "arguments": '{"path": "a.c", "content": "new\\n"}',
                                },
                            }
                        ],
                    },
                    {"role": "assistant", "content": "không ghi", "tool_calls": []},
                ]
            )
            run(client, Sandbox(root), "ghi đè", mode="chat")
            self.assertEqual((root / "a.c").read_text(encoding="utf-8"), "old\n")

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.c").write_text("old\n", encoding="utf-8")
            client = ScriptedClient(
                [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {
                                    "name": "write_file",
                                    "arguments": '{"path": "a.c", "content": "new\\n"}',
                                },
                            }
                        ],
                    },
                    {"role": "assistant", "content": "xong", "tool_calls": []},
                ]
            )
            result = run(client, Sandbox(root), "đổi", mode="edit", dry_run=True)
            self.assertEqual((root / "a.c").read_text(encoding="utf-8"), "old\n")
            self.assertEqual(result.writes, ["a.c"])

    def test_fallback_when_tools_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.c").write_text("old\n", encoding="utf-8")
            diff = (
                "```diff\n--- a/a.c\n+++ b/a.c\n@@ -1 +1 @@\n-old\n+new\n```"
            )
            client = ScriptedClient(
                [{"role": "assistant", "content": diff, "tool_calls": []}],
                fail_tools=True,
            )
            result = run(client, Sandbox(root), "đổi old thành new", mode="edit")
            self.assertEqual((root / "a.c").read_text(encoding="utf-8"), "new\n")
            self.assertEqual(result.writes, ["a.c"])
            self.assertIsNone(client.calls[1]["tools"])


if __name__ == "__main__":
    unittest.main()
