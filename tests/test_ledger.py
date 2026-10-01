import os
import sqlite3
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ledger import Ledger, vnd  # noqa: E402
from nlu import understand  # noqa: E402

KET = "chat1"
BILL_IN = {"amount": 1250000, "account": "0123456789", "bank": "VCB", "bank_name": "Vietcombank",
           "content": "tien thue phong", "txn": "FT26274ABCDE", "trust": "high"}


@pytest.fixture
def lg(tmp_path):
    ledger = Ledger(str(tmp_path / "ket.db"), big_amount=50_000_000)
    ledger.add_user("1", "admin", "Aech")
    ledger.add_user("2", "quan_tri", "Quan tri")
    ledger.add_user("3", "nhan_vien", "NV")
    return ledger


def _in(lg, amount=1250000, txn="FT1", img=b"img1", actor="3"):
    info = dict(BILL_IN, amount=amount, txn=txn)
    return lg.submit_bill(KET, info, actor, "in", image_bytes=img)


def _out(lg, amount=500000, txn="OUT1", img=b"out1", actor="3"):
    info = dict(BILL_IN, amount=amount, txn=txn)
    return lg.submit_bill(KET, info, actor, "out", image_bytes=img)


def test_confirm_credits_exactly_once(lg):
    b = _in(lg)
    assert b["code"] == "pending" and lg.balance(KET) == 0
    r = lg.confirm_bill(b["bill_id"], "2")
    assert r["ok"] and r["balance"] == 1250000 and "+1.250.000đ" in r["message"]
    again = lg.confirm_bill(b["bill_id"], "1")
    assert again["code"] == "already_done" and lg.balance(KET) == 1250000
    assert len(lg.history(KET)) == 1


def test_export_debits_exactly_once(lg):
    lg.confirm_bill(_in(lg)["bill_id"], "2")
    o = _out(lg, 500000)
    r = lg.export_bill(o["bill_id"], "2")
    assert r["ok"] and r["balance"] == 750000 and "-500.000đ" in r["message"]
    assert lg.export_bill(o["bill_id"], "2")["code"] == "already_done"
    assert lg.balance(KET) == 750000


def test_export_refused_when_not_enough_money(lg):
    lg.confirm_bill(_in(lg, 100000)["bill_id"], "2")
    o = _out(lg, 500000)
    r = lg.export_bill(o["bill_id"], "2")
    assert not r["ok"] and r["code"] == "insufficient" and lg.balance(KET) == 100000
    assert lg.pending(KET)[0]["id"] == o["bill_id"]


def test_negative_allowed_only_when_configured(tmp_path):
    lg2 = Ledger(str(tmp_path / "n.db"), allow_negative=True)
    lg2.add_user("1", "admin")
    o = lg2.submit_bill(KET, dict(BILL_IN, amount=300000), "1", "out", image_bytes=b"x")
    assert lg2.export_bill(o["bill_id"], "1")["balance"] == -300000


def test_wrong_button_for_direction(lg):
    i, o = _in(lg), _out(lg)
    assert lg.export_bill(i["bill_id"], "2")["code"] == "wrong_direction"
    assert lg.confirm_bill(o["bill_id"], "2")["code"] == "wrong_direction"
    assert lg.balance(KET) == 0


def test_permissions(lg):
    b = _in(lg)
    assert lg.confirm_bill(b["bill_id"], "3")["code"] == "forbidden"
    assert lg.confirm_bill(b["bill_id"], "999")["code"] == "forbidden"
    assert lg.submit_bill(KET, BILL_IN, "999", "in")["code"] == "forbidden"
    assert lg.balance(KET) == 0
    assert lg.add_user("9", "admin", actor="2")["code"] == "forbidden"
    assert lg.add_user("9", "quan_tri", actor="1")["ok"]


def test_big_amount_needs_admin(lg):
    b = _in(lg, 80_000_000, txn="BIG", img=b"big")
    assert lg.confirm_bill(b["bill_id"], "2")["code"] == "big_amount_admin_only"
    assert lg.balance(KET) == 0
    assert lg.confirm_bill(b["bill_id"], "1")["balance"] == 80_000_000


