# Bot két (bill-scanner + ledger)

Bot Telegram: đọc ảnh/paste CK → QR VietQR, xác nhận thì cộng két, xuất bill thì trừ két. Parse local, SQLite bền, không bắt buộc OpenAI.

## Cấu trúc

```
config.py          # Biến môi trường + nguyên lý vận hành
main.py            # Điểm vào Telegram (1 process)
bill_scanner.py    # QR VietQR + OCR + parse paste CK
ledger.py          # Sổ quỹ SQLite (bill chờ, cộng/trừ, phí, chốt)
nlu.py             # Lệnh tiếng Việt local (không AI)
excel_export.py    # Báo cáo .xlsx
run_bot.ps1        # Windows: dừng process cũ rồi chạy lại main.py
.env.example       # Mẫu biến môi trường
tests/             # pytest
my-web-tool/       # App chat AI riêng (không thuộc bot két)
```

## Nguyên lý hoạt động

1. **Parse local trước** — pipe / nhãn / bullet / VietQR. Không phụ thuộc OpenAI.
2. **Dán đủ CK** (STK · NH · số tiền · ND) → tự ra QR đúng số tiền; thiếu ND vẫn giữ số tiền đã có.
3. **Nhận tin CK → luôn trả lời** (QR hoặc báo thiếu) — không im lặng.
4. **Callback nút** — `answer` đúng 1 lần bằng `message` từ Ledger.
5. **Tiền chỉ đổi qua Ledger** trong 1 transaction, 1 lần / bill (UNIQUE). NLU chỉ nhận ý định.
6. **SQLite WAL** — bill chờ + số dư sống sót khi bot chết (`DATA_DIR` / `DB_PATH`).
7. **Một process** `python main.py` (Railway/Docker cùng lệnh).
8. **Trả lời đúng nhóm gửi tin** — khách nhóm A gửi lệnh thì bot reply trong nhóm A (không chỉ admin nhận). Thành viên nhóm tự được cấp `nhan_vien`; admin Telegram của nhóm → `quan_tri`.
9. **Đồng bộ mọi nhóm** — cùng đọc CK chữ + ảnh QR/bill (photo hoặc file ảnh), cùng nút/lệnh (`groups.py`). `/kiemtra` · `/nhom`.
10. **Nhóm không thấy bot trả lời?** BotFather → `/setprivacy` → Disable, hoặc cấp bot làm Quản trị nhóm.

## Cài

Ubuntu/Debian:

    sudo apt-get install -y tesseract-ocr tesseract-ocr-vie tesseract-ocr-eng
    pip install -r requirements.txt
    cp .env.example .env   # điền TELEGRAM_BOT_TOKEN + ADMIN_CHAT_ID
    python main.py

Windows: cài Tesseract (`vie`), `pip install -r requirements.txt`, chạy `.\run_bot.ps1` khi cần restart.

## Biến môi trường

| Biến | Bắt buộc | Ý nghĩa |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | có | Token bot |
| `ADMIN_CHAT_ID` / `ADMIN_USER_IDS` | nên có | Bootstrap Admin lần đầu |
| `DATA_DIR` / `DB_PATH` | không | Mặc định `./data/ket.db` (Docker: `/data/ket.db`) |
| `BIG_AMOUNT` | không | Bill ≥ mức này cần Admin (mặc định 50tr) |
| `DEFAULT_DIRECTION` | không | Ảnh/paste mặc định `in` (tiền vào) |
| `USE_AI_FALLBACK` | không | Mặc định tắt |

## Luồng nối module

    from bill_scanner import scan_image, parse_text
    from ledger import Ledger
    from nlu import understand

    lg = Ledger("ket.db")
    lg.add_user("ID_TELEGRAM_ADMIN", "admin", "Tên")       # lần đầu, actor=None
    lg.add_user("ID_QUAN_TRI", "quan_tri", actor="ID_TELEGRAM_ADMIN")

    # 1) Nhận ảnh bill
    info = scan_image(image_bytes)
    r = lg.submit_bill(chat_id, info, actor=user_id, direction="in", image_bytes=image_bytes)
    # r["message"] luôn có để trả lời. Hiện nút [Xác nhận] hoặc [Xuất bill].

    # 2) Bấm nút
    r = lg.confirm_bill(bill_id, actor=user_id)   # tiền vào: CỘNG két
    r = lg.export_bill(bill_id, actor=user_id)    # tiền ra: TRỪ két
    # trả lời callback đúng 1 lần bằng r["message"]

    # 3) Lệnh chữ
    cmd = understand(message_text)

Mỗi hàm trả `{"ok", "code", "message", "balance", "bill_id", "entry_id"}`.

### Quy tắc tiền (đã có test)

- Cộng/trừ trong một transaction, **một lần** / bill (UNIQUE). Bấm 2 lần / 2 người / 16 luồng: vẫn một lần.
- Trừ khi không đủ tiền bị từ chối (`Ledger(allow_negative=True)` để đổi).
- Bill trùng ảnh hoặc mã GD không gửi lại; bill đã hủy thì gửi lại được.
- Số dư = tổng dòng sổ (chỉ thêm). Sai → Admin hoàn tác bằng dòng đối ứng.
- Quyền: Nhân viên gửi; Quản trị xác nhận/xuất/hủy; Admin hoàn tác, cấp quyền, duyệt ≥ 50tr.
- SQLite WAL + `synchronous=FULL`.
- NLU chỉ nhận ý định; đổi tiền vẫn do Ledger kiểm quyền/trạng thái.

## Phí, chốt sổ, Excel

    a = lg.add_customer(chat_id, "Nguyen A", fee_in_pct=1.5, fee_out_pct=0.5, fee_out_fixed=2000, actor=qt_id)["customer_id"]
    lg.assign_customer(bill_id, a, actor=qt_id)
    lg.confirm_bill(bill_id, qt_id)
    lg.report(chat_id)
    r = lg.close_period(chat_id, qt_id, note="Ngày 01/10")
    from excel_export import export_xlsx
    export_xlsx(lg, chat_id, "chot_so.xlsx")

- Khách chịu phí. Tiền vào: còn lại = tiền − phí. Tiền ra: còn lại = tiền + phí.
- Chốt khóa kỳ; kỳ sau bắt đầu từ số dư cuối kỳ trước. Lệch đầu+vào−ra ≠ cuối → từ chối chốt.
- Excel là báo cáo; gốc luôn ở SQLite.

## Đọc bill (CLI)

    python bill_scanner.py bill.jpg
    python bill_scanner.py --json bill.jpg
    python bill_scanner.py --text "0123456789 | Vietcombank | 500.000 | tien an"

`trust`: `high` (VietQR CRC) / `medium` (OCR đồng thuận) / `low` (mâu thuẫn). Chỉ `high` nên tự động hoàn toàn.

## Test

    pip install pytest qrcode
    python -m pytest tests
