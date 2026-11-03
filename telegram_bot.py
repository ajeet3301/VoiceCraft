"""
VoiceCraft Telegram Bot
-----------------------
Flow:
  1. User sends a voice/audio message  -> Bot asks: "Whose voice is this?" and saves
                                          audio & transcript in bot_data/<user_id>/<name>/
  2. User sends text                   -> Bot displays buttons with all saved voice names.
                                          User taps a name and bot generates speech in that voice.
  3. Commands:
     /voices        - List all saved voices
     /delete <name> - Remove a specific saved voice
     /start         - Overview & instructions
     /id            - Check Telegram User ID

Setup:
  pip install "python-telegram-bot>=20" faster-whisper imageio-ffmpeg
  export BOT_TOKEN="123456:ABC..."          # from @BotFather
  python telegram_bot.py
"""

import asyncio
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

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

# Load local environment settings
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)

import numpy as np
import soundfile as sf
import torch

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN or BOT_TOKEN.strip() == "your_telegram_bot_token_here":
    print("[ERROR] BOT_TOKEN or TELEGRAM_BOT_TOKEN is missing. Set it in .env or pass BOT_TOKEN=xxx")
    sys.exit(1)

DATA = BASE_DIR / "bot_data"
DATA.mkdir(exist_ok=True)

MAX_REF_SECONDS = 15          # Max reference audio duration in seconds
MAX_TEXT_CHARS = 300          # Max characters per generation request
DEFAULT_SEC_PER_CHAR = 0.35   # First-run guess, auto-calibrated after each job

gpu_lock = asyncio.Lock()      # One job at a time (protects compute & memory)
sec_per_char = DEFAULT_SEC_PER_CHAR
_whisper = None
_tts_model = None

# Access control from .env
ALLOWED_USER_IDS: set[int] = set()
raw_ids = os.environ.get("ALLOWED_TELEGRAM_USER_IDS", "").strip()
if raw_ids:
    for item in raw_ids.split(","):
        item = item.strip()
        if item.isdigit():
            ALLOWED_USER_IDS.add(int(item))


# ---------------------------------------------------------------- helpers ---
def is_authorized(uid: int) -> bool:
    """Checks if the given Telegram user ID is authorized."""
    if not ALLOWED_USER_IDS:
        return True
    return uid in ALLOWED_USER_IDS


async def check_auth(update: Update) -> bool:
    """Replies and denies access if the user is not in the allowed list."""
    uid = update.effective_user.id if update.effective_user else 0
    if not is_authorized(uid):
        user_name = update.effective_user.first_name if update.effective_user else "User"
        await update.message.reply_text(
            f"🚫 *Access Restricted*\n\n"
            f"Hello {user_name}, this private VoiceCraft bot is configured for authorized users only.\n\n"
            f"Your Telegram User ID: `{uid}`",
            parse_mode="Markdown",
        )
        return False
    return True


def get_ffmpeg_exe() -> str:
    """Locate ffmpeg binary from PATH or bundled imageio-ffmpeg."""
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def user_dir(uid: int) -> Path:
    d = DATA / str(uid)
    d.mkdir(exist_ok=True)
    return d


def get_user_voices(uid: int) -> list[str]:
    """Returns list of voice profile names saved by the user."""
    d = user_dir(uid)

    # Legacy migration: if ref.wav is at root of user_dir, migrate to Default
    legacy_ref = d / "ref.wav"
    if legacy_ref.exists():
        legacy_dir = d / "Default"
        legacy_dir.mkdir(exist_ok=True)
        shutil.move(str(legacy_ref), str(legacy_dir / "ref.wav"))
        legacy_txt = d / "ref.txt"
        if legacy_txt.exists():
            shutil.move(str(legacy_txt), str(legacy_dir / "ref.txt"))

    voices = []
    if d.exists():
        for item in sorted(d.iterdir()):
            if item.is_dir() and (item / "ref.wav").exists():
                voices.append(item.name)
    return voices


