#!/usr/bin/env python3
"""Smoke: cấu hình + parse CK giữ số tiền khi thiếu ND + import main."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_config_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ADMIN_CHAT_ID", "999")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    # reload config with new env
    import importlib
    import config

    importlib.reload(config)
    assert config.TELEGRAM_BOT_TOKEN == "123:ABC"
    assert "999" in config.bootstrap_admin_ids()
    config.ensure_data_dir()
    assert (tmp_path / "data").is_dir()
    assert config.USE_AI_FALLBACK is False
    assert config.ALWAYS_REPLY_ON_CK is True


def test_parse_ck_keeps_amount_without_content():
    from bill_scanner import parse_text

    info = parse_text("0123456789 | Vietcombank | 500000")
    assert info["amount"] == 500_000
    assert info["account"] == "0123456789"
    assert info["bank"]
    assert info.get("vietqr_url")  # đủ STK+NH+tiền → QR dù thiếu ND
    assert "content" in (info.get("missing") or [])


def test_main_imports():
    # Không chạy polling — chỉ import được
    import main as bot_main

    assert callable(bot_main.build_app)
    assert callable(bot_main.main)
