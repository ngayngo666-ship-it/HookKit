#!/usr/bin/env python3
"""Đăng ký nhóm — mọi nhóm dùng cùng bộ chức năng (đồng bộ cấu hình)."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

# Cùng chức năng trên mọi nhóm đã bật
SYNCED_FEATURES = {
    "read_ck_text": True,       # dán STK · NH · số tiền · ND
    "read_qr_image": True,      # ảnh QR / bill (photo)
    "read_image_file": True,    # ảnh gửi dạng file/document
    "confirm_buttons": True,    # nút xác nhận / xuất / hủy
    "commands": True,           # số dư, bill chờ, excel...
    "reply_in_group": True,     # trả lời đúng nhóm khách gửi
    "auto_grant_members": True, # tự cấp quyền thành viên
}


class GroupRegistry:
    def __init__(self, path: str | Path):
        self.path = str(path)
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS groups(
                  chat_id TEXT PRIMARY KEY,
                  title TEXT,
                  enabled INTEGER NOT NULL DEFAULT 1,
                  features_json TEXT NOT NULL,
                  joined_at INTEGER NOT NULL,
                  last_seen INTEGER NOT NULL
                )
                """
            )
            db.commit()
        finally:
            db.close()

    @contextmanager
    def _tx(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.execute("COMMIT")
        except BaseException:
            try:
                db.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            db.close()

    def touch(self, chat_id, title: str | None = None, enabled: bool = True) -> dict:
        """Ghi nhận / cập nhật nhóm với đúng bộ chức năng đồng bộ."""
        cid = str(chat_id)
        now = int(time.time())
        feats = json.dumps(SYNCED_FEATURES, ensure_ascii=False)
        with self._tx() as db:
            row = db.execute("SELECT * FROM groups WHERE chat_id=?", (cid,)).fetchone()
            if row:
                db.execute(
                    "UPDATE groups SET title=COALESCE(?, title), enabled=?, features_json=?, last_seen=? WHERE chat_id=?",
                    (title, 1 if enabled else 0, feats, now, cid),
                )
            else:
                db.execute(
                    "INSERT INTO groups(chat_id, title, enabled, features_json, joined_at, last_seen) VALUES(?,?,?,?,?,?)",
                    (cid, title, 1 if enabled else 0, feats, now, now),
                )
            row = db.execute("SELECT * FROM groups WHERE chat_id=?", (cid,)).fetchone()
        return self._row(row)

    def is_enabled(self, chat_id) -> bool:
        with self._tx() as db:
            row = db.execute("SELECT enabled FROM groups WHERE chat_id=?", (str(chat_id),)).fetchone()
        if row is None:
            return True  # nhóm mới: mặc định cho phép (sẽ touch khi có tin)
        return bool(row["enabled"])

    def features(self, chat_id) -> dict:
        with self._tx() as db:
            row = db.execute("SELECT features_json FROM groups WHERE chat_id=?", (str(chat_id),)).fetchone()
        if not row:
            return dict(SYNCED_FEATURES)
        try:
            data = json.loads(row["features_json"] or "{}")
        except json.JSONDecodeError:
            data = {}
        # Luôn merge với SYNCED_FEATURES để nhóm cũ cũng được nâng cấp chức năng mới
        out = dict(SYNCED_FEATURES)
        out.update({k: bool(v) for k, v in data.items() if k in SYNCED_FEATURES})
        # Ép lại các flag đồng bộ bắt buộc
        for k, v in SYNCED_FEATURES.items():
            if v:
                out[k] = True
        return out

    def list_groups(self) -> list[dict]:
        with self._tx() as db:
            rows = db.execute("SELECT * FROM groups ORDER BY last_seen DESC").fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(row) -> dict:
        d = dict(row)
        try:
            d["features"] = json.loads(d.get("features_json") or "{}")
        except json.JSONDecodeError:
            d["features"] = dict(SYNCED_FEATURES)
        return d
