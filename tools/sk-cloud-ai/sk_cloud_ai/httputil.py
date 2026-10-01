"""Small JSON HTTP helper. Secrets are stripped from errors."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable


class ApiError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


Transport = Callable[[str, str, dict[str, str], bytes | None, float], tuple[int, bytes]]


def redact(text: str, secrets: list[str]) -> str:
    cleaned = text
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "***")
    return cleaned


def urllib_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def json_call(
    transport: Transport,
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None,
    timeout: float,
    secrets: list[str],
) -> Any:
    body = None
    sent = dict(headers)
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        sent["Content-Type"] = "application/json"
    try:
        status, raw = transport(method, url, sent, body, timeout)
    except urllib.error.URLError as exc:
        reason = redact(str(exc.reason), secrets)
        raise ApiError(f"Không kết nối được {url}: {reason}") from None
    except TimeoutError:
        raise ApiError(f"Hết thời gian chờ khi gọi {url}.") from None
    text = redact(raw.decode("utf-8", errors="replace"), secrets)
    if status >= 400:
        detail = _error_detail(text) or text.strip()[:500]
        raise ApiError(f"HTTP {status}: {detail}", status=status)
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ApiError(f"API không trả JSON: {text[:300]}") from exc


def _error_detail(text: str) -> str:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return ""
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)
        if isinstance(error, str):
            return error
        if parsed.get("message"):
            return str(parsed["message"])
    return ""
