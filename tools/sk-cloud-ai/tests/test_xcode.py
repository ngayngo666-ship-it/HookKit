import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sk_cloud_ai.cli import main
from sk_cloud_ai.config import load_settings
from sk_cloud_ai.xcode import XcodeError, discover, resolve_xcode


def _write_project(root: Path, name: str = "Demo") -> None:
    project = root / f"{name}.xcodeproj"
    schemes = project / "xcshareddata" / "xcschemes"
    schemes.mkdir(parents=True)
    (project / "project.pbxproj").write_text(
        "\n".join(
            [
                "// !$*UTF8*$!",
                "{",
                "objects = {",
                "ABC = { isa = XCBuildConfiguration; name = Debug; };",
                "DEF = { isa = XCBuildConfiguration; name = Release; };",
                "TGT = { isa = PBXNativeTarget; name = App; };",
                "};",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (schemes / f"{name}.xcscheme").write_text(
        '<Scheme><LaunchAction buildConfiguration = "Debug"></LaunchAction></Scheme>\n',
        encoding="utf-8",
    )
    internal = project / "project.xcworkspace"
    internal.mkdir()
    (internal / "contents.xcworkspacedata").write_text("<Workspace/>\n", encoding="utf-8")


class XcodeDiscoveryTests(unittest.TestCase):
    def test_reads_scheme_and_ignores_internal_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_project(root)
            hidden = root / "vendor" / "Hidden.xcodeproj"
            (hidden / "xcshareddata" / "xcschemes").mkdir(parents=True)
            (hidden / "project.pbxproj").write_text(
                "ABC = { isa = XCBuildConfiguration; name = Secret; };\n",
                encoding="utf-8",
            )
            found = discover(root)
            self.assertEqual(found.projects, ["Demo.xcodeproj"])
            self.assertEqual(found.workspaces, [])
            self.assertEqual(found.schemes["Demo.xcodeproj"], ["Demo"])
            self.assertEqual(found.configurations["Demo.xcodeproj"], ["Debug", "Release"])
            self.assertEqual(found.targets["Demo.xcodeproj"], ["App"])

    def test_resolve_single_project_and_rejects_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_project(root)
            settings = load_settings(environ={})
            resolved = resolve_xcode(root, settings, discover(root))
            command = resolved.command("build")
            self.assertEqual(command[0], "xcodebuild")
            self.assertIn("-project", command)
            self.assertNotIn("-workspace", command)
            self.assertIn("Demo", command)
            self.assertIn("Debug", command)
            self.assertIn("generic/platform=iOS", command)
            self.assertEqual(command[-1], "build")
            with self.assertRaises(XcodeError):
                resolve_xcode(
                    root,
                    load_settings(environ={"XCODE_PROJECT": "../outside.xcodeproj"}),
                    discover(root),
                )

    def test_cli_dry_run_prints_xcodebuild_without_running_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_project(root)
            with mock.patch("sk_cloud_ai.xcode.subprocess.run") as run:
                with mock.patch("sys.stdout") as stdout:
                    code = main(["--root", str(root), "--dry-run", "xcode", "build"])
        self.assertEqual(code, 0)
        run.assert_not_called()
        printed = "".join(call.args[0] for call in stdout.write.call_args_list)
        self.assertIn("xcodebuild", printed)
        self.assertIn("Demo", printed)
        self.assertIn("build", printed)


if __name__ == "__main__":
    unittest.main()