def to_wav(src: Path, dst: Path, max_seconds: int = MAX_REF_SECONDS):
    """Convert anything to 16 kHz mono wav and trim to max_seconds."""
    ffmpeg = get_ffmpeg_exe()
    subprocess.run(
        [
            ffmpeg, "-y", "-i", str(src),
            "-t", str(max_seconds),
            "-ar", "16000", "-ac", "1",
            str(dst),
        ],
        check=True,
        capture_output=True,
    )


def transcribe(wav: Path) -> str:
    """VoiceCraft reference audio transcription using faster-whisper."""
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel("base", compute_type="int8")
    segments, _ = _whisper.transcribe(str(wav))
    return " ".join(s.text.strip() for s in segments).strip()


def bar(pct: int, width: int = 12) -> str:
    filled = max(0, min(width, int(width * pct / 100)))
    return "█" * filled + "░" * (width - filled) + f" {pct}%"


def fmt_time(sec: float) -> str:
    sec = max(1, int(round(sec)))
    return f"{sec}s" if sec < 60 else f"{sec // 60}m {sec % 60}s"


# ------------------------------------------------------- MODEL CONNECTION ---
def get_tts_model():
    """Load Chatterbox Multilingual TTS model once at module level."""
    global _tts_model
    if _tts_model is None:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        device = "cuda" if torch.cuda.is_available() else "cpu"
        t3_model = os.getenv("CHATTERBOX_MULTILINGUAL_T3_MODEL", "v3")
        print(f"[VoiceCraft Bot] Loading TTS model ({t3_model}) on {device.upper()}...")
        _tts_model = ChatterboxMultilingualTTS.from_pretrained(device, t3_model=t3_model)
        if hasattr(_tts_model, "eval"):
            _tts_model.eval()
        print("[VoiceCraft Bot] TTS Model ready in memory!")
    return _tts_model


