#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_merge_keeps_amount_from_caption():
    from bill_scanner import merge_payment_info, parse_text

    img = {"amount": None, "account": "0123456789", "bank": None, "trust": "low"}
    text = parse_text("0123456789 | Vietcombank | 750000 | mua hang")
    merged = merge_payment_info(img, text)
    assert merged["amount"] == 750_000
    assert merged["account"] == "0123456789"
    assert merged["bank"]
    assert merged.get("vietqr_url")


def test_merge_prefers_qr_amount():
    from bill_scanner import merge_payment_info

    qr = {
        "amount": 100_000,
        "account": "111",
        "bank": "VCB",
        "bank_bin": "970436",
        "bank_name": "Vietcombank",
        "trust": "high",
    }
    text = {"amount": 999, "account": None, "content": "abc", "trust": "low"}
    merged = merge_payment_info(qr, text)
    assert merged["amount"] == 100_000
    assert merged["content"] == "abc"
    assert merged["trust"] == "high"


def test_group_registry_syncs_features(tmp_path):
    from groups import SYNCED_FEATURES, GroupRegistry

    reg = GroupRegistry(tmp_path / "groups.db")
    g1 = reg.touch(-1001, title="Nhom A")
    g2 = reg.touch(-1002, title="Nhom B")
    assert g1["features"] == SYNCED_FEATURES or reg.features(-1001) == SYNCED_FEATURES
    assert reg.features(-1001) == reg.features(-1002) == SYNCED_FEATURES
    assert reg.is_enabled(-1001)
    assert len(reg.list_groups()) == 2


def test_resolve_ket_shared(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1:x")
    monkeypatch.setenv("SHARED_KET_ID", "ket-chung")
    import importlib
    import config
    import main as bot_main

    importlib.reload(config)
    importlib.reload(bot_main)
    assert bot_main.resolve_ket_id(-10099) == "ket-chung"
