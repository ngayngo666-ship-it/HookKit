#!/usr/bin/env python3
"""Bot két Telegram — điểm vào duy nhất (python main.py).

Cấu trúc:
  config.py        biến môi trường + nguyên lý vận hành
  bill_scanner.py  đọc ảnh / paste CK → amount, STK, NH, ND, VietQR
  ledger.py        sổ quỹ SQLite (bill chờ, cộng/trừ, phí, chốt)
  nlu.py           hiểu lệnh chữ tiếng Việt (local, không AI)
  excel_export.py  xuất báo cáo .xlsx
  main.py          (file này) nối Telegram ↔ các module trên

Luồng:
  ảnh bill / paste CK  → scan/parse → submit_bill → trả phiếu + QR (nếu đủ)
  nút Xác nhận/Xuất    → confirm_bill / export_bill → answer callback 1 lần
  lệnh chữ             → nlu.understand → Ledger (không tự động trừ chỉ vì chat)
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from bill_scanner import parse_text, scan_image
from excel_export import export_xlsx
from ledger import Ledger, summary_text, vnd
from nlu import understand

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("ket-bot")

# Callback data: action:bill_id
CB_CONFIRM = "cf"
CB_EXPORT = "ex"
CB_REJECT = "rj"


def get_ledger(context: ContextTypes.DEFAULT_TYPE) -> Ledger:
    return context.application.bot_data["ledger"]


def ket_id(chat_id) -> str:
    return str(chat_id)


def uid(user) -> str:
    return str(user.id)


async def ensure_user(lg: Ledger, user) -> None:
    """Bootstrap admin từ env lần đầu; user mới chưa cấp quyền thì Ledger sẽ báo forbidden."""
    for admin_id in config.bootstrap_admin_ids():
        with lg._tx(write=False) as db:
            exists = db.execute("SELECT 1 FROM users WHERE user_id=?", (admin_id,)).fetchone()
        if not exists:
            lg.add_user(admin_id, "admin", name="Admin", actor=None)
            log.info("Bootstrapped admin %s", admin_id)


def bill_keyboard(bill_id: int, direction: str) -> InlineKeyboardMarkup:
    if direction == "out":
        rows = [
            [
                InlineKeyboardButton("✅ Xuất bill (trừ két)", callback_data=f"{CB_EXPORT}:{bill_id}"),
                InlineKeyboardButton("❌ Hủy", callback_data=f"{CB_REJECT}:{bill_id}"),
            ]
        ]
    else:
        rows = [
            [
                InlineKeyboardButton("✅ Xác nhận (cộng két)", callback_data=f"{CB_CONFIRM}:{bill_id}"),
                InlineKeyboardButton("❌ Hủy", callback_data=f"{CB_REJECT}:{bill_id}"),
            ]
        ]
    return InlineKeyboardMarkup(rows)


def format_bill_card(info: dict, r: dict, direction: str) -> str:
    lines = [r.get("message") or ""]
    if info.get("amount"):
        lines.append(f"Số tiền: {vnd(info['amount'])}")
    if info.get("account"):
        lines.append(f"STK: {info['account']}")
    if info.get("bank_name") or info.get("bank"):
        lines.append(f"NH: {info.get('bank_name') or info.get('bank')}")
    if info.get("content"):
        lines.append(f"ND: {info['content']}")
    if info.get("name"):
        lines.append(f"Tên: {info['name']}")
    if info.get("trust"):
        lines.append(f"Tin cậy: {info['trust']}")
    if info.get("missing"):
        lines.append("Thiếu: " + ", ".join(info["missing"]))
    what = "Tiền vào" if direction == "in" else "Tiền ra"
    lines.insert(0, f"📋 {what} #{r.get('bill_id')}")
    return "\n".join(lines)


def looks_like_ck(text: str) -> bool:
    """Đoán tin chuyển khoản / paste CK (không phải lệnh ngắn)."""
    if not text or len(text.strip()) < 8:
        return False
    cmd = understand(text)
    if cmd["intent"] != "unknown":
        return False
    info = parse_text(text)
    return bool(info.get("amount") or info.get("account") or info.get("bank") or info.get("vietqr_url"))


# ---- Handlers -----------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lg = get_ledger(context)
    await ensure_user(lg, update.effective_user)
    await update.message.reply_text(
        "Bot két sẵn sàng.\n"
        "• Gửi ảnh bill hoặc dán CK (STK · NH · số tiền · ND) → QR / phiếu chờ\n"
        "• Nút Xác nhận = cộng két · Xuất bill = trừ két\n"
        "• Lệnh: số dư · bill chờ · xuất excel · chốt sổ · xác nhận #id"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Lệnh nhanh:\n"
        "số dư · bill chờ · lịch sử\n"
        "xác nhận #12 · xuất bill 7 · hủy #5\n"
        "chi 500k tiền điện · thu 1tr\n"
        "xuất excel · chốt sổ\n"
        "Ảnh bill: gửi ảnh (mặc định tiền vào). Caption 'ra'/'out' = tiền ra."
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Nhận ảnh bill → scan → lưu pending → trả lời luôn (QR nếu high/đủ CK)."""
    lg = get_ledger(context)
    user = update.effective_user
    chat = update.effective_chat
    await ensure_user(lg, user)

    photo = update.message.photo[-1]
    tg_file = await photo.get_file()
    raw = bytes(await tg_file.download_as_bytearray())

    caption = (update.message.caption or "").strip().lower()
    direction = "out" if caption in ("ra", "out", "chi", "xuất", "xuat") else config.DEFAULT_DIRECTION

    try:
        info = scan_image(raw)
    except Exception:
        log.exception("scan_image failed")
        await update.message.reply_text("Không đọc được ảnh. Gửi lại ảnh rõ hơn hoặc dán CK dạng chữ.")
        return

    r = lg.submit_bill(
        ket_id(chat.id),
        info,
        actor=uid(user),
        direction=direction,
        image_bytes=raw,
    )
    # Luôn trả lời — không im lặng
    text = format_bill_card(info, r, direction)
    kb = bill_keyboard(r["bill_id"], direction) if r.get("bill_id") and r.get("ok") else None

    if info.get("vietqr_url") and info.get("amount"):
        try:
            await update.message.reply_photo(
                photo=info["vietqr_url"],
                caption=text[:1024],
                reply_markup=kb,
            )
            return
        except Exception:
            log.warning("Gửi QR ảnh thất bại, fallback text")

    await update.message.reply_text(text, reply_markup=kb)