def voicecraft_generate(ref_wav: str, ref_text: str, text: str, out_wav: str):
    """
    Connected VoiceCraft inference engine.
    - If local VoiceCraft server is active (port 7860), reuses its warm model via HTTP to prevent memory duplication.
    - If running standalone, loads ChatterboxMultilingualTTS model directly into memory.
    - Uses in-memory sentence chunking and crossfade smoothing.
    - Saves single final continuous output to out_wav (zero chunk files on disk).
    """
    import urllib.request
    import json

    lang = "hi" if any("\u0900" <= ch <= "\u097f" for ch in text) else os.getenv("TELEGRAM_DEFAULT_LANG", "en")
    server_port = os.getenv("SERVER_PORT", "7860")
    server_host = os.getenv("SERVER_HOST", "127.0.0.1")
    server_url = f"http://{server_host}:{server_port}"

    # 1. Attempt to reuse already-warm model from running server process
    try:
        req_data = json.dumps({
            "text": text,
            "voice_path": str(Path(ref_wav).resolve()),
            "language": lang,
            "stream_playback": False,
        }).encode("utf-8")
        http_req = urllib.request.Request(
            f"{server_url}/api/generate/stream",
            data=req_data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(http_req, timeout=300) as resp:
            for raw_line in resp:
                line_str = raw_line.decode("utf-8", errors="replace").strip()
                if line_str.startswith("data:"):
                    try:
                        payload = json.loads(line_str[5:].strip())
                        if payload.get("status") == "complete":
                            rel_url = payload.get("audio_url", "").lstrip("/")
                            source_path = BASE_DIR / rel_url
                            if source_path.exists():
                                shutil.copy(source_path, out_wav)
                                print(f"[VoiceCraft Bot] Generated via local server: {out_wav}")
                                return
                    except Exception:
                        pass
    except Exception as srv_err:
        print(f"[VoiceCraft Bot] Local server dispatch notice ({srv_err}); using direct model...")

    # 2. Standalone fallback: execute directly via ChatterboxMultilingualTTS
    model = get_tts_model()
    model.prepare_conditionals(ref_wav, exaggeration=0.5)

    from multilingual_app import split_text_into_chunks, join_audio_chunks
    chunks = split_text_into_chunks(text, max_chars=200)
    if not chunks:
        chunks = [text]

    chunks_audio = []
    with torch.inference_mode():
        for chunk in chunks:
            wav = model.generate(
                chunk,
                language_id=lang,
                audio_prompt_path=None,
                exaggeration=0.5,
                cfg_weight=0.5,
                temperature=0.8,
            )
            chunk_np = wav.squeeze(0).cpu().numpy().astype(np.float32)
            chunks_audio.append(chunk_np)

    joined = join_audio_chunks(chunks_audio, model.sr, pause_ms=180, crossfade_ms=30)
    sf.write(out_wav, joined, model.sr, format="WAV", subtype="PCM_16")
    print(f"[VoiceCraft Bot] Audio generated directly: {out_wav} ({len(joined)/model.sr:.2f}s)")


# --------------------------------------------------------------- handlers ---
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    await update.message.reply_text(
        "🎙 *VoiceCraft Multilingual Bot*\n\n"
        "1️⃣ *Send a voice message* – I'll ask: _\"Whose voice is this?\"_ and save it under that name (e.g. Tamanna, Ayushi).\n"
        "2️⃣ *Send any text* – I'll show buttons for your saved voices. Tap one to speak your text!\n\n"
        "Commands:\n"
        "• `/voices` – List all your saved voices\n"
        "• `/delete <name>` – Delete a specific voice\n"
        "• `/id` – Show your Telegram User ID",
        parse_mode="Markdown",
    )


async def id_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else 0
    await update.message.reply_text(f"🆔 Your Telegram User ID: `{uid}`", parse_mode="Markdown")


async def on_audio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    msg = update.message
    media = msg.voice or msg.audio or msg.video_note or msg.document
    uid = update.effective_user.id
    d = user_dir(uid)

    status = await msg.reply_text("⬇️ Receiving voice sample… " + bar(15))
    temp_raw = d / "_temp_raw"
    temp_wav = d / "_temp_ref.wav"
    f = await media.get_file()
    await f.download_to_drive(temp_raw)

    await status.edit_text("🔧 Normalizing audio… " + bar(45))
    try:
        to_wav(temp_raw, temp_wav)
    except Exception as e:
        await status.edit_text(f"❌ Failed to process audio: {e}")
        return

    await status.edit_text("🧠 Analyzing voice… " + bar(75))
    try:
        ref_text = await asyncio.to_thread(transcribe, temp_wav)
    except Exception:
        ref_text = "Reference Voice"

    if not ref_text or not ref_text.strip():
        ref_text = "Reference Voice"

    # Store pending voice in user_data awaiting name response
    ctx.user_data["pending_voice"] = {
        "wav": str(temp_wav),
        "text": ref_text,
    }

    await status.edit_text(
        f"🎙 *Whose voice is this?*\n\n"
        f"Reply with a name for this voice (example: *Tamanna*, *Ayushi*):\n\n"
        f"📝 _I heard: {ref_text[:120]}_",
        parse_mode="Markdown",
    )


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    uid = update.effective_user.id
    text = update.message.text.strip()
    d = user_dir(uid)

    # 1. Check if the user is answering "Whose voice is this?"
    if "pending_voice" in ctx.user_data:
        pending = ctx.user_data.pop("pending_voice")
        # Sanitize voice name: letters, numbers, spaces, hyphens
        voice_name = re.sub(r"[^\w\s-]", "", text).strip()
        voice_name = re.sub(r"\s+", " ", voice_name)[:30]
        if not voice_name:
            ctx.user_data["pending_voice"] = pending
            await update.message.reply_text("❌ Please enter a valid name (example: Tamanna, Ayushi):")
            return

        target_dir = d / voice_name
        target_dir.mkdir(parents=True, exist_ok=True)

        shutil.move(pending["wav"], str(target_dir / "ref.wav"))
        (target_dir / "ref.txt").write_text(pending["text"], encoding="utf-8")

        temp_raw = d / "_temp_raw"
        if temp_raw.exists():
            try:
                temp_raw.unlink()
            except Exception:
                pass

        await update.message.reply_text(
            f"✅ Saved voice as *{voice_name}*! {bar(100)}\n\n"
            f"📝 *Transcript:* _{pending['text']}_\n\n"
            f"👉 Now send me any text to speak in *{voice_name}*'s voice!",
            parse_mode="Markdown",
        )
        return

    # 2. User is sending text to synthesize!
    voices = get_user_voices(uid)
    if not voices:
        # Check if voices/my_voice.wav exists in repo as fallback
        shared = BASE_DIR / "voices" / "my_voice.wav"
        if shared.exists():
            default_dir = d / "MyVoice"
            default_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(shared, default_dir / "ref.wav")
            (default_dir / "ref.txt").write_text("Studio Voice", encoding="utf-8")
            voices = ["MyVoice"]
        else:
            await update.message.reply_text(
                "🎤 You have no saved voices yet! First send me a voice message to save one."
            )
            return

    if len(text) > MAX_TEXT_CHARS:
        await update.message.reply_text(
            f"✂️ Text is too long ({len(text)} chars). Maximum allowed is {MAX_TEXT_CHARS} characters."
        )
        return

    # Store text for voice button selection
    ctx.user_data["pending_text"] = text

    # Build inline buttons for each saved voice
    keyboard = []
    row = []
    for v in voices:
        row.append(InlineKeyboardButton(f"🎙 {v}", callback_data=f"voice:{v}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await update.message.reply_text(
        f"💬 *Text:* \"{text[:120]}{'...' if len(text)>120 else ''}\"\n\n"
        f"👉 *Whose voice should speak this?*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def on_voice_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handles tapping a voice name button."""
    query = update.callback_query
    await query.answer()

    if not is_authorized(query.from_user.id):
        await query.edit_message_text("🚫 Unauthorized.")
        return

    uid = query.from_user.id
    voice_name = query.data.split("voice:", 1)[1]
    d = user_dir(uid)
    voice_dir = d / voice_name

    if not (voice_dir / "ref.wav").exists():
        await query.edit_message_text(f"❌ Voice *{voice_name}* not found. Send text again to choose another.")
        return

    text = ctx.user_data.get("pending_text", "")
    if not text:
        await query.edit_message_text("⚠️ No text found. Please send your text message again.")
        return

    global sec_per_char
    estimate = max(5, len(text) * sec_per_char)
    queue_note = "\n⏳ Another job is currently running, you're queued next." if gpu_lock.locked() else ""

    await query.edit_message_text(
        f"🎙 Generating voice as *{voice_name}*…\n"
        f"⏱ Estimated time: ~{fmt_time(estimate)}{queue_note}\n{bar(0)}",
        parse_mode="Markdown",
    )

    ref_wav = str(voice_dir / "ref.wav")
    ref_text = (voice_dir / "ref.txt").read_text(encoding="utf-8") if (voice_dir / "ref.txt").exists() else "Reference"
    out = d / "out.wav"

    async with gpu_lock:
        start_t = time.time()
        job = asyncio.create_task(
            asyncio.to_thread(voicecraft_generate, ref_wav, ref_text, text, str(out))
        )

        last = -1
        while not job.done():
            await asyncio.sleep(2)
            pct = min(95, int((time.time() - start_t) / estimate * 100))
            if pct != last:
                last = pct
                left = max(1, estimate - (time.time() - start_t))
                try:
                    await query.edit_message_text(
                        f"🎙 Generating voice as *{voice_name}*… ~{fmt_time(left)} remaining\n{bar(pct)}",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass

        try:
            await job
        except Exception as e:
            await query.edit_message_text(f"❌ Generation failed: {e}")
            return

        took = time.time() - start_t
        sec_per_char = 0.7 * sec_per_char + 0.3 * (took / max(1, len(text)))

    await query.edit_message_text(
        f"✅ Spoken as *{voice_name}* in {fmt_time(took)}! {bar(100)}",
        parse_mode="Markdown",
    )
    await query.message.chat.send_action(ChatAction.RECORD_VOICE)

    # Convert to OGG/Opus for Telegram voice note
    ogg = d / "out.ogg"
    ffmpeg = get_ffmpeg_exe()
    converted_ogg = False
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", str(out), "-c:a", "libopus", str(ogg)],
            check=True,
            capture_output=True,
        )
        converted_ogg = True
    except Exception:
        converted_ogg = False

    caption_text = f"🗣 {voice_name}: {text[:180]}"
    try:
        if converted_ogg and ogg.exists():
            with open(ogg, "rb") as fh:
                await query.message.reply_voice(fh, caption=caption_text)
        else:
            with open(out, "rb") as fh:
                await query.message.reply_audio(
                    fh,
                    filename=f"{voice_name}_voicecraft.wav",
                    title=f"VoiceCraft ({voice_name})",
                    performer=voice_name,
                    caption=caption_text,
                )
    except Exception as send_err:
        await query.message.reply_text(f"❌ Failed to send voice: {send_err}")


async def voices_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Lists all voices saved by the user."""
    if not await check_auth(update):
        return

    uid = update.effective_user.id
    voices = get_user_voices(uid)
    if not voices:
        await update.message.reply_text(
            "🎙 You have no saved voices yet.\nSend me a voice message to save one!",
            parse_mode="Markdown",
        )
        return

    lines = ["🎙 *Your Saved Voices:*\n"]
    for idx, name in enumerate(voices, 1):
        v_dir = user_dir(uid) / name
        txt_path = v_dir / "ref.txt"
        transcript = txt_path.read_text(encoding="utf-8")[:60] if txt_path.exists() else "Voice reference"
        lines.append(f"{idx}. *{name}* – _{transcript}_")

    lines.append("\n💡 To delete a voice: `/delete <name>`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def delete_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Deletes a specific saved voice by name."""
    if not await check_auth(update):
        return

    uid = update.effective_user.id
    if not ctx.args:
        await update.message.reply_text(
            "⚠️ Please specify which voice to delete.\nExample: `/delete Tamanna`",
            parse_mode="Markdown",
        )
        return

    name = " ".join(ctx.args).strip()
    d = user_dir(uid)
    voice_dir = d / name

    if voice_dir.exists() and voice_dir.is_dir():
        shutil.rmtree(voice_dir, ignore_errors=True)
        await update.message.reply_text(f"🗑 Voice *{name}* has been deleted.", parse_mode="Markdown")
    else:
        # Case-insensitive fallback
        matched = None
        for item in d.iterdir():
            if item.is_dir() and item.name.lower() == name.lower():
                matched = item
                break
        if matched:
            shutil.rmtree(matched, ignore_errors=True)
            await update.message.reply_text(f"🗑 Voice *{matched.name}* has been deleted.", parse_mode="Markdown")
        else:
            await update.message.reply_text(
                f"❌ Voice *{name}* not found. Use `/voices` to see your saved voices.",
                parse_mode="Markdown",
            )


def main():
    print(f"============================================================")
    print(f"       VoiceCraft Telegram Bot (Multi-Voice Enabled)        ")
    print(f"============================================================")
    if ALLOWED_USER_IDS:
        print(f"[VoiceCraft Bot] Restricted access: User IDs {ALLOWED_USER_IDS}")
    else:
        print(f"[VoiceCraft Bot] Open access: All Telegram users allowed")
    print(f"[VoiceCraft Bot] Listening for voice messages and text...")

    app = Application.builder().token(BOT_TOKEN.strip()).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("voices", voices_cmd))
    app.add_handler(CommandHandler("status", voices_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(CommandHandler("id", id_cmd))
    app.add_handler(CallbackQueryHandler(on_voice_select, pattern=r"^voice:"))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.VIDEO_NOTE | filters.Document.AUDIO, on_audio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.run_polling()


if __name__ == "__main__":
    main()
