# bill-scanner

Bộ công cụ cho bot két: đọc ảnh bill chuyển khoản, xác nhận thì cộng két, xuất bill thì trừ két, hiểu lệnh tiếng Việt của admin/quản trị. Chạy local, không cần OpenAI/API.

| File | Việc |
|---|---|
| `bill_scanner.py` | Đọc ảnh bill: QR VietQR (kiểm CRC) + OCR 2 engine (Tesseract, RapidOCR) + bỏ phiếu + mức tin cậy |
| `ledger.py` | Sổ quỹ SQLite: bill chờ, xác nhận (cộng), xuất bill (trừ), hoàn tác, phân quyền, nhật ký |
| `nlu.py` | Hiểu lệnh tiếng Việt: "xác nhận #12", "xuất bill 7", "chi 1tr2 tiền điện", "số dư"... |

## Cài

Ubuntu/Debian:

    sudo apt-get install -y tesseract-ocr tesseract-ocr-vie tesseract-ocr-eng
    pip install -r requirements.txt

Windows: cài Tesseract (kèm gói ngôn ngữ `vie`), thêm vào PATH, rồi `pip install -r requirements.txt`.
`rapidocr-onnxruntime` là engine thứ 2. Không cài được thì tool vẫn chạy bằng Tesseract (mức `medium` khi đó không có đối chiếu chéo).

## Luồng nối vào bot

    from bill_scanner import scan_image
    from ledger import Ledger
    from nlu import understand

    lg = Ledger("ket.db")
    lg.add_user("ID_TELEGRAM_ADMIN", "admin", "Tên")       # lần đầu, actor=None
    lg.add_user("ID_QUAN_TRI", "quan_tri", actor="ID_TELEGRAM_ADMIN")

    # 1) Nhận ảnh bill
    info = scan_image(image_bytes)
    r = lg.submit_bill(chat_id, info, actor=user_id, direction="in", image_bytes=image_bytes)  # "in" = tiền vào, "out" = tiền ra
    # r["message"] luôn có để trả lời. Hiện nút [Xác nhận] hoặc [Xuất bill] kèm info (số tiền, STK, NH, trust).

    # 2) Bấm nút
    r = lg.confirm_bill(bill_id, actor=user_id)   # tiền vào: CỘNG két ngay
    r = lg.export_bill(bill_id, actor=user_id)    # tiền ra: TRỪ két ngay
    # trả lời callback đúng 1 lần bằng r["message"]

    # 3) Lệnh chữ
    cmd = understand(message_text)   # {"intent": "confirm" | "export" | "reject" | "balance" | ... , "bill_id", "amount", "note"}

Mỗi hàm trả `{"ok", "code", "message", "balance", "bill_id", "entry_id"}`.

### Quy tắc tiền (đã có test)

- Cộng/trừ xảy ra trong một transaction và chỉ **một lần** cho mỗi bill (ràng buộc UNIQUE ngay trong DB). Bấm 2 lần, 2 người cùng bấm, 16 luồng cùng lúc: vẫn một lần.
- Trừ két khi không đủ tiền bị từ chối (đổi bằng `Ledger(allow_negative=True)`). Hai lệnh trừ đồng thời không làm âm két.
- Bill trùng ảnh hoặc trùng mã giao dịch không được gửi lại. Bill đã hủy thì gửi lại được.
- Số dư là tổng các dòng sổ, chỉ thêm không sửa. Sai thì Admin hoàn tác bằng dòng đối ứng.
- Phân quyền: Nhân viên gửi bill; Quản trị xác nhận/xuất/hủy; Admin hoàn tác, cấp quyền, và duyệt bill từ 50 triệu (đổi bằng `big_amount`).
- Dữ liệu ghi SQLite (WAL, `synchronous=FULL`): bot chết vẫn còn bill chờ và số dư.
- Lệnh chữ ("ok", "xuất bill") chỉ nhận ra ý định. Bot nên chỉ nhận lệnh xác nhận khi trả lời đúng tin nhắn bill hoặc có `#số`; mọi thay đổi tiền vẫn do `Ledger` kiểm quyền và trạng thái.

## Phí theo từng người, chốt sổ, báo cáo

    a = lg.add_customer(chat_id, "Nguyen A", fee_in_pct=1.5, fee_out_pct=0.5, fee_out_fixed=2000, actor=qt_id)["customer_id"]
    lg.assign_customer(bill_id, a, actor=qt_id)         # gán người cho bill đang chờ (hoặc submit_bill(..., customer_id=a))
    lg.confirm_bill(bill_id, qt_id)                      # phí tính và CHỤP LẠI lúc xác nhận/xuất
    lg.set_customer_fee(a, qt_id, fee_in_pct=2)          # đổi phí: chỉ áp dụng bill SAU, bill cũ giữ nguyên
    lg.report(chat_id)                                   # xem trước kỳ đang mở (chưa chốt)
    r = lg.close_period(chat_id, qt_id, note="Ngày 01/10")   # chốt sổ, khóa kỳ
    export_csv(lg.report(chat_id, r["closing_id"]), "chot_so.csv")   # mở thẳng bằng Excel / Google Sheets

