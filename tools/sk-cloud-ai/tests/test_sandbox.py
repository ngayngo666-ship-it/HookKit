import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sk_cloud_ai.sandbox import Sandbox, SandboxError


class SandboxTests(unittest.TestCase):
    def test_blocks_escape_and_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ok.c").write_text("int x;\n", encoding="utf-8")
            (root / ".env").write_text("SK_CLOUD_AI_API_KEY=sk-hidden\n", encoding="utf-8")
            (root / "skai.env").write_text("SK_CLOUD_AI_API_KEY=sk-hidden\n", encoding="utf-8")
            box = Sandbox(root)
            self.assertIn("int x;", box.read("ok.c"))
            with self.assertRaises(SandboxError):
                box.read("../etc/passwd")
            with self.assertRaises(SandboxError):
                box.read(".env")
            with self.assertRaises(SandboxError):
                box.write("nested/token.pem", "secret")
            self.assertEqual(box.list_files(), ["ok.c"])
            self.assertEqual(box.search("int"), ["ok.c:1: int x;"])

    def test_write_stays_inside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            box = Sandbox(root)
            rel = box.write("src/a.c", "void a(void) {}\n")
            self.assertEqual(rel, "src/a.c")
            self.assertTrue((root / "src" / "a.c").is_file())


if __name__ == "__main__":
    unittest.main()
