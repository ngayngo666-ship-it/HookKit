import io
import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from bill_scanner import consensus, crc16_ccitt, normalize_amount, parse_text, parse_vietqr, scan_image  # noqa: E402

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("500.000", 500000),
        ("500,000", 500000),
        ("1,500,000.00", 1500000),
        ("1.500.000,00", 1500000),
        ("2 000 000", 2000000),
        ("350000", 350000),
        ("-1.250.000", 1250000),
        ("0", None),
    ],
)
def test_normalize_amount(raw, expected):
    assert normalize_amount(raw) == expected


def test_vietcombank_style_bill():
    text = """
    Chuyển khoản thành công
    Số tiền: 1,500,000 VND
    Từ tài khoản: 0011004455667
    Tài khoản nhận: 9704 1234 5678
    Tên người nhận: NGUYEN VAN A
    Ngân hàng: Techcombank
    Nội dung: NGUYEN VAN B chuyen tien an
    Mã giao dịch: FT26274ABCDE
    14:35 01/10/2026
    """
    r = parse_text(text)
    assert r["amount"] == 1500000
    assert r["account"] == "970412345678"
    assert r["bank"] == "TCB" and r["bank_bin"] == "970407"
    assert r["name"] == "NGUYEN VAN A"
    assert r["content"] == "NGUYEN VAN B chuyen tien an"
    assert r["txn"] == "FT26274ABCDE"
    assert r["time"] == "14:35 01/10/2026"
    assert r["status"] == "success"
    assert r["complete"] and r["missing"] == []
    assert r["vietqr_url"].startswith("https://img.vietqr.io/image/970407-970412345678-compact2.png?amount=1500000")


def test_sender_account_is_not_picked():
    text = "Từ tài khoản: 1111222233\nĐến tài khoản: 9999888877\nNgân hàng nhận: MB\nSố tiền: 200.000đ"
    r = parse_text(text)
    assert r["account"] == "9999888877"
    assert r["bank"] == "MB"
    assert r["amount"] == 200000


def test_value_on_next_line_layout():
    text = "Số tiền\n750.000 VND\nSố tài khoản\n0123456789\nNgân hàng\nBIDV\nNội dung\ntra no tien nha"
    r = parse_text(text)
    assert (r["amount"], r["account"], r["bank"], r["content"]) == (750000, "0123456789", "BIDV", "tra no tien nha")


def test_pipe_label_and_bullet_forms():
    r = parse_text("• STK: 0123456789\n• NH: Vietcombank\n• Số tiền: 500000\n• ND: tien an")
    assert (r["amount"], r["account"], r["bank"], r["content"]) == (500000, "0123456789", "VCB", "tien an")


def test_positional_pipe_full_and_missing_content():
    r = parse_text("0123456789 | Vietcombank | 500.000 | tien an trua")
    assert (r["amount"], r["account"], r["bank"], r["content"]) == (500000, "0123456789", "VCB", "tien an trua")
    r = parse_text("0123456789 | Vietcombank | 500.000")
    assert r["amount"] == 500000 and r["complete"] and r["missing"] == ["content"]
    assert r["vietqr_url"] and "addInfo" not in r["vietqr_url"]


@pytest.mark.parametrize(
    "raw,expected",
    [("500k", 500000), ("1tr2", 1200000), ("1tr25", 1250000), ("1tr250", 1250000), ("2 triệu 5", 2500000), ("1tr", 1000000), ("1k5", 1500), ("abc", None)],
)
def test_parse_shorthand(raw, expected):
    from bill_scanner import parse_shorthand

    assert parse_shorthand(raw) == expected


def test_positional_dot_separator_and_shorthand():
    r = parse_text("0123456789 · Vietcombank · 500.000 · tien an")
    assert (r["amount"], r["account"], r["bank"], r["content"]) == (500000, "0123456789", "VCB", "tien an")
    r = parse_text("9876543210 | MB | 1tr2")
    assert (r["amount"], r["account"], r["bank"]) == (1200000, "9876543210", "MB") and r["missing"] == ["content"]


def test_ocr_digit_confusion_in_account():
    r = parse_text("STK: O123456789\nNgân hàng: ACB\nSố tiền: 100.000 VND")
    assert r["account"] == "0123456789"


def test_missing_is_reported_not_silent():
    r = parse_text("Số tiền: 300.000 VND\nNgân hàng: ACB")
    assert r["amount"] == 300000 and r["bank"] == "ACB"
    assert not r["complete"] and "account" in r["missing"]
    assert r["vietqr_url"] is None


