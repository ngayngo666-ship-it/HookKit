#!/usr/bin/env python3
"""Cấu hình vận hành bot két (NINJAA / aech).

Nguyên lý hoạt động (cố định — đừng phá khi sửa code):
1. Parse local trước (pipe / nhãn / bullet / VietQR). Không phụ thuộc OpenAI nếu hết quota.
2. Dán đủ CK (STK · NH · số tiền · ND) → tự ra QR đúng số tiền ngay; thiếu ND thì giữ phần đã có.
3. Nhận tin CK thì luôn trả lời (có QR hoặc báo thiếu) — không im lặng.
4. Nút callback: answer đúng 1 lần bằng message từ Ledger.
5. Mọi tiền vào/ra ghi SQLite (WAL). Bot chết vẫn còn bill chờ và số dư.
6. Cộng/trừ chỉ qua Ledger (1 lần / bill). NLU chỉ nhận ý định.
7. Chỉ 1 process main.py.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _env(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name)
    if val is None or val.strip() == "":
        return default
    return val.strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    return int(raw)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


# --- Telegram ---
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN") or _env("BOT_TOKEN")
# User id Admin (số cá nhân Telegram). KHÔNG dùng id nhóm ở đây.
ADMIN_USER_IDS = [
    x.strip()
    for x in (_env("ADMIN_USER_IDS") or _env("ADMIN_CHAT_ID") or _env("ADMIN_ID") or "").split(",")
    if x.strip()
]
# Giữ alias cũ — chỉ là user id admin, không phải "chỉ chat này được trả lời"
ADMIN_CHAT_ID = ADMIN_USER_IDS[0] if ADMIN_USER_IDS else None
# Rỗng = mọi nhóm/chat đều được bot trả lời tại chỗ. Có list thì chỉ các chat đó.
ALLOWED_CHAT_IDS = [
    x.strip()
    for x in (_env("ALLOWED_CHAT_IDS") or "").split(",")
    if x.strip()
]
# Tự cấp quyền: thành viên nhóm = nhân viên; admin Telegram của nhóm = quản trị
AUTO_GRANT_GROUP_MEMBERS = _env_bool("AUTO_GRANT_GROUP_MEMBERS", True)

# --- Lưu trữ ---
# Ưu tiên volume bền (/data trên Railway). Fallback thư mục local.
DATA_DIR = Path(_env("DATA_DIR", str(ROOT / "data")))
DB_PATH = Path(_env("DB_PATH", str(DATA_DIR / "ket.db")))

# --- Ledger ---
BIG_AMOUNT = _env_int("BIG_AMOUNT", 50_000_000)
ALLOW_NEGATIVE = _env_bool("ALLOW_NEGATIVE", False)
REQUIRE_CUSTOMER = _env_bool("REQUIRE_CUSTOMER", False)

# --- Bot hành vi ---
BOT_TIMEZONE = _env("BOT_TIMEZONE", "Asia/Ho_Chi_Minh")
DEFAULT_DIRECTION = _env("DEFAULT_DIRECTION", "in")  # in = tiền vào khi gửi ảnh
# Tin paste CK / ảnh: luôn trả lời, kể cả thiếu trường
ALWAYS_REPLY_ON_CK = True
# Parse local trước AI (AI chỉ optional — mặc định tắt)
USE_AI_FALLBACK = _env_bool("USE_AI_FALLBACK", False)
OPENAI_API_KEY = _env("OPENAI_API_KEY")
AI_API_KEY = _env("AI_API_KEY")

# --- VietQR (ảnh QR dùng img.vietqr.io từ bill_scanner; API key chỉ khi cần dịch vụ ngoài) ---
VIETQR_CLIENT_ID = _env("VIETQR_CLIENT_ID")
VIETQR_API_KEY = _env("VIETQR_API_KEY")
VIETQR_TEMPLATE = _env("VIETQR_TEMPLATE", "compact2")


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def require_token() -> str:
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit(
            "Thiếu TELEGRAM_BOT_TOKEN. Đặt biến môi trường rồi chạy lại: python main.py"
        )
    return TELEGRAM_BOT_TOKEN


def bootstrap_admin_ids() -> list[str]:
    """Danh sách user_id bootstrap Admin lần đầu (chưa có trong DB)."""
    ids = list(ADMIN_USER_IDS)
    if ADMIN_CHAT_ID and ADMIN_CHAT_ID not in ids:
        ids.append(ADMIN_CHAT_ID)
    return ids
