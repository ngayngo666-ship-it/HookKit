"""Load Cloud AI, GitHub, and Cursor credentials without printing secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT = 60.0
DEFAULT_CURSOR_BASE = "https://api.cursor.com"
DEFAULT_GITHUB_API = "https://api.github.com"

PLACEHOLDERS = {
    "sk-...",
    "sk-your-api-key",
    "changeme",
    "ghp_your-token",
    "github_pat_your-token",
    "cursor_your-api-key",
}

TOOL_DIR = Path(__file__).resolve().parents[1]


class ConfigError(Exception):
    """A credential or endpoint is missing or unusable."""


@dataclass(frozen=True)
class Config:
    api_key: str
    base_url: str
    model: str
    timeout: float
    key_source: str

    def redacted_key(self) -> str:
        return redact_secret(self.api_key)


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model: str
    timeout: float
    key_source: str
    github_token: str
    github_token_source: str
    github_api_base: str
    cursor_api_key: str
    cursor_api_key_source: str
    cursor_base_url: str

    def status_text(self) -> str:
        lines = [
            _status("cloud_ai", self.api_key, self.key_source),
            f"cloud_ai_base: {self.base_url}",
            f"cloud_ai_model: {self.model}",
            _status("github", self.github_token, self.github_token_source),
            f"github_api: {self.github_api_base}",
            _status("cursor", self.cursor_api_key, self.cursor_api_key_source),
            f"cursor_base: {self.cursor_base_url}",
            f"timeout: {self.timeout}",
        ]
        return "\n".join(lines)

    def require_cloud(self) -> Config:
        _require(self.api_key, self.key_source, "SK_CLOUD_AI_API_KEY", (
            "Chưa có API key. Đặt SK_CLOUD_AI_API_KEY trong skai.env "
            "hoặc biến môi trường. Mẫu: tools/sk-cloud-ai/skai.env.example"
        ))
        return Config(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            timeout=self.timeout,
            key_source=self.key_source,
        )

    def require_github(self) -> str:
        _require(
            self.github_token,
            self.github_token_source,
            "GITHUB_TOKEN",
            "Chưa gắn GITHUB_TOKEN hoặc GH_TOKEN.",
        )
        return self.github_token

    def require_cursor(self) -> str:
        _require(
            self.cursor_api_key,
            self.cursor_api_key_source,
            "CURSOR_API_KEY",
            "Chưa gắn CURSOR_API_KEY. Tạo key tại Cursor Dashboard → API Keys.",
        )
        return self.cursor_api_key


def redact_secret(secret: str) -> str:
    if len(secret) <= 8:
        return "***"
    return f"{secret[:3]}…{secret[-4:]}"


def _status(label: str, value: str, source: str) -> str:
    if not value:
        return f"{label}: chưa gắn"
    if value in PLACEHOLDERS:
        where = source or "skai.env"
        return f"{label}: giá trị mẫu ({where})"
    return f"{label}: {redact_secret(value)}  nguồn: {source}"


def _require(value: str, source: str, label: str, missing: str) -> None:
    if not value:
        raise ConfigError(missing)
    if value in PLACEHOLDERS:
        where = source or "skai.env"
        raise ConfigError(f"{label} vẫn là giá trị mẫu. Hãy thay key thật trong {where}.")


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    text = path.read_text(encoding="utf-8")
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise ConfigError(f"{path}:{line_no}: thiếu dấu '='")
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if not name:
            raise ConfigError(f"{path}:{line_no}: tên biến trống")
        values[name] = value
    return values


def _first_existing(candidates: list[Path]) -> Path | None:
    for path in candidates:
        if path.is_file():
            return path
    return None


def _https_base(value: str, label: str) -> str:
    base = value.strip().rstrip("/")
    if not base.startswith("https://"):
        raise ConfigError(f"{label} phải là URL https://")
    return base


def load_settings(
    *,
    env_file: Path | None = None,
    base_url: str | None = None,
    model: str | None = None,
    environ: dict[str, str] | None = None,
) -> Settings:
    """File values fill gaps. Environment variables override the file."""

    env = os.environ if environ is None else environ
    file_values: dict[str, str] = {}
    file_source = ""

    if env_file is not None:
        if not env_file.is_file():
            raise ConfigError(f"Không thấy file cấu hình: {env_file}")
        file_values = _parse_env_file(env_file)
        file_source = str(env_file)
    else:
        found = _first_existing([Path.cwd() / "skai.env", TOOL_DIR / "skai.env"])
        if found is not None:
            file_values = _parse_env_file(found)
            file_source = str(found)

    def pick(*names: str) -> tuple[str, str]:
        for name in names:
            if env.get(name):
                return env[name].strip(), name
        for name in names:
            if file_values.get(name):
                return file_values[name].strip(), file_source or name
        return "", ""

    api_key, key_source = pick("SK_CLOUD_AI_API_KEY", "OPENAI_API_KEY")
    file_base, _ = pick("SK_CLOUD_AI_BASE_URL", "OPENAI_BASE_URL")
    resolved_base = _https_base(
        base_url or file_base or DEFAULT_BASE_URL,
        "Base URL",
    )
    file_model, _ = pick("SK_CLOUD_AI_MODEL", "OPENAI_MODEL")
    resolved_model = (model or file_model or DEFAULT_MODEL).strip()
    if not resolved_model:
        raise ConfigError("Thiếu tên model.")

    timeout_raw, _ = pick("SK_CLOUD_AI_TIMEOUT")
    timeout = DEFAULT_TIMEOUT
    if timeout_raw:
        try:
            timeout = float(timeout_raw)
        except ValueError as exc:
            raise ConfigError(f"SK_CLOUD_AI_TIMEOUT không phải số: {timeout_raw}") from exc
        if timeout <= 0:
            raise ConfigError("SK_CLOUD_AI_TIMEOUT phải lớn hơn 0.")

    github_token, github_source = pick("GITHUB_TOKEN", "GH_TOKEN")
    github_base_raw, _ = pick("GITHUB_API_BASE", "GITHUB_API_URL")
    cursor_key, cursor_source = pick("CURSOR_API_KEY")
    cursor_base_raw, _ = pick("CURSOR_API_BASE")

    return Settings(
        api_key=api_key,
        base_url=resolved_base,
        model=resolved_model,
        timeout=timeout,
        key_source=key_source,
        github_token=github_token,
        github_token_source=github_source,
        github_api_base=_https_base(github_base_raw or DEFAULT_GITHUB_API, "GitHub API"),
        cursor_api_key=cursor_key,
        cursor_api_key_source=cursor_source,
        cursor_base_url=_https_base(cursor_base_raw or DEFAULT_CURSOR_BASE, "Cursor API"),
    )


def load_config(
    *,
    env_file: Path | None = None,
    base_url: str | None = None,
    model: str | None = None,
    environ: dict[str, str] | None = None,
) -> Config:
    return load_settings(
        env_file=env_file,
        base_url=base_url,
        model=model,
        environ=environ,
    ).require_cloud()
