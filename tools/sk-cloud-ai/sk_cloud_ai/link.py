"""Text summary of a GitHub account and the repos Cursor's GitHub App can see."""

from __future__ import annotations

from typing import Any

from sk_cloud_ai.github_api import normalize_repo


def render_link(
    *,
    cursor_me: dict[str, Any],
    cursor_repos: list[dict[str, Any]] | None,
    repo_error: str,
    github_user: dict[str, Any],
    github_repo: dict[str, Any] | None,
    repo: str,
) -> str:
    email = str(cursor_me.get("userEmail") or "")
    key_name = str(cursor_me.get("apiKeyName") or "")
    who = email or key_name or "đã xác thực"
    if email and key_name:
        who = f"{email} ({key_name})"
    lines = [
        f"Cursor: {who}",
        f"GitHub: {github_user.get('login') or '?'}",
    ]
    if repo_error:
        lines.append(f"Repo Cursor thấy: lỗi — {repo_error}")
    else:
        urls = _urls(cursor_repos or [])
        lines.append(f"Repo Cursor thấy: {len(urls)}")
        if repo:
            wanted = normalize_repo(repo)
            visible = wanted in urls
            state = "Cursor GitHub App thấy repo này" if visible else "Cursor chưa thấy repo này"
            lines.append(f"{wanted}: {state}")
    if github_repo is not None:
        full_name = github_repo.get("full_name") or "?"
        branch = github_repo.get("default_branch") or "?"
        private = "riêng" if github_repo.get("private") else "công khai"
        lines.append(f"GitHub token đọc được {full_name} ({private}, nhánh {branch})")
    return "\n".join(lines)


def _urls(rows: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()
    for row in rows:
        raw = str(row.get("url") or "")
        if not raw:
            continue
        try:
            found.add(normalize_repo(raw))
        except ValueError:
            continue
    return found
