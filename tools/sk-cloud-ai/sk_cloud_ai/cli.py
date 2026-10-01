"""Command line for Cloud AI, GitHub, and Cursor."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sk_cloud_ai.agent import run
from sk_cloud_ai.client import CloudAIClient, CloudAIError
from sk_cloud_ai.config import ConfigError, load_settings
from sk_cloud_ai.cursor_api import CursorClient, format_created, format_run
from sk_cloud_ai.github_api import GitHubClient, normalize_repo
from sk_cloud_ai.httputil import ApiError
from sk_cloud_ai.link import render_link
from sk_cloud_ai.sandbox import Sandbox, SandboxError


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        settings = load_settings(
            env_file=Path(args.env_file) if args.env_file else None,
            base_url=args.base_url,
            model=args.model,
        )
        if args.command == "config":
            print(settings.status_text())
            return 0
        if args.command == "models":
            return _cloud_models(settings)
        if args.command in {"chat", "edit"}:
            return _talk(CloudAIClient(settings.require_cloud()), args)
        if args.command == "github":
            return _github(settings, args)
        if args.command == "cursor":
            return _cursor(settings, args)
        if args.command == "connect":
            return _connect(settings, args)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    except SandboxError as exc:
        print(exc, file=sys.stderr)
        return 2
    except (CloudAIError, ApiError) as exc:
        print(exc, file=sys.stderr)
        return 1
    parser.error(f"lệnh không hỗ trợ: {args.command}")
    return 2


def _cloud_models(settings) -> int:
    names = CloudAIClient(settings.require_cloud()).list_models()
    if not names:
        print("API không trả model nào.")
        return 1
    print("\n".join(names))
    return 0


def _talk(client: CloudAIClient, args: argparse.Namespace) -> int:
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        prompt = sys.stdin.read().strip()
    if not prompt:
        print('Thiếu nội dung. Ví dụ: skai chat "giải thích hàm này"', file=sys.stderr)
        return 2
    sandbox = Sandbox(Path(args.root))
    result = run(
        client,
        sandbox,
        prompt,
        mode=args.command,
        max_steps=args.max_steps,
        dry_run=args.dry_run,
        extra_files=args.file or [],
    )
    if result.writes:
        label = "Sẽ ghi" if args.dry_run else "Đã ghi"
        print(f"{label} {len(result.writes)} file:")
        for path in result.writes:
            print(f"- {path}")
    if result.text:
        print(result.text)
    return 0


def _github(settings, args: argparse.Namespace) -> int:
    client = GitHubClient(
        settings.require_github(),
        base_url=settings.github_api_base,
        timeout=settings.timeout,
    )
    if args.github_command == "whoami":
        user = client.whoami()
        print(user.get("login") or "?")
        if user.get("name"):
            print(user["name"])
        return 0
    if args.github_command == "repos":
        for row in client.list_repos():
            name = row.get("full_name")
            if name:
                print(name)
        return 0
    if args.github_command == "repo":
        info = client.repo(normalize_repo(args.name))
        print(info.get("full_name") or args.name)
        print(f"nhánh: {info.get('default_branch') or '?'}")
        print("riêng" if info.get("private") else "công khai")
        return 0
    raise ConfigError(f"lệnh github không hỗ trợ: {args.github_command}")


def _cursor(settings, args: argparse.Namespace) -> int:
    client = _cursor_client(settings)
    if args.cursor_command == "me":
        me = client.me()
        print(me.get("userEmail") or me.get("apiKeyName") or "đã xác thực")
        if me.get("apiKeyName") and me.get("userEmail"):
            print(me["apiKeyName"])
        return 0
    if args.cursor_command == "models":
        for row in client.list_models():
            name = row.get("displayName") or row.get("id")
            model_id = row.get("id") or ""
            print(f"{model_id}\t{name}" if name and name != model_id else model_id)
        return 0
    if args.cursor_command == "repos":
        for row in client.repositories():
            if row.get("url"):
                print(row["url"])
        return 0
    if args.cursor_command == "agents":
        for row in client.list_agents():
            print(f"{row.get('id') or '?'}\t{row.get('status') or '?'}\t{row.get('name') or ''}")
            if row.get("url"):
                print(row["url"])
        return 0
    if args.cursor_command == "agent":
        agent = client.get_agent(args.agent_id)
        print(format_created(agent))
        return 0
    if args.cursor_command == "run":
        created = client.create_agent(
            prompt=" ".join(args.prompt),
            repo=args.repo or "",
            pr=args.pr or "",
            ref=args.ref or "",
            model=args.cursor_model or "",
            auto_create_pr=args.auto_create_pr,
        )
        print(format_created(created))
        return 0
    if args.cursor_command == "follow":
        run_payload = client.follow_up(args.agent_id, " ".join(args.prompt))
        print(format_run(run_payload))
        return 0
    raise ConfigError(f"lệnh cursor không hỗ trợ: {args.cursor_command}")


def _connect(settings, args: argparse.Namespace) -> int:
    settings.require_cursor()
    settings.require_github()
    cursor = _cursor_client(settings)
    github = GitHubClient(
        settings.github_token,
        base_url=settings.github_api_base,
        timeout=settings.timeout,
    )
    me = cursor.me()
    user = github.whoami()
    repos = None
    repo_error = ""
    try:
        repos = cursor.repositories()
    except ApiError as exc:
        repo_error = str(exc)
    github_repo = None
    if args.repo:
        github_repo = github.repo(normalize_repo(args.repo))
    print(
        render_link(
            cursor_me=me,
            cursor_repos=repos,
            repo_error=repo_error,
            github_user=user,
            github_repo=github_repo,
            repo=args.repo or "",
        )
    )
    if repo_error:
        return 1
    if args.repo:
        wanted = normalize_repo(args.repo)
        visible = any(
            _same_repo(str(row.get("url") or ""), wanted) for row in (repos or [])
        )
        if not visible:
            return 1
    return 0


def _same_repo(raw: str, wanted: str) -> bool:
    try:
        return normalize_repo(raw) == wanted
    except ValueError:
        return False


def _cursor_client(settings) -> CursorClient:
    return CursorClient(
        settings.require_cursor(),
        base_url=settings.cursor_base_url,
        timeout=settings.timeout,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skai",
        description="Công cụ mã nguồn: Cloud AI, GitHub, và Cursor Cloud Agent.",
    )
    parser.add_argument("--env-file", help="File KEY=VALUE, mặc định skai.env")
    parser.add_argument("--base-url", help="Endpoint OpenAI-compatible, có /v1")
    parser.add_argument("--model", help="Model Cloud AI cho chat/edit")
    parser.add_argument("--root", default=".", help="Thư mục mã nguồn được phép đọc/ghi")
    parser.add_argument("--dry-run", action="store_true", help="Không ghi file ở lệnh edit")
    parser.add_argument("--max-steps", type=int, default=8)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("config", help="In cấu hình, key bị che")
    sub.add_parser("models", help="Model của Cloud AI (POST /chat/completions)")
    for name, help_text in (
        ("chat", "Hỏi về mã nguồn, không ghi file"),
        ("edit", "Sửa file trong --root"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("prompt", nargs="*")
        command.add_argument("--file", action="append", default=[], help="Đính kèm file")

    connect = sub.add_parser("connect", help="Kiểm tra GitHub và Cursor trên cùng một repo")
    connect.add_argument("--repo", default="", help="owner/name hoặc URL GitHub")

    github = sub.add_parser("github", help="GitHub REST bằng GITHUB_TOKEN")
    gh = github.add_subparsers(dest="github_command", required=True)
    gh.add_parser("whoami")
    gh.add_parser("repos")
    gh_repo = gh.add_parser("repo")
    gh_repo.add_argument("name", help="owner/name hoặc URL")

    cursor = sub.add_parser("cursor", help="Cursor Cloud Agents API")
    cu = cursor.add_subparsers(dest="cursor_command", required=True)
    cu.add_parser("me")
    cu.add_parser("models")
    cu.add_parser("repos", help="Repo GitHub mà Cursor App nhìn thấy")
    cu.add_parser("agents")
    agent = cu.add_parser("agent")
    agent.add_argument("agent_id")
    run_cmd = cu.add_parser("run", help="Mở agent trên một repo GitHub")
    run_cmd.add_argument("prompt", nargs="+")
    run_cmd.add_argument("--repo", default="", help="owner/name hoặc https://github.com/owner/name")
    run_cmd.add_argument("--ref", default="", help="Nhánh hoặc SHA bắt đầu")
    run_cmd.add_argument("--pr", default="", help="URL pull request")
    run_cmd.add_argument("--model", dest="cursor_model", default="", help="model.id của Cursor")
    run_cmd.add_argument("--auto-pr", dest="auto_create_pr", action="store_true", default=True)
    run_cmd.add_argument("--no-auto-pr", dest="auto_create_pr", action="store_false")
    follow = cu.add_parser("follow", help="Gửi tiếp một prompt cho agent đang có")
    follow.add_argument("agent_id")
    follow.add_argument("prompt", nargs="+")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
