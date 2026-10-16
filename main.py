#!/usr/bin/env python3
"""Bot két Telegram — điểm vào duy nhất (python main.py).

Đồng bộ mọi nhóm:
  - Đọc CK chữ (STK · NH · số tiền · ND) + ảnh QR/bill (photo hoặc file ảnh)
  - Trả lời đúng nhóm khách gửi
  - Cùng bộ chức năng (groups.SYNCED_FEATURES) trên mọi nhóm đã mở
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
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from bill_scanner import merge_payment_info, parse_text, scan_image
from excel_export import export_xlsx
from groups import SYNCED_FEATURES, GroupRegistry
from ledger import Ledger, summary_text, vnd
from nlu import understand

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("ket-bot")

CB_CONFIRM = "cf"
CB_EXPORT = "ex"
CB_REJECT = "rj"
GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}
IMAGE_MIME_PREFIXES = ("image/",)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def get_ledger(context: ContextTypes.DEFAULT_TYPE) -> Ledger:
    return context.application.bot_data["ledger"]


def get_groups(context: ContextTypes.DEFAULT_TYPE) -> GroupRegistry:
    return context.application.bot_data["groups"]


def resolve_ket_id(chat_id) -> str:
    """Sổ quỹ: SHARED_KET_ID nếu đồng bộ két; không thì mỗi nhóm một sổ."""
    if config.SHARED_KET_ID:
        return config.SHARED_KET_ID
    return str(chat_id)


def uid(user) -> str:
    return str(user.id)


def chat_allowed(chat_id) -> bool:
    if not config.ALLOWED_CHAT_IDS:
        return True
    return str(chat_id) in config.ALLOWED_CHAT_IDS


async def reply_here(update: Update, text: str, **kwargs) -> None:
    msg = update.effective_message
    if not msg:
        return
    await msg.reply_text(text, **kwargs)


def sync_group(context: ContextTypes.DEFAULT_TYPE, chat) -> dict | None:
    """Ghi nhận nhóm + ép cùng bộ chức năng đồng bộ."""
    if not chat:
        return None
    reg = get_groups(context)
    title = getattr(chat, "title", None) or getattr(chat, "full_name", None)
    return reg.touch(chat.id, title=title, enabled=True)


async def ensure_user(lg: Ledger, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str | None:
    user = update.effective_user
    chat = update.effective_chat
    if not user or user.is_bot:
        return None

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

    if user_id in set(config.bootstrap_admin_ids()):
        if role != "admin":
            lg.add_user(user_id, "admin", name=name, actor=None)
            role = "admin"
        return role

    if not config.AUTO_GRANT_GROUP_MEMBERS:
        return role

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
        rank = {"nhan_vien": 1, "quan_tri": 2, "admin": 3}
        if role is None or rank.get(role, 0) < rank[want]:
            lg.add_user(user_id, want, name=name, actor=None)
            log.info("Auto-grant %s → %s (chat=%s)", user_id, want, chat.id)
            role = want
    elif role is None and chat and chat.type == ChatType.PRIVATE:
        lg.add_user(user_id, "nhan_vien", name=name, actor=None)
        role = "nhan_vien"

    return role


def bill_keyboard(bill_id: int, direction: str) -> InlineKeyboardMarkup:
    if direction == "out":
        rows = [[
            InlineKeyboardButton("✅ Xuất bill (trừ két)", callback_data=f"{CB_EXPORT}:{bill_id}"),
            InlineKeyboardButton("❌ Hủy", callback_data=f"{CB_REJECT}:{bill_id}"),
        ]]
    else:
        rows = [[
            InlineKeyboardButton("✅ Xác nhận (cộng két)", callback_data=f"{CB_CONFIRM}:{bill_id}"),
            InlineKeyboardButton("❌ Hủy", callback_data=f"{CB_REJECT}:{bill_id}"),
        ]]
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
    if not text or len(text.strip()) < 8:
        return False
    cmd = understand(text)
    if cmd["intent"] != "unknown":
        return False
    info = parse_text(text)
    return bool(info.get("amount") or info.get("account") or info.get("bank") or info.get("vietqr_url"))


def direction_from_caption(caption: str | None) -> str:
    c = (caption or "").strip().lower()
    if c in ("ra", "out", "chi", "xuất", "xuat") or c.startswith("ra ") or c.startswith("chi "):
        return "out"
    return config.DEFAULT_DIRECTION


async def gate_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    if not chat:
        return False
    if not chat_allowed(chat.id):
        await reply_here(
            update,
            f"Nhóm này chưa được mở bot (chat_id={chat.id}). Admin thêm id vào ALLOWED_CHAT_IDS.",
        )
        return False
    sync_group(context, chat)
    reg = get_groups(context)
    if not reg.is_enabled(chat.id):
        await reply_here(update, "Nhóm này đang tắt bot.")
        return False
    return True


async def send_bill_result(update: Update, info: dict, r: dict, direction: str) -> None:
    text = format_bill_card(info, r, direction)
    kb = bill_keyboard(r["bill_id"], direction) if r.get("bill_id") and r.get("ok") else None
    if not info.get("complete"):
        missing = ", ".join(info.get("missing") or [])
        text += f"\n⚠️ Thiếu: {missing}. Gửi thêm STK/NH/số tiền/ND hoặc ảnh QR."

    if info.get("vietqr_url") and info.get("amount"):
        try:
            await update.effective_message.reply_photo(
                photo=info["vietqr_url"],
                caption=text[:1024],
                reply_markup=kb,
            )
            return
        except Exception:
            log.warning("Gửi QR ảnh thất bại, fallback text")
    await update.effective_message.reply_text(text, reply_markup=kb)


async def process_payment_image(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    raw: bytes,
    caption: str | None,
) -> None:
    """Đọc ảnh QR/bill + gộp caption chữ → submit + trả lời đúng nhóm."""
    lg = get_ledger(context)
    user = update.effective_user
    chat = update.effective_chat
    await ensure_user(lg, update, context)
    kid = resolve_ket_id(chat.id)
    direction = direction_from_caption(caption)

    try:
        img_info = scan_image(raw)
    except Exception:
        log.exception("scan_image failed chat=%s", chat.id if chat else "?")
        img_info = {}

    text_info = parse_text(caption) if caption and len(caption.strip()) >= 3 else {}
    # Bỏ hướng "ra/out" khỏi parse nếu caption chỉ là hướng
    if caption and caption.strip().lower() in ("ra", "out", "chi", "xuất", "xuat"):
        text_info = {}

    info = merge_payment_info(img_info, text_info)
    log.info(
        "payment_image chat=%s user=%s amount=%s account=%s bank=%s trust=%s",
        chat.id, uid(user), info.get("amount"), info.get("account"), info.get("bank"), info.get("trust"),
    )

    if not (info.get("amount") or info.get("account") or info.get("bank") or info.get("vietqr_url")):
        await reply_here(
            update,
            "Chưa đọc được thông tin thanh toán từ ảnh. "
            "Gửi lại ảnh QR rõ hơn hoặc dán CK: STK | Ngân hàng | số tiền | nội dung.",
        )
        return

    r = lg.submit_bill(
        kid,
        info,
        actor=uid(user),
        direction=direction,
        image_bytes=raw,
    )
    await send_bill_result(update, info, r, direction)


# ---- Handlers -----------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await gate_chat(update, context):
        return
    lg = get_ledger(context)
    await ensure_user(lg, update, context)
    chat = update.effective_chat
    where = "nhóm này" if chat and chat.type in GROUP_TYPES else "chat này"
    feats = ", ".join(k for k, v in SYNCED_FEATURES.items() if v)
    await reply_here(
        update,
        f"Bot két sẵn sàng tại {where} (đồng bộ chức năng mọi nhóm).\n"
        "• Dán CK hoặc gửi ảnh QR/bill → đọc STK, NH, số tiền, ND → QR / phiếu\n"
        "• Nút Xác nhận = cộng két · Xuất bill = trừ két\n"
        "• /kiemtra · /nhom — kiểm tra nhóm & chức năng\n"
        f"• Đang bật: {feats}",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await gate_chat(update, context):
        return
    await reply_here(
        update,
        "Lệnh nhanh:\n"
        "số dư · bill chờ · lịch sử\n"
        "xác nhận #12 · xuất bill 7 · hủy #5\n"
        "chi 500k tiền điện · thu 1tr\n"
        "xuất excel · chốt sổ\n"
        "/kiemtra · /nhom\n"
        "Gửi ảnh QR/bill (photo hoặc file ảnh) hoặc dán CK chữ.",
    )


async def cmd_kiemtra(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return
    sync_group(context, chat)
    feats = get_groups(context).features(chat.id)
    lines = [
        f"Chat id: `{chat.id}`",
        f"Loại: {chat.type}",
        f"User id: `{user.id}`",
        f"Két id: `{resolve_ket_id(chat.id)}`",
        f"Allowed: {'có' if chat_allowed(chat.id) else 'KHÔNG'}",
        "Chức năng đồng bộ:",
    ]
    for k, v in feats.items():
        lines.append(f"  • {k}: {'ON' if v else 'off'}")

    if chat.type in GROUP_TYPES:
        try:
            me = await context.bot.get_chat_member(chat.id, context.bot.id)
            bot_admin = me.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
            lines.append(f"Bot quản trị nhóm: {'CÓ' if bot_admin else 'KHÔNG'}")
            if not bot_admin:
                lines.append(
                    "→ Cấp bot làm Quản trị (hoặc BotFather /setprivacy → Disable) "
                    "để đọc hết tin CK + ảnh QR khách gửi."
                )
        except Exception as exc:
            lines.append(f"Không kiểm tra được quyền bot: {exc}")

    lg = get_ledger(context)
    role = await ensure_user(lg, update, context)
    lines.append(f"Quyền sổ của bạn: {role or 'chưa có'}")
    lines.append("Bot trả lời NGAY trong chat này.")
    await reply_here(update, "\n".join(lines))


async def cmd_nhom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Liệt kê nhóm đã đồng bộ cấu hình (admin)."""
    if not await gate_chat(update, context):
        return
    lg = get_ledger(context)
    role = await ensure_user(lg, update, context)
    if role not in ("admin", "quan_tri"):
        await reply_here(update, "Chỉ Quản trị/Admin xem danh sách nhóm.")
        return
    rows = get_groups(context).list_groups()
    if not rows:
        await reply_here(update, "Chưa có nhóm nào được ghi nhận.")
        return
    lines = [f"Đã đồng bộ {len(rows)} nhóm (cùng chức năng):"]
    for g in rows[:30]:
        on = "ON" if g.get("enabled") else "off"
        lines.append(f"• {g.get('title') or '?'} (`{g['chat_id']}`) {on}")
    await reply_here(update, "\n".join(lines))


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await gate_chat(update, context):
        return
    feats = get_groups(context).features(update.effective_chat.id)
    if not feats.get("read_qr_image", True):
        await reply_here(update, "Nhóm này đang tắt đọc ảnh QR.")
        return
    photo = update.message.photo[-1]
    tg_file = await photo.get_file()
    raw = bytes(await tg_file.download_as_bytearray())
    await process_payment_image(update, context, raw, update.message.caption)


