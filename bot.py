import logging
from collections import defaultdict
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ForceReply,
)
from telegram.error import Forbidden, BadRequest
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from config import BOT_TOKEN, ADMIN_IDS, MAX_MESSAGES_PER_MINUTE
from database import (
    init_db,
    block_user,
    unblock_user,
    is_blocked,
    get_all_blocked,
    save_message,
    mark_thread_replied,
    save_thread_link,
    get_thread_link,
    get_stats,
    get_category_stats,
)

# -------- لاگ‌گیری --------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def is_admin(user_id: int) -> bool:
    """بررسی اینکه آیا کاربر یکی از ادمین‌هاست"""
    return user_id in ADMIN_IDS


# -------- دسته‌بندی پیام‌ها --------
CATEGORIES = {
    "suggestion": "💡 پیشنهاد",
    "criticism": "⚠️ انتقاد",
    "romantic": "❤️ عاشقانه",
    "question": "❓ سوال",
    "other": "✉️ سایر",
}


def category_keyboard() -> InlineKeyboardMarkup:
    """ساخت کیبورد انتخاب دسته‌بندی پیام"""
    items = list(CATEGORIES.items())
    rows = []
    for i in range(0, len(items), 2):
        pair = items[i:i + 2]
        rows.append([InlineKeyboardButton(label, callback_data=f"cat:{code}") for code, label in pair])
    return InlineKeyboardMarkup(rows)


def admin_keyboard(user_id: int, thread_id: int) -> InlineKeyboardMarkup:
    """کیبورد استاندارد ادمین برای هر پیام (پاسخ / مسدود / رفع مسدودیت)"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✉️ پاسخ", callback_data=f"reply:{user_id}:{thread_id}"),
            InlineKeyboardButton("⛔ مسدود", callback_data=f"block_confirm:{user_id}"),
        ],
        [InlineKeyboardButton("🔓 رفع مسدودیت", callback_data=f"unblock:{user_id}")],
    ])


async def notify_all_admins(context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None, exclude: int | None = None):
    """ارسال پیام به تمام ادمین‌ها (به‌جز ادمینی که exclude شده، اگر مشخص شده باشد)"""
    for admin_id in ADMIN_IDS:
        if admin_id == exclude:
            continue
        try:
            await context.bot.send_message(chat_id=admin_id, text=text, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"خطا در ارسال پیام به ادمین {admin_id}: {e}")


# -------- Rate Limiting (در RAM — فقط شمارنده موقت) --------
user_message_times: dict[int, list[datetime]] = defaultdict(list)


def is_rate_limited(user_id: int) -> bool:
    """بررسی اینکه آیا کاربر بیش از حد پیام فرستاده"""
    now = datetime.now()
    cutoff = now - timedelta(minutes=1)
    times = [t for t in user_message_times[user_id] if t > cutoff]
    user_message_times[user_id] = times
    if len(times) >= MAX_MESSAGES_PER_MINUTE:
        return True
    user_message_times[user_id].append(now)
    return False


# -------- /start --------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """خوشامدگویی به کاربر"""
    user = update.effective_user
    if is_blocked(user.id):
        return
    await update.message.reply_text(
        "سلام ❤️\n"
        "پیامی که می‌خوای به صورت ناشناس بفرستی رو اینجا بنویس.\n"
        "بعد از فرستادن، دسته پیامت رو انتخاب کن تا برای ادمین ارسال شه.\n\n"
        "وقتی ادمین جواب داد، کافیه روی همون پیام Reply بزنی تا گفتگو ادامه پیدا کنه 💬\n\n"
        "برای دیدن منو: /menu"
    )
    logger.info(f"کاربر {user.id} (@{user.username}) استارت زد.")


# -------- /menu --------
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """نمایش منوی دکمه‌ای ربات"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 راهنما", callback_data="menu:help")],
        [InlineKeyboardButton("ℹ️ درباره ربات", callback_data="menu:about")],
    ])
    await update.message.reply_text("📋 منو:", reply_markup=keyboard)


