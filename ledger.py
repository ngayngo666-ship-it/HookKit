#!/usr/bin/env python3
"""So quy tien (SQLite) cho bot: xac nhan bill -> cong ket, xuat bill -> tru ket.

Nguyen tac (tien bac khong duoc sai):
- Moi thay doi tien nam trong MOT transaction (BEGIN IMMEDIATE) va chi xay ra mot lan cho moi bill
  (UNIQUE bill_id + kind), bam nut 2 lan / 2 nguoi cung bam / bot chay lai deu khong cong-tru lan 2.
- So du = tong cac dong trong `entries` (chi them, khong sua/xoa). Sai thi hoan tac bang dong doi ung.
- Du lieu (bill cho, phieu xac nhan, so quy) luon o SQLite, bot chet van con.
- So tien la so nguyen VND.

    from ledger import Ledger
    lg = Ledger("ket.db")
    lg.add_user("123", "admin", "Aech")
    r = lg.submit_bill("chat1", info, actor="123", image_bytes=raw)   # info tu bill_scanner.scan_image
    r = lg.confirm_bill(r["bill_id"], actor="123")                    # CONG ket
    r = lg.export_bill(out_bill_id, actor="123")                      # TRU ket
Moi ham tra ve {"ok", "code", "message"(tieng Viet ngan), "balance", "bill_id", "entry_id"} de bot tra loi dung 1 lan.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager

ROLES = {"admin": 3, "quan_tri": 2, "nhan_vien": 1}
ROLE_NAMES = {"admin": "Admin", "quan_tri": "Quản trị", "nhan_vien": "Nhân viên"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  user_id TEXT PRIMARY KEY,
  role TEXT NOT NULL CHECK(role IN ('admin','quan_tri','nhan_vien')),
  name TEXT
);
CREATE TABLE IF NOT EXISTS customers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ket_id TEXT NOT NULL,
  name TEXT NOT NULL,
  fee_in_bp INTEGER NOT NULL DEFAULT 0 CHECK(fee_in_bp BETWEEN 0 AND 10000),
  fee_in_fixed INTEGER NOT NULL DEFAULT 0 CHECK(fee_in_fixed >= 0),
  fee_out_bp INTEGER NOT NULL DEFAULT 0 CHECK(fee_out_bp BETWEEN 0 AND 10000),
  fee_out_fixed INTEGER NOT NULL DEFAULT 0 CHECK(fee_out_fixed >= 0),
  UNIQUE(ket_id, name)
);
CREATE TABLE IF NOT EXISTS closings(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ket_id TEXT NOT NULL,
  closed_by TEXT NOT NULL, closed_at INTEGER NOT NULL,
  opening_balance INTEGER NOT NULL, closing_balance INTEGER NOT NULL,
  note TEXT
);
CREATE TABLE IF NOT EXISTS bills(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ket_id TEXT NOT NULL,
  direction TEXT NOT NULL CHECK(direction IN ('in','out')),
  source TEXT NOT NULL CHECK(source IN ('image','manual')),
  status TEXT NOT NULL CHECK(status IN ('pending','confirmed','exported','rejected')),
  amount INTEGER CHECK(amount IS NULL OR amount > 0),
  account TEXT, bank TEXT, content TEXT, name TEXT, txn TEXT,
  trust TEXT, image_hash TEXT, info_json TEXT,
  created_by TEXT NOT NULL, created_at INTEGER NOT NULL,
  decided_by TEXT, decided_at INTEGER,
  customer_id INTEGER REFERENCES customers(id),
  fee INTEGER, fee_bp INTEGER, fee_fixed INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_bills_image ON bills(ket_id, direction, image_hash)
  WHERE image_hash IS NOT NULL AND status != 'rejected';
CREATE UNIQUE INDEX IF NOT EXISTS ux_bills_txn ON bills(ket_id, direction, txn)
  WHERE txn IS NOT NULL AND status != 'rejected';
CREATE TABLE IF NOT EXISTS entries(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ket_id TEXT NOT NULL,
  bill_id INTEGER REFERENCES bills(id),
  kind TEXT NOT NULL CHECK(kind IN ('in','out','reverse_in','reverse_out')),
  amount INTEGER NOT NULL CHECK(amount > 0),
  note TEXT, actor TEXT NOT NULL, created_at INTEGER NOT NULL,
  reverses INTEGER REFERENCES entries(id),
  closing_id INTEGER REFERENCES closings(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_entries_bill_kind ON entries(bill_id, kind) WHERE bill_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_entries_reverses ON entries(reverses) WHERE reverses IS NOT NULL;
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, actor TEXT, action TEXT NOT NULL, detail TEXT
);
"""


