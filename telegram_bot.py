import asyncio
import logging
import os
from pathlib import Path
import sys

# Ensure UTF-8 console output on Windows
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv

# Load local environment configuration
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("VoiceCraftBot")

try:
    from telegram import Update
    from telegram.ext import (
        ApplicationBuilder,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
except ImportError:
    logger.error("python-telegram-bot is not installed. Run: pip install python-telegram-bot")

# User language preferences mapping {user_id: lang_code}
USER_LANG = {}


def get_allowed_user_ids() -> set[int]:
    """Parse comma-separated allowed Telegram user IDs from environment."""
    raw = os.getenv("ALLOWED_TELEGRAM_USER_IDS", "").strip()
    if not raw:
        return set()
    ids = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


def is_user_authorized(user_id: int) -> bool:
    """Checks if the user is authorized to use the bot."""
    allowed = get_allowed_user_ids()
    if not allowed:
        return True  # If no IDs configured, allow open access
    return user_id in allowed


async def check_auth_or_warn(update: Update) -> bool:
    """Verifies user authorization; replies with rejection message if unauthorized."""
    user = update.effective_user
    if not user:
        return False
    if not is_user_authorized(user.id):
        logger.warning(f"Unauthorized access attempt from user {user.id} ({user.username})")
        await update.message.reply_text(
            f"🚫 **Access Restricted**\n\n"
            f"This VoiceCraft bot is configured for authorized users only.\n"
            f"Your Telegram User ID: `{user.id}`",
            parse_mode="Markdown",
        )
        return False
    return True


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth_or_warn(update):
        return

    user_name = update.effective_user.first_name if update.effective_user else "there"
    welcome_msg = (
        f"👋 Hello {user_name}! Welcome to **VoiceCraft Bot**.\n\n"
        "🎙️ Send me any text message, and I will synthesize and speak it back to you in your cloned voice!\n\n"
        "Commands:\n"
        "• `/lang <code>` - Change speech language (e.g. `/lang en` or `/lang hi`)\n"
        "• `/status` - Check current voice and model status\n"
        "• `/id` - Check your Telegram User ID\n"
        "• `/help` - Show instructions and supported languages"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id if user else "Unknown"
    is_auth = is_user_authorized(uid)
    await update.message.reply_text(
        f"👤 **Your Telegram Profile**\n\n"
        f"• User ID: `{uid}`\n"
        f"• Name: {user.full_name if user else 'N/A'}\n"
        f"• Username: @{user.username if user and user.username else 'None'}\n"
        f"• Authorization Status: {'✅ Authorized' if is_auth else '❌ Unauthorized'}",
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth_or_warn(update):
        return

    from chatterbox.mtl_tts import SUPPORTED_LANGUAGES

    lang_list = ", ".join([f"`{code}` ({name})" for code, name in sorted(SUPPORTED_LANGUAGES.items())[:12]])
    help_text = (
        "📖 **VoiceCraft Bot Help**\n\n"
        "Just send any text message directly in this chat to clone it into speech.\n\n"
        "**Changing Language**:\n"
        "Use `/lang <code>` to switch language.\n"
        f"Sample languages: {lang_list}...\n"
        "Default language is configured in your VoiceCraft settings."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth_or_warn(update):
        return

    from chatterbox.mtl_tts import SUPPORTED_LANGUAGES

    if not context.args:
        curr = USER_LANG.get(update.effective_user.id, os.getenv("TELEGRAM_DEFAULT_LANG", "en"))
        await update.message.reply_text(
            f"Current language is set to `{curr}`. Use `/lang <code>` to change (e.g. `/lang hi` or `/lang en`).",
            parse_mode="Markdown",
        )
        return

    code = context.args[0].lower().strip()
    if code in SUPPORTED_LANGUAGES:
        USER_LANG[update.effective_user.id] = code
        await update.message.reply_text(
            f"✅ Language updated to **{SUPPORTED_LANGUAGES[code]}** (`{code}`).",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"❌ Unknown language code `{code}`. Use `/help` to see options.",
            parse_mode="Markdown",
        )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth_or_warn(update):
        return

    from multilingual_app import MY_VOICE_PATH

    has_voice = MY_VOICE_PATH.exists()
    status_str = (
        "🤖 **VoiceCraft Status**\n\n"
        f"• Saved Voice Sample: {'✅ Loaded (' + MY_VOICE_PATH.name + ')' if has_voice else '❌ Not found (Please save in Web UI)'}\n"
        f"• Model: Multilingual V3\n"
        f"• Active Language: `{USER_LANG.get(update.effective_user.id, os.getenv('TELEGRAM_DEFAULT_LANG', 'en'))}`\n"
        f"• Single File Output: Enabled (Zero chunk clutter)"
    )
    await update.message.reply_text(status_str, parse_mode="Markdown")


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth_or_warn(update):
        return

    text = update.message.text
    if not text or not text.strip():
        return

    user_id = update.effective_user.id
    lang = USER_LANG.get(user_id, os.getenv("TELEGRAM_DEFAULT_LANG", "en"))

    # Send typing / record audio action to Telegram UI
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="record_voice")

    from multilingual_app import generate_speech, MY_VOICE_PATH

    if not MY_VOICE_PATH.exists():
        await update.message.reply_text(
            "⚠️ No cloned voice found on the server. Please upload and save your voice sample in the VoiceCraft Web UI first.",
        )
        return

    status_msg = await update.message.reply_text("⏳ Synthesizing speech in your cloned voice...")

    try:
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(
            None,
            generate_speech,
            text,
            lang,
            None,
            0.5,
            0.5,
            0.8,
            False,
            200,
            30,
            False,
            None,
        )
        wav_path = res[0]

        if not wav_path or not os.path.exists(wav_path):
            await status_msg.edit_text("❌ Failed to synthesize audio.")
            return

        # Send voice message or audio
        with open(wav_path, "rb") as audio_file:
            await context.bot.send_audio(
                chat_id=update.effective_chat.id,
                audio=audio_file,
                filename=Path(wav_path).name,
                title="VoiceCraft Cloned Speech",
                performer="VoiceCraft AI",
            )
        await status_msg.delete()
    except Exception as e:
        logger.error(f"Error generating voice for Telegram: {e}")
        await status_msg.edit_text(f"❌ Error generating voice: {str(e)}")


def run_bot(token: str | None = None):
    token = token or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or token == "your_telegram_bot_token_here" or not token.strip():
        print("[Telegram Bot] ERROR: No TELEGRAM_BOT_TOKEN provided. Set it in .env or via Settings tab.")
        return

    allowed = get_allowed_user_ids()
    print(f"[Telegram Bot] Starting VoiceCraft Telegram Bot...")
    if allowed:
        print(f"[Telegram Bot] Access restricted to authorized User ID(s): {allowed}")
    else:
        print("[Telegram Bot] Open access mode (no user ID restriction)")

    app = ApplicationBuilder().token(token.strip()).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("lang", lang_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    print("[Telegram Bot] Bot is live! Listening for Telegram messages...")
    app.run_polling()


if __name__ == "__main__":
    run_bot()