# -------- /stats (فقط ادمین) --------
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """نمایش آمار ربات به ادمین"""
    if not is_admin(update.effective_user.id):
        return
    s = get_stats()
    text = (
        "📊 آمار ربات\n\n"
        f"📩 کل پیام‌ها: {s['total_messages']}\n"
        f"👥 کاربران منحصربه‌فرد: {s['unique_users']}\n"
        f"⛔ کاربران مسدود: {s['blocked_count']}\n"
        f"📭 پیام‌های بی‌پاسخ: {s['unanswered']}\n"
    )
    cat_stats = get_category_stats()
    if cat_stats:
        text += "\n🏷 دسته‌بندی پیام‌ها:\n"
        for code, cnt in cat_stats.items():
            text += f"{CATEGORIES.get(code, code)}: {cnt}\n"
    await update.message.reply_text(text)


# -------- /blocked (فقط ادمین) --------
async def blocked_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """لیست کاربران مسدود"""
    if not is_admin(update.effective_user.id):
        return
    blocked = get_all_blocked()
    if not blocked:
        await update.message.reply_text("هیچ کاربری مسدود نشده ✅")
        return
    lines = ["⛔ کاربران مسدود شده:\n"]
    for b in blocked:
        lines.append(f"🆔 {b['user_id']} — {b['blocked_at'][:10]}")
    await update.message.reply_text("\n".join(lines))


# -------- /unblock (فقط ادمین) --------
async def unblock_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """رفع مسدودیت با دستور /unblock user_id"""
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("فرمت صحیح:\n/unblock 123456789")
        return
    uid = int(args[0])
    if unblock_user(uid):
        await update.message.reply_text(f"✅ کاربر {uid} از مسدودیت خارج شد.")
        logger.info(f"ادمین کاربر {uid} را آنبلاک کرد.")
    else:
        await update.message.reply_text(f"⚠️ کاربر {uid} در لیست مسدودها نبود.")


# -------- /admins (فقط ادمین) --------
async def admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """نمایش لیست ادمین‌های فعلی ربات"""
    if not is_admin(update.effective_user.id):
        return
    lines = ["👮 ادمین‌های فعلی ربات:\n"]
    for admin_id in ADMIN_IDS:
        lines.append(f"🆔 {admin_id}")
    lines.append(
        "\nبرای افزودن یا حذف ادمین، متغیر ADMIN_IDS را در تنظیمات Railway "
        "ویرایش کن (آیدی‌های عددی را با کاما جدا کن)."
    )
    await update.message.reply_text("\n".join(lines))


# -------- پیام متنی کاربران --------
async def user_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دریافت پیام متنی از کاربر — ادامه گفتگو یا شروع گفتگوی جدید با دسته‌بندی"""
    user = update.effective_user
    if is_admin(user.id):
        return
    if is_blocked(user.id):
        await update.message.reply_text("⛔ شما توسط ادمین مسدود شده‌اید.")
        return
    if is_rate_limited(user.id):
        await update.message.reply_text(
            "⚠️ خیلی سریع پیام می‌فرستی! لطفاً چند لحظه صبر کن."
        )
        return

    text = update.message.text
    username = user.username or "NoUsername"

    # آیا این پیام ادامه‌ی یک گفتگوی قبلیه؟ (ریپلای به جواب ادمین)
    reply_to = update.message.reply_to_message
    thread_id = get_thread_link(reply_to.message_id, user.id) if reply_to else None

    if thread_id:
        # ادامه گفتگو — نیازی به دسته‌بندی نیست
        _, thread_id = save_message(user.id, username, text, media_type="text", thread_id=thread_id)
        msg = (
            f"💬 پاسخ جدید در گفتگو #{thread_id}\n\n"
            f"👤 @{username} | 🆔 {user.id}\n\n"
            f"✉️ متن:\n{text}"
        )
        await notify_all_admins(context, msg, reply_markup=admin_keyboard(user.id, thread_id))
        await update.message.reply_text("✅ پاسخ شما در ادامه گفتگو ارسال شد.")
        logger.info(f"پیام جدید در گفتگو #{thread_id} از کاربر {user.id}.")
        return

    # پیام جدید — اول دسته‌بندی کن
    context.user_data["pending_message"] = {"text": text}
    await update.message.reply_text(
        "این پیام رو در چه دسته‌ای قرار می‌دی؟",
        reply_markup=category_keyboard(),
    )


# -------- پیام مدیا (عکس، ویس، ویدیو، فایل) --------
async def user_media_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دریافت مدیا از کاربر و forward به همه ادمین‌ها"""
    user = update.effective_user
    if is_admin(user.id):
        return
    if is_blocked(user.id):
        await update.message.reply_text("⛔ شما توسط ادمین مسدود شده‌اید.")
        return
    if is_rate_limited(user.id):
        await update.message.reply_text("⚠️ خیلی سریع پیام می‌فرستی! لطفاً صبر کن.")
        return

    username = user.username or "NoUsername"

    if update.message.photo:
        media_type = "photo"
    elif update.message.voice:
        media_type = "voice"
    elif update.message.video:
        media_type = "video"
    elif update.message.document:
        media_type = "document"
    else:
        media_type = "other"

    caption = update.message.caption or ""

    reply_to = update.message.reply_to_message
    existing_thread_id = get_thread_link(reply_to.message_id, user.id) if reply_to else None
    is_continuation = existing_thread_id is not None

    _, thread_id = save_message(
        user.id, username, caption or f"[{media_type}]",
        media_type=media_type, thread_id=existing_thread_id
    )

    if is_continuation:
        header = (
            f"💬 پاسخ جدید (مدیا) در گفتگو #{thread_id}\n"
            f"👤 @{username} | 🆔 {user.id}\nنوع: {media_type}"
        )
    else:
        header = (
            f"📩 پیام جدید (مدیا) — گفتگو #{thread_id}\n"
            f"👤 @{username} | 🆔 {user.id}\nنوع: {media_type}"
        )

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=header)
            await update.message.forward(chat_id=admin_id)
            await context.bot.send_message(
                chat_id=admin_id, text="⬆️ پیام بالا", reply_markup=admin_keyboard(user.id, thread_id)
            )
        except Exception as e:
            logger.error(f"خطا در forward مدیا به ادمین {admin_id}: {e}")

    await update.message.reply_text("✅ پیام شما به صورت ناشناس ارسال شد.")