def test_duplicate_image_and_txn_not_double_counted(lg):
    a = _in(lg, txn="FT-A", img=b"same")
    dup_img = _in(lg, txn="FT-B", img=b"same")
    assert dup_img["code"] == "duplicate" and dup_img["bill_id"] == a["bill_id"]
    dup_txn = _in(lg, txn="FT-A", img=b"other")
    assert dup_txn["code"] == "duplicate"
    lg.confirm_bill(a["bill_id"], "2")
    assert _in(lg, txn="FT-A", img=b"third")["code"] == "duplicate"
    assert lg.balance(KET) == 1250000


def test_rejected_bill_cannot_be_confirmed_but_can_be_resubmitted(lg):
    b = _in(lg)
    assert lg.reject_bill(b["bill_id"], "2")["ok"]
    assert lg.confirm_bill(b["bill_id"], "2")["code"] == "wrong_state"
    assert lg.balance(KET) == 0
    again = _in(lg)
    assert again["ok"] and again["bill_id"] != b["bill_id"]


def test_confirmed_bill_cannot_be_rejected(lg):
    b = _in(lg)
    lg.confirm_bill(b["bill_id"], "2")
    assert lg.reject_bill(b["bill_id"], "2")["code"] == "wrong_state"
    assert lg.balance(KET) == 1250000


def test_bill_without_amount_cannot_settle(lg):
    b = lg.submit_bill(KET, {"account": "123456", "txn": "NOAMT"}, "3", "in", image_bytes=b"na")
    assert b["code"] == "pending_no_amount"
    assert lg.confirm_bill(b["bill_id"], "2")["code"] == "no_amount"
    assert lg.balance(KET) == 0


def test_manual_entries_still_need_confirm(lg):
    m = lg.create_manual(KET, "in", 500000, "khach A tra", "3")
    assert lg.balance(KET) == 0
    assert lg.confirm_bill(m["bill_id"], "2")["balance"] == 500000
    assert lg.create_manual(KET, "out", 0, "x", "3")["code"] == "no_amount"


def test_reverse_is_admin_only_idempotent_and_keeps_history(lg):
    r = lg.confirm_bill(_in(lg)["bill_id"], "2")
    assert lg.reverse_entry(r["entry_id"], "2")["code"] == "forbidden"
    rev = lg.reverse_entry(r["entry_id"], "1")
    assert rev["ok"] and rev["balance"] == 0
    assert lg.reverse_entry(r["entry_id"], "1")["code"] == "already_done"
    assert lg.balance(KET) == 0 and len(lg.history(KET)) == 2
    assert lg.reverse_entry(rev["entry_id"], "1")["code"] == "wrong_state"


def test_data_survives_restart(tmp_path):
    path = str(tmp_path / "persist.db")
    a = Ledger(path)
    a.add_user("1", "admin")
    pend = a.submit_bill(KET, BILL_IN, "1", "in", image_bytes=b"p")
    b_id = pend["bill_id"]
    a.confirm_bill(b_id, "1")
    pend2 = a.submit_bill(KET, dict(BILL_IN, txn="P2", amount=200000), "1", "in", image_bytes=b"p2")
    del a
    reopened = Ledger(path)
    assert reopened.balance(KET) == 1250000
    assert [p["id"] for p in reopened.pending(KET)] == [pend2["bill_id"]]
    assert reopened.confirm_bill(b_id, "1")["code"] == "already_done"


