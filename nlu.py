#!/usr/bin/env python3
"""Hieu lenh tieng Viet cua admin/quan tri bang quy tac local (khong AI, khong API).

    from nlu import understand
    understand("xác nhận #12")        -> {"intent": "confirm", "bill_id": 12, ...}
    understand("xuất bill 7")         -> {"intent": "export", "bill_id": 7, ...}
    understand("chi 1tr2 tiền điện")  -> {"intent": "manual_out", "amount": 1200000, "note": "tiền điện"}
    understand("số dư")               -> {"intent": "balance"}

Luu y: NLU chi nhan ra y dinh. Lenh dong den tien (confirm/export/manual_*/reverse) bot van phai
chay qua nut bam/phieu xac nhan va Ledger kiem tra quyen; khong tu dong tru/cong chi vi mot cau chat.
"""
from __future__ import annotations

import re

from bill_scanner import fold, normalize_amount, parse_shorthand

# (intent, cac cum tu da bo dau) - cum dai khop truoc cum ngan.
COMMANDS = [
    ("export", ["xuat bill", "xuat bil", "xuat hoa don", "da thanh toan", "thanh toan xong", "da chuyen khoan", "da chuyen", "da tra", "xuat"]),
    ("confirm", ["xac nhan", "da nhan tien", "da nhan", "nhan tien", "duyet", "dong y", "xn", "ok"]),
    ("reject", ["tu choi", "khong nhan", "huy bill", "huy", "bo qua", "bo"]),
    ("reverse", ["hoan tac", "hoan tien", "dao lai", "undo"]),
    ("balance", ["so du", "ket con bao nhieu", "con bao nhieu", "tien ket", "ket bao nhieu", "ket con", "ton quy", "quy con"]),
    ("history", ["lich su", "sao ke", "giao dich gan day", "lich su ket"]),
    ("close", ["chot so", "chot ky", "ket so", "dong so", "chot"]),
    ("report", ["bao cao", "tong ket", "thong ke", "bang tinh", "xuat bang tinh", "xuat excel", "file excel", "bang excel", "excel"]),
    ("pending", ["bill cho", "cho xac nhan", "ds cho", "danh sach cho"]),
    ("manual_in", ["them tien", "thu tien", "nhan", "thu", "cong"]),
    ("manual_out", ["tra tien", "chi tien", "xuat tien", "rut tien", "chi", "tra", "tru", "rut"]),
]
_ALL_PHRASES = sorted(((ph, intent) for intent, phrases in COMMANDS for ph in phrases), key=lambda x: -len(x[0]))
_ID_RE = re.compile(r"(?:#|bill\s*|phieu\s*|gd\s*|giao dich\s*)(\d+)", re.I)
_NUM_RE = re.compile(r"^[+-]?\d{1,3}(?:[., ]\d{3})+(?:đ|d|vnd|vnđ)?$|^[+-]?\d{4,12}(?:đ|d|vnd|vnđ)?$", re.I)


def _amount(token: str):
    short = parse_shorthand(token)
    if short:
        return short
    if _NUM_RE.match(token.strip()):
        return normalize_amount(re.sub(r"(?i)(đ|d|vnd|vnđ)$", "", token))
    return None


def _strip_mention(text: str) -> str:
    return re.sub(r"@\w+", " ", text).strip()


def understand(text: str) -> dict:
    out = {"intent": "unknown", "amount": None, "note": None, "bill_id": None, "text": text}
    raw = _strip_mention(text or "")
    if not raw:
        return out
    folded = fold(raw)
    m = _ID_RE.search(folded)
    if m:
        out["bill_id"] = int(m.group(1))
    head = re.sub(r"[^\w\s#]", " ", folded)
    head = re.sub(r"\s+", " ", head).strip()
    chosen = None
    for ph, intent in _ALL_PHRASES:
        if head == ph or head.startswith(ph + " ") or head.startswith(ph + "#"):
            chosen = (intent, ph)
            break
    if not chosen:
        return out
    intent, phrase = chosen
    out["intent"] = intent
    n_words = len(phrase.split())
    tokens = raw.split()
    rest = tokens[n_words:]
    if intent in ("manual_in", "manual_out"):
        note = []
        for tok in rest:
            amt = _amount(tok)
            if amt and out["amount"] is None:
                out["amount"] = amt
            elif not _ID_RE.fullmatch(tok):
                note.append(tok)
        out["note"] = " ".join(note) or None
        if out["amount"] is None:
            out["intent"] = "unknown"
    elif intent in ("confirm", "export", "reject", "reverse"):
        if out["bill_id"] is None:
            for tok in rest:
                m2 = re.fullmatch(r"#?(\d{1,5})", tok)
                if m2:
                    out["bill_id"] = int(m2.group(1))
                    break
        if intent in ("confirm", "export"):
            leftover = [t for t in rest if not re.fullmatch(r"#?\d{1,5}|bill|phieu|gd|giao|dich", fold(t))]
            out["note"] = " ".join(leftover) or None
    return out