async def handle_ck_or_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tin chữ: lệnh NLU hoặc paste CK → parse local → QR / báo thiếu."""
    lg = get_ledger(context)
    user = update.effective_user
    chat = update.effective_chat
    text = (update.message.text or "").strip()
    if not text:
        return

    await ensure_user(lg, user)
    kid = ket_id(chat.id)
    actor = uid(user)

    cmd = understand(text)

    # --- Lệnh ---
    if cmd["intent"] == "balance":
        bal = lg.balance(kid)
        await update.message.reply_text(f"Số dư két: {vnd(bal)}")
        return

    if cmd["intent"] == "pending":
        rows = lg.pending(kid)
        if not rows:
            await update.message.reply_text("Không có bill chờ.")
            return
        lines = []
        for b in rows:
            amt = vnd(b["amount"]) if b["amount"] else "?"
            d = "vào" if b["direction"] == "in" else "ra"
            lines.append(f"#{b['id']} {d} {amt} {b.get('bank') or ''} {b.get('account') or ''}")
        await update.message.reply_text("Bill chờ:\n" + "\n".join(lines))
        return

    if cmd["intent"] == "history":
        rows = lg.history(kid, limit=10)
        if not rows:
            await update.message.reply_text("Chưa có giao dịch.")
            return
        lines = [f"#{r['id']} {r['kind']} {vnd(r['amount'])} {r.get('note') or ''}" for r in rows]
        await update.message.reply_text("Gần đây:\n" + "\n".join(lines))
        return

    if cmd["intent"] in ("confirm", "export", "reject", "reverse"):
        if not cmd.get("bill_id"):
            await update.message.reply_text("Thiếu mã. Ví dụ: xác nhận #12")
            return
        if cmd["intent"] == "confirm":
            r = lg.confirm_bill(cmd["bill_id"], actor)
        elif cmd["intent"] == "export":
            r = lg.export_bill(cmd["bill_id"], actor)
        elif cmd["intent"] == "reject":
            r = lg.reject_bill(cmd["bill_id"], actor)
        else:
            r = lg.reverse_entry(cmd["bill_id"], actor)
        await update.message.reply_text(r["message"])
        return

    if cmd["intent"] in ("manual_in", "manual_out"):
        direction = "in" if cmd["intent"] == "manual_in" else "out"
        r = lg.create_manual(kid, direction, cmd["amount"], cmd.get("note") or "", actor)
        if r.get("ok") and r.get("bill_id"):
            kb = bill_keyboard(r["bill_id"], direction)
            await update.message.reply_text(r["message"], reply_markup=kb)
        else:
            await update.message.reply_text(r["message"])
        return

    if cmd["intent"] == "report":
        try:
            path = Path(tempfile.gettempdir()) / f"chot_so_{kid}.xlsx"
            export_xlsx(lg, kid, str(path))
            await update.message.reply_document(document=path.open("rb"), filename="bao_cao.xlsx")
        except Exception:
            log.exception("export_xlsx")
            rep = lg.report(kid)
            await update.message.reply_text(summary_text(rep["summary"]) if rep else "Không xuất được báo cáo.")
        return

    if cmd["intent"] == "close":
        note = cmd.get("note")
        r = lg.close_period(kid, actor, note=note)
        await update.message.reply_text(r["message"])
        return

    # --- Paste CK (parse local) ---
    if looks_like_ck(text) or config.ALWAYS_REPLY_ON_CK:
        info = parse_text(text)
        # Có dấu hiệu CK: amount / account / bank
        if info.get("amount") or info.get("account") or info.get("bank"):
            direction = config.DEFAULT_DIRECTION
            # Thiếu ND vẫn giữ số tiền đã có (finalize không xoá amount)
            r = lg.submit_bill(kid, info, actor=actor, direction=direction, source="manual")
            card = format_bill_card(info, r, direction)
            kb = bill_keyboard(r["bill_id"], direction) if r.get("bill_id") and r.get("ok") else None

            if info.get("vietqr_url") and info.get("amount"):
                try:
                    await update.message.reply_photo(
                        photo=info["vietqr_url"],
                        caption=card[:1024],
                        reply_markup=kb,
                    )
                    return
                except Exception:
                    log.warning("QR URL gửi lỗi, gửi text")

            # Đủ hoặc thiếu: luôn trả lời
            if not info.get("complete"):
                missing = ", ".join(info.get("missing") or [])
                card += f"\n⚠️ Thiếu: {missing}. Gửi thêm để ra QR."
            await update.message.reply_text(card, reply_markup=kb)
            return

        # Không phải CK và không phải lệnh đã biết
        if cmd["intent"] == "unknown":
            return

    await update.message.reply_text("Không hiểu lệnh. Gõ /help")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Nút xác nhận / xuất / hủy — answer đúng 1 lần."""
    q = update.callback_query
    lg = get_ledger(context)
    actor = uid(q.from_user)
    await ensure_user(lg, q.from_user)

    data = (q.data or "").split(":")
    if len(data) != 2:
        await q.answer("Nút không hợp lệ.", show_alert=True)
        return
    action, bid_s = data
    try:
        bill_id = int(bid_s)
    except ValueError:
        await q.answer("Mã bill lỗi.", show_alert=True)
        return

    if action == CB_CONFIRM:
        r = lg.confirm_bill(bill_id, actor)
    elif action == CB_EXPORT:
        r = lg.export_bill(bill_id, actor)
    elif action == CB_REJECT:
        r = lg.reject_bill(bill_id, actor)
    else:
        await q.answer("Nút không hợp lệ.", show_alert=True)
        return

    # Đúng 1 lần — không answer "OK" trước rồi nuốt
    await q.answer(r["message"][:200], show_alert=not r.get("ok"))
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    try:
        if q.message:
            await q.message.reply_text(r["message"])
    except Exception:
        log.exception("callback reply")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Handler error: %s", context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("Lỗi xử lý. Thử lại hoặc gửi lại CK.")
        except Exception:
            pass


def build_app() -> Application:
    config.ensure_data_dir()
    token = config.require_token()
    lg = Ledger(
        str(config.DB_PATH),
        big_amount=config.BIG_AMOUNT,
        allow_negative=config.ALLOW_NEGATIVE,
        require_customer=config.REQUIRE_CUSTOMER,
    )
    app = Application.builder().token(token).build()
    app.bot_data["ledger"] = lg

    app.add_handler(CommandHandler(["start", "batdau"], cmd_start))
    app.add_handler(CommandHandler(["help", "trogiup"], cmd_help))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ck_or_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    log.info(
        "Khởi động bot két | db=%s | big_amount=%s | ai_fallback=%s",
        config.DB_PATH,
        config.BIG_AMOUNT,
        config.USE_AI_FALLBACK,
    )
    app = build_app()
    # Một process duy nhất — polling
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)


if __name__ == "__main__":
    main()
