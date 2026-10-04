import logging
import asyncio
from flask import Blueprint, request, jsonify, current_app
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

support_bp = Blueprint('support_bot', __name__, url_prefix='/tg-webhook')

logger = logging.getLogger(__name__)

BOT_TOKEN = "8708834124:AAF6qNA_cFYfi7xIJxnwPmOiyppSk3xo0GY"
ADMIN_CHAT_ID = 5370959021438146805
SECRET_PATH = "support-2026-secret"  # любой секрет, чтобы URL был непредсказуемым
PROXY_URL = "socks5h://64.90.10.204:1080"

# Одно приложение Telegram, создаётся один раз
_tg_app = None


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("📚 Документация", url="https://testrun.pro/docs")],
        [InlineKeyboardButton("❓ FAQ", url="https://testrun.pro/docs?page=faq")],
    ]
    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋\n\n"
        "Это поддержка TestRun. Опиши вопрос — я передам его команде.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message
    text = (
        f"📩 Новое сообщение от пользователя\n\n"
        f"👤 {user.first_name or '—'} {user.last_name or ''}\n"
        f"🆔 ID: {user.id}\n"
        f"🔗 @{user.username or '—'}\n\n"
        f"💬 Текст:\n{message.text}"
    )
    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text)
        await message.reply_text("✅ Сообщение отправлено в поддержку.")
    except Exception as e:
        logger.error(f"send_message error: {e}")
        await message.reply_text("❌ Не удалось отправить. Попробуйте позже.")


async def reply_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if message.from_user.id != ADMIN_CHAT_ID:
        return
    if not message.reply_to_message:
        await message.reply_text("Ответь реплаем на сообщение пользователя.")
        return
    original = message.reply_to_message.text or ""
    user_id = None
    for line in original.split("\n"):
        if line.startswith("🆔 ID:"):
            try:
                user_id = int(line.replace("🆔 ID:", "").strip())
            except ValueError:
                pass
            break
    if not user_id:
        await message.reply_text("❌ Не удалось определить ID.")
        return
    try:
        await context.bot.send_message(chat_id=user_id, text=f"💬 Ответ поддержки:\n\n{message.text}")
        await message.reply_text("✅ Ответ отправлен.")
    except Exception as e:
        logger.error(f"reply error: {e}")
        await message.reply_text(f"❌ Ошибка: {e}")


def get_tg_app():
    """Создаёт Telegram-приложение один раз."""
    global _tg_app
    if _tg_app is None:
        req = HTTPXRequest(proxy=PROXY_URL, connect_timeout=15.0, read_timeout=15.0)
        _tg_app = Application.builder().token(BOT_TOKEN).request(req).build()
        _tg_app.add_handler(CommandHandler("start", cmd_start))
        _tg_app.add_handler(MessageHandler(
            filters.TEXT & filters.User(ADMIN_CHAT_ID) & filters.REPLY,
            reply_to_user
        ))
        _tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return _tg_app


@support_bp.route(f'/{SECRET_PATH}', methods=['POST'])
def webhook():
    """Telegram присылает сюда обновления."""
    data = request.get_json(force=True)
    if not data:
        return jsonify({"ok": False}), 400

    try:
        tg_app = get_tg_app()
        update = Update.de_json(data, tg_app.bot)

        # Запускаем обработку в отдельном event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(tg_app.initialize())
            loop.run_until_complete(tg_app.process_update(update))
        finally:
            loop.close()
    except Exception as e:
        logger.exception(f"Webhook processing error: {e}")
        return jsonify({"ok": False}), 500

    return jsonify({"ok": True})
