"""Bounded tool loop: the model may read the workspace and, in edit mode, write it."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sk_cloud_ai.client import CloudAIClient, CloudAIError
from sk_cloud_ai.patch import PatchError, apply_unified_diff, extract_file_diffs
from sk_cloud_ai.sandbox import Sandbox, SandboxError


READ_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "Liệt kê file văn bản trong workspace.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Đọc một file trong workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Tìm một chuỗi trong các file văn bản.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
]

WRITE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Ghi toàn bộ nội dung mới của một file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_diff",
            "description": "Áp unified diff vào một file đã có.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "diff": {"type": "string"},
                },
                "required": ["path", "diff"],
                "additionalProperties": False,
            },
        },
    },
]

SYSTEM = """Bạn là công cụ mã nguồn. Người dùng gắn API Cloud AI (key dạng sk- hoặc key gateway) qua cấu hình, không qua nội dung chat.
Chỉ đọc và sửa file trong workspace. Không yêu cầu người dùng dán API key.
Không đụng file bí mật (.env, skai.env, pem, key).
Khi cần sửa, ưu tiên apply_diff. Nếu viết lại cả file thì dùng write_file với nội dung đầy đủ.
Trả lời ngắn, cùng ngôn ngữ với câu hỏi."""

MAX_TOOL_CHARS = 20_000


@dataclass
class RunResult:
    text: str
    writes: list[str] = field(default_factory=list)


def run(
    client: CloudAIClient,
    sandbox: Sandbox,
    prompt: str,
    *,
    mode: str,
    max_steps: int = 8,
    dry_run: bool = False,
    extra_files: list[str] | None = None,
) -> RunResult:
    if mode not in {"chat", "edit"}:
        raise ValueError(f"mode không hợp lệ: {mode}")
    tools = list(READ_TOOLS)
    if mode == "edit":
        tools.extend(WRITE_TOOLS)

    user = prompt.strip()
    attached = _attach(sandbox, extra_files or [])
    if attached:
        user = f"{user}\n\nFile đính kèm:\n{attached}"
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user},
    ]
    writes: list[str] = []
    tools_enabled = True

    for _step in range(max_steps):
        try:
            reply = client.chat(messages, tools=tools if tools_enabled else None)
        except CloudAIError as exc:
            if tools_enabled and exc.status == 400:
                tools_enabled = False
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Gateway này không nhận tool call. "
                            "Nếu cần sửa file, trả một khối ```diff unified diff."
                        ),
                    }
                )
                continue
            raise
        messages.append(_assistant_message(reply))
        calls = reply["tool_calls"] if tools_enabled else []
        if not calls:
            text = reply["content"].strip()
            if mode == "edit" and not writes:
                writes.extend(_apply_text_diffs(sandbox, text, dry_run))
            return RunResult(text=text, writes=writes)
        for call in calls:
            name, arguments, call_id = _decode_call(call)
            body = _dispatch(sandbox, name, arguments, mode=mode, dry_run=dry_run, writes=writes)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": body[:MAX_TOOL_CHARS],
                }
            )
    return RunResult(text="Đã đạt giới hạn số bước.", writes=writes)


def _attach(sandbox: Sandbox, paths: list[str]) -> str:
    chunks: list[str] = []
    for path in paths:
        try:
            text = sandbox.read(path)
        except SandboxError as exc:
            chunks.append(f"--- {path}\n(không đọc được: {exc})")
            continue
        chunks.append(f"--- {path}\n{text}")
    return "\n".join(chunks)


def _assistant_message(reply: dict[str, Any]) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": reply["content"] or None,
    }
    if reply["tool_calls"]:
        message["tool_calls"] = reply["tool_calls"]
    return message


def _decode_call(call: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    function = call.get("function") or {}
    name = str(function.get("name") or "")
    raw = function.get("arguments") or "{}"
    if isinstance(raw, str):
        try:
            arguments = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            arguments = {}
    elif isinstance(raw, dict):
        arguments = raw
    else:
        arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    return name, arguments, str(call.get("id") or name)


def _dispatch(
    sandbox: Sandbox,
    name: str,
    arguments: dict[str, Any],
    *,
    mode: str,
    dry_run: bool,
    writes: list[str],
) -> str:
    try:
        if name == "list_files":
            files = sandbox.list_files()
            return "\n".join(files) if files else "(trống)"
        if name == "read_file":
            return sandbox.read(str(arguments.get("path") or ""))
        if name == "search":
            hits = sandbox.search(str(arguments.get("query") or ""))
            return "\n".join(hits) if hits else "(không thấy)"
        if name == "write_file":
            return _write(sandbox, arguments, mode=mode, dry_run=dry_run, writes=writes)
        if name == "apply_diff":
            return _apply(sandbox, arguments, mode=mode, dry_run=dry_run, writes=writes)
        return f"Công cụ không hỗ trợ: {name}"
    except (SandboxError, PatchError, OSError) as exc:
        return f"lỗi: {exc}"


def _write(
    sandbox: Sandbox,
    arguments: dict[str, Any],
    *,
    mode: str,
    dry_run: bool,
    writes: list[str],
) -> str:
    if mode != "edit":
        return "lỗi: chế độ chat không ghi file."
    path = str(arguments.get("path") or "")
    content = arguments.get("content")
    if not isinstance(content, str):
        return "lỗi: content phải là chuỗi."
    if dry_run:
        sandbox.resolve(path)
        rel = path
        writes.append(rel)
        return f"dry-run: sẽ ghi {rel}"
    rel = sandbox.write(path, content)
    writes.append(rel)
    return f"đã ghi {rel}"


def _apply(
    sandbox: Sandbox,
    arguments: dict[str, Any],
    *,
    mode: str,
    dry_run: bool,
    writes: list[str],
) -> str:
    if mode != "edit":
        return "lỗi: chế độ chat không ghi file."
    path = str(arguments.get("path") or "")
    diff = arguments.get("diff")
    if not isinstance(diff, str) or "@@" not in diff:
        return "lỗi: diff phải là unified diff có hunk @@."
    original = sandbox.read(path)
    updated = apply_unified_diff(original, diff)
    if dry_run:
        writes.append(path)
        return f"dry-run: sẽ sửa {path}"
    rel = sandbox.write(path, updated)
    writes.append(rel)
    return f"đã sửa {rel}"


def _apply_text_diffs(sandbox: Sandbox, text: str, dry_run: bool) -> list[str]:
    written: list[str] = []
    for path, diff in extract_file_diffs(text):
        try:
            original = sandbox.read(path)
            updated = apply_unified_diff(original, diff)
        except (SandboxError, PatchError):
            continue
        if dry_run:
            written.append(path)
            continue
        written.append(sandbox.write(path, updated))
    return written
