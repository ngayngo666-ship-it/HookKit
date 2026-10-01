"""Cursor Cloud Agents API. GitHub is attached as a repository URL, not a token."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

from sk_cloud_ai.github_api import resolve_repo_and_pr
from sk_cloud_ai.httputil import ApiError, Transport, json_call, urllib_transport


class CursorClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.cursor.com",
        timeout: float = 60,
        transport: Transport | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport or urllib_transport

    def me(self) -> dict[str, Any]:
        data = self._request("GET", "/v1/me", None, self.timeout)
        if not isinstance(data, dict):
            raise ApiError("Cursor không trả object cho /v1/me.")
        return data

    def list_models(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/v1/models", None, self.timeout)
        return _items(data, "Cursor không trả danh sách model.")

    def repositories(self) -> list[dict[str, Any]]:
        # Cursor documents a strict limit: 1/minute and 30/hour, and slow replies.
        data = self._request("GET", "/v1/repositories", None, max(self.timeout, 90))
        return _items(data, "Cursor không trả danh sách repository GitHub.")

    def list_agents(self, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = min(max(limit, 1), 100)
        data = self._request("GET", f"/v1/agents?limit={safe_limit}", None, self.timeout)
        return _items(data, "Cursor không trả danh sách agent.")

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        data = self._request("GET", _agent_path(agent_id), None, self.timeout)
        if not isinstance(data, dict):
            raise ApiError("Cursor không trả object cho agent.")
        return data

    def create_agent(
        self,
        *,
        prompt: str,
        repo: str = "",
        pr: str = "",
        ref: str = "",
        model: str = "",
        auto_create_pr: bool = True,
    ) -> dict[str, Any]:
        text = prompt.strip()
        if not text:
            raise ApiError("Thiếu nội dung giao cho Cursor.")
        try:
            repo_url, pr_url = resolve_repo_and_pr(repo, pr)
        except ValueError as exc:
            raise ApiError(str(exc)) from None
        entry: dict[str, Any] = {"url": repo_url}
        if pr_url:
            entry["prUrl"] = pr_url
        elif ref.strip():
            entry["startingRef"] = ref.strip()
        payload: dict[str, Any] = {
            "prompt": {"text": text},
            "repos": [entry],
            "autoCreatePR": auto_create_pr,
        }
        if model.strip():
            payload["model"] = {"id": model.strip()}
        data = self._request("POST", "/v1/agents", payload, self.timeout)
        if not isinstance(data, dict):
            raise ApiError("Cursor không trả object khi tạo agent.")
        return data

    def follow_up(self, agent_id: str, prompt: str) -> dict[str, Any]:
        text = prompt.strip()
        if not text:
            raise ApiError("Thiếu nội dung follow-up.")
        data = self._request(
            "POST",
            _agent_path(agent_id) + "/runs",
            {"prompt": {"text": text}},
            self.timeout,
        )
        if not isinstance(data, dict):
            raise ApiError("Cursor không trả object cho run mới.")
        return data

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        timeout: float,
    ) -> Any:
        basic = base64.b64encode(f"{self.api_key}:".encode()).decode("ascii")
        return json_call(
            self.transport,
            method,
            self.base_url + path,
            {
                "Authorization": f"Basic {basic}",
                "Accept": "application/json",
            },
            payload,
            timeout,
            [self.api_key, basic],
        )


def format_created(payload: dict[str, Any]) -> str:
    agent = payload.get("agent") if isinstance(payload.get("agent"), dict) else payload
    run = payload.get("run") if isinstance(payload.get("run"), dict) else {}
    lines = ["Đã mở Cursor agent trên GitHub."]
    if agent.get("id"):
        lines.append(f"id: {agent['id']}")
    if agent.get("status"):
        lines.append(f"trạng thái: {agent['status']}")
    repos = agent.get("repos") if isinstance(agent.get("repos"), list) else []
    if repos and isinstance(repos[0], dict) and repos[0].get("url"):
        lines.append(f"repo: {repos[0]['url']}")
    if agent.get("url"):
        lines.append(f"url: {agent['url']}")
    if run.get("id"):
        lines.append(f"run: {run['id']} ({run.get('status') or '?'})")
    return "\n".join(lines)


def format_run(payload: dict[str, Any]) -> str:
    run = payload.get("run") if isinstance(payload.get("run"), dict) else payload
    lines = ["Đã gửi follow-up."]
    if run.get("id"):
        lines.append(f"run: {run['id']}")
    if run.get("status"):
        lines.append(f"trạng thái: {run['status']}")
    if run.get("agentId"):
        lines.append(f"agent: {run['agentId']}")
    return "\n".join(lines)


def _items(data: Any, empty_message: str) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        raise ApiError(empty_message)
    rows = data.get("items")
    if not isinstance(rows, list):
        raise ApiError(empty_message)
    return [row for row in rows if isinstance(row, dict)]


def _agent_path(agent_id: str) -> str:
    cleaned = agent_id.strip()
    if not cleaned or "/" in cleaned or cleaned.startswith("."):
        raise ApiError("Mã agent không hợp lệ.")
    return "/v1/agents/" + quote(cleaned, safe="")