MIGRATIONS = [
    ("bills", "customer_id", "INTEGER REFERENCES customers(id)"),
    ("bills", "fee", "INTEGER"),
    ("bills", "fee_bp", "INTEGER"),
    ("bills", "fee_fixed", "INTEGER"),
    ("entries", "closing_id", "INTEGER REFERENCES closings(id)"),
]


def calc_fee(amount: int, bp: int, fixed: int) -> int:
    """Phi = amount * bp/10000 (lam tron len tu .5) + co dinh. Chi dung so nguyen, khong float."""
    return (amount * bp + 5000) // 10000 + fixed


def pct_to_bp(pct) -> int:
    from decimal import Decimal

    bp = Decimal(str(pct)) * 100
    if bp != bp.to_integral_value() or not (0 <= bp <= 10000):
        raise ValueError("phi % phai tu 0 den 100, toi da 2 chu so thap phan")
    return int(bp)


def vnd(n) -> str:
    return f"{int(n):,}".replace(",", ".") + "đ"


def image_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _res(ok, code, message, **extra):
    out = {"ok": ok, "code": code, "message": message, "balance": None, "bill_id": None, "entry_id": None}
    out.update(extra)
    return out


class Ledger:
    def __init__(self, path: str, big_amount: int = 50_000_000, allow_negative: bool = False, require_customer: bool = False):
        self.path = path
        self.big_amount = big_amount
        self.allow_negative = allow_negative
        self.require_customer = require_customer
        with self._tx(write=False) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            self._migrate(db)

    @staticmethod
    def _migrate(db):
        for table, col, decl in MIGRATIONS:
            cols = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

    @contextmanager
    def _tx(self, write: bool = True):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.execute("COMMIT")
        except BaseException:
            if write:
                try:
                    db.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise
        finally:
            db.close()

    @staticmethod
    def _audit(db, actor, action, detail=None):
        db.execute("INSERT INTO audit(ts, actor, action, detail) VALUES(?,?,?,?)",
                   (int(time.time()), actor, action, json.dumps(detail, ensure_ascii=False) if detail is not None else None))

    @staticmethod
    def _balance(db, ket_id) -> int:
        row = db.execute(
            "SELECT COALESCE(SUM(CASE WHEN kind IN ('in','reverse_out') THEN amount ELSE -amount END),0) AS b "
            "FROM entries WHERE ket_id=?", (ket_id,)).fetchone()
        return int(row["b"])

    @staticmethod
    def _role(db, user_id):
        row = db.execute("SELECT role FROM users WHERE user_id=?", (str(user_id),)).fetchone()
        return row["role"] if row else None

    def _need(self, db, actor, min_role):
        role = self._role(db, actor)
        if role is None:
            return None, _res(False, "forbidden", "Bạn chưa được cấp quyền dùng bot.")
        if ROLES[role] < ROLES[min_role]:
            return role, _res(False, "forbidden", f"Cần quyền {ROLE_NAMES[min_role]} trở lên.")
        return role, None

    def add_user(self, user_id, role, name=None, actor=None):
        """Bootstrap admin dau tien: actor=None. Sau do chi admin moi cap/doi quyen."""
        if role not in ROLES:
            raise ValueError(f"role phai la mot trong {list(ROLES)}")
        with self._tx() as db:
            if actor is not None:
                _, err = self._need(db, actor, "admin")
                if err:
                    return err
            db.execute("INSERT INTO users(user_id, role, name) VALUES(?,?,?) "
                       "ON CONFLICT(user_id) DO UPDATE SET role=excluded.role, name=COALESCE(excluded.name, name)",
                       (str(user_id), role, name))
            self._audit(db, actor, "add_user", {"user": str(user_id), "role": role})
        return _res(True, "ok", f"Đã cấp quyền {ROLE_NAMES[role]}.")

    def balance(self, ket_id) -> int:
        with self._tx(write=False) as db:
            return self._balance(db, ket_id)

    def submit_bill(self, ket_id, info: dict, actor, direction="in", image_bytes: bytes | None = None, source="image", customer_id=None):
        """Luu bill CHO xac nhan vao SQLite (chua dong den tien). Trung anh/ma GD -> tra bill cu."""
        if direction not in ("in", "out"):
            raise ValueError("direction phai la 'in' hoac 'out'")
        h = image_hash(image_bytes) if image_bytes else None
        amount = info.get("amount")
        amount = int(amount) if amount else None
        txn = info.get("txn")
        with self._tx() as db:
            _, err = self._need(db, actor, "nhan_vien")
            if err:
                return err
            dup = None
            if h:
                dup = db.execute("SELECT id, status FROM bills WHERE ket_id=? AND direction=? AND image_hash=? AND status!='rejected'",
                                 (ket_id, direction, h)).fetchone()
            if not dup and txn:
                dup = db.execute("SELECT id, status FROM bills WHERE ket_id=? AND direction=? AND txn=? AND status!='rejected'",
                                 (ket_id, direction, txn)).fetchone()
            if dup:
                return _res(False, "duplicate", f"Bill này đã gửi rồi (#{dup['id']}, {self._status_vi(dup['status'])}).",
                            bill_id=dup["id"])
            if customer_id is not None and not db.execute("SELECT 1 FROM customers WHERE id=? AND ket_id=?", (customer_id, ket_id)).fetchone():
                return _res(False, "customer_not_found", f"Không có người #{customer_id} trong két này.")
            cur = db.execute(
                "INSERT INTO bills(ket_id,direction,source,status,amount,account,bank,content,name,txn,trust,image_hash,info_json,created_by,created_at,customer_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ket_id, direction, source, "pending", amount, info.get("account"),
                 info.get("bank_name") or info.get("bank"), info.get("content"), info.get("name"), txn,
                 info.get("trust"), h, json.dumps(info, ensure_ascii=False, default=str), str(actor), int(time.time()), customer_id))
            bill_id = cur.lastrowid
            self._audit(db, actor, "submit_bill", {"bill": bill_id, "direction": direction, "amount": amount, "trust": info.get("trust")})
        what = "tiền vào" if direction == "in" else "tiền ra"
        if not amount:
            return _res(True, "pending_no_amount", f"Đã lưu bill #{bill_id} ({what}) nhưng chưa đọc được số tiền, cần nhập tay.", bill_id=bill_id)
        return _res(True, "pending", f"Bill #{bill_id} ({what}) {vnd(amount)} đang chờ xác nhận.", bill_id=bill_id)

    def create_manual(self, ket_id, direction, amount, note, actor):
        """Phieu thu/chi nhap tay: van phai bam xac nhan/xuat bill moi dong den tien."""
        amount = int(amount) if amount else 0
        if amount <= 0:
            return _res(False, "no_amount", "Số tiền không hợp lệ.")
        return self.submit_bill(ket_id, {"amount": amount, "content": note}, actor, direction=direction, source="manual")

    @staticmethod
    def _status_vi(status):
        return {"pending": "chờ xác nhận", "confirmed": "đã cộng két", "exported": "đã trừ két", "rejected": "đã hủy"}[status]

    def _settle(self, bill_id, actor, direction, kind, status_after, verb):
        with self._tx() as db:
            role, err = self._need(db, actor, "quan_tri")
            if err:
                return err
            b = db.execute("SELECT * FROM bills WHERE id=?", (bill_id,)).fetchone()
            if not b:
                return _res(False, "not_found", f"Không có bill #{bill_id}.")
            if b["direction"] != direction:
                right = "Xuất bill" if b["direction"] == "out" else "Xác nhận"
                return _res(False, "wrong_direction", f"Bill #{bill_id} là tiền {'ra' if b['direction']=='out' else 'vào'}, hãy dùng nút {right}.",
                            bill_id=bill_id)
            if b["status"] == status_after:
                return _res(True, "already_done", f"Bill #{bill_id} đã {verb} trước đó, không {verb} lần nữa.",
                            bill_id=bill_id, balance=self._balance(db, b["ket_id"]))
            if b["status"] != "pending":
                return _res(False, "wrong_state", f"Bill #{bill_id} đang {self._status_vi(b['status'])}, không thể {verb}.", bill_id=bill_id)
            if not b["amount"]:
                return _res(False, "no_amount", f"Bill #{bill_id} chưa có số tiền, không thể {verb}.", bill_id=bill_id)
            if b["amount"] >= self.big_amount and ROLES[role] < ROLES["admin"]:
                return _res(False, "big_amount_admin_only", f"Bill {vnd(b['amount'])} lớn, cần Admin {verb}.", bill_id=bill_id)
            bal = self._balance(db, b["ket_id"])
            if direction == "out" and not self.allow_negative and bal < b["amount"]:
                return _res(False, "insufficient", f"Két chỉ còn {vnd(bal)}, không đủ trừ {vnd(b['amount'])}.",
                            bill_id=bill_id, balance=bal)
            fee, bp, fixed, who = 0, 0, 0, None
            if b["customer_id"] is None:
                if self.require_customer:
                    return _res(False, "no_customer", f"Bill #{bill_id} chưa gán người nên chưa tính được phí. Hãy gán người trước.", bill_id=bill_id)
            else:
                c = db.execute("SELECT * FROM customers WHERE id=?", (b["customer_id"],)).fetchone()
                bp, fixed, who = c[f"fee_{direction}_bp"], c[f"fee_{direction}_fixed"], c["name"]
                fee = calc_fee(b["amount"], bp, fixed)
                if fee > b["amount"]:
                    return _res(False, "fee_too_high", f"Phí {vnd(fee)} lớn hơn số tiền {vnd(b['amount'])}, kiểm tra lại mức phí của {who}.", bill_id=bill_id)
            cur = db.execute("INSERT INTO entries(ket_id,bill_id,kind,amount,note,actor,created_at) VALUES(?,?,?,?,?,?,?)",
                             (b["ket_id"], bill_id, kind, b["amount"], b["content"], str(actor), int(time.time())))
            db.execute("UPDATE bills SET status=?, decided_by=?, decided_at=?, fee=?, fee_bp=?, fee_fixed=? WHERE id=? AND status='pending'",
                       (status_after, str(actor), int(time.time()), fee, bp, fixed, bill_id))
            self._audit(db, actor, f"{verb}_bill", {"bill": bill_id, "amount": b["amount"], "fee": fee, "customer": who, "trust": b["trust"], "entry": cur.lastrowid})
            new_bal = self._balance(db, b["ket_id"])
        sign = "+" if direction == "in" else "-"
        action = "Đã cộng két" if direction == "in" else "Đã trừ két"
        net = b["amount"] - fee if direction == "in" else b["amount"] + fee
        fee_txt = f" Phí {vnd(fee)} ({who}), còn lại {vnd(net)}." if who else (" Chưa gán người nên phí 0." if not self.require_customer else "")
        return _res(True, "ok", f"{action} {sign}{vnd(b['amount'])}.{fee_txt} Số dư: {vnd(new_bal)}.",
                    bill_id=bill_id, entry_id=cur.lastrowid, balance=new_bal, fee=fee)

    def confirm_bill(self, bill_id, actor):
        """Xac nhan bill TIEN VAO -> cong ket ngay (1 lan)."""
        return self._settle(bill_id, actor, "in", "in", "confirmed", "xác nhận")

    def export_bill(self, bill_id, actor):
        """Xuat bill TIEN RA (khi thanh toan) -> tru ket ngay (1 lan)."""
        return self._settle(bill_id, actor, "out", "out", "exported", "xuất")

    def reject_bill(self, bill_id, actor):
        with self._tx() as db:
            _, err = self._need(db, actor, "quan_tri")
            if err:
                return err
            b = db.execute("SELECT * FROM bills WHERE id=?", (bill_id,)).fetchone()
            if not b:
                return _res(False, "not_found", f"Không có bill #{bill_id}.")
            if b["status"] == "rejected":
                return _res(True, "already_done", f"Bill #{bill_id} đã hủy trước đó.", bill_id=bill_id)
            if b["status"] != "pending":
                return _res(False, "wrong_state", f"Bill #{bill_id} {self._status_vi(b['status'])}, không hủy được. Dùng hoàn tác (Admin).", bill_id=bill_id)
            db.execute("UPDATE bills SET status='rejected', decided_by=?, decided_at=? WHERE id=?",
                       (str(actor), int(time.time()), bill_id))
            self._audit(db, actor, "reject_bill", {"bill": bill_id})
        return _res(True, "ok", f"Đã hủy bill #{bill_id}.", bill_id=bill_id)

    def reverse_entry(self, entry_id, actor):
        """Hoan tac mot dong so quy bang dong doi ung (chi Admin). Khong xoa/sua dong cu."""
        with self._tx() as db:
            _, err = self._need(db, actor, "admin")
            if err:
                return err
            e = db.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
            if not e:
                return _res(False, "not_found", f"Không có giao dịch #{entry_id}.")
            if e["kind"].startswith("reverse"):
                return _res(False, "wrong_state", "Không hoàn tác một giao dịch hoàn tác.")
            if db.execute("SELECT 1 FROM entries WHERE reverses=?", (entry_id,)).fetchone():
                return _res(True, "already_done", f"Giao dịch #{entry_id} đã hoàn tác trước đó.", balance=self._balance(db, e["ket_id"]))
            kind = "reverse_in" if e["kind"] == "in" else "reverse_out"
            if kind == "reverse_in" and not self.allow_negative and self._balance(db, e["ket_id"]) < e["amount"]:
                return _res(False, "insufficient", "Két không đủ để hoàn tác khoản thu này.", balance=self._balance(db, e["ket_id"]))
            cur = db.execute("INSERT INTO entries(ket_id,bill_id,kind,amount,note,actor,created_at,reverses) VALUES(?,?,?,?,?,?,?,?)",
                             (e["ket_id"], None, kind, e["amount"], f"hoàn tác #{entry_id}", str(actor), int(time.time()), entry_id))
            self._audit(db, actor, "reverse_entry", {"entry": entry_id, "new": cur.lastrowid})
            new_bal = self._balance(db, e["ket_id"])
        return _res(True, "ok", f"Đã hoàn tác #{entry_id}. Số dư: {vnd(new_bal)}.", entry_id=cur.lastrowid, balance=new_bal)

    def history(self, ket_id, limit=10):
        with self._tx(write=False) as db:
            rows = db.execute("SELECT id, kind, amount, note, actor, created_at, bill_id FROM entries WHERE ket_id=? ORDER BY id DESC LIMIT ?",
                              (ket_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def pending(self, ket_id):
        with self._tx(write=False) as db:
            rows = db.execute("SELECT id, direction, amount, account, bank, content, trust FROM bills WHERE ket_id=? AND status='pending' ORDER BY id",
                              (ket_id,)).fetchall()
        return [dict(r) for r in rows]

    # ---- Nguoi (khach) va muc phi rieng ------------------------------------------------------
    def add_customer(self, ket_id, name, fee_in_pct=0, fee_in_fixed=0, fee_out_pct=0, fee_out_fixed=0, actor=None):
        """Them nguoi voi muc phi rieng (% toi da 2 so thap phan + phi co dinh), tach chieu vao/ra."""
        name = (name or "").strip()
        if not name:
            return _res(False, "bad_name", "Tên không được để trống.")
        try:
            vals = (pct_to_bp(fee_in_pct), int(fee_in_fixed), pct_to_bp(fee_out_pct), int(fee_out_fixed))
            if min(vals) < 0:
                raise ValueError
        except (ValueError, ArithmeticError):
            return _res(False, "bad_fee", "Mức phí không hợp lệ (phần trăm 0-100, phí cố định ≥ 0).")
        with self._tx() as db:
            _, err = self._need(db, actor, "quan_tri")
            if err:
                return err
            if db.execute("SELECT 1 FROM customers WHERE ket_id=? AND name=?", (ket_id, name)).fetchone():
                return _res(False, "duplicate", f"Đã có người tên {name}.")
            cur = db.execute("INSERT INTO customers(ket_id,name,fee_in_bp,fee_in_fixed,fee_out_bp,fee_out_fixed) VALUES(?,?,?,?,?,?)",
                             (ket_id, name, vals[0], vals[1], vals[2], vals[3]))
            self._audit(db, actor, "add_customer", {"id": cur.lastrowid, "name": name, "fee": vals})
        return _res(True, "ok", f"Đã thêm {name} (#{cur.lastrowid}).", customer_id=cur.lastrowid)

    def set_customer_fee(self, customer_id, actor, fee_in_pct=None, fee_in_fixed=None, fee_out_pct=None, fee_out_fixed=None):
        """Doi muc phi chi ap dung cho bill SAU NAY; bill da xac nhan giu nguyen phi da chot."""
        with self._tx() as db:
            _, err = self._need(db, actor, "quan_tri")
            if err:
                return err
            c = db.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
            if not c:
                return _res(False, "customer_not_found", f"Không có người #{customer_id}.")
            try:
                new = {
                    "fee_in_bp": c["fee_in_bp"] if fee_in_pct is None else pct_to_bp(fee_in_pct),
                    "fee_in_fixed": c["fee_in_fixed"] if fee_in_fixed is None else int(fee_in_fixed),
                    "fee_out_bp": c["fee_out_bp"] if fee_out_pct is None else pct_to_bp(fee_out_pct),
                    "fee_out_fixed": c["fee_out_fixed"] if fee_out_fixed is None else int(fee_out_fixed),
                }
                if min(new.values()) < 0:
                    raise ValueError
            except (ValueError, ArithmeticError):
                return _res(False, "bad_fee", "Mức phí không hợp lệ.")
            db.execute("UPDATE customers SET fee_in_bp=?, fee_in_fixed=?, fee_out_bp=?, fee_out_fixed=? WHERE id=?",
                       (new["fee_in_bp"], new["fee_in_fixed"], new["fee_out_bp"], new["fee_out_fixed"], customer_id))
            self._audit(db, actor, "set_customer_fee", {"id": customer_id, "old": dict(c), "new": new})
        return _res(True, "ok", f"Đã đổi mức phí của {c['name']}, áp dụng từ bill sau.")

    def list_customers(self, ket_id):
        with self._tx(write=False) as db:
            return [dict(r) for r in db.execute("SELECT * FROM customers WHERE ket_id=? ORDER BY name", (ket_id,))]

    def assign_customer(self, bill_id, customer_id, actor):
        """Gan nguoi cho bill CHO xac nhan (de tinh phi). Bill da xac nhan thi khong doi duoc."""
        with self._tx() as db:
            _, err = self._need(db, actor, "quan_tri")
            if err:
                return err
            b = db.execute("SELECT * FROM bills WHERE id=?", (bill_id,)).fetchone()
            if not b:
                return _res(False, "not_found", f"Không có bill #{bill_id}.")
            if b["status"] != "pending":
                return _res(False, "wrong_state", f"Bill #{bill_id} {self._status_vi(b['status'])}, phí đã chốt, không đổi người được.", bill_id=bill_id)
            c = db.execute("SELECT * FROM customers WHERE id=? AND ket_id=?", (customer_id, b["ket_id"])).fetchone()
            if not c:
                return _res(False, "customer_not_found", f"Không có người #{customer_id} trong két này.", bill_id=bill_id)
            db.execute("UPDATE bills SET customer_id=? WHERE id=?", (customer_id, bill_id))
            self._audit(db, actor, "assign_customer", {"bill": bill_id, "customer": c["name"]})
        d = b["direction"]
        bp, fixed = c[f"fee_{d}_bp"], c[f"fee_{d}_fixed"]
        fee = calc_fee(b["amount"], bp, fixed) if b["amount"] else None
        extra = f" Phí dự kiến {vnd(fee)}." if fee is not None else ""
        return _res(True, "ok", f"Đã gán bill #{bill_id} cho {c['name']}.{extra}", bill_id=bill_id)

    # ---- Chot so va bao cao ---------------------------------------------------------------------
    def _period(self, db, ket_id, closing_id):
        where, args = ("closing_id=?", (closing_id,)) if closing_id else ("closing_id IS NULL", ())
        entries = db.execute(f"SELECT * FROM entries WHERE ket_id=? AND {where} ORDER BY id", (ket_id,) + args).fetchall()
        rows = []
        tin = tout = fin = fout = 0
        for n, e in enumerate(entries, 1):
            reverse = e["kind"].startswith("reverse")
            bill_id = e["bill_id"]
            if reverse:
                orig = db.execute("SELECT * FROM entries WHERE id=?", (e["reverses"],)).fetchone()
                bill_id = orig["bill_id"] if orig else None
            b = db.execute("SELECT * FROM bills WHERE id=?", (bill_id,)).fetchone() if bill_id else None
            fee = (b["fee"] or 0) if b else 0
            direction = "in" if e["kind"] in ("in", "reverse_in") else "out"
            sign = -1 if reverse else 1
            if direction == "in":
                tin += sign * e["amount"]
                fin += sign * fee
                net = e["amount"] - fee
            else:
                tout += sign * e["amount"]
                fout += sign * fee
                net = e["amount"] + fee
            cname = None
            if b and b["customer_id"]:
                cname = db.execute("SELECT name FROM customers WHERE id=?", (b["customer_id"],)).fetchone()["name"]
            rows.append({
                "stt": n, "time": e["created_at"], "bill_id": bill_id, "entry_id": e["id"],
                "loai": ("Hoàn tác " if reverse else "") + ("vào" if direction == "in" else "ra"),
                "nguoi": cname, "account": b["account"] if b else None, "bank": b["bank"] if b else None,
                "content": (b["content"] if b else None) or e["note"],
                "amount": sign * e["amount"], "fee": sign * fee, "net": sign * net, "actor": e["actor"],
            })
        return rows, {"total_in": tin, "total_out": tout, "fee_in": fin, "fee_out": fout}

    def _opening(self, db, ket_id):
        r = db.execute("SELECT closing_balance FROM closings WHERE ket_id=? ORDER BY id DESC LIMIT 1", (ket_id,)).fetchone()
        return int(r["closing_balance"]) if r else 0

    @staticmethod
    def _summarize(tot, opening, closing):
        position = "DƯƠNG" if closing > 0 else ("ÂM" if closing < 0 else "CÂN BẰNG")
        return {
            **tot,
            "net_in": tot["total_in"] - tot["fee_in"], "net_out": tot["total_out"] + tot["fee_out"],
            "fee_income": tot["fee_in"] + tot["fee_out"],
            "opening": opening, "closing": closing, "change": tot["total_in"] - tot["total_out"],
            "position": position, "consistent": opening + tot["total_in"] - tot["total_out"] == closing,
        }

    def report(self, ket_id, closing_id=None):
        """Bao cao tung bill + tong. closing_id=None -> ky dang mo (xem truoc, chua chot)."""
        with self._tx(write=False) as db:
            if closing_id:
                c = db.execute("SELECT * FROM closings WHERE id=? AND ket_id=?", (closing_id, ket_id)).fetchone()
                if not c:
                    return None
                opening, closing = int(c["opening_balance"]), int(c["closing_balance"])
            else:
                c = None
                opening, closing = self._opening(db, ket_id), self._balance(db, ket_id)
            rows, tot = self._period(db, ket_id, closing_id)
        return {"ket_id": ket_id, "closing_id": closing_id, "closed_at": c["closed_at"] if c else None,
                "note": c["note"] if c else None, "rows": rows, "summary": self._summarize(tot, opening, closing)}

    def list_closings(self, ket_id):
        with self._tx(write=False) as db:
            return [dict(r) for r in db.execute("SELECT * FROM closings WHERE ket_id=? ORDER BY id", (ket_id,))]

    def close_period(self, ket_id, actor, note=None):
        """Chot so: khoa cac giao dich dang mo vao mot ky, ghi so du dau/cuoi ky. Sai thi dieu chinh o ky sau."""
        with self._tx() as db:
            _, err = self._need(db, actor, "quan_tri")
            if err:
                return err
            rows, tot = self._period(db, ket_id, None)
            if not rows:
                return _res(False, "nothing_to_close", "Chưa có giao dịch mới để chốt sổ.")
            opening, closing = self._opening(db, ket_id), self._balance(db, ket_id)
            summary = self._summarize(tot, opening, closing)
            if not summary["consistent"]:
                return _res(False, "inconsistent", "Số dư không khớp tổng giao dịch, không chốt. Cần kiểm tra dữ liệu.", balance=closing)
            cur = db.execute("INSERT INTO closings(ket_id,closed_by,closed_at,opening_balance,closing_balance,note) VALUES(?,?,?,?,?,?)",
                             (ket_id, str(actor), int(time.time()), opening, closing, note))
            db.execute("UPDATE entries SET closing_id=? WHERE ket_id=? AND closing_id IS NULL", (cur.lastrowid, ket_id))
            pending = db.execute("SELECT COUNT(*) AS n FROM bills WHERE ket_id=? AND status='pending'", (ket_id,)).fetchone()["n"]
            self._audit(db, actor, "close_period", {"closing": cur.lastrowid, **summary, "pending": pending})
        warn = f" Còn {pending} bill chờ, chuyển sang kỳ sau." if pending else ""
        return _res(True, "ok", f"Đã chốt sổ #{cur.lastrowid}. {summary_text(summary)}{warn}",
                    balance=closing, closing_id=cur.lastrowid, summary=summary)


def summary_text(s: dict) -> str:
    sign = {"DƯƠNG": "+", "ÂM": "-", "CÂN BẰNG": ""}[s["position"]]
    return (f"Vào {vnd(s['total_in'])}, ra {vnd(s['total_out'])}, phí {vnd(s['fee_income'])}. "
            f"Đầu kỳ {vnd(s['opening'])}, cuối kỳ {sign}{vnd(abs(s['closing']))} ({s['position']}).")


CSV_HEADER = ["STT", "Thời gian", "Mã bill", "Mã GD sổ", "Loại", "Người", "STK", "Ngân hàng", "Nội dung",
              "Số tiền (không phí)", "Phí", "Số còn lại (sau phí)", "Người thao tác"]


def export_csv(report: dict, path: str) -> str:
    """Xuat bao cao ra CSV (UTF-8 co BOM, mo thang bang Excel/Google Sheets)."""
    import csv

    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_HEADER)
        for r in report["rows"]:
            w.writerow([r["stt"], time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(r["time"])), r["bill_id"] or "", r["entry_id"],
                        r["loai"], r["nguoi"] or "", r["account"] or "", r["bank"] or "", r["content"] or "",
                        r["amount"], r["fee"], r["net"], r["actor"]])
        s = report["summary"]
        w.writerow([])
        for label, key in (("Số dư đầu kỳ", "opening"), ("Tổng vào (không phí)", "total_in"), ("Tổng ra (không phí)", "total_out"),
                           ("Phí thu từ tiền vào", "fee_in"), ("Phí thu từ tiền ra", "fee_out"), ("Tổng phí", "fee_income"),
                           ("Còn lại từ tiền vào (sau phí)", "net_in"), ("Ra sau phí", "net_out"), ("Số dư cuối kỳ", "closing")):
            w.writerow(["", "", "", "", "", "", "", "", label, s[key]])
        w.writerow(["", "", "", "", "", "", "", "", "Kết quả", s["position"]])
    return path
