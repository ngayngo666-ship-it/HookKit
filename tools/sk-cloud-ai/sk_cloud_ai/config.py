"""Load Cloud AI, GitHub, and Cursor credentials without printing secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_TIMEOUT = 60.0
DEFAULT_CURSOR_BASE = "https://api.cursor.com"
DEFAULT_GITHUB_API = "https://api.github.com"
DEFAULT_XCODE_CONFIGURATION = "Debug"
DEFAULT_XCODE_DESTINATION = "generic/platform=iOS"

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
    organization: str = ""
    project: str = ""

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
    xcode_project: str
    xcode_project_source: str
    xcode_workspace: str
    xcode_workspace_source: str
    xcode_scheme: str
    xcode_scheme_source: str
    xcode_configuration: str
    xcode_configuration_source: str
    xcode_destination: str
    xcode_destination_source: str
    xcode_sdk: str
    openai_api_key: str
    openai_api_key_source: str
    openai_base_url: str
    openai_model: str
    openai_organization: str
    openai_project: str

    def status_text(self) -> str:
        lines = [
            _status("cloud_ai", self.api_key, self.key_source),
            f"cloud_ai_base: {self.base_url}",
            f"cloud_ai_model: {self.model}",
            self._openai_status(),
            f"openai_base: {self.openai_base_url or DEFAULT_BASE_URL}",
            f"openai_model: {self.openai_model or DEFAULT_MODEL}",
            _plain("openai_org", self.openai_organization, ""),
            _plain("openai_project", self.openai_project, ""),
            _status("github", self.github_token, self.github_token_source),
            f"github_api: {self.github_api_base}",
            _status("cursor", self.cursor_api_key, self.cursor_api_key_source),
            f"cursor_base: {self.cursor_base_url}",
            _plain("xcode_project", self.xcode_project, self.xcode_project_source),
            _plain("xcode_workspace", self.xcode_workspace, self.xcode_workspace_source),
            _plain("xcode_scheme", self.xcode_scheme, self.xcode_scheme_source),
            _plain(
                "xcode_configuration",
                self.xcode_configuration,
                self.xcode_configuration_source,
                DEFAULT_XCODE_CONFIGURATION,
            ),
            _plain(
                "xcode_destination",
                self.xcode_destination,
                self.xcode_destination_source,
                DEFAULT_XCODE_DESTINATION,
            ),
            _plain("xcode_sdk", self.xcode_sdk, ""),
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
            organization=self.openai_organization if _is_openai(self.base_url) else "",
            project=self.openai_project if _is_openai(self.base_url) else "",
        )

    def require_openai(self) -> Config:
        key = self.openai_api_key
        source = self.openai_api_key_source
        model = self.openai_model or DEFAULT_MODEL
        usable = bool(key) and key not in PLACEHOLDERS
        if not usable and _is_openai(self.base_url) and self.api_key not in PLACEHOLDERS:
            key = self.api_key
            source = self.key_source
            if not self.openai_model:
                model = self.model or DEFAULT_MODEL
        _require(
            key,
            source,
            "OPENAI_API_KEY",
            "Chưa gắn OPENAI_API_KEY. Tạo key tại https://platform.openai.com/api-keys",
        )
        base = _https_base(self.openai_base_url or DEFAULT_BASE_URL, "OpenAI API")
        return Config(
            api_key=key,
            base_url=base,
            model=model,
            timeout=self.timeout,
            key_source=source,
            organization=self.openai_organization,
            project=self.openai_project,
        )

    def _openai_status(self) -> str:
        if self.openai_api_key and self.openai_api_key not in PLACEHOLDERS:
            return _status("openai", self.openai_api_key, self.openai_api_key_source)
        if self.api_key and self.api_key not in PLACEHOLDERS and _is_openai(self.base_url):
            return "openai: dùng chung cloud_ai"
        if self.openai_api_key:
            return _status("openai", self.openai_api_key, self.openai_api_key_source)
        return "openai: chưa gắn"

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


def _plain(label: str, value: str, source: str, default: str = "") -> str:
    if value:
        suffix = f"  nguồn: {source}" if source else ""
        return f"{label}: {value}{suffix}"
    if default:
        return f"{label}: {default} (mặc định)"
    return f"{label}: chưa gắn"


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


def _is_openai(base_url: str) -> bool:
    return base_url.startswith("https://api.openai.com")


def _is_anthropic_key(api_key: str) -> bool:
    return api_key.startswith("sk-ant-")


def _is_anthropic_base(base_url: str) -> bool:
    return base_url.startswith(ANTHROPIC_BASE_URL)


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
        placeholder = ("", "")
        for name in names:
            if not env.get(name):
                continue
            value = env[name].strip()
            if value in PLACEHOLDERS:
                placeholder = (value, name)
                continue
            return value, name
        for name in names:
            if not file_values.get(name):
                continue
            value = file_values[name].strip()
            source = file_source or name
            if value in PLACEHOLDERS:
                if not placeholder[0]:
                    placeholder = (value, source)
                continue
            return value, source
        return placeholder

    api_key, key_source = pick("SK_CLOUD_AI_API_KEY", "OPENAI_API_KEY")
    file_base, _ = pick("SK_CLOUD_AI_BASE_URL")
    openai_base_for_cloud, _ = pick("OPENAI_BASE_URL")
    explicit_base = (base_url or "").strip() or file_base
    resolved_base = _https_base(
        explicit_base or openai_base_for_cloud or DEFAULT_BASE_URL,
        "Base URL",
    )
    if _is_anthropic_key(api_key) and not explicit_base:
        resolved_base = ANTHROPIC_BASE_URL
    file_model, _ = pick("SK_CLOUD_AI_MODEL", "OPENAI_MODEL")
    chosen_model = (model or "").strip()
    if not chosen_model:
        chosen_model = file_model
    if (
        _is_anthropic_base(resolved_base)
        and (not chosen_model or chosen_model == DEFAULT_MODEL)
        and not (model or "").strip()
    ):
        chosen_model = ANTHROPIC_MODEL
    resolved_model = (chosen_model or DEFAULT_MODEL).strip()
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
    xcode_project, xcode_project_source = pick("XCODE_PROJECT")
    xcode_workspace, xcode_workspace_source = pick("XCODE_WORKSPACE")
    xcode_scheme, xcode_scheme_source = pick("XCODE_SCHEME")
    xcode_configuration, xcode_configuration_source = pick("XCODE_CONFIGURATION")
    xcode_destination, xcode_destination_source = pick("XCODE_DESTINATION")
    xcode_sdk, _ = pick("XCODE_SDK")
    openai_key, openai_source = pick("OPENAI_API_KEY")
    openai_base, _ = pick("OPENAI_BASE_URL")
    openai_model, _ = pick("OPENAI_MODEL")
    openai_org, _ = pick("OPENAI_ORG_ID", "OPENAI_ORGANIZATION")
    openai_project, _ = pick("OPENAI_PROJECT_ID", "OPENAI_PROJECT")

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
        xcode_project=xcode_project,
        xcode_project_source=xcode_project_source,
        xcode_workspace=xcode_workspace,
        xcode_workspace_source=xcode_workspace_source,
        xcode_scheme=xcode_scheme,
        xcode_scheme_source=xcode_scheme_source,
        xcode_configuration=xcode_configuration,
        xcode_configuration_source=xcode_configuration_source,
        xcode_destination=xcode_destination,
        xcode_destination_source=xcode_destination_source,
        xcode_sdk=xcode_sdk,
        openai_api_key=openai_key,
        openai_api_key_source=openai_source,
        openai_base_url=_https_base(openai_base, "OpenAI API") if openai_base else "",
        openai_model=openai_model,
        openai_organization=openai_org,
        openai_project=openai_project,
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
