"""Workspace file access that stays inside one root and skips secrets."""

from __future__ import annotations

from pathlib import Path


class SandboxError(Exception):
    pass


SKIP_DIRS = {
    ".git",
    ".theos",
    ".slim",
    "__pycache__",
    "node_modules",
    "vendor",
}
BINARY_SUFFIXES = {
    ".a",
    ".o",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".zip",
    ".gz",
    ".dylib",
    ".so",
    ".framework",
    ".dmg",
    ".ipa",
}
SECRET_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "skai.env",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "credentials.json",
    "secrets.json",
}
SECRET_SUFFIXES = (".pem", ".p12", ".key", ".pfx", ".kdbx")

MAX_READ_BYTES = 100_000
MAX_WRITE_CHARS = 500_000
MAX_LIST = 300


class Sandbox:
    def __init__(self, root: Path):
        self.root = root.resolve()
        if not self.root.is_dir():
            raise SandboxError(f"Thư mục gốc không tồn tại: {self.root}")

    def resolve(self, user_path: str) -> Path:
        if not user_path or user_path.strip() == "":
            raise SandboxError("Thiếu đường dẫn.")
        raw = Path(user_path)
        candidate = raw if raw.is_absolute() else self.root / raw
        resolved = candidate.resolve()
        if not _is_inside(resolved, self.root):
            raise SandboxError(f"Đường dẫn nằm ngoài workspace: {user_path}")
        if _is_secret(resolved):
            raise SandboxError(f"Không đọc hoặc ghi file bí mật: {resolved.name}")
        return resolved

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def read(self, user_path: str) -> str:
        path = self.resolve(user_path)
        if not path.is_file():
            raise SandboxError(f"Không thấy file: {user_path}")
        if path.stat().st_size > MAX_READ_BYTES:
            raise SandboxError(f"File quá lớn để đưa vào prompt: {user_path}")
        data = path.read_bytes()
        if b"\0" in data:
            raise SandboxError(f"Bỏ qua file nhị phân: {user_path}")
        return data.decode("utf-8", errors="replace")

    def write(self, user_path: str, content: str) -> str:
        if len(content) > MAX_WRITE_CHARS:
            raise SandboxError(f"Nội dung ghi quá dài: {user_path}")
        path = self.resolve(user_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not _is_inside(path.parent.resolve(), self.root):
            raise SandboxError(f"Đường dẫn nằm ngoài workspace: {user_path}")
        path.write_text(content, encoding="utf-8")
        return self.relative(path)

    def list_files(self) -> list[str]:
        found: list[str] = []
        for path in _walk(self.root):
            if _is_secret(path) or path.suffix.lower() in BINARY_SUFFIXES:
                continue
            found.append(path.relative_to(self.root).as_posix())
            if len(found) >= MAX_LIST:
                break
        return found

    def search(self, query: str, limit: int = 40) -> list[str]:
        needle = query.strip()
        if not needle:
            raise SandboxError("Thiếu chuỗi cần tìm.")
        lowered = needle.lower()
        hits: list[str] = []
        for path in _walk(self.root):
            if _is_secret(path) or path.suffix.lower() in BINARY_SUFFIXES:
                continue
            try:
                if path.stat().st_size > MAX_READ_BYTES:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "\0" in text:
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if lowered in line.lower():
                    rel = path.relative_to(self.root).as_posix()
                    hits.append(f"{rel}:{number}: {line.strip()[:200]}")
                    if len(hits) >= limit:
                        return hits
        return hits


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _is_secret(path: Path) -> bool:
    name = path.name.lower()
    if name in SECRET_NAMES or name.startswith(".env"):
        return True
    return name.endswith(SECRET_SUFFIXES)


def _walk(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        yield path
