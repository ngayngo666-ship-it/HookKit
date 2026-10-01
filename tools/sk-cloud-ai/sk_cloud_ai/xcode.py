"""Find an Xcode project and build the xcodebuild command. Does not require macOS."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sk_cloud_ai.config import (
    DEFAULT_XCODE_CONFIGURATION,
    DEFAULT_XCODE_DESTINATION,
    TOOL_DIR,
    Settings,
)


class XcodeError(Exception):
    pass


SKIP_DIRS = {
    ".git",
    ".theos",
    ".slim",
    "vendor",
    "Pods",
    "DerivedData",
    "node_modules",
    "Carthage",
}

_CONFIG_NAME = re.compile(r"buildConfiguration\s*=\s*\"([^\"]+)\"")
_PBX_NAME = re.compile(r"name = \"?([^\";]+)\"?\s*;")


@dataclass(frozen=True)
class ResolvedXcode:
    workspace: str
    project: str
    scheme: str
    configuration: str
    destination: str
    sdk: str

    def command(self, action: str) -> list[str]:
        if action not in {"build", "test"}:
            raise XcodeError(f"Hành động Xcode không hỗ trợ: {action}")
        if not self.scheme:
            raise XcodeError("Thiếu scheme. Đặt XCODE_SCHEME hoặc để đúng một scheme trong project.")
        cmd = ["xcodebuild"]
        if self.workspace:
            cmd.extend(["-workspace", self.workspace])
        elif self.project:
            cmd.extend(["-project", self.project])
        else:
            raise XcodeError("Thiếu XCODE_WORKSPACE hoặc XCODE_PROJECT.")
        cmd.extend(["-scheme", self.scheme, "-configuration", self.configuration])
        if self.sdk:
            cmd.extend(["-sdk", self.sdk])
        if self.destination:
            cmd.extend(["-destination", self.destination])
        cmd.append(action)
        return cmd

    def display_command(self, action: str) -> str:
        return " ".join(shlex.quote(part) for part in self.command(action))


@dataclass(frozen=True)
class Discovered:
    projects: list[str]
    workspaces: list[str]
    schemes: dict[str, list[str]]
    configurations: dict[str, list[str]]
    targets: dict[str, list[str]]

    def render(self) -> str:
        if not self.projects and not self.workspaces:
            return (
                "Không thấy .xcodeproj hoặc .xcworkspace trong thư mục này.\n"
                "Đặt XCODE_PROJECT hoặc XCODE_WORKSPACE nếu project nằm chỗ khác."
            )
        lines: list[str] = []
        _section(lines, "workspace", self.workspaces)
        _section(lines, "project", self.projects)
        for container, names in self.schemes.items():
            _section(lines, f"scheme ({container})", names)
        for container, names in self.configurations.items():
            _section(lines, f"configuration ({container})", names)
        for container, names in self.targets.items():
            _section(lines, f"target ({container})", names)
        return "\n".join(lines)


def discover(root: Path) -> Discovered:
    root = root.resolve()
    if not root.is_dir():
        raise XcodeError(f"Thư mục gốc không tồn tại: {root}")
    projects: list[str] = []
    workspaces: list[str] = []
    schemes: dict[str, list[str]] = {}
    configurations: dict[str, list[str]] = {}
    targets: dict[str, list[str]] = {}
    for current, dirnames, _filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRS)
        here = Path(current)
        for name in list(dirnames):
            path = here / name
            if name.endswith(".xcodeproj"):
                rel = path.relative_to(root).as_posix()
                projects.append(rel)
                schemes[rel] = _schemes(path)
                configurations[rel] = _configurations(path)
                targets[rel] = _targets(path)
            elif name.endswith(".xcworkspace") and not _internal_workspace(path):
                rel = path.relative_to(root).as_posix()
                workspaces.append(rel)
                schemes[rel] = _schemes(path)
    return Discovered(projects, workspaces, schemes, configurations, targets)


def resolve_xcode(
    root: Path,
    settings: Settings,
    found: Discovered,
    *,
    project: str = "",
    workspace: str = "",
    scheme: str = "",
    configuration: str = "",
    destination: str = "",
    sdk: str = "",
) -> ResolvedXcode:
    workspace_text = _one_line(workspace or settings.xcode_workspace, "XCODE_WORKSPACE")
    project_text = _one_line(project or settings.xcode_project, "XCODE_PROJECT")
    if not workspace_text and not project_text:
        if len(found.workspaces) == 1:
            workspace_text = found.workspaces[0]
        elif len(found.projects) == 1 and not found.workspaces:
            project_text = found.projects[0]
        elif found.projects or found.workspaces:
            raise XcodeError(
                "Có nhiều project/workspace. Đặt XCODE_PROJECT hoặc XCODE_WORKSPACE.\n"
                + found.render()
            )
        else:
            raise XcodeError(found.render())

    workspace_path = _existing(root, workspace_text, "workspace") if workspace_text else ""
    project_path = _existing(root, project_text, "project") if project_text else ""
    container = workspace_path or project_path
    container_key = _relative_key(root, container, found)
    scheme_name = _one_line(scheme or settings.xcode_scheme, "XCODE_SCHEME")
    available = found.schemes.get(container_key, [])
    if not scheme_name:
        if len(available) == 1:
            scheme_name = available[0]
        else:
            listed = ", ".join(available) if available else "(không có scheme dùng chung)"
            raise XcodeError(f"Chọn XCODE_SCHEME. Scheme thấy được: {listed}")
    elif available and scheme_name not in available:
        raise XcodeError(
            f"Không thấy scheme {scheme_name}. Scheme có sẵn: {', '.join(available)}"
        )
    configuration_name = _one_line(
        configuration or settings.xcode_configuration or DEFAULT_XCODE_CONFIGURATION,
        "XCODE_CONFIGURATION",
    )
    destination_name = _one_line(
        destination or settings.xcode_destination or DEFAULT_XCODE_DESTINATION,
        "XCODE_DESTINATION",
    )
    sdk_name = _one_line(sdk or settings.xcode_sdk, "XCODE_SDK")
    return ResolvedXcode(
        workspace=workspace_path,
        project="" if workspace_path else project_path,
        scheme=scheme_name,
        configuration=configuration_name,
        destination=destination_name,
        sdk=sdk_name,
    )


def run_xcodebuild(command: list[str], cwd: Path, *, dry_run: bool) -> int:
    print(shlex.join(command))
    if dry_run:
        return 0
    if shutil.which("xcodebuild") is None:
        raise XcodeError("Không thấy xcodebuild. Build/test cần macOS đã cài Xcode.")
    completed = subprocess.run(command, cwd=cwd, check=False)
    return completed.returncode


def behavior_text() -> str:
    script = TOOL_DIR / "xcode" / "behavior.sh"
    return (
        "Trong Xcode: Settings → Behaviors → dấu + → Run.\n"
        f"Chọn script:\n{script}\n\n"
        "Script đọc workspace và scheme đang mở, rồi in lệnh xcodebuild.\n"
        "Có thêm câu chữ thì script gửi câu đó cho `skai chat`."
    )


def _schemes(container: Path) -> list[str]:
    names: list[str] = []
    for folder in ("xcshareddata",):
        scheme_dir = container / folder / "xcschemes"
        if not scheme_dir.is_dir():
            continue
        for path in sorted(scheme_dir.glob("*.xcscheme")):
            if path.stem not in names:
                names.append(path.stem)
    user_root = container / "xcuserdata"
    if user_root.is_dir():
        for path in sorted(user_root.glob("*/xcschemes/*.xcscheme")):
            if path.stem not in names:
                names.append(path.stem)
    return names


def _configurations(project: Path) -> list[str]:
    pbx = project / "project.pbxproj"
    names: list[str] = []
    if pbx.is_file():
        names.extend(_isa_names(pbx.read_text(encoding="utf-8", errors="replace"), "XCBuildConfiguration"))
    for scheme in _scheme_files(project):
        text = scheme.read_text(encoding="utf-8", errors="replace")
        for name in _CONFIG_NAME.findall(text):
            if name not in names:
                names.append(name)
    return names


def _targets(project: Path) -> list[str]:
    pbx = project / "project.pbxproj"
    if not pbx.is_file():
        return []
    return _isa_names(pbx.read_text(encoding="utf-8", errors="replace"), "PBXNativeTarget")


def _isa_names(text: str, isa: str) -> list[str]:
    names: list[str] = []
    pending = False
    for line in text.splitlines():
        if f"isa = {isa}" in line:
            pending = True
        if not pending:
            continue
        match = _PBX_NAME.search(line)
        if not match:
            continue
        name = match.group(1).strip()
        if name not in names:
            names.append(name)
        pending = False
    return names


def _scheme_files(container: Path) -> list[Path]:
    found: list[Path] = []
    shared = container / "xcshareddata" / "xcschemes"
    if shared.is_dir():
        found.extend(sorted(shared.glob("*.xcscheme")))
    return found


def _internal_workspace(path: Path) -> bool:
    return path.name == "project.xcworkspace" and path.parent.suffix == ".xcodeproj"


def _section(lines: list[str], title: str, values: list[str]) -> None:
    if not values:
        return
    lines.append(f"{title}:")
    lines.extend(f"- {value}" for value in values)


def _one_line(value: str, label: str) -> str:
    text = value.strip()
    if "\n" in text or "\r" in text or "\x00" in text:
        raise XcodeError(f"{label} không được xuống dòng.")
    return text


def _existing(root: Path, value: str, kind: str) -> str:
    raw = Path(value)
    if raw.is_absolute():
        resolved = raw.resolve()
    else:
        resolved = (root / raw).resolve()
        try:
            resolved.relative_to(root.resolve())
        except ValueError as exc:
            raise XcodeError(f"Đường dẫn {kind} nằm ngoài thư mục gốc: {value}") from exc
    if not resolved.exists():
        raise XcodeError(f"Không thấy {kind}: {value}")
    return str(resolved)


def _relative_key(root: Path, container: str, found: Discovered) -> str:
    path = Path(container).resolve()
    try:
        rel = path.relative_to(root.resolve()).as_posix()
    except ValueError:
        rel = str(path)
    if rel in found.schemes:
        return rel
    for key in found.schemes:
        if Path(key).name == path.name:
            return key
    return rel