def test_concurrent_confirms_credit_once(lg):
    b = _in(lg)
    results = []

    def go(actor):
        results.append(lg.confirm_bill(b["bill_id"], actor))

    threads = [threading.Thread(target=go, args=("2" if i % 2 else "1",)) for i in range(16)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert lg.balance(KET) == 1250000
    assert sum(1 for r in results if r["code"] == "ok") == 1
    assert all(r["ok"] for r in results)


def test_concurrent_exports_cannot_overdraw(lg):
    lg.confirm_bill(_in(lg, 1000000)["bill_id"], "2")
    outs = [_out(lg, 600000, txn=f"O{i}", img=f"o{i}".encode())["bill_id"] for i in range(5)]
    results = []
    threads = [threading.Thread(target=lambda i=i: results.append(lg.export_bill(i, "2"))) for i in outs]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert lg.balance(KET) == 400000
    assert sum(1 for r in results if r["code"] == "ok") == 1
    assert sum(1 for r in results if r["code"] == "insufficient") == 4


def test_database_rejects_double_entry_even_if_code_is_bypassed(lg):
    r = lg.confirm_bill(_in(lg)["bill_id"], "2")
    db = sqlite3.connect(lg.path)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO entries(ket_id,bill_id,kind,amount,actor,created_at) VALUES(?,?,?,?,?,?)",
                   (KET, 1, "in", 1250000, "x", 0))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO entries(ket_id,bill_id,kind,amount,actor,created_at) VALUES(?,?,?,?,?,?)",
                   (KET, None, "in", -5, "x", 0))
    db.close()
    assert lg.balance(KET) == 1250000 and r["ok"]


def test_kets_are_isolated(lg):
    b = _in(lg)
    lg.confirm_bill(b["bill_id"], "2")
    assert lg.balance("other-chat") == 0


def test_audit_records_actions(lg):
    b = _in(lg)
    lg.confirm_bill(b["bill_id"], "2")
    db = sqlite3.connect(lg.path)
    actions = [r[0] for r in db.execute("SELECT action FROM audit ORDER BY id")]
    db.close()
    assert "submit_bill" in actions and "xác nhận_bill" in actions


def test_vnd_format():
    assert vnd(1250000) == "1.250.000đ" and vnd(0) == "0đ"


@pytest.mark.parametrize(
    "text,intent,bill_id,amount",
    [
        ("xác nhận #12", "confirm", 12, None),
        ("Xác nhận 12", "confirm", 12, None),
        ("ok", "confirm", None, None),
        ("xuất bill 7", "export", 7, None),
        ("xuat bill", "export", None, None),
        ("đã chuyển khoản", "export", None, None),
        ("xuất tiền 500k", "manual_out", None, 500000),
        ("chi 1tr2 tiền điện", "manual_out", None, 1200000),
        ("thu 500.000 khách A trả", "manual_in", None, 500000),
        ("nhận tiền", "confirm", None, None),
        ("@NinjaaBot số dư", "balance", None, None),
        ("két còn bao nhiêu?", "balance", None, None),
        ("lịch sử", "history", None, None),
        ("hủy bill 5", "reject", 5, None),
        ("hoàn tác #3", "reverse", 3, None),
        ("thu", "unknown", None, None),
        ("hôm nay trời đẹp", "unknown", None, None),
        ("", "unknown", None, None),
    ],
)
def test_nlu_understands_vietnamese_admin_commands(text, intent, bill_id, amount):
    r = understand(text)
    assert (r["intent"], r["bill_id"], r["amount"]) == (intent, bill_id, amount)


def test_nlu_note_extraction():
    assert understand("chi 1tr2 tiền điện")["note"] == "tiền điện"
    assert understand("thu 500.000 khách A trả")["note"] == "khách A trả"


# ---------------- phi theo tung nguoi, chot so, bao cao ----------------
import csv  # noqa: E402

from ledger import calc_fee, export_csv, pct_to_bp  # noqa: E402


@pytest.mark.parametrize(
    "amount,bp,fixed,expected",
    [(10_000_000, 150, 0, 150_000), (1_000_000, 100, 5_000, 15_000), (333, 150, 0, 5), (100, 50, 0, 1), (99, 50, 0, 0), (500_000, 0, 0, 0)],
)
def test_calc_fee_integer_rounding(amount, bp, fixed, expected):
    assert calc_fee(amount, bp, fixed) == expected


def test_pct_to_bp():
    assert pct_to_bp("1.5") == 150 and pct_to_bp(2) == 200 and pct_to_bp(0.25) == 25
    for bad in (-1, 101, "1.234"):
        with pytest.raises(ValueError):
            pct_to_bp(bad)