async def handle_image_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ảnh QR/bill gửi dạng file (không nén) — cùng luồng đọc như photo."""
    if not await gate_chat(update, context):
        return
    if not config.READ_IMAGE_DOCUMENTS:
        return
    feats = get_groups(context).features(update.effective_chat.id)
    if not feats.get("read_image_file", True):
        return

    doc = update.message.document
    if not doc:
        return
    mime = (doc.mime_type or "").lower()
    name = (doc.file_name or "").lower()
    ok_mime = mime.startswith(IMAGE_MIME_PREFIXES)
    ok_name = any(name.endswith(suf) for suf in IMAGE_SUFFIXES)
    if not (ok_mime or ok_name):
        return
    if doc.file_size and doc.file_size > 15 * 1024 * 1024:
        await reply_here(update, "Ảnh quá nặng (>15MB). Gửi ảnh nhỏ hơn hoặc dạng photo.")
        return

    tg_file = await doc.get_file()
    raw = bytes(await tg_file.download_as_bytearray())
    await process_payment_image(update, context, raw, update.message.caption)


async def handle_ck_or_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await gate_chat(update, context):
        return
    lg = get_ledger(context)
    user = update.effective_user
    chat = update.effective_chat
    text = (update.message.text or "").strip()
    if not text:
        return

    await ensure_user(lg, update, context)
    kid = resolve_ket_id(chat.id)
    actor = uid(user)
    feats = get_groups(context).features(chat.id)
    log.info("text chat=%s user=%s len=%s", chat.id, actor, len(text))

    cmd = understand(text)

    if cmd["intent"] != "unknown" and not feats.get("commands", True):
        await reply_here(update, "Lệnh chữ đang tắt trên nhóm này.")
        return

    if cmd["intent"] == "balance":
        await reply_here(update, f"Số dư két: {vnd(lg.balance(kid))}")
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
            await update.message.reply_text(r["message"], reply_markup=bill_keyboard(r["bill_id"], direction))
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
        r = lg.close_period(kid, actor, note=cmd.get("note"))
        await reply_here(update, r["message"])
        return

    # Paste CK
    if not feats.get("read_ck_text", True):
        if cmd["intent"] == "unknown":
            return
        await reply_here(update, "Đọc CK chữ đang tắt trên nhóm này.")
        return

    if looks_like_ck(text) or config.ALWAYS_REPLY_ON_CK:
        info = parse_text(text)
        if info.get("amount") or info.get("account") or info.get("bank"):
            direction = config.DEFAULT_DIRECTION
            r = lg.submit_bill(kid, info, actor=actor, direction=direction, source="manual")
            await send_bill_result(update, info, r, direction)
            return
        if cmd["intent"] == "unknown":
            return

    await reply_here(update, "Không hiểu lệnh. Gõ /help")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not await gate_chat(update, context):
        await q.answer("Nhóm chưa mở bot.", show_alert=True)
        return
    feats = get_groups(context).features(update.effective_chat.id)
    if not feats.get("confirm_buttons", True):
        await q.answer("Nút xác nhận đang tắt.", show_alert=True)
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


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Bot được thêm vào nhóm → bật ngay cùng cấu hình đồng bộ."""
    mcm = update.my_chat_member
    if not mcm:
        return
    chat = mcm.chat
    new = mcm.new_chat_member
    if new.user.id != context.bot.id:
        return
    status = new.status
    if status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR):
        sync_group(context, chat)
        log.info("Bot joined/enabled chat=%s title=%s", chat.id, getattr(chat, "title", None))
        try:
            await context.bot.send_message(
                chat.id,
                "Bot két đã vào nhóm — cấu hình đồng bộ với các nhóm khác.\n"
                "Khách gửi ảnh QR/bill hoặc dán CK → bot đọc và trả lời tại đây.\n"
                "Nên cấp bot làm Quản trị (hoặc tắt Privacy) để đọc hết tin.\n"
                "Gõ /kiemtra để kiểm tra.",
            )
        except Exception:
            log.warning("Không gửi được tin chào nhóm %s", chat.id)
    elif status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
        get_groups(context).touch(chat.id, title=getattr(chat, "title", None), enabled=False)
        log.info("Bot left/disabled chat=%s", chat.id)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Handler error: %s", context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("Lỗi xử lý. Thử lại hoặc gửi lại CK/ảnh QR.")
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
    groups = GroupRegistry(config.GROUPS_DB_PATH)
    app = Application.builder().token(token).build()
    app.bot_data["ledger"] = lg
    app.bot_data["groups"] = groups

    app.add_handler(CommandHandler(["start", "batdau"], cmd_start))
    app.add_handler(CommandHandler(["help", "trogiup"], cmd_help))
    app.add_handler(CommandHandler(["kiemtra", "check"], cmd_kiemtra))
    app.add_handler(CommandHandler(["nhom", "groups"], cmd_nhom))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_image_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ck_or_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    log.info(
        "Khởi động bot két | db=%s | groups=%s | allowed=%s | shared_ket=%s | sync=%s",
        config.DB_PATH,
        config.GROUPS_DB_PATH,
        config.ALLOWED_CHAT_IDS or "ALL",
        config.SHARED_KET_ID or "(per-chat)",
        config.SYNC_ALL_GROUPS,
    )
    app = build_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)


if __name__ == "__main__":
    main()