# -------- دکمه‌ها --------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """مدیریت کلیک روی دکمه‌های شیشه‌ای"""
    query = update.callback_query
    await query.answer()

    data = query.data
    parts = data.split(":")
    action = parts[0]

    # ---- منو (برای همه کاربران) ----
    if action == "menu":
        section = parts[1]
        if section == "help":
            text = (
                "📖 راهنما:\n\n"
                "• پیامت رو بنویس\n"
                "• یکی از دسته‌ها رو انتخاب کن (پیشنهاد، انتقاد، عاشقانه، سوال، سایر)\n"
                "• پیام به صورت کامل ناشناس برای ادمین ارسال میشه\n"
                "• وقتی ادمین جواب داد، روی همون پیام Reply بزن تا گفتگو ادامه پیدا کنه"
            )
        else:
            text = "ℹ️ این ربات یک سیستم چت ناشناس است. پیام‌هایت بدون مشخصات شخصی برای ادمین ارسال می‌شود ❤️"
        await query.message.reply_text(text)
        return

    # ---- انتخاب دسته‌بندی پیام جدید (برای کاربر فرستنده) ----
    if action == "cat":
        code = parts[1]
        pending = context.user_data.get("pending_message")
        if not pending:
            await query.edit_message_text("⚠️ این پیام منقضی شده. لطفاً پیام جدیدی بفرست.")
            return
        user = query.from_user
        username = user.username or "NoUsername"
        text = pending["text"]
        _, thread_id = save_message(user.id, username, text, media_type="text", category=code)
        label = CATEGORIES.get(code, "✉️ سایر")
        admin_msg = (
            f"📩 پیام جدید — گفتگو #{thread_id}\n"
            f"🏷 دسته: {label}\n\n"
            f"👤 @{username} | 🆔 {user.id}\n\n"
            f"✉️ متن:\n{text}"
        )
        await notify_all_admins(context, admin_msg, reply_markup=admin_keyboard(user.id, thread_id))
        await query.edit_message_text(f"✅ پیام شما (دسته: {label}) به صورت ناشناس ارسال شد.")
        context.user_data.pop("pending_message", None)
        logger.info(f"پیام #{thread_id} (دسته: {code}) از کاربر {user.id} دریافت شد.")
        return

    # ---- از این به بعد فقط ادمین‌ها ----
    if not is_admin(query.from_user.id):
        return

    if action == "reply":
        user_id = int(parts[1])
        thread_id = int(parts[2])
        context.user_data["pending_reply"] = {"user_id": user_id, "thread_id": thread_id}
        sent = await query.message.reply_text(
            f"✏️ پاسخ به گفتگو #{thread_id} را بنویسید:",
            reply_markup=ForceReply(selective=True),
        )
        context.user_data["force_reply_msg_id"] = sent.message_id

    elif action == "block_confirm":
        user_id = int(parts[1])
        confirm_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ بله، مسدود کن", callback_data=f"block:{user_id}"),
                InlineKeyboardButton("❌ انصراف", callback_data="cancel"),
            ]
        ])
        await query.message.reply_text(
            f"⚠️ آیا مطمئنی که می‌خوای کاربر {user_id} را مسدود کنی؟",
            reply_markup=confirm_keyboard,
        )

    elif action == "block":
        user_id = int(parts[1])
        block_user(user_id)
        await query.message.reply_text(f"⛔ کاربر {user_id} مسدود شد.")
        logger.info(f"ادمین {query.from_user.id} کاربر {user_id} را مسدود کرد.")
        await notify_all_admins(
            context, f"ℹ️ کاربر {user_id} توسط ادمین دیگری مسدود شد.", exclude=query.from_user.id
        )

    elif action == "unblock":
        user_id = int(parts[1])
        if unblock_user(user_id):
            await query.message.reply_text(f"✅ مسدودیت کاربر {user_id} برداشته شد.")
            await notify_all_admins(
                context, f"ℹ️ مسدودیت کاربر {user_id} توسط ادمین دیگری برداشته شد.", exclude=query.from_user.id
            )
        else:
            await query.message.reply_text(f"ℹ️ کاربر {user_id} مسدود نبود.")

    elif action == "cancel":
        await query.message.reply_text("❌ عملیات لغو شد.")


