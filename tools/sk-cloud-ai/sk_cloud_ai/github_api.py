"""GitHub REST calls used to check the account and repository."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from sk_cloud_ai.httputil import ApiError, Transport, json_call, urllib_transport


_REPO = re.compile(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$")
_REPO_URL = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$")
_PR_URL = re.compile(
    r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/([0-9]+)$"
)


class GitHubClient:
    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://api.github.com",
        timeout: float = 60,
        transport: Transport | None = None,
    ):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport or urllib_transport

    def whoami(self) -> dict[str, Any]:
        data = self._get("/user")
        if not isinstance(data, dict):
            raise ApiError("GitHub không trả object cho /user.")
        return data

    def list_repos(self, limit: int = 30) -> list[dict[str, Any]]:
        safe_limit = min(max(limit, 1), 100)
        data = self._get(f"/user/repos?per_page={safe_limit}&sort=updated")
        if not isinstance(data, list):
            raise ApiError("GitHub không trả danh sách repository.")
        return [row for row in data if isinstance(row, dict)]

    def repo(self, repo_url: str) -> dict[str, Any]:
        owner, name = split_repo(repo_url)
        data = self._get(f"/repos/{quote(owner)}/{quote(name)}")
        if not isinstance(data, dict):
            raise ApiError("GitHub không trả object cho repository.")
        return data

    def _get(self, path: str) -> Any:
        return json_call(
            self.transport,
            "GET",
            self.base_url + path,
            {
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "skai-cloud-ai",
            },
            None,
            self.timeout,
            [self.token],
        )


def normalize_repo(value: str) -> str:
    text = value.strip()
    text = text.split("?", 1)[0].split("#", 1)[0]
    if text.endswith(".git"):
        text = text[: -len(".git")]
    text = text.rstrip("/")
    if "://" in text and not text.startswith("https://github.com/"):
        raise ValueError("Repo phải là owner/name hoặc https://github.com/owner/name.")
    match = _REPO.fullmatch(text) or _REPO_URL.fullmatch(text)
    if not match:
        raise ValueError("Repo phải là owner/name hoặc https://github.com/owner/name.")
    return f"https://github.com/{match.group(1)}/{match.group(2)}"


def normalize_pr(value: str) -> tuple[str, str]:
    text = value.strip().split("?", 1)[0].split("#", 1)[0].rstrip("/")
    match = _PR_URL.fullmatch(text)
    if not match:
        raise ValueError("PR phải là https://github.com/owner/name/pull/123.")
    repo_url = f"https://github.com/{match.group(1)}/{match.group(2)}"
    return repo_url, f"{repo_url}/pull/{match.group(3)}"


def resolve_repo_and_pr(repo: str, pr: str) -> tuple[str, str]:
    pr_url = ""
    repo_url = normalize_repo(repo) if repo.strip() else ""
    if pr.strip():
        pr_repo, pr_url = normalize_pr(pr)
        if repo_url and repo_url != pr_repo:
            raise ValueError("Repo và pull request không cùng một repository.")
        repo_url = pr_repo
    if not repo_url:
        raise ValueError("Thiếu repo GitHub (owner/name hoặc URL).")
    return repo_url, pr_url


def split_repo(repo_url: str) -> tuple[str, str]:
    normalized = normalize_repo(repo_url)
    owner, name = normalized.removeprefix("https://github.com/").split("/", 1)
    return owner, name
