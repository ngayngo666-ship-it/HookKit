#!/usr/bin/env python3
"""Doc anh bill chuyen khoan: OCR local (Tesseract) + parse local, khong dung AI/API.

Dung nhu thu vien:
    from bill_scanner import scan_image, parse_text
    info = scan_image("bill.jpg")      # OCR + parse
    info = parse_text("STK: 0123456789\\nSo tien: 500.000 VND")   # chi parse

Dung nhu CLI:
    python bill_scanner.py bill1.jpg bill2.png
    python bill_scanner.py --text "0123456789 | Vietcombank | 500000 | tien an"
    python bill_scanner.py --json bill.jpg
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from urllib.parse import quote

BANKS = {
    "VCB": ("Vietcombank", "970436", ["vietcombank", "vcb", "ngoai thuong"]),
    "TCB": ("Techcombank", "970407", ["techcombank", "tcb", "ky thuong"]),
    "MB": ("MB Bank", "970422", ["mbbank", "mb bank", "mb", "quan doi"]),
    "BIDV": ("BIDV", "970418", ["bidv", "dau tu va phat trien"]),
    "CTG": ("VietinBank", "970415", ["vietinbank", "ctg", "cong thuong"]),
    "AGR": ("Agribank", "970405", ["agribank", "nong nghiep"]),
    "ACB": ("ACB", "970416", ["acb", "a chau"]),
    "STB": ("Sacombank", "970403", ["sacombank", "stb", "sai gon thuong tin"]),
    "VPB": ("VPBank", "970432", ["vpbank", "vpb", "viet nam thinh vuong"]),
    "TPB": ("TPBank", "970423", ["tpbank", "tpb", "tien phong"]),
    "SHB": ("SHB", "970443", ["shb", "sai gon ha noi"]),
    "HDB": ("HDBank", "970437", ["hdbank", "hdb"]),
    "OCB": ("OCB", "970448", ["ocb", "phuong dong"]),
    "MSB": ("MSB", "970426", ["msb", "maritime", "hang hai"]),
    "VIB": ("VIB", "970441", ["vib"]),
    "SEAB": ("SeABank", "970440", ["seabank", "seab", "dong nam a"]),
    "EIB": ("Eximbank", "970431", ["eximbank", "eib", "xuat nhap khau"]),
    "LPB": ("LPBank", "970449", ["lpbank", "lpb", "lienvietpostbank", "buu dien lien viet"]),
    "NAB": ("Nam A Bank", "970428", ["nam a bank", "namabank", "nab"]),
    "ABB": ("ABBank", "970425", ["abbank", "abb", "an binh"]),
    "BAB": ("Bac A Bank", "970409", ["bac a bank", "bacabank", "bab", "bac a"]),
    "VBB": ("VietBank", "970433", ["vietbank", "vbb"]),
    "NCB": ("NCB", "970419", ["ncb", "quoc dan"]),
    "PVCB": ("PVcomBank", "970412", ["pvcombank", "pvcb"]),
    "KLB": ("Kienlongbank", "970452", ["kienlongbank", "klb", "kien long"]),
    "SCB": ("SCB", "970429", ["scb"]),
    "CAKE": ("Cake", "546034", ["cake"]),
    "UBANK": ("Ubank", "546035", ["ubank"]),
    "TIMO": ("Timo", "963388", ["timo"]),
}

SENDER_LABELS = (
    r"tu tai khoan|tai khoan nguon|tai khoan chuyen|tk nguon|tk chuyen|"
    r"nguoi chuyen|nguoi gui|ben chuyen|from account|from|sender|ten nguoi chuyen"
)
FIELD_LABELS = {
    "amount": r"so tien chuyen|so tien giao dich|so tien|tong tien|gia tri|amount|trans amount|transfer amount",
    "account": (
        r"so tai khoan nhan|stk nhan|tai khoan nhan|tk nhan|den tai khoan|tai khoan thu huong|"
        r"tk thu huong|so tai khoan|so tk|stk|tai khoan|to account|beneficiary account|account number|account no"
    ),
    "bank": (
        r"ngan hang nhan|ngan hang thu huong|ngan hang|nh nhan|nh thu huong|nh|"
        r"beneficiary bank|receiving bank|to bank|bank"
    ),
    "name": (
        r"ten nguoi nhan|ten nguoi thu huong|nguoi thu huong|nguoi nhan|ten chu tai khoan|chu tai khoan|"
        r"ten tai khoan|ten tk|beneficiary name|beneficiary|account name|receiver name|receiver"
    ),
    "content": (
        r"noi dung chuyen khoan|noi dung chuyen tien|noi dung ck|noi dung|loi nhan|loi nhan nguoi nhan|"
        r"dien giai|mo ta|nd|message|content|remark|description|memo|details"
    ),
    "txn": (
        r"ma giao dich|ma gd|so giao dich|so tham chieu|ma tham chieu|ma tra cuu|"
        r"transaction id|transaction no|transaction code|reference no|reference|ref no|ref|trace no"
    ),
}
# Nhan cu the phai thang nhan chung ("tai khoan nhan" truoc "tai khoan"), nen kiem tra sender truoc.
LABEL_ORDER = ("txn", "amount", "name", "content", "bank", "account")

_AMOUNT_NUM = r"\d{1,3}(?:[ .,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_CURRENCY = r"(?:vnd|vnđ|đ|₫|dong|d(?![a-z]))"
RE_AMOUNT_SUFFIX = re.compile(rf"([+-]?\s*(?:{_AMOUNT_NUM}))\s*{_CURRENCY}", re.I)
RE_AMOUNT_PREFIX = re.compile(rf"{_CURRENCY}\s*([+-]?\s*(?:{_AMOUNT_NUM}))(?!\d)", re.I)
RE_AMOUNT_PLAIN = re.compile(rf"(?<![\d.,])({_AMOUNT_NUM})(?![\d])")
RE_DATETIME = [
    re.compile(r"(\d{1,2}[:h]\d{2}(?::\d{2})?)\s*[,\-]?\s*(?:ngay\s*)?(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})", re.I),
    re.compile(r"(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})\s*[,\-]?\s*(\d{1,2}[:h]\d{2}(?::\d{2})?)", re.I),
]
RE_STATUS_OK = re.compile(r"thanh cong|successful|success|completed|hoan thanh", re.I)
RE_STATUS_BAD = re.compile(r"that bai|khong thanh cong|failed|error|loi\b", re.I)
RE_STATUS_WAIT = re.compile(r"dang xu ly|processing|pending|cho xu ly", re.I)
BULLET = "•·●○▪■□◆◇*-–—>»+ \t"


def fold(text: str) -> str:
    """Bo dau + lower de so khop nhan/ngan hang khong bi anh huong boi OCR dau."""
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.lower()


_LABEL_RES = {
    key: re.compile(rf"^\s*(?:{pat})\b\s*[:：=\-–]?\s*(.*)$", re.I) for key, pat in FIELD_LABELS.items()
}
_SENDER_RE = re.compile(rf"^\s*(?:{SENDER_LABELS})\b\s*[:：=\-–]?\s*(.*)$", re.I)
_ANY_LABEL_RE = re.compile(
    rf"^\s*(?:{'|'.join(FIELD_LABELS.values())}|{SENDER_LABELS})\b\s*[:：=\-–]", re.I
)


def _bank_aliases():
    out = []
    for code, (display, _bin, aliases) in BANKS.items():
        for a in aliases:
            out.append((a, code))
    out.sort(key=lambda x: -len(x[0]))
    return out


_BANK_ALIASES = _bank_aliases()


def find_bank(text: str):
    """Tra ve ma ngan hang dau tien khop (uu tien ten dai) hoac None."""
    f = " " + re.sub(r"[^a-z0-9]+", " ", fold(text)) + " "
    for alias, code in _BANK_ALIASES:
        if f" {alias} " in f:
            return code
    return None


def normalize_amount(raw: str):
    s = re.sub(r"[^\d.,]", "", raw.replace(" ", ""))
    if not s:
        return None
    m = re.search(r"[.,](\d{1,2})$", s)
    if m and len(s) > len(m.group(0)) and re.search(r"\d[.,]\d{3}[.,]\d{1,2}$|^\d+[.,]\d{1,2}$", s) and len(m.group(1)) != 3:
        s = s[: m.start()]
    digits = re.sub(r"[.,]", "", s)
    if not digits:
        return None
    val = int(digits)
    return val if val > 0 else None


def fix_digits(token: str) -> str:
    """Sua nham lan chu/so thuong gap cua OCR trong chuoi so (O->0, l/I->1...)."""
    table = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "l": "1", "I": "1", "|": "1", "i": "1", "S": "5", "B": "8", "Z": "2"})
    letters = sum(c.isalpha() for c in token)
    digits = sum(c.isdigit() for c in token)
    if digits >= 5 and letters <= max(2, digits // 4):
        return token.translate(table)
    return token


def _clean_line(line: str) -> str:
    line = line.replace("\u00a0", " ").strip()
    return line.lstrip(BULLET).strip() if line[:1] in BULLET else line


def _expand_lines(text: str):
    """Tach dong, mo rong dang 'nhan | gia tri' thanh 'nhan: gia tri'."""
    out = []
    for raw in text.splitlines():
        line = _clean_line(raw)
        if not line:
            continue
        out.append(line)
    return out


def _find_amounts(text: str):
    found = []
    for rx in (RE_AMOUNT_SUFFIX, RE_AMOUNT_PREFIX):
        for m in rx.finditer(text):
            v = normalize_amount(m.group(1))
            if v:
                found.append(v)
    return found


_RE_SHORTHAND = re.compile(r"(\d+(?:[.,]\d+)?)\s*(k|nghin|ngan|tr|trieu|m|cu)\s*(\d{1,3})?")


def parse_shorthand(raw: str):
    """500k -> 500000, 1tr2 -> 1200000, 2 trieu 5 -> 2500000, 1tr250 -> 1250000."""
    m = _RE_SHORTHAND.fullmatch(fold(raw).strip())
    if not m:
        return None
    num, unit, tail = m.groups()
    base = float(num.replace(",", "."))
    scale = 1_000 if unit in ("k", "nghin", "ngan") else 1_000_000
    val = base * scale
    if tail:
        if scale == 1_000 and len(tail) > 3 or scale == 1_000_000 and len(tail) > 6:
            return None
        val = int(base) * scale + int(tail) * 10 ** (len(str(scale)) - 1 - len(tail))
    val = int(round(val))
    return val if val > 0 else None


def _amount_from_value(value: str):
    short = parse_shorthand(value)
    if short:
        return short
    cands = _find_amounts(value)
    if cands:
        return cands[0]
    m = RE_AMOUNT_PLAIN.search(value)
    return normalize_amount(m.group(1)) if m else None


_RE_ACCOUNT_LOOSE = re.compile(r"(?<![A-Za-z0-9])[0-9OoDQlIiSBZ|](?:[0-9OoDQlIiSBZ| ]{4,24})[0-9OoDQlIiSBZ|](?![A-Za-z0-9])")


def _account_from_value(value: str):
    """STK 6-19 chu so; chiu duoc khoang trang va chu bi OCR doc nham thanh so (O->0...)."""
    for m in _RE_ACCOUNT_LOOSE.finditer(value):
        tok = m.group(0)
        if sum(c.isdigit() for c in tok) < 5:
            continue
        digits = re.sub(r"\D", "", fix_digits(tok.replace(" ", "")))
        if 6 <= len(digits) <= 19:
            return digits
    return None


def _match_label(line: str):
    """(field, value) neu dong bat dau bang nhan da biet; sender -> ('sender', value)."""
    if _SENDER_RE.match(line):
        return "sender", _SENDER_RE.match(line).group(1).strip()
    f = re.sub(r"^\s*s[6o0]\s+(?=tien\b|tai khoan\b|tk\b|giao dich\b|tham chieu\b)", "so ", fold(line))
    for key in LABEL_ORDER:
        m = _LABEL_RES[key].match(f)
        if m:
            tail = m.group(1)
            value = line[len(line) - len(tail):].strip() if tail else ""
            return key, value
    return None


def _split_pipes(line: str):
    return [p.strip() for p in re.split(r"\s*[|·•]\s*", line) if p.strip()]


def _from_positional(line: str, info: dict):
    """Dang dan nhanh: 'STK | NH | so tien | ND' (khong nhan), phan nao thieu thi bo qua."""
    parts = _split_pipes(line)
    if len(parts) < 2:
        return False
    used = False
    rest = []
    for p in parts:
        bank = find_bank(p)
        acc = _account_from_value(p) if re.fullmatch(r"[\d\s.\-]{6,24}", p) else None
        amt = None
        if parse_shorthand(p) or _find_amounts(p) or re.fullmatch(r"[+-]?\d{1,3}(?:[., ]\d{3})+|[+-]?\d{4,10}", p):
            amt = _amount_from_value(p)
        if bank and not info["bank"] and len(p.split()) <= 3:
            info["bank"] = bank
            used = True
        elif acc and not info["account"] and (not amt or len(re.sub(r"\D", "", p)) >= 9):
            info["account"] = acc
            used = True
        elif amt and not info["amount"]:
            info["amount"] = amt
            used = True
        else:
            rest.append(p)
    if used and rest and not info["content"]:
        info["content"] = " | ".join(rest)
    return used


def parse_text(text: str) -> dict:
    info = {
        "amount": None, "account": None, "bank": None, "bank_name": None, "bank_bin": None,
        "name": None, "content": None, "txn": None, "time": None, "status": None,
    }
    lines = _expand_lines(text)
    sender_idx = set()
    bank_lines = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        parsed = _match_label(line)
        if not parsed:
            i += 1
            continue
        field, value = parsed
        consumed = 1
        if not value and i + 1 < len(lines) and not _ANY_LABEL_RE.match(fold(lines[i + 1])) and not _SENDER_RE.match(fold(lines[i + 1])):
            value = lines[i + 1]
            consumed = 2
        if field == "sender":
            sender_idx.add(i)
            sender_idx.add(i + 1)
        elif field == "amount" and not info["amount"]:
            info["amount"] = _amount_from_value(value)
        elif field == "account" and not info["account"]:
            acc = _account_from_value(value)
            if acc:
                info["account"] = acc
                bank = find_bank(value)
                if bank and not info["bank"]:
                    info["bank"] = bank
        elif field == "bank" and not info["bank"]:
            code = find_bank(value)
            if code:
                info["bank"] = code
            elif value:
                info["bank_name"] = value
        elif field == "name" and not info["name"] and value:
            info["name"] = re.sub(r"\s+", " ", value).strip()
        elif field == "txn" and not info["txn"]:
            m = re.search(r"[A-Za-z0-9][A-Za-z0-9\-_.]{4,}", value)
            if m:
                info["txn"] = m.group(0)
        elif field == "content" and not info["content"]:
            parts = [value] if value else []
            j = i + consumed
            while j < len(lines) and len(parts) < 3:
                nxt = lines[j]
                if _match_label(nxt) or _ANY_LABEL_RE.match(fold(nxt)):
                    break
                if any(rx.search(nxt) for pair in RE_DATETIME for rx in [pair]):
                    break
                if len(nxt) > 90 or re.fullmatch(r"[\d\s.,]+(vnd|đ)?", fold(nxt)):
                    break
                parts.append(nxt)
                j += 1
            if parts:
                info["content"] = re.sub(r"\s+", " ", " ".join(parts)).strip()
                consumed = j - i
        i += consumed

    if not (info["amount"] and info["account"] and info["bank"]):
        for line in lines:
            if _match_label(line):
                continue
            _from_positional(line, info)

    if not info["amount"]:
        cands = []
        for idx, line in enumerate(lines):
            if idx in sender_idx:
                continue
            cands += _find_amounts(line)
        if cands:
            info["amount"] = max(cands)

    if not info["bank"]:
        for idx, line in enumerate(lines):
            if idx in sender_idx or _SENDER_RE.match(fold(line)):
                continue
            code = find_bank(line)
            if code:
                info["bank"] = code
                break

    if not info["account"]:
        for idx, line in enumerate(lines):
            if idx in sender_idx or _SENDER_RE.match(fold(line)):
                continue
            if re.search(r"\d[\d ]{6,}\d", line) and not _find_amounts(line) and not any(r.search(line) for r in RE_DATETIME):
                acc = _account_from_value(line)
                if acc:
                    info["account"] = acc
                    break

    flat = "\n".join(lines)
    for rx in RE_DATETIME:
        m = rx.search(flat)
        if m:
            info["time"] = " ".join(g for g in (m.group(1), m.group(2)) if g)
            break

    ff = fold(flat)
    if RE_STATUS_BAD.search(ff):
        info["status"] = "failed"
    elif RE_STATUS_WAIT.search(ff):
        info["status"] = "processing"
    elif RE_STATUS_OK.search(ff):
        info["status"] = "success"

    if info["bank"]:
        display, bank_bin, _ = BANKS[info["bank"]]
        info["bank_name"] = display
        info["bank_bin"] = bank_bin
    return finalize(info)


def finalize(info: dict) -> dict:
    required = ("amount", "account", "bank")
    info["missing"] = [k for k in required + ("content",) if not info.get(k) and not (k == "bank" and info.get("bank_name"))]
    info["complete"] = all(k not in info["missing"] for k in required)
    info["vietqr_url"] = None
    if info["complete"] and info.get("bank_bin"):
        url = f"https://img.vietqr.io/image/{info['bank_bin']}-{info['account']}-compact2.png?amount={info['amount']}"
        if info.get("content"):
            url += f"&addInfo={quote(info['content'])}"
        if info.get("name"):
            url += f"&accountName={quote(info['name'])}"
        info["vietqr_url"] = url
    return info


_MERGE_FIELDS = (
    "amount", "account", "bank", "bank_name", "bank_bin",
    "name", "content", "txn", "time", "status",
)


def merge_payment_info(primary: dict, *extras: dict) -> dict:
    """Gộp ảnh QR/OCR + caption/paste chữ: thiếu trường nào lấy từ nguồn còn lại (không mất số tiền)."""
    out = dict(primary or {})
    for extra in extras:
        if not extra:
            continue
        for key in _MERGE_FIELDS:
            if not out.get(key) and extra.get(key):
                out[key] = extra[key]
        # Giữ trust cao hơn nếu có
        rank = {"low": 0, "medium": 1, "high": 2}
        if rank.get(extra.get("trust"), -1) > rank.get(out.get("trust"), -1):
            out["trust"] = extra["trust"]
    return finalize(out)


def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def _tlv(s: str):
    out, i = [], 0
    while i < len(s):
        if i + 4 > len(s) or not s[i + 2:i + 4].isdigit():
            return None
        n = int(s[i + 2:i + 4])
        val = s[i + 4:i + 4 + n]
        if len(val) != n:
            return None
        out.append((s[i:i + 2], val))
        i += 4 + n
    return out


_BIN_TO_CODE = {v[1]: k for k, v in BANKS.items()}


def parse_vietqr(payload: str):
    """Giai ma chuoi VietQR (EMVCo). Chi tra ve khi CRC dung va co tai khoan nhan; nguoc lai None."""
    s = payload.strip()
    if len(s) < 20 or s[-8:-4] != "6304" or not re.fullmatch(r"[0-9A-Fa-f]{4}", s[-4:]):
        return None
    if crc16_ccitt(s[:-4].encode()) != int(s[-4:], 16):
        return None
    top = _tlv(s)
    if not top:
        return None
    fields = dict(top)
    acct = _tlv(fields.get("38", "")) if "38" in fields else None
    if not acct or dict(acct).get("00") != "A000000727":
        return None
    receiver = _tlv(dict(acct).get("01", ""))
    if not receiver:
        return None
    rec = dict(receiver)
    bank_bin, account = rec.get("00"), rec.get("01")
    if not bank_bin or not account or not re.fullmatch(r"\d{6}", bank_bin):
        return None
    amount = None
    if fields.get("54"):
        try:
            f = float(fields["54"])
            amount = int(f) if f == int(f) and f > 0 else None
        except ValueError:
            amount = None
    extra = _tlv(fields.get("62", "")) or []
    content = dict(extra).get("08")
    code = _BIN_TO_CODE.get(bank_bin)
    return {
        "account": account,
        "bank_bin": bank_bin,
        "bank": code,
        "bank_name": BANKS[code][0] if code else f"BIN {bank_bin}",
        "amount": amount,
        "content": content.strip() if content else None,
        "name": fields.get("59"),
        "static": fields.get("01") == "11",
        "service": rec.get("02"),
    }


def _load_image(path_or_bytes):
    import cv2
    import numpy as np

    if isinstance(path_or_bytes, (bytes, bytearray)):
        data = np.frombuffer(path_or_bytes, dtype=np.uint8)
    else:
        data = np.fromfile(path_or_bytes, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Khong doc duoc anh (file hong hoac khong phai anh)")
    return img


def decode_vietqr(img):
    """Tim ma QR trong anh bill (nhieu ti le/lam net) va tra ve VietQR hop le dau tien, hoac None."""
    import cv2

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    detectors = [cv2.QRCodeDetector()]
    if hasattr(cv2, "QRCodeDetectorAruco"):
        detectors.insert(0, cv2.QRCodeDetectorAruco())
    sharp_kernel = [[0, -1, 0], [-1, 5, -1], [0, -1, 0]]
    import numpy as np

    scales = (1.0, 0.5, 0.35) if gray.shape[1] >= 1000 else (1.0, 2.0, 0.5, 1.5, 3.0)
    for scale in scales:
        g = gray if scale == 1.0 else cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
        for variant in (g, cv2.filter2D(g, -1, np.array(sharp_kernel, dtype=np.float32)), cv2.bitwise_not(g)):
            for det in detectors:
                try:
                    ok, texts, _pts, _ = det.detectAndDecodeMulti(variant)
                except cv2.error:
                    continue
                if not ok:
                    continue
                for t in texts:
                    qr = parse_vietqr(t) if t else None
                    if qr:
                        return qr
    return None


def _variants(img):
    import cv2

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    scale = 1.0
    if w < 1400:
        scale = 1400 / w
    elif w > 2600:
        scale = 2600 / w
    if scale != 1.0:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
    dark = gray.mean() < 120
    base = cv2.bitwise_not(gray) if dark else gray
    yield "gray", base
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(base)
    yield "clahe", clahe
    _, otsu = cv2.threshold(cv2.GaussianBlur(base, (3, 3), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield "otsu", otsu


_RAPID = None


def _rapid_engine():
    """RapidOCR (ONNX, chay CPU) la engine thu 2, doc lap voi Tesseract. Khong co thi bo qua."""
    global _RAPID
    if _RAPID is None:
        try:
            from rapidocr_onnxruntime import RapidOCR

            _RAPID = RapidOCR()
        except Exception:
            _RAPID = False
    return _RAPID or None


def _rapid_text(engine, img) -> str:
    res, _ = engine(img)
    if not res:
        return ""
    items = []
    for box, txt, _conf in res:
        ys = [pt[1] for pt in box]
        xs = [pt[0] for pt in box]
        items.append([sum(ys) / len(ys), min(xs), max(ys) - min(ys), txt])
    items.sort(key=lambda it: it[0])
    lines = []
    for cy, x, h, txt in items:
        if lines and abs(cy - lines[-1]["cy"]) < 0.6 * max(h, lines[-1]["h"]):
            line = lines[-1]
            line["parts"].append((x, txt))
            line["cy"] = (line["cy"] * (len(line["parts"]) - 1) + cy) / len(line["parts"])
            line["h"] = max(line["h"], h)
        else:
            lines.append({"cy": cy, "h": h, "parts": [(x, txt)]})
    return "\n".join("  ".join(t for _, t in sorted(line["parts"])) for line in lines)


def ocr_text_variants(img):
    """Yield (tag, text, engine), xen ke Tesseract/RapidOCR de quyet dinh som van co du 2 engine."""
    import cv2
    import pytesseract

    langs = pytesseract.get_languages(config="")
    lang = "vie+eng" if "vie" in langs and "eng" in langs else "eng"
    rapid = _rapid_engine()
    variants = dict(_variants(img))

    def tess(name, psm):
        return f"{name}/psm{psm}", pytesseract.image_to_string(variants[name], lang=lang, config=f"--oem 1 --psm {psm}"), "tesseract"

    yield tess("gray", 6)
    if rapid:
        yield "rapid/orig", _rapid_text(rapid, img), "rapid"
    yield tess("gray", 4)
    if rapid:
        yield "rapid/gray", _rapid_text(rapid, cv2.cvtColor(variants["gray"], cv2.COLOR_GRAY2BGR)), "rapid"
    for name in ("clahe", "otsu"):
        for psm in (6, 4):
            yield tess(name, psm)
    if rapid:
        yield "rapid/clahe", _rapid_text(rapid, cv2.cvtColor(variants["clahe"], cv2.COLOR_GRAY2BGR)), "rapid"


CRITICAL = ("amount", "account", "bank")
OPTIONAL = ("name", "content", "txn", "time", "status")
STABLE_VOTES = 3


def _vote(parses, field):
    """(gia tri nhieu phieu nhat, so phieu, so phieu cua gia tri ke tiep, cac engine da bau cho gia tri do)."""
    counts = Counter(p[field] for p in parses if p.get(field))
    if not counts:
        return None, 0, 0, set()
    ranked = counts.most_common(2)
    second = ranked[1][1] if len(ranked) > 1 else 0
    top = ranked[0][0]
    engines = {p.get("_engine") for p in parses if p.get(field) == top}
    return top, ranked[0][1], second, engines


def consensus(parses, qr=None):
    """Gop nhieu lan OCR bang bo phieu; QR hop le la nguon chinh. Tra ve info day du + do tin cay."""
    info = {k: None for k in ("amount", "account", "bank", "bank_name", "bank_bin", "name", "content", "txn", "time", "status")}
    source, votes, conflicts, unstable, voters = {}, {}, {}, [], {}
    multi_engine = len({p.get("_engine") for p in parses}) >= 2
    for f in CRITICAL + OPTIONAL:
        val, top, second, engines = _vote(parses, f)
        info[f] = val
        votes[f] = top
        voters[f] = engines
        stable = bool(val) and top >= 2 and top > second
        source[f] = "ocr_stable" if stable else ("ocr_unstable" if val else None)
        if val and not stable and f in CRITICAL:
            unstable.append(f)
    if qr:
        for f in ("account", "bank", "amount", "content", "name"):
            q = qr.get(f)
            if not q:
                continue
            if info.get(f) and info[f] != q and source.get(f) == "ocr_stable" and f in CRITICAL + ("content",):
                conflicts[f] = {"qr": q, "ocr": info[f]}
            info[f] = q
            source[f] = "qr"
        info["bank_bin"] = qr["bank_bin"]
        if not info.get("bank_name"):
            info["bank_name"] = qr["bank_name"]
    if info.get("bank") and not info.get("bank_bin"):
        info["bank_name"], info["bank_bin"] = BANKS[info["bank"]][0], BANKS[info["bank"]][1]

    def have(f):
        return bool(info.get(f) or (f == "bank" and info.get("bank_bin")))

    def ok(f):
        if source.get(f) == "qr":
            return True
        independent = len(voters.get(f, ())) >= 2 or not multi_engine
        return source.get(f) == "ocr_stable" and votes[f] >= STABLE_VOTES and independent

    if qr and not conflicts and source.get("account") == "qr" and (source.get("bank") == "qr" or info.get("bank_bin")) and ok("amount"):
        trust = "high"
    elif not qr and all(ok(f) for f in CRITICAL):
        trust = "medium"
    elif qr and not conflicts and all(have(f) for f in CRITICAL) and all(source[f] != "ocr_unstable" for f in CRITICAL):
        trust = "medium"
    else:
        trust = "low"
    finalize(info)
    info["trust"] = trust
    info["needs_confirm"] = trust != "high"
    info["sources"] = source
    info["conflicts"] = conflicts
    info["unstable"] = unstable
    info["qr_found"] = bool(qr)
    return info


def scan_image(path_or_bytes, debug: bool = False) -> dict:
    from concurrent.futures import ThreadPoolExecutor

    img = _load_image(path_or_bytes)
    parses, texts = [], []
    with ThreadPoolExecutor(max_workers=1) as pool:
        qr_future = pool.submit(decode_vietqr, img)
        for tag, text, engine in ocr_text_variants(img):
            texts.append((tag, text))
            parsed = parse_text(text)
            parsed["_engine"] = engine
            parses.append(parsed)
            qr_now = qr_future.result() if qr_future.done() else None
            if qr_now and qr_now.get("amount") and len(parses) >= 2:
                break
            if len(parses) >= 4:
                agree = Counter((p["amount"], p["account"], p["bank"]) for p in parses if p["complete"])
                engines_ok = {p["_engine"] for p in parses if p["complete"]}
                need_engines = 2 if _rapid_engine() else 1
                if len(agree) == 1 and agree.most_common(1)[0][1] >= STABLE_VOTES + 1 and len(engines_ok) >= need_engines:
                    break
        qr = qr_future.result()
    info = consensus(parses, qr)
    info["ocr_text"] = "\n--\n".join(f"[{t}]\n{x}" for t, x in texts[:2]) if debug else (texts[0][1] if texts else "")
    info["engines"] = sorted({p["_engine"] for p in parses})
    if debug:
        info["ocr_variants"] = {t: x for t, x in texts}
    return info


def summary(info: dict) -> str:
    amt = f"{info['amount']:,}".replace(",", ".") + " VND" if info.get("amount") else "(thieu)"
    rows = [
        f"So tien : {amt}",
        f"STK     : {info.get('account') or '(thieu)'}",
        f"Ngan hang: {info.get('bank_name') or '(thieu)'}",
        f"Nguoi nhan: {info.get('name') or '-'}",
        f"Noi dung: {info.get('content') or '(thieu)'}",
        f"Ma GD   : {info.get('txn') or '-'}",
        f"Thoi gian: {info.get('time') or '-'}",
        f"Trang thai: {info.get('status') or '-'}",
    ]
    trust = {"high": "CAO (co ma QR hop le)", "medium": "TRUNG BINH - can xac nhan", "low": "THAP - bat buoc xac nhan"}
    if info.get("trust"):
        rows.append(f"Do tin cay: {trust[info['trust']]}")
    for f, c in (info.get("conflicts") or {}).items():
        rows.append(f"MAU THUAN {f}: QR={c['qr']} / OCR={c['ocr']}")
    if info.get("unstable"):
        rows.append("Khong chac: " + ", ".join(info["unstable"]) + " (cac lan doc khac nhau)")
    if info.get("vietqr_url"):
        rows.append(f"QR      : {info['vietqr_url']}")
    elif info.get("missing"):
        rows.append("Thieu   : " + ", ".join(info["missing"]))
    return "\n".join(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Doc bill chuyen khoan tu anh (OCR local)")
    ap.add_argument("images", nargs="*", help="duong dan anh bill")
    ap.add_argument("--text", action="append", default=[], help="parse thang tu van ban (khong OCR), dung duoc nhieu lan")
    ap.add_argument("--text-file", help="parse tu file van ban")
    ap.add_argument("--json", action="store_true", help="in JSON")
    ap.add_argument("--debug", action="store_true", help="in them van ban OCR")
    args = ap.parse_args(argv)

    results = []
    for n, txt in enumerate(args.text, 1):
        results.append((f"--text #{n}", parse_text(txt)))
    if args.text_file:
        with open(args.text_file, encoding="utf-8") as fh:
            results.append((args.text_file, parse_text(fh.read())))
    for path in args.images:
        try:
            results.append((path, scan_image(path, debug=args.debug)))
        except Exception as exc:
            results.append((path, {"error": str(exc)}))
    if not results:
        ap.print_help()
        return 2

    if args.json:
        print(json.dumps({p: r for p, r in results}, ensure_ascii=False, indent=2))
        return 0
    for path, info in results:
        print(f"== {path}")
        if "error" in info:
            print("Loi:", info["error"])
        else:
            print(summary(info))
            if args.debug:
                print("--- OCR ---")
                print(info.get("ocr_text", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