# -------- پاسخ ادمین (reply به ForceReply) --------
async def admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ارسال پاسخ ادمین به کاربر و فعال‌سازی قابلیت ادامه گفتگو"""
    if not is_admin(update.effective_user.id):
        return

    pending = context.user_data.get("pending_reply")
    force_reply_msg_id = context.user_data.get("force_reply_msg_id")

    reply_to = update.message.reply_to_message
    if not pending or not reply_to or reply_to.message_id != force_reply_msg_id:
        return

    user_id = pending["user_id"]
    thread_id = pending["thread_id"]
    text = update.message.text
    replying_admin_id = update.effective_user.id

    try:
        sent = await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"✉️ جواب پیامت رسید:\n\n{text}\n\n"
                f"💬 برای ادامه گفتگو، روی همین پیام Reply بزن."
            ),
        )
        save_thread_link(sent.message_id, user_id, thread_id)
        mark_thread_replied(thread_id)
        await update.message.reply_text("✅ پاسخ ارسال شد.")
        logger.info(f"ادمین {replying_admin_id} به گفتگو #{thread_id} (کاربر {user_id}) پاسخ داد.")
        # اطلاع به سایر ادمین‌ها که این گفتگو پاسخ داده شده، تا پاسخ تکراری نفرستند
        await notify_all_admins(
            context,
            f"ℹ️ گفتگو #{thread_id} توسط ادمین دیگری پاسخ داده شد.",
            exclude=replying_admin_id,
        )
    except Forbidden:
        await update.message.reply_text("⚠️ کاربر ربات را بلاک کرده و پیام نرسید.")
        logger.warning(f"کاربر {user_id} ربات را بلاک کرده.")
    except BadRequest as e:
        await update.message.reply_text(f"⚠️ خطا در ارسال: {e}")
        logger.error(f"BadRequest برای کاربر {user_id}: {e}")
    finally:
        context.user_data.pop("pending_reply", None)
        context.user_data.pop("force_reply_msg_id", None)


# -------- اجرای ربات --------
def main() -> None:
    init_db()
    logger.info("ربات در حال راه‌اندازی...")
    logger.info(f"ادمین‌های فعال: {ADMIN_IDS}")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # دستورات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("blocked", blocked_command))
    app.add_handler(CommandHandler("unblock", unblock_command))
    app.add_handler(CommandHandler("admins", admins_command))

    # پاسخ ادمین — باید قبل از user_text_message باشد
    app.add_handler(MessageHandler(filters.REPLY & filters.TEXT & filters.User(user_id=ADMIN_IDS), admin_reply))

    # پیام متنی کاربران
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, user_text_message))

    # پیام مدیا
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.VOICE | filters.VIDEO | filters.Document.ALL,
        user_media_message
    ))

    # دکمه‌ها
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("ربات با موفقیت راه‌اندازی شد ✅")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
