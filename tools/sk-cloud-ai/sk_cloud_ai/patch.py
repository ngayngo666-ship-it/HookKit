"""Apply a single-file unified diff produced by the model."""

from __future__ import annotations

import re


class PatchError(Exception):
    pass


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def apply_unified_diff(original: str, diff: str) -> str:
    original_lines = original.splitlines(keepends=True)
    diff_lines = [line for line in diff.splitlines() if not line.startswith("\\")]
    hunks = _hunks(diff_lines)
    if not hunks:
        raise PatchError("Diff không có hunk @@.")

    out: list[str] = []
    cursor = 0
    for old_start, body in hunks:
        target = max(old_start - 1, 0)
        if target < cursor:
            raise PatchError("Các hunk chồng lên nhau.")
        out.extend(original_lines[cursor:target])
        cursor = target
        for kind, text in body:
            if kind in {" ", "-"}:
                if cursor >= len(original_lines):
                    raise PatchError("Hunk vượt quá cuối file.")
                current = original_lines[cursor]
                if current.rstrip("\r\n") != text:
                    raise PatchError(
                        f"Không khớp dòng {cursor + 1}: dự kiến {text!r}, "
                        f"thấy {current.rstrip(chr(10) + chr(13))!r}"
                    )
                if kind == " ":
                    out.append(current)
                cursor += 1
            elif kind == "+":
                out.append(text + ("\n" if not text.endswith("\n") else ""))
            else:
                raise PatchError(f"Dòng diff không hợp lệ: {kind}{text}")
    out.extend(original_lines[cursor:])
    return "".join(out)


def extract_file_diffs(text: str) -> list[tuple[str, str]]:
    """Return (path, diff) pairs from a model reply that contains unified diffs."""

    fenced = _fenced_diffs(text)
    blocks = fenced or [text]
    found: list[tuple[str, str]] = []
    for block in blocks:
        found.extend(_split_paths(block))
    return found


def _hunks(lines: list[str]) -> list[tuple[int, list[tuple[str, str]]]]:
    hunks: list[tuple[int, list[tuple[str, str]]]] = []
    index = 0
    while index < len(lines):
        match = _HUNK.match(lines[index])
        if not match:
            index += 1
            continue
        old_start = int(match.group(1))
        index += 1
        body: list[tuple[str, str]] = []
        while index < len(lines) and not lines[index].startswith("@@"):
            line = lines[index]
            if line.startswith(("diff ", "index ", "--- ", "+++ ")):
                break
            if line.startswith((" ", "+", "-")):
                body.append((line[0], line[1:]))
            elif line == "":
                body.append((" ", ""))
            else:
                raise PatchError(f"Dòng diff không hợp lệ: {line}")
            index += 1
        hunks.append((old_start, body))
    return hunks


def _fenced_diffs(text: str) -> list[str]:
    blocks: list[str] = []
    parts = text.split("```")
    for part in parts[1::2]:
        body = part
        if body.startswith("diff") or body.startswith("patch"):
            newline = body.find("\n")
            body = body[newline + 1 :] if newline != -1 else ""
        if "@@" in body:
            blocks.append(body)
    return blocks


def _split_paths(block: str) -> list[tuple[str, str]]:
    lines = block.splitlines()
    groups: list[tuple[str, list[str]]] = []
    current_path = ""
    current: list[str] = []
    for line in lines:
        if line.startswith("+++ "):
            path = _path_from_header(line[4:])
            if current and "@@" in "\n".join(current):
                groups.append((current_path, current))
            current_path = path or current_path
            current = []
            continue
        if line.startswith("--- "):
            continue
        current.append(line)
    if current and "@@" in "\n".join(current):
        groups.append((current_path, current))
    return [(path, "\n".join(body)) for path, body in groups if path]


def _path_from_header(header: str) -> str:
    token = header.strip().split("\t", 1)[0].strip('"')
    if token in {"/dev/null", "dev/null"}:
        return ""
    for prefix in ("b/", "a/"):
        if token.startswith(prefix):
            token = token[2:]
            break
    return token