def _people(lg):
    a = lg.add_customer(KET, "Nguyen A", fee_in_pct=1.5, fee_out_pct=0.5, fee_out_fixed=2000, actor="2")["customer_id"]
    b = lg.add_customer(KET, "Tran B", fee_in_pct=3, actor="2")["customer_id"]
    return a, b


def test_each_person_has_their_own_fee(lg):
    a, b = _people(lg)
    r1 = _in(lg, 10_000_000, txn="A1", img=b"a1")
    r2 = _in(lg, 10_000_000, txn="B1", img=b"b1")
    assert lg.assign_customer(r1["bill_id"], a, "2")["ok"] and lg.assign_customer(r2["bill_id"], b, "2")["ok"]
    x = lg.confirm_bill(r1["bill_id"], "2")
    y = lg.confirm_bill(r2["bill_id"], "2")
    assert (x["fee"], y["fee"]) == (150_000, 300_000)
    assert "Phí 150.000đ (Nguyen A)" in x["message"] and "còn lại 9.850.000đ" in x["message"]
    assert lg.balance(KET) == 20_000_000


def test_out_direction_uses_out_fee(lg):
    a, _ = _people(lg)
    lg.confirm_bill(_in(lg, 5_000_000, txn="I", img=b"i")["bill_id"], "2")
    o = _out(lg, 1_000_000, txn="O", img=b"o")
    lg.assign_customer(o["bill_id"], a, "2")
    r = lg.export_bill(o["bill_id"], "2")
    assert r["fee"] == 7000 and lg.balance(KET) == 4_000_000


def test_fee_is_frozen_at_confirm_when_rate_changes_later(lg):
    a, _ = _people(lg)
    b1 = _in(lg, 10_000_000, txn="F1", img=b"f1")
    lg.assign_customer(b1["bill_id"], a, "2")
    lg.confirm_bill(b1["bill_id"], "2")
    assert lg.set_customer_fee(a, "2", fee_in_pct=5)["ok"]
    b2 = _in(lg, 10_000_000, txn="F2", img=b"f2")
    lg.assign_customer(b2["bill_id"], a, "2")
    assert lg.confirm_bill(b2["bill_id"], "2")["fee"] == 500_000
    rep = lg.report(KET)
    assert [r["fee"] for r in rep["rows"]] == [150_000, 500_000]


def test_cannot_reassign_after_confirm_and_wrong_ket_customer(lg):
    a, b = _people(lg)
    r = _in(lg, txn="R1", img=b"r1")
    lg.assign_customer(r["bill_id"], a, "2")
    lg.confirm_bill(r["bill_id"], "2")
    assert lg.assign_customer(r["bill_id"], b, "2")["code"] == "wrong_state"
    other = lg.add_customer("chat-khac", "Nguoi Khac", actor="2")["customer_id"]
    r2 = _in(lg, txn="R2", img=b"r2")
    assert lg.assign_customer(r2["bill_id"], other, "2")["code"] == "customer_not_found"
    assert lg.submit_bill(KET, BILL_IN, "3", "in", image_bytes=b"zz", customer_id=other)["code"] == "customer_not_found"


def test_customer_permissions_and_validation(lg):
    assert lg.add_customer(KET, "X", actor="3")["code"] == "forbidden"
    assert lg.add_customer(KET, "  ", actor="2")["code"] == "bad_name"
    assert lg.add_customer(KET, "X", fee_in_pct=150, actor="2")["code"] == "bad_fee"
    assert lg.add_customer(KET, "X", actor="2")["ok"] and lg.add_customer(KET, "X", actor="2")["code"] == "duplicate"


def test_require_customer_blocks_unassigned_bill(tmp_path):
    lg2 = Ledger(str(tmp_path / "rc.db"), require_customer=True)
    lg2.add_user("2", "quan_tri")
    b = lg2.submit_bill(KET, BILL_IN, "2", "in", image_bytes=b"q")
    r = lg2.confirm_bill(b["bill_id"], "2")
    assert r["code"] == "no_customer" and lg2.balance(KET) == 0


