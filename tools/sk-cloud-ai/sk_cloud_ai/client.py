"""HTTP client for an OpenAI-compatible /v1/chat/completions endpoint."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable

from sk_cloud_ai.config import Config


class CloudAIError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


Transport = Callable[[str, str, dict[str, str], bytes | None, float], tuple[int, bytes]]


def redact(text: str, secret: str) -> str:
    if not secret or not text:
        return text
    return text.replace(secret, "***")


def endpoint(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    for suffix in ("/chat/completions", "/messages", "/models"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def is_anthropic(base_url: str) -> bool:
    return base_url.startswith("https://api.anthropic.com")


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
        payload = exc.read()
        return exc.code, payload


def _anthropic_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for tool in tools or []:
        function = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        if not isinstance(function, dict) or not function.get("name"):
            continue
        schema = function.get("parameters") or {"type": "object", "properties": {}}
        converted.append(
            {
                "name": str(function["name"]),
                "description": str(function.get("description") or ""),
                "input_schema": schema if isinstance(schema, dict) else {"type": "object"},
            }
        )
    return converted


def _anthropic_messages(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            text = message_text(message.get("content")).strip()
            if text:
                system_parts.append(text)
            continue
        if role == "assistant":
            blocks: list[dict[str, Any]] = []
            text = message_text(message.get("content"))
            if text:
                blocks.append({"type": "text", "text": text})
            for call in message.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                function = call.get("function") if isinstance(call.get("function"), dict) else {}
                raw = function.get("arguments") or "{}"
                if isinstance(raw, str):
                    try:
                        parsed = json.loads(raw) if raw.strip() else {}
                    except json.JSONDecodeError:
                        parsed = {}
                else:
                    parsed = raw
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": str(call.get("id") or "tool"),
                        "name": str(function.get("name") or ""),
                        "input": parsed if isinstance(parsed, dict) else {},
                    }
                )
            if not blocks:
                blocks.append({"type": "text", "text": ""})
            converted.append({"role": "assistant", "content": blocks})
            continue
        if role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": str(message.get("tool_call_id") or ""),
                "content": message_text(message.get("content")),
            }
            if (
                converted
                and converted[-1]["role"] == "user"
                and isinstance(converted[-1]["content"], list)
            ):
                converted[-1]["content"].append(block)
            else:
                converted.append({"role": "user", "content": [block]})
            continue
        converted.append({"role": "user", "content": message_text(message.get("content"))})
    return "\n".join(system_parts), converted


def message_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
        return "".join(parts)
    return str(content)


class CloudAIClient:
    def __init__(self, config: Config, transport: Transport | None = None):
        self.config = config
        self.transport = transport or urllib_transport

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if is_anthropic(self.config.base_url):
            return self._anthropic_chat(messages, tools)
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        data = self._post("/chat/completions", payload)
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise CloudAIError("API không trả về choices.")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise CloudAIError("API không trả về message.")
        return {
            "role": "assistant",
            "content": message_text(message.get("content")),
            "tool_calls": message.get("tool_calls") or [],
        }

    def list_models(self) -> list[str]:
        path = "/v1/models" if is_anthropic(self.config.base_url) else "/models"
        data = self._get(path)
        rows = data.get("data")
        if not isinstance(rows, list):
            raise CloudAIError("API không trả về danh sách model.")
        names: list[str] = []
        for row in rows:
            if isinstance(row, dict) and row.get("id"):
                names.append(str(row["id"]))
            elif isinstance(row, str):
                names.append(row)
        return names

    def _anthropic_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        system, converted = _anthropic_messages(messages)
        payload: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": 4096,
            "messages": converted,
        }
        if system:
            payload["system"] = system
        anthropic_tools = _anthropic_tools(tools)
        if anthropic_tools:
            payload["tools"] = anthropic_tools
        data = self._post("/v1/messages", payload)
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise CloudAIError("API không trả về content.")
        texts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                texts.append(str(block.get("text") or ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    {
                        "id": str(block.get("id") or ""),
                        "type": "function",
                        "function": {
                            "name": str(block.get("name") or ""),
                            "arguments": json.dumps(
                                block.get("input") or {},
                                ensure_ascii=False,
                            ),
                        },
                    }
                )
        return {
            "role": "assistant",
            "content": "".join(texts),
            "tool_calls": tool_calls,
        }

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "skai-cloud-ai",
        }
        if is_anthropic(self.config.base_url):
            headers["x-api-key"] = self.config.api_key
            headers["anthropic-version"] = "2023-06-01"
            return headers
        headers["Authorization"] = f"Bearer {self.config.api_key}"
        if self.config.organization:
            headers["OpenAI-Organization"] = self.config.organization
        if self.config.project:
            headers["OpenAI-Project"] = self.config.project
        return headers

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = self._headers()
        headers["Content-Type"] = "application/json"
        return self._call("POST", path, headers, body)

    def _get(self, path: str) -> dict[str, Any]:
        return self._call("GET", path, self._headers(), None)

    def _call(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: bytes | None,
    ) -> dict[str, Any]:
        url = endpoint(self.config.base_url, path)
        try:
            status, raw = self.transport(method, url, headers, body, self.config.timeout)
        except urllib.error.URLError as exc:
            reason = redact(str(exc.reason), self.config.api_key)
            raise CloudAIError(f"Không kết nối được {url}: {reason}") from None
        except TimeoutError:
            raise CloudAIError(f"Hết thời gian chờ khi gọi {url}.") from None
        text = raw.decode("utf-8", errors="replace")
        text = redact(text, self.config.api_key)
        if status >= 400:
            detail = _error_detail(text) or text.strip()[:500]
            raise CloudAIError(f"API trả về HTTP {status}: {detail}", status=status)
        try:
            parsed = json.loads(text) if text else {}
        except json.JSONDecodeError as exc:
            raise CloudAIError(f"API không trả JSON: {text[:300]}") from exc
        if not isinstance(parsed, dict):
            raise CloudAIError("API trả JSON không phải object.")
        return parsed


def _error_detail(text: str) -> str:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, dict):
        return ""
    error = parsed.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)
    if isinstance(error, str):
        return error
    if parsed.get("message"):
        return str(parsed["message"])
    return ""