def test_multiline_content_and_failed_status():
    r = parse_text("Giao dịch thất bại\nSố tiền: 10.000 VND\nNội dung: chuyen tien\nthue phong thang 10\nMã giao dịch: ABC12345")
    assert r["content"] == "chuyen tien thue phong thang 10"
    assert r["status"] == "failed"


def test_empty_text():
    r = parse_text("")
    assert r["amount"] is None and not r["complete"]


def _emv(tag, val):
    return f"{tag}{len(val):02d}{val}"


def make_vietqr(bank_bin, account, amount=None, content=None, name="NGUYEN VAN A"):
    receiver = _emv("00", bank_bin) + _emv("01", account) + _emv("02", "QRIBFTTA")
    s = (
        _emv("00", "01") + _emv("01", "12" if amount else "11")
        + _emv("38", _emv("00", "A000000727") + _emv("01", receiver))
        + _emv("53", "704") + (_emv("54", str(amount)) if amount else "")
        + _emv("58", "VN") + _emv("59", name)
        + (_emv("62", _emv("08", content)) if content else "") + "6304"
    )
    return s + f"{crc16_ccitt(s.encode()):04X}"


def _draw_bill(rows, dark=False, width=720, font_size=30, title="Chuyển khoản thành công", qr=None):
    from PIL import Image, ImageDraw, ImageFont

    bg, fg, sub = ((20, 24, 33), (240, 240, 240), (160, 170, 185)) if dark else ((255, 255, 255), (20, 20, 20), (110, 110, 110))
    font = ImageFont.truetype(FONT, font_size)
    bold = ImageFont.truetype(FONT_BOLD, font_size + 6)
    row_h = font_size * 2
    qr_h = 380 if qr else 0
    img = Image.new("RGB", (width, 160 + row_h * len(rows) + 60 + qr_h), bg)
    d = ImageDraw.Draw(img)
    d.text((40, 40), title, font=bold, fill=fg)
    y = 130
    for label, value in rows:
        d.text((40, y), label, font=font, fill=sub)
        w = d.textlength(value, font=font)
        d.text((width - 40 - w, y), value, font=font, fill=fg)
        y += row_h
    if qr:
        import qrcode

        q = qrcode.QRCode(box_size=6, border=4)
        q.add_data(qr)
        q.make(fit=True)
        qimg = q.make_image(fill_color="black", back_color="white").convert("RGB")
        img.paste(qimg, ((width - qimg.width) // 2, y + 10))
    return img


def _png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


ROWS = [
    ("Số tiền", "1,250,000 VND"),
    ("Tên người nhận", "NGUYEN VAN A"),
    ("Số tài khoản", "0123456789"),
    ("Ngân hàng", "Vietcombank"),
    ("Nội dung", "tien thue phong"),
    ("Mã giao dịch", "FT26274ABCDE"),
]

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="can cai tesseract-ocr tesseract-ocr-vie")


@needs_tesseract
def test_ocr_light_bill():
    r = scan_image(_png_bytes(_draw_bill(ROWS)))
    assert r["amount"] == 1250000
    assert r["account"] == "0123456789"
    assert r["bank"] == "VCB"
    assert r["complete"]
    assert "thue phong" in (r["content"] or "")


@needs_tesseract
def test_ocr_dark_mode_bill():
    r = scan_image(_png_bytes(_draw_bill(ROWS, dark=True)))
    assert (r["amount"], r["account"], r["bank"]) == (1250000, "0123456789", "VCB")


@needs_tesseract
def test_ocr_small_blurry_bill():
    from PIL import ImageFilter

    img = _draw_bill(ROWS, width=420, font_size=20).filter(ImageFilter.GaussianBlur(0.8))
    r = scan_image(_png_bytes(img))
    assert (r["amount"], r["account"], r["bank"]) == (1250000, "0123456789", "VCB")


@needs_tesseract
def test_ocr_negative_amount_spaced_account_and_other_bank():
    rows = [("Số tiền", "-2.500.000 VND"), ("Đến tài khoản", "1903 6789 0123"), ("Ngân hàng nhận", "Techcombank"), ("Nội dung", "NGUYEN VAN C chuyen khoan")]
    r = scan_image(_png_bytes(_draw_bill(rows, width=900)))
    assert (r["amount"], r["account"], r["bank"]) == (2500000, "190367890123", "TCB")
    assert "chuyen khoan" in (r["content"] or "")


@needs_tesseract
def test_ocr_bad_file_raises():
    with pytest.raises(ValueError):
        scan_image(b"not an image")


def test_crc16_ccitt_known_vector():
    assert crc16_ccitt(b"123456789") == 0x29B1


def test_parse_vietqr_valid_and_corrupted():
    payload = make_vietqr("970436", "0123456789", 1250000, "tien thue phong")
    q = parse_vietqr(payload)
    assert (q["account"], q["bank"], q["bank_bin"], q["amount"], q["content"], q["name"]) == (
        "0123456789", "VCB", "970436", 1250000, "tien thue phong", "NGUYEN VAN A")
    assert parse_vietqr(payload[:-1] + ("0" if payload[-1] != "0" else "1")) is None
    assert parse_vietqr(payload.replace("1250000", "1250001")) is None
    assert parse_vietqr("hello world") is None


def test_static_qr_has_no_amount():
    q = parse_vietqr(make_vietqr("970422", "9876543210"))
    assert q["amount"] is None and q["static"] and q["bank"] == "MB"


def _parse(amount):
    return {"amount": amount, "account": "0123456789", "bank": "VCB", "complete": True}


def test_voting_stable_vs_unstable():
    stable = consensus([_parse(1250000)] * 4 + [_parse(1250)])
    assert stable["amount"] == 1250000 and stable["trust"] == "medium"
    split = consensus([_parse(1250000)] * 2 + [_parse(1250)] * 2)
    assert split["trust"] == "low" and split["needs_confirm"] and "amount" in split["unstable"]
    lone = consensus([_parse(1250000)])
    assert lone["trust"] == "low"


@needs_tesseract
def test_qr_bill_is_high_trust():
    qr = make_vietqr("970436", "0123456789", 1250000, "tien thue phong")
    r = scan_image(_png_bytes(_draw_bill(ROWS, qr=qr)))
    assert r["qr_found"] and r["trust"] == "high" and not r["needs_confirm"]
    assert (r["amount"], r["account"], r["bank"]) == (1250000, "0123456789", "VCB")
    assert r["conflicts"] == {}


@needs_tesseract
def test_qr_wins_when_text_is_unreadable():
    from PIL import ImageFilter

    qr = make_vietqr("970407", "190367890123", 2500000, "chuyen khoan")
    img = _draw_bill(ROWS, qr=qr).filter(ImageFilter.GaussianBlur(6))
    qimg = _draw_bill([], qr=qr)
    img.paste(qimg.crop((0, 160, qimg.width, qimg.height)), (0, 160 + 60 * len(ROWS) + 60))
    r = scan_image(_png_bytes(img))
    assert r["qr_found"]
    assert (r["amount"], r["account"], r["bank"]) == (2500000, "190367890123", "TCB")


@needs_tesseract
def test_conflict_between_qr_and_printed_text_is_flagged():
    qr = make_vietqr("970436", "0123456789", 500000, "tien thue phong")
    r = scan_image(_png_bytes(_draw_bill(ROWS, qr=qr)))
    assert r["qr_found"] and "amount" in r["conflicts"]
    assert r["conflicts"]["amount"] == {"qr": 500000, "ocr": 1250000}
    assert r["needs_confirm"] and r["trust"] != "high"


@needs_tesseract
def test_never_confidently_wrong_on_degraded_images():
    """Anh cang hong cang phai ha do tin cay; da tu tin (high/medium) thi phai dung."""
    import random

    from PIL import ImageFilter

    random.seed(7)
    base = _draw_bill(ROWS, width=640, font_size=26)
    cases = []
    for sigma in (0.5, 1.2, 2.0, 3.0, 4.5):
        cases.append(base.filter(ImageFilter.GaussianBlur(sigma)))
    for factor in (0.5, 0.35, 0.25):
        small = base.resize((int(base.width * factor), int(base.height * factor)))
        cases.append(small)
    noisy = base.copy()
    px = noisy.load()
    for _ in range(40000):
        x, y = random.randrange(noisy.width), random.randrange(noisy.height)
        v = random.choice((0, 255))
        px[x, y] = (v, v, v)
    cases.append(noisy)
    cases.append(base.rotate(4, fillcolor=(255, 255, 255)))
    cases.append(base.rotate(-6, fillcolor=(255, 255, 255)))
    truth = (1250000, "0123456789", "VCB")
    confident_wrong = []
    for n, img in enumerate(cases):
        r = scan_image(_png_bytes(img))
        got = (r["amount"], r["account"], r["bank"])
        if r["trust"] in ("high", "medium") and got != truth:
            confident_wrong.append((n, got, r["trust"]))
    assert not confident_wrong, confident_wrong