def test_fee_bigger_than_amount_is_refused(lg):
    c = lg.add_customer(KET, "Phi cao", fee_in_fixed=2_000_000, actor="2")["customer_id"]
    b = _in(lg, 1_000_000, txn="H", img=b"h")
    lg.assign_customer(b["bill_id"], c, "2")
    r = lg.confirm_bill(b["bill_id"], "2")
    assert r["code"] == "fee_too_high" and lg.balance(KET) == 0


def _month(lg):
    a, b = _people(lg)
    i1 = _in(lg, 10_000_000, txn="M1", img=b"m1"); lg.assign_customer(i1["bill_id"], a, "2"); lg.confirm_bill(i1["bill_id"], "2")
    i2 = _in(lg, 4_000_000, txn="M2", img=b"m2"); lg.assign_customer(i2["bill_id"], b, "2"); lg.confirm_bill(i2["bill_id"], "2")
    o1 = _out(lg, 6_000_000, txn="M3", img=b"m3"); lg.assign_customer(o1["bill_id"], a, "2"); lg.export_bill(o1["bill_id"], "2")
    return a, b


def test_report_totals_and_position(lg):
    _month(lg)
    rep = lg.report(KET)
    s = rep["summary"]
    assert (s["total_in"], s["total_out"]) == (14_000_000, 6_000_000)
    assert (s["fee_in"], s["fee_out"], s["fee_income"]) == (150_000 + 120_000, 30_000 + 2_000, 302_000)
    assert (s["net_in"], s["net_out"]) == (14_000_000 - 270_000, 6_000_000 + 32_000)
    assert (s["opening"], s["closing"], s["change"]) == (0, 8_000_000, 8_000_000)
    assert s["position"] == "DƯƠNG" and s["consistent"]
    assert [r["nguoi"] for r in rep["rows"]] == ["Nguyen A", "Tran B", "Nguyen A"]
    assert [r["net"] for r in rep["rows"]] == [9_850_000, 3_880_000, 6_032_000]


def test_close_period_locks_and_next_period_starts_from_closing(lg):
    _month(lg)
    c = lg.close_period(KET, "2", note="thang 10")
    assert c["ok"] and c["balance"] == 8_000_000 and "DƯƠNG" in c["message"]
    assert lg.close_period(KET, "2")["code"] == "nothing_to_close"
    assert lg.report(KET)["rows"] == []
    nxt = _out(lg, 9_000_000, txn="N1", img=b"n1")
    r = lg.export_bill(nxt["bill_id"], "2")
    assert r["code"] == "insufficient"
    nxt2 = _out(lg, 3_000_000, txn="N2", img=b"n2")
    assert lg.export_bill(nxt2["bill_id"], "2")["balance"] == 5_000_000
    open_now = lg.report(KET)["summary"]
    assert (open_now["opening"], open_now["total_out"], open_now["closing"]) == (8_000_000, 3_000_000, 5_000_000)
    closed = lg.report(KET, c["closing_id"])
    assert closed["summary"]["closing"] == 8_000_000 and len(closed["rows"]) == 3 and closed["note"] == "thang 10"


def test_negative_position_after_close(tmp_path):
    lg2 = Ledger(str(tmp_path / "neg.db"), allow_negative=True)
    lg2.add_user("2", "quan_tri")
    b = lg2.submit_bill(KET, dict(BILL_IN, amount=700_000), "2", "out", image_bytes=b"n")
    lg2.export_bill(b["bill_id"], "2")
    c = lg2.close_period(KET, "2")
    assert c["summary"]["position"] == "ÂM" and "(ÂM)" in c["message"] and c["balance"] == -700_000
    nxt = lg2.report(KET)
    assert nxt["summary"]["opening"] == -700_000


def test_closing_permissions_and_pending_warning(lg):
    _month(lg)
    _in(lg, 1_000_000, txn="PEND", img=b"pend")
    assert lg.close_period(KET, "3")["code"] == "forbidden"
    c = lg.close_period(KET, "2")
    assert c["ok"] and "1 bill chờ" in c["message"]
    assert len(lg.pending(KET)) == 1