- Mỗi người có phí riêng cho chiều vào và chiều ra: phần trăm (tối đa 2 số thập phân) cộng phí cố định. Tính bằng số nguyên, làm tròn lên từ 0,5.
- Mỗi dòng báo cáo có: **số tiền không phí**, **phí**, **số còn lại (sau phí)**, người, STK, ngân hàng, nội dung, người thao tác.
- Quy ước phí: **khách hàng là người chịu phí**. Tiền vào: **số còn lại = số tiền − phí** (đã được xác nhận). Tiền ra: số còn lại = số tiền + phí; nếu không thu phí tiền ra thì để phí ra của người đó bằng 0 (mặc định là 0). Số dư két luôn tính theo số tiền thực đã vào/ra, phí chỉ là cột kế toán riêng.
- Tổng kỳ: tổng vào, tổng ra, phí thu (vào/ra/tổng), còn lại từ tiền vào, ra sau phí, số dư đầu kỳ, số dư cuối kỳ và kết quả **DƯƠNG / ÂM / CÂN BẰNG**.
- Chốt sổ khóa các giao dịch đang mở thành một kỳ, ghi số dư đầu/cuối. Kỳ sau bắt đầu từ số dư cuối kỳ trước. Sai sót đã chốt thì Admin hoàn tác, dòng hoàn tác nằm ở kỳ sau (kỳ cũ không đổi). Bill còn chờ được báo và chuyển sang kỳ sau.
- Khi chốt, hệ thống kiểm tra số dư đầu kỳ + vào − ra phải đúng bằng số dư cuối kỳ; lệch thì từ chối chốt.
### Xuất Excel (.xlsx)

    from excel_export import export_xlsx
    export_xlsx(lg, chat_id, "chot_so.xlsx")      # rồi gửi file vào chat bằng sendDocument

File gồm: sheet **Tổng hợp** (mỗi kỳ một dòng, bấm tên kỳ để nhảy tới sheet đó, có dòng tổng các kỳ), mỗi kỳ chốt một sheet (**Chốt 1, Chốt 2...**), và sheet **Kỳ đang mở** (xem trước, chưa khóa, có hoàn tác thì hiện số âm màu đỏ).

- Mỗi sheet kỳ có khối tổng kết ở trên (đầu kỳ, vào, ra, phí, còn lại, cuối kỳ, **DƯƠNG/ÂM** tô xanh/đỏ) và bảng từng bill ở dưới, có lọc và cố định hàng tiêu đề, in ngang vừa một trang.
- Các số tổng là **công thức Excel** tính từ chính các dòng bill, nên ai mở file cũng kiểm tra lại được.
- Ô **Kiểm tra khớp sổ quỹ** so với số dư cuối kỳ ghi trong SQLite: hiện KHỚP, hoặc LỆCH nếu ai đó sửa tay một số trong file.
- STK để dạng chữ nên không mất số 0 đầu. Excel chỉ là bản báo cáo, bot không đọc ngược số liệu từ file.
- Chat gõ "xuất excel", "file excel", "báo cáo" thì `understand()` trả `intent = "report"`.

- Muốn bắt buộc gán người trước khi xác nhận: `Ledger(path, require_customer=True)`.
- Sổ tạo bằng bản trước tự được nâng cấp (thêm cột) khi mở, không mất dữ liệu.
- Bảng tính chỉ là bản báo cáo: số liệu gốc luôn nằm trong SQLite, không đọc ngược từ bảng tính.

## Đọc bill

    python bill_scanner.py bill.jpg            # tóm tắt
    python bill_scanner.py --json bill.jpg
    python bill_scanner.py --text "0123456789 | Vietcombank | 500.000 | tien an"

Kết quả: `amount`, `account`, `bank`, `bank_name`, `bank_bin`, `name`, `content`, `txn`, `time`, `status`, `missing`, `complete`, `vietqr_url`, `trust`, `needs_confirm`, `conflicts`, `unstable`.

### Độ tin cậy

Không OCR/AI nào đúng 100%, nên mỗi kết quả có `trust`:

| trust | Điều kiện | Bot nên làm |
|---|---|---|
| `high` | Có mã VietQR trong ảnh, CRC đúng, không mâu thuẫn với chữ trên bill | Tự ra QR |
| `medium` | Không có QR; các lần đọc (cả 2 engine) cùng ra một kết quả | Hiện phiếu xác nhận |
| `low` | Các lần đọc khác nhau, thiếu trường, hoặc mâu thuẫn | Hỏi lại / báo ảnh mờ |

- `medium` không phải bảo đảm. Chỉ `high` (QR) là tự động.
- Đo trên 12 ảnh giả lập bị làm hỏng (mờ, nhỏ, nhiễu, xoay): 8 ảnh đúng và tự tin, 4 ảnh bị hạ `low`, 0 ảnh tự tin mà sai. Đây là bill tự vẽ, chưa phải bill ngân hàng thật.
- Đọc ảnh bill **không chứng minh tiền đã vào** (bill giả vẫn đọc ra số "đúng"). Với tiền vào, đối chiếu thêm với giao dịch thật từ ngân hàng (webhook/sao kê) mới chắc.

## Test

    pip install pytest qrcode
    python -m pytest tests          # 107 test
