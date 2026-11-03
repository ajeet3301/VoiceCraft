"""
VoiceCraft Telegram Bot
-----------------------
Flow:
  1. User sends a voice/audio message  -> bot saves it as the "reference voice"
                                          (VoiceCraft is zero-shot: no real training needed)
  2. User sends text                   -> bot replies with estimated time,
                                          shows live percent, then sends cloned voice

Setup:
  pip install "python-telegram-bot>=20" faster-whisper imageio-ffmpeg
  export BOT_TOKEN="123456:ABC..."          # from @BotFather
  python telegram_bot.py
"""

import asyncio
import os
from pathlib import Path
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

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN or BOT_TOKEN.strip() == "your_telegram_bot_token_here":
    print("[ERROR] BOT_TOKEN or TELEGRAM_BOT_TOKEN is missing. Set it in .env or run with BOT_TOKEN=xxx")
    sys.exit(1)

DATA = BASE_DIR / "bot_data"
DATA.mkdir(exist_ok=True)

MAX_REF_SECONDS = 15     # Max reference audio duration in seconds
MAX_TEXT_CHARS = 300     # Max characters per generation request
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
        # Use base model with int8 compute for high speed on CPU
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
        "🎙 *VoiceCraft Telegram Studio*\n\n"
        "1️⃣ *Send me a voice or audio note* (5–15 sec) to clone your voice.\n"
        "2️⃣ *Send any text message* — I'll speak it back in your exact voice!\n\n"
        "Commands:\n"
        "• `/status` – View your current saved voice\n"
        "• `/reset` – Delete your saved voice\n"
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
    raw = d / "ref_raw"
    f = await media.get_file()
    await f.download_to_drive(raw)

    await status.edit_text("🔧 Normalizing & trimming audio… " + bar(45))
    try:
        to_wav(raw, d / "ref.wav")
    except Exception as e:
        await status.edit_text(f"❌ Failed to process audio: {e}")
        return

    await status.edit_text("🧠 Analyzing speech & voice acoustics… " + bar(75))
    try:
        ref_text = await asyncio.to_thread(transcribe, d / "ref.wav")
    except Exception:
        ref_text = "Cloned Reference Voice"

    if not ref_text or not ref_text.strip():
        ref_text = "Cloned Reference Voice"

    (d / "ref.txt").write_text(ref_text, encoding="utf-8")

    await status.edit_text(
        f"✅ *Voice successfully saved!* {bar(100)}\n\n"
        f"📝 *Audio Reference:* _{ref_text}_\n\n"
        f"👉 *Now send me any text message to speak in your voice!*",
        parse_mode="Markdown",
    )


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    global sec_per_char
    uid = update.effective_user.id
    d = user_dir(uid)
    text = update.message.text.strip()

    # If user hasn't sent a voice yet, check if repo has voices/my_voice.wav
    if not (d / "ref.wav").exists():
        shared_voice = BASE_DIR / "voices" / "my_voice.wav"
        if shared_voice.exists():
            shutil.copy(shared_voice, d / "ref.wav")
            (d / "ref.txt").write_text("Default Studio Voice", encoding="utf-8")
        else:
            await update.message.reply_text("🎤 First send me a voice message to clone!")
            return

    if len(text) > MAX_TEXT_CHARS:
        await update.message.reply_text(
            f"✂️ Text is too long ({len(text)} chars). Maximum allowed is {MAX_TEXT_CHARS} characters."
        )
        return

    estimate = max(5, len(text) * sec_per_char)
    queue_note = "\n⏳ Another job is currently running, you're queued next." if gpu_lock.locked() else ""
    status = await update.message.reply_text(
        f"⏱ Estimated time: ~{fmt_time(estimate)}{queue_note}\n{bar(0)}"
    )

    async with gpu_lock:
        ref_text = (d / "ref.txt").read_text(encoding="utf-8") if (d / "ref.txt").exists() else "Reference"
        out = d / "out.wav"
        start_t = time.time()

        job = asyncio.create_task(
            asyncio.to_thread(
                voicecraft_generate,
                str(d / "ref.wav"),
                ref_text,
                text,
                str(out),
            )
        )

        last = -1
        while not job.done():
            await asyncio.sleep(2)
            pct = min(95, int((time.time() - start_t) / estimate * 100))
            if pct != last:
                last = pct
                left = max(1, estimate - (time.time() - start_t))
                try:
                    await status.edit_text(f"🎙 Generating voice… ~{fmt_time(left)} remaining\n{bar(pct)}")
                except Exception:
                    pass

        try:
            await job
        except Exception as e:
            await status.edit_text(f"❌ Generation failed: {e}")
            return

        took = time.time() - start_t
        sec_per_char = 0.7 * sec_per_char + 0.3 * (took / max(1, len(text)))

    await status.edit_text(f"✅ Generated in {fmt_time(took)}! {bar(100)}")
    await update.message.chat.send_action(ChatAction.RECORD_VOICE)

    # Convert to OGG/Opus so Telegram displays it as an interactive voice note
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

    try:
        if converted_ogg and ogg.exists():
            with open(ogg, "rb") as fh:
                await update.message.reply_voice(fh, caption=text[:200])
        else:
            with open(out, "rb") as fh:
                await update.message.reply_audio(
                    fh,
                    filename="voicecraft.wav",
                    title="VoiceCraft Speech",
                    performer="VoiceCraft AI",
                    caption=text[:200],
                )
    except Exception as send_err:
        await status.edit_text(f"❌ Failed to send voice: {send_err}")


async def status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    d = user_dir(update.effective_user.id)
    if (d / "ref.txt").exists():
        transcript = (d / "ref.txt").read_text(encoding="utf-8")
        await update.message.reply_text(
            f"✅ *Saved Voice Status: Active*\n\n"
            f"📝 *Transcript Preview:* _{transcript}_\n\n"
            f"Send any text to synthesize in this voice.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("No voice saved yet. Send me a voice message to get started!")


async def reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    d = user_dir(update.effective_user.id)
    for f in d.glob("*"):
        try:
            f.unlink()
        except Exception:
            pass
    await update.message.reply_text("🗑 Saved voice deleted. Send a new voice message anytime.")


def main():
    print(f"============================================================")
    print(f"           VoiceCraft Telegram Bot Running                  ")
    print(f"============================================================")
    if ALLOWED_USER_IDS:
        print(f"[VoiceCraft Bot] Restricted access: User IDs {ALLOWED_USER_IDS}")
    else:
        print(f"[VoiceCraft Bot] Open access: All Telegram users allowed")
    print(f"[VoiceCraft Bot] Listening for voice messages and text...")

    app = Application.builder().token(BOT_TOKEN.strip()).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("id", id_cmd))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.VIDEO_NOTE | filters.Document.AUDIO, on_audio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.run_polling()


if __name__ == "__main__":
    main()
