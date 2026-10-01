import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sk_cloud_ai.patch import PatchError, apply_unified_diff, extract_file_diffs


class PatchTests(unittest.TestCase):
    def test_replaces_a_line(self):
        original = "alpha\nbeta\ngamma\n"
        diff = """--- a/demo.c
+++ b/demo.c
@@ -1,3 +1,3 @@
 alpha
-beta
+beta2
 gamma
"""
        self.assertEqual(apply_unified_diff(original, diff), "alpha\nbeta2\ngamma\n")

    def test_mismatch_raises(self):
        with self.assertRaises(PatchError):
            apply_unified_diff("alpha\n", "@@ -1,1 +1,1 @@\n-nope\n+yes\n")

    def test_extracts_fenced_diff(self):
        text = """Đây là diff:

```diff
--- a/src/a.c
+++ b/src/a.c
@@ -1 +1 @@
-old
+new
```
"""
        found = extract_file_diffs(text)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], "src/a.c")
        self.assertIn("@@", found[0][1])


if __name__ == "__main__":
    unittest.main()