def test_reversal_after_close_goes_to_next_period_and_report_stays_consistent(lg):
    a, _ = _people(lg)
    b = _in(lg, 10_000_000, txn="RV", img=b"rv")
    lg.assign_customer(b["bill_id"], a, "2")
    entry = lg.confirm_bill(b["bill_id"], "2")["entry_id"]
    c = lg.close_period(KET, "2")
    rev = lg.reverse_entry(entry, "1")
    assert rev["ok"] and rev["balance"] == 0
    old = lg.report(KET, c["closing_id"])
    assert old["summary"]["total_in"] == 10_000_000 and old["summary"]["closing"] == 10_000_000
    cur = lg.report(KET)
    s = cur["summary"]
    assert (s["total_in"], s["fee_in"], s["opening"], s["closing"]) == (-10_000_000, -150_000, 10_000_000, 0)
    assert s["consistent"] and cur["rows"][0]["loai"] == "Hoàn tác vào" and cur["rows"][0]["fee"] == -150_000


def test_export_csv_opens_in_excel_with_vietnamese(lg, tmp_path):
    _month(lg)
    path = export_csv(lg.report(KET), str(tmp_path / "bc.csv"))
    raw = open(path, "rb").read()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(open(path, encoding="utf-8-sig")))
    assert rows[0][9:12] == ["Số tiền (không phí)", "Phí", "Số còn lại (sau phí)"]
    assert rows[1][5] == "Nguyen A" and rows[1][9] == "10000000" and rows[1][10] == "150000" and rows[1][11] == "9850000"
    tail = {r[8]: r[9] for r in rows if len(r) > 9 and r[8]}
    assert tail["Tổng phí"] == "302000" and tail["Số dư cuối kỳ"] == "8000000" and tail["Kết quả"] == "DƯƠNG"


def test_old_database_is_upgraded_without_losing_data(tmp_path):
    path = str(tmp_path / "old.db")
    db = sqlite3.connect(path)
    db.executescript("""
    CREATE TABLE users(user_id TEXT PRIMARY KEY, role TEXT NOT NULL, name TEXT);
    CREATE TABLE bills(id INTEGER PRIMARY KEY AUTOINCREMENT, ket_id TEXT NOT NULL, direction TEXT NOT NULL, source TEXT NOT NULL,
      status TEXT NOT NULL, amount INTEGER, account TEXT, bank TEXT, content TEXT, name TEXT, txn TEXT, trust TEXT, image_hash TEXT,
      info_json TEXT, created_by TEXT NOT NULL, created_at INTEGER NOT NULL, decided_by TEXT, decided_at INTEGER);
    CREATE TABLE entries(id INTEGER PRIMARY KEY AUTOINCREMENT, ket_id TEXT NOT NULL, bill_id INTEGER, kind TEXT NOT NULL,
      amount INTEGER NOT NULL, note TEXT, actor TEXT NOT NULL, created_at INTEGER NOT NULL, reverses INTEGER);
    CREATE TABLE audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, actor TEXT, action TEXT NOT NULL, detail TEXT);
    INSERT INTO users VALUES('1','admin','Aech');
    INSERT INTO bills(ket_id,direction,source,status,amount,created_by,created_at) VALUES('chat1','in','manual','confirmed',900000,'1',0);
    INSERT INTO entries(ket_id,bill_id,kind,amount,actor,created_at) VALUES('chat1',1,'in',900000,'1',0);
    """)
    db.commit(); db.close()
    lg2 = Ledger(path)
    assert lg2.balance("chat1") == 900000
    assert lg2.report("chat1")["summary"]["closing"] == 900000
    assert lg2.close_period("chat1", "1")["ok"]


def test_nlu_close_and_report_intents():
    assert understand("chốt sổ")["intent"] == "close"
    assert understand("chốt sổ hôm nay")["intent"] == "close"
    assert understand("báo cáo")["intent"] == "report"
    assert understand("xuất bảng tính")["intent"] == "report"
    assert understand("lịch sử")["intent"] == "history"
