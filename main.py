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

Quan trọng — trả lời ĐÚNG nhóm gửi tin (không chỉ admin chat):
  Khách ở nhóm A gửi lệnh → bot reply trong nhóm A.
  Admin chỉ là người có quyền cao, không phải nơi nhận thay mọi tin.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus, ChatType
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

GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}


def get_ledger(context: ContextTypes.DEFAULT_TYPE) -> Ledger:
    return context.application.bot_data["ledger"]


def ket_id(chat_id) -> str:
    return str(chat_id)


def uid(user) -> str:
    return str(user.id)


def chat_allowed(chat_id) -> bool:
    """Rỗng ALLOWED_CHAT_IDS = mọi nhóm được dùng. Có list thì chỉ các id đó."""
    if not config.ALLOWED_CHAT_IDS:
        return True
    return str(chat_id) in config.ALLOWED_CHAT_IDS


async def reply_here(update: Update, text: str, **kwargs) -> None:
    """Luôn trả lời đúng chat đang nói — không chuyển sang admin chat."""
    msg = update.effective_message
    if not msg:
        return
    await msg.reply_text(text, **kwargs)


async def ensure_user(lg: Ledger, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str | None:
    """Bootstrap admin env; tự cấp quyền thành viên/admin nhóm để khách không bị im.

    Trả về role hiện tại (hoặc None nếu chưa có).
    """
    user = update.effective_user
    chat = update.effective_chat
    if not user or user.is_bot:
        return None

    # Bootstrap admin từ env (user id cá nhân)
    for admin_id in config.bootstrap_admin_ids():
        with lg._tx(write=False) as db:
            exists = db.execute("SELECT 1 FROM users WHERE user_id=?", (admin_id,)).fetchone()
        if not exists:
            lg.add_user(admin_id, "admin", name="Admin", actor=None)
            log.info("Bootstrapped admin user %s", admin_id)

    user_id = uid(user)
    name = (user.full_name or user.username or user_id)[:80]

    with lg._tx(write=False) as db:
        row = db.execute("SELECT role FROM users WHERE user_id=?", (user_id,)).fetchone()
    role = row["role"] if row else None

    # Admin env luôn giữ admin
    if user_id in set(config.bootstrap_admin_ids()):
        if role != "admin":
            lg.add_user(user_id, "admin", name=name, actor=None)
            role = "admin"
        return role

    if not config.AUTO_GRANT_GROUP_MEMBERS:
        return role

    # Trong nhóm: admin/owner Telegram → quan_tri; thành viên → nhan_vien
    if chat and chat.type in GROUP_TYPES:
        try:
            member = await context.bot.get_chat_member(chat.id, user.id)
            is_tg_admin = member.status in (
                ChatMemberStatus.OWNER,
                ChatMemberStatus.ADMINISTRATOR,
            )
        except Exception:
            log.warning("Không lấy được quyền Telegram của %s trong %s", user_id, chat.id)
            is_tg_admin = False

        want = "quan_tri" if is_tg_admin else "nhan_vien"
        # Không hạ admin hệ thống; không đè quan_tri xuống nhan_vien nếu đã có sẵn cao hơn
        rank = {"nhan_vien": 1, "quan_tri": 2, "admin": 3}
        if role is None or rank.get(role, 0) < rank[want]:
            lg.add_user(user_id, want, name=name, actor=None)
            log.info("Auto-grant %s → %s (chat=%s)", user_id, want, chat.id)
            role = want
    elif role is None and chat and chat.type == ChatType.PRIVATE:
        # Chat riêng: cấp nhân viên để vẫn gửi được bill (không im)
        lg.add_user(user_id, "nhan_vien", name=name, actor=None)
        role = "nhan_vien"

    return role


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


async def gate_chat(update: Update) -> bool:
    """True = được xử lý. Sai thì báo ngay trong nhóm đó (không im, không chỉ báo admin)."""
    chat = update.effective_chat
    if not chat:
        return False
    if chat_allowed(chat.id):
        return True
    await reply_here(
        update,
        f"Nhóm này chưa được mở bot (chat_id={chat.id}). Admin thêm id vào ALLOWED_CHAT_IDS.",
    )
    return False


# ---- Handlers -----------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await gate_chat(update):
        return
    lg = get_ledger(context)
    await ensure_user(lg, update, context)
    chat = update.effective_chat
    where = "nhóm này" if chat and chat.type in GROUP_TYPES else "chat này"
    await reply_here(
        update,
        f"Bot két sẵn sàng tại {where}.\n"
        "• Gửi ảnh bill hoặc dán CK (STK · NH · số tiền · ND) → QR / phiếu chờ\n"
        "• Nút Xác nhận = cộng két · Xuất bill = trừ két\n"
        "• Lệnh: số dư · bill chờ · xuất excel · chốt sổ · xác nhận #id\n"
        "• /kiemtra — kiểm tra bot có thấy tin trong nhóm không",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await gate_chat(update):
        return
    await reply_here(
        update,
        "Lệnh nhanh:\n"
        "số dư · bill chờ · lịch sử\n"
        "xác nhận #12 · xuất bill 7 · hủy #5\n"
        "chi 500k tiền điện · thu 1tr\n"
        "xuất excel · chốt sổ\n"
        "/kiemtra — bot có nhận tin nhóm?\n"
        "Ảnh bill: gửi ảnh (mặc định tiền vào). Caption 'ra'/'out' = tiền ra.",
    )


async def cmd_kiemtra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Kiểm tra bot có là admin nhóm + có trả lời đúng chat này không."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    lines = [
        f"Chat id: `{chat.id}`",
        f"Loại: {chat.type}",
        f"User id: `{user.id}`",
        f"Allowed: {'có' if chat_allowed(chat.id) else 'KHÔNG — thêm vào ALLOWED_CHAT_IDS'}",
    ]

    if chat.type in GROUP_TYPES:
        try:
            me = await context.bot.get_chat_member(chat.id, context.bot.id)
            bot_admin = me.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
            lines.append(f"Bot là quản trị nhóm: {'CÓ' if bot_admin else 'KHÔNG'}")
            if not bot_admin:
                lines.append(
                    "→ Cấp bot làm Quản trị nhóm (hoặc tắt Privacy trên BotFather: /setprivacy → Disable) "
                    "để bot thấy tin thường, không chỉ lệnh /slash."
                )
        except Exception as exc:
            lines.append(f"Không kiểm tra được quyền bot: {exc}")
    else:
        lines.append("Đây là chat riêng — bot luôn thấy tin.")

    lg = get_ledger(context)
    role = await ensure_user(lg, update, context)
    lines.append(f"Quyền sổ của bạn: {role or 'chưa có'}")
    lines.append("Bot sẽ trả lời NGAY trong chat này (không chuyển sang admin).")

    await reply_here(update, "\n".join(lines))


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Nhận ảnh bill → scan → lưu pending → trả lời luôn đúng nhóm gửi."""
    if not await gate_chat(update):
        return
    lg = get_ledger(context)
    user = update.effective_user
    chat = update.effective_chat
    await ensure_user(lg, update, context)
    log.info("photo chat=%s user=%s", chat.id if chat else "?", uid(user) if user else "?")

    photo = update.message.photo[-1]
    tg_file = await photo.get_file()
    raw = bytes(await tg_file.download_as_bytearray())

    caption = (update.message.caption or "").strip().lower()
    direction = "out" if caption in ("ra", "out", "chi", "xuất", "xuat") else config.DEFAULT_DIRECTION

    try:
        info = scan_image(raw)
    except Exception:
        log.exception("scan_image failed")
        await reply_here(update, "Không đọc được ảnh. Gửi lại ảnh rõ hơn hoặc dán CK dạng chữ.")
        return

    r = lg.submit_bill(
        ket_id(chat.id),
        info,
        actor=uid(user),
        direction=direction,
        image_bytes=raw,
    )
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
    """Tin chữ: lệnh NLU hoặc paste CK — luôn reply đúng nhóm khách gửi."""
    if not await gate_chat(update):
        return
    lg = get_ledger(context)
    user = update.effective_user
    chat = update.effective_chat
    text = (update.message.text or "").strip()
    if not text:
        return

    await ensure_user(lg, update, context)
    kid = ket_id(chat.id)
    actor = uid(user)
    log.info("text chat=%s user=%s len=%s", chat.id, actor, len(text))

    cmd = understand(text)

    # --- Lệnh ---
    if cmd["intent"] == "balance":
        bal = lg.balance(kid)
        await reply_here(update, f"Số dư két: {vnd(bal)}")
        return

    if cmd["intent"] == "pending":
        rows = lg.pending(kid)
        if not rows:
            await reply_here(update, "Không có bill chờ.")
            return
        lines = []
        for b in rows:
            amt = vnd(b["amount"]) if b["amount"] else "?"
            d = "vào" if b["direction"] == "in" else "ra"
            lines.append(f"#{b['id']} {d} {amt} {b.get('bank') or ''} {b.get('account') or ''}")
        await reply_here(update, "Bill chờ:\n" + "\n".join(lines))
        return

    if cmd["intent"] == "history":
        rows = lg.history(kid, limit=10)
        if not rows:
            await reply_here(update, "Chưa có giao dịch.")
            return
        lines = [f"#{r['id']} {r['kind']} {vnd(r['amount'])} {r.get('note') or ''}" for r in rows]
        await reply_here(update, "Gần đây:\n" + "\n".join(lines))
        return

    if cmd["intent"] in ("confirm", "export", "reject", "reverse"):
        if not cmd.get("bill_id"):
            await reply_here(update, "Thiếu mã. Ví dụ: xác nhận #12")
            return
        if cmd["intent"] == "confirm":
            r = lg.confirm_bill(cmd["bill_id"], actor)
        elif cmd["intent"] == "export":
            r = lg.export_bill(cmd["bill_id"], actor)
        elif cmd["intent"] == "reject":
            r = lg.reject_bill(cmd["bill_id"], actor)
        else:
            r = lg.reverse_entry(cmd["bill_id"], actor)
        await reply_here(update, r["message"])
        return

    if cmd["intent"] in ("manual_in", "manual_out"):
        direction = "in" if cmd["intent"] == "manual_in" else "out"
        r = lg.create_manual(kid, direction, cmd["amount"], cmd.get("note") or "", actor)
        if r.get("ok") and r.get("bill_id"):
            kb = bill_keyboard(r["bill_id"], direction)
            await update.message.reply_text(r["message"], reply_markup=kb)
        else:
            await reply_here(update, r["message"])
        return

    if cmd["intent"] == "report":
        try:
            path = Path(tempfile.gettempdir()) / f"chot_so_{kid}.xlsx"
            export_xlsx(lg, kid, str(path))
            await update.message.reply_document(document=path.open("rb"), filename="bao_cao.xlsx")
        except Exception:
            log.exception("export_xlsx")
            rep = lg.report(kid)
            await reply_here(update, summary_text(rep["summary"]) if rep else "Không xuất được báo cáo.")
        return

    if cmd["intent"] == "close":
        note = cmd.get("note")
        r = lg.close_period(kid, actor, note=note)
        await reply_here(update, r["message"])
        return

    # --- Paste CK (parse local) ---
    if looks_like_ck(text) or config.ALWAYS_REPLY_ON_CK:
        info = parse_text(text)
        if info.get("amount") or info.get("account") or info.get("bank"):
            direction = config.DEFAULT_DIRECTION
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

            if not info.get("complete"):
                missing = ", ".join(info.get("missing") or [])
                card += f"\n⚠️ Thiếu: {missing}. Gửi thêm để ra QR."
            await update.message.reply_text(card, reply_markup=kb)
            return

        if cmd["intent"] == "unknown":
            return

    await reply_here(update, "Không hiểu lệnh. Gõ /help")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Nút xác nhận / xuất / hủy — answer đúng 1 lần, reply đúng nhóm."""
    q = update.callback_query
    if not await gate_chat(update):
        await q.answer("Nhóm chưa mở bot.", show_alert=True)
        return
    lg = get_ledger(context)
    await ensure_user(lg, update, context)
    actor = uid(q.from_user)

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
    app.add_handler(CommandHandler(["kiemtra", "check"], cmd_kiemtra))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ck_or_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    log.info(
        "Khởi động bot két | db=%s | allowed_chats=%s | auto_grant=%s",
        config.DB_PATH,
        config.ALLOWED_CHAT_IDS or "ALL",
        config.AUTO_GRANT_GROUP_MEMBERS,
    )
    app = build_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)


if __name__ == "__main__":
    main()
