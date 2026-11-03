"""
VoiceCraft Telegram Bot
-----------------------
Flow:
  1. User sends a voice/audio message  -> Bot asks: "Whose voice is this?" and saves
                                          audio & transcript in bot_data/<user_id>/<name>/
  2. User sends text                   -> Bot displays buttons with all saved voice names.
                                          User taps a name and bot generates speech in that voice.
  3. Audio Management:
     - Each generated audio has [ 💾 Save Audio ] and [ 🗑 Delete Audio ] buttons.
     - /audios lists recent generated audio messages with instant action buttons.
  4. Access & Resource Control:
     - Configurable from localhost (http://127.0.0.1:7860/#tab-settings):
       - Max Allowed Users (TELEGRAM_MAX_USERS)
       - Max Words Per Request (TELEGRAM_MAX_WORDS)
       - Authorized Telegram User IDs (ALLOWED_TELEGRAM_USER_IDS)
  5. Commands:
     /voices        - List all saved voices
     /delete <name> - Remove a specific saved voice
     /audios        - Manage recent generated audios
     /clear_audios  - Delete all generated audio history
     /status        - View bot statistics and limits
     /restart       - Restart the bot process
     /start         - Overview & instructions
     /id            - Check Telegram User ID
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

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH, override=True)

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
    print("[ERROR] BOT_TOKEN or TELEGRAM_BOT_TOKEN is missing. Set it in .env or localhost settings.")
    sys.exit(1)

DATA = BASE_DIR / "bot_data"
DATA.mkdir(exist_ok=True)

MAX_REF_SECONDS = 15          # Max reference audio duration in seconds
DEFAULT_SEC_PER_CHAR = 0.35   # First-run guess, auto-calibrated after each job

gpu_lock = asyncio.Lock()      # One job at a time (protects compute & memory)
sec_per_char = DEFAULT_SEC_PER_CHAR
_whisper = None
_tts_model = None


# ---------------------------------------------------------------- Settings Helpers ---
def reload_env():
    """Reloads .env so changes in localhost settings apply instantly."""
    load_dotenv(ENV_PATH, override=True)


def get_max_words() -> int:
    reload_env()
    try:
        return max(5, int(os.getenv("TELEGRAM_MAX_WORDS", "60")))
    except Exception:
        return 60


def get_max_users() -> int:
    reload_env()
    try:
        return max(0, int(os.getenv("TELEGRAM_MAX_USERS", "1")))
    except Exception:
        return 1


def get_allowed_user_ids() -> set[int]:
    reload_env()
    allowed = set()
    raw = os.getenv("ALLOWED_TELEGRAM_USER_IDS", "").strip()
    if raw:
        for item in raw.split(","):
            item = item.strip()
            if item.isdigit():
                allowed.add(int(item))
    return allowed


def get_active_user_ids() -> set[int]:
    """Finds all users who have active profiles in bot_data."""
    uids = set()
    if DATA.exists():
        for p in DATA.iterdir():
            if p.is_dir() and p.name.isdigit():
                uids.add(int(p.name))
    return uids


def is_authorized(uid: int) -> bool:
    """Checks if the user ID is permitted under current whitelist & user capacity limits."""
    allowed = get_allowed_user_ids()
    if allowed and uid in allowed:
        return True

    # If whitelist is explicitly set and user is not in it, reject
    if allowed and uid not in allowed:
        return False

    # Otherwise check capacity (max_users)
    max_users = get_max_users()
    active_users = get_active_user_ids()

    if uid in active_users:
        return True

    if max_users > 0 and len(active_users) >= max_users:
        return False

    return True


async def check_auth(update: Update) -> bool:
    """Verifies authorization and informs user if capped or unauthorized."""
    uid = update.effective_user.id if update.effective_user else 0
    user_name = update.effective_user.first_name if update.effective_user else "User"

    if is_authorized(uid):
        return True

    allowed = get_allowed_user_ids()
    max_users = get_max_users()
    active_users = get_active_user_ids()

    msg = update.effective_message
    if not msg:
        return False

    if max_users > 0 and uid not in active_users and len(active_users) >= max_users and (not allowed or uid not in allowed):
        await msg.reply_text(
            f"🚫 *User Capacity Reached*\n\n"
            f"Hello {user_name}, this bot is currently capped at *{max_users}* user(s).\n\n"
            f"💡 To allow more users, increase **Max Allowed Users** on the localhost settings panel (`http://127.0.0.1:7860/#tab-settings`).\n\n"
            f"Your Telegram ID: `{uid}`",
            parse_mode="Markdown",
        )
        return False

    await msg.reply_text(
        f"🚫 *Access Restricted*\n\n"
        f"Hello {user_name}, this private VoiceCraft bot is configured for authorized users only.\n\n"
        f"To grant access, add your ID on localhost settings (`http://127.0.0.1:7860`) or in `.env`:\n"
        f"Your Telegram ID: `{uid}`",
        parse_mode="Markdown",
    )
    return False


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


def user_audios_dir(uid: int) -> Path:
    d = user_dir(uid) / "audios"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_user_voices(uid: int) -> list[str]:
    """Returns list of voice profile names saved by the user."""
    d = user_dir(uid)

    # Automatically load 'my_voice' as default if voices/my_voice.wav exists
    default_src = BASE_DIR / "voices" / "my_voice.wav"
    user_my_voice = d / "my_voice"
    deleted_marker = d / ".deleted_my_voice"
    if default_src.exists() and not user_my_voice.exists() and not deleted_marker.exists():
        try:
            user_my_voice.mkdir(parents=True, exist_ok=True)
            to_wav(default_src, user_my_voice / "ref.wav", max_seconds=15)
            try:
                txt = transcribe(user_my_voice / "ref.wav")
            except Exception:
                txt = "Default my_voice sample"
            (user_my_voice / "ref.txt").write_text(txt or "Default my_voice sample", encoding="utf-8")
        except Exception as e:
            print(f"[VoiceCraft Bot] Default my_voice init notice: {e}")

    # Legacy migration: if ref.wav is at root of user_dir, migrate to my_voice
    legacy_ref = d / "ref.wav"
    if legacy_ref.exists():
        user_my_voice.mkdir(exist_ok=True)
        shutil.move(str(legacy_ref), str(user_my_voice / "ref.wav"))
        legacy_txt = d / "ref.txt"
        if legacy_txt.exists():
            shutil.move(str(legacy_txt), str(user_my_voice / "ref.txt"))

    voices = []
    if d.exists():
        for item in sorted(d.iterdir()):
            if item.is_dir() and item.name != "audios" and (item / "ref.wav").exists():
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
    - If local VoiceCraft server is active (port 7860), reuses warm model via HTTP.
    - If running standalone, runs ChatterboxMultilingualTTS directly.
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


# --------------------------------------------------------------- Handlers ---
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    max_w = get_max_words()
    max_u = get_max_users()

    await update.message.reply_text(
        "🎙 *VoiceCraft Multilingual Studio Bot*\n\n"
        "1️⃣ *Send a voice message* – I'll ask: _\"Whose voice is this?\"_ and save it under your chosen name.\n"
        "2️⃣ *Send any text* – Choose from your saved voices to speak it!\n"
        "3️⃣ *Audio Controls* – Every audio has instant `[ 💾 Save Audio ]` and `[ 🗑 Delete Audio ]` buttons.\n\n"
        f"⚙️ *Current Limits:* Max words: `{max_w}` | Max users: `{max_u if max_u>0 else 'Unlimited'}`\n\n"
        "Commands:\n"
        "• `/voices` – List all saved voice profiles\n"
        "• `/audios` – View and manage recent generated audios\n"
        "• `/delete <name>` – Delete a saved voice profile\n"
        "• `/clear_audios` – Clear cached audio files\n"
        "• `/status` – View system status and config\n"
        "• `/restart` – Restart bot process\n"
        "• `/id` – Check your Telegram User ID",
        parse_mode="Markdown",
    )


async def id_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else 0
    await update.message.reply_text(f"🆔 Your Telegram User ID: `{uid}`", parse_mode="Markdown")


async def status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    uid = update.effective_user.id
    max_w = get_max_words()
    max_u = get_max_users()
    active_u = get_active_user_ids()
    voices = get_user_voices(uid)
    audios = list(user_audios_dir(uid).glob("*.wav"))

    await update.message.reply_text(
        "📊 *VoiceCraft Bot Status*\n\n"
        f"• *Max Words Per Request:* `{max_w}` words\n"
        f"• *Max Allowed Users:* `{max_u if max_u>0 else 'Unlimited'}` (Currently active: `{len(active_u)}`)\n"
        f"• *Your Saved Voices:* `{len(voices)}`\n"
        f"• *Your Cached Audios:* `{len(audios)}`\n"
        f"• *Hardware Engine:* `{'CUDA (GPU)' if torch.cuda.is_available() else 'CPU'}`\n\n"
        f"💡 Change limits anytime on localhost: `http://127.0.0.1:7860/#tab-settings`",
        parse_mode="Markdown",
    )


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
        f"Reply with the name for this voice:\n\n"
        f"📝 _I heard: {ref_text[:120]}_",
        parse_mode="Markdown",
    )


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    uid = update.effective_user.id
    text = update.message.text.strip()
    d = user_dir(uid)

    # 1. Check if user is naming a newly recorded voice
    if "pending_voice" in ctx.user_data:
        pending = ctx.user_data.pop("pending_voice")
        voice_name = re.sub(r"[^\w\s-]", "", text).strip()
        voice_name = re.sub(r"\s+", " ", voice_name)[:30]
        if not voice_name:
            ctx.user_data["pending_voice"] = pending
            await update.message.reply_text("❌ Please enter a name for this voice:")
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

    # 2. Check Word Limit
    words = text.split()
    max_words = get_max_words()
    if len(words) > max_words:
        await update.message.reply_text(
            f"⚠️ *Text exceeds maximum word limit!*\n\n"
            f"Your message contains *{len(words)} words*, but the limit is currently set to *{max_words} words*.\n\n"
            f"💡 Please shorten your text or increase **Max Words Per Request** in the Localhost Settings panel (`http://127.0.0.1:7860/#tab-settings`).",
            parse_mode="Markdown",
        )
        return

    # 3. User is sending text to synthesize!
    voices = get_user_voices(uid)
    if not voices:
        await update.message.reply_text(
            "🎤 You don't have any saved voices yet!\n\n"
            "Send me a voice message first, and I will ask you for a name to save it.",
            parse_mode="Markdown",
        )
        return

    # Store text for voice selection callback
    ctx.user_data["pending_text"] = text

    # Build inline keyboard for voice selection
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
        f"💬 *Text ({len(words)} words):* \"{text[:120]}{'...' if len(text)>120 else ''}\"\n\n"
        f"👉 *Whose voice should speak this?*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def on_voice_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handles tapping a voice profile button."""
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
    if not text and query.message and query.message.text:
        msg_text = query.message.text
        if '💬 Text' in msg_text and '"' in msg_text:
            try:
                text = msg_text.split('"', 1)[1].rsplit('"', 1)[0].strip()
            except Exception:
                pass
        if not text and "👉 Whose voice should speak this?" in msg_text:
            text = msg_text.replace("👉 Whose voice should speak this?", "").strip()

    if not text:
        try:
            await query.edit_message_text("⚠️ Please send your text message again.")
        except Exception:
            pass
        return

    # Generate unique audio ID
    audio_id = f"{int(time.time())}_{re.sub(r'[^a-zA-Z0-9]', '', voice_name)[:10]}"
    audios_dir = user_audios_dir(uid)
    out_wav = audios_dir / f"{audio_id}.wav"
    out_ogg = audios_dir / f"{audio_id}.ogg"
    meta_txt = audios_dir / f"{audio_id}.txt"

    global sec_per_char
    estimate = max(5, len(text) * sec_per_char)
    queue_note = "\n⏳ Another job is currently running, you're queued next." if gpu_lock.locked() else ""

    try:
        await query.edit_message_text(
            f"🎙 Generating voice as *{voice_name}*…\n"
            f"⏱ Estimated time: ~{fmt_time(estimate)}{queue_note}\n{bar(0)}",
            parse_mode="Markdown",
        )
    except Exception:
        pass

    ref_wav = str(voice_dir / "ref.wav")
    ref_text = (voice_dir / "ref.txt").read_text(encoding="utf-8") if (voice_dir / "ref.txt").exists() else "Reference"

    async with gpu_lock:
        start_t = time.time()
        job = asyncio.create_task(
            asyncio.to_thread(voicecraft_generate, ref_wav, ref_text, text, str(out_wav))
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
            try:
                await query.edit_message_text(f"❌ Generation failed: {e}")
            except Exception:
                pass
            return

        took = time.time() - start_t
        sec_per_char = 0.7 * sec_per_char + 0.3 * (took / max(1, len(text)))

    # Save metadata for /audios manager
    try:
        meta_txt.write_text(f"{voice_name}:::{text}", encoding="utf-8")
    except Exception:
        pass

    try:
        await query.edit_message_text(
            f"✅ Spoken as *{voice_name}* in {fmt_time(took)}! {bar(100)}",
            parse_mode="Markdown",
        )
    except Exception:
        pass
    await query.message.chat.send_action(ChatAction.RECORD_VOICE)

    # Convert to OGG/Opus for Telegram voice note
    ffmpeg = get_ffmpeg_exe()
    converted_ogg = False
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", str(out_wav), "-c:a", "libopus", str(out_ogg)],
            check=True,
            capture_output=True,
        )
        converted_ogg = True
    except Exception:
        converted_ogg = False

    # Audio Action Buttons: Save & Delete
    audio_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💾 Save Audio", callback_data=f"save_audio:{audio_id}"),
            InlineKeyboardButton("🗑 Delete Audio", callback_data=f"del_audio:{audio_id}"),
        ]
    ])

    caption_text = f"🗣 {voice_name}: {text[:180]}"
    try:
        if converted_ogg and out_ogg.exists():
            with open(out_ogg, "rb") as fh:
                await query.message.reply_voice(fh, caption=caption_text, reply_markup=audio_markup)
        else:
            with open(out_wav, "rb") as fh:
                await query.message.reply_audio(
                    fh,
                    filename=f"{voice_name}_voicecraft.wav",
                    title=f"VoiceCraft ({voice_name})",
                    performer=voice_name,
                    caption=caption_text,
                    reply_markup=audio_markup,
                )
    except Exception as send_err:
        await query.message.reply_text(f"❌ Failed to send voice: {send_err}")


# ---------------------------------------------------- Audio Management Callbacks ---
async def on_del_audio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Deletes the audio file from disk and deletes or updates the Telegram message."""
    query = update.callback_query
    await query.answer()

    if not is_authorized(query.from_user.id):
        await query.answer("🚫 Unauthorized.", show_alert=True)
        return

    uid = query.from_user.id
    audio_id = query.data.split("del_audio:", 1)[1]
    audios_dir = user_audios_dir(uid)

    wav_p = audios_dir / f"{audio_id}.wav"
    ogg_p = audios_dir / f"{audio_id}.ogg"
    txt_p = audios_dir / f"{audio_id}.txt"

    # Delete local files
    for p in (wav_p, ogg_p, txt_p):
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass

    # Delete message from chat
    try:
        await query.message.delete()
        await query.answer("🗑 Audio deleted successfully!", show_alert=False)
    except Exception:
        try:
            await query.edit_message_caption(caption="🗑 *Audio has been deleted.*", parse_mode="Markdown")
        except Exception:
            try:
                await query.edit_message_text("🗑 *Audio has been deleted.*", parse_mode="Markdown")
            except Exception:
                pass
        await query.answer("🗑 Audio deleted!", show_alert=False)


async def on_save_audio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Permanently saves the generated audio to the project outputs/ folder."""
    query = update.callback_query

    if not is_authorized(query.from_user.id):
        await query.answer("🚫 Unauthorized.", show_alert=True)
        return

    uid = query.from_user.id
    audio_id = query.data.split("save_audio:", 1)[1]
    audios_dir = user_audios_dir(uid)
    wav_p = audios_dir / f"{audio_id}.wav"

    outputs_dir = BASE_DIR / "outputs"
    outputs_dir.mkdir(exist_ok=True)
    target_wav = outputs_dir / f"saved_{audio_id}.wav"

    if wav_p.exists():
        shutil.copy(wav_p, target_wav)
        new_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Saved to Outputs", callback_data=f"saved_done:{audio_id}"),
                InlineKeyboardButton("🗑 Delete Audio", callback_data=f"del_audio:{audio_id}"),
            ]
        ])
        try:
            await query.edit_message_reply_markup(reply_markup=new_markup)
        except Exception:
            pass
        await query.answer(f"💾 Saved to outputs/saved_{audio_id}.wav! Visible in History tab.", show_alert=True)
    else:
        await query.answer("⚠️ Original audio file not found.", show_alert=True)


async def on_saved_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("✅ This audio is already permanently saved in .\outputs\ folder.", show_alert=True)


async def audios_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Lists recent generated audios with Save & Delete buttons."""
    if not await check_auth(update):
        return

    uid = update.effective_user.id
    audios_dir = user_audios_dir(uid)

    txt_files = sorted(audios_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not txt_files:
        wav_files = sorted(audios_dir.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not wav_files:
            await update.message.reply_text("📂 You have no generated audios saved yet.")
            return
        txt_files = wav_files

    recent = txt_files[:5]
    await update.message.reply_text(
        f"📁 *Your Recent Generated Audios ({len(txt_files)} total):*\n"
        f"Showing latest {len(recent)} audios. Use `[ 💾 Save ]` or `[ 🗑 Delete ]`:",
        parse_mode="Markdown",
    )

    for item in recent:
        stem = item.stem
        wav_p = audios_dir / f"{stem}.wav"
        ogg_p = audios_dir / f"{stem}.ogg"
        txt_p = audios_dir / f"{stem}.txt"

        caption = stem
        if txt_p.exists():
            try:
                content = txt_p.read_text(encoding="utf-8")
                if ":::" in content:
                    v_name, txt_body = content.split(":::", 1)
                    caption = f"🗣 {v_name}: {txt_body[:100]}"
                else:
                    caption = content[:100]
            except Exception:
                pass

        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("💾 Save Audio", callback_data=f"save_audio:{stem}"),
                InlineKeyboardButton("🗑 Delete Audio", callback_data=f"del_audio:{stem}"),
            ]
        ])

        if ogg_p.exists():
            with open(ogg_p, "rb") as fh:
                await update.message.reply_voice(fh, caption=caption, reply_markup=markup)
        elif wav_p.exists():
            with open(wav_p, "rb") as fh:
                await update.message.reply_audio(fh, filename=f"{stem}.wav", caption=caption, reply_markup=markup)


async def clear_audios_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Deletes all cached audio files for this user."""
    if not await check_auth(update):
        return

    uid = update.effective_user.id
    audios_dir = user_audios_dir(uid)
    deleted = 0
    if audios_dir.exists():
        for f in list(audios_dir.glob("*")):
            try:
                f.unlink()
                deleted += 1
            except Exception:
                pass

    await update.message.reply_text(f"🧹 Cleaned up {deleted} cached audio files.")


async def restart_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Restarts the bot daemon process."""
    if not await check_auth(update):
        return

    await update.message.reply_text("🔄 Restarting VoiceCraft Bot...")
    os.execv(sys.executable, [sys.executable] + sys.argv)


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
            "⚠️ Please specify which voice to delete.\nUsage: `/delete <name>`",
            parse_mode="Markdown",
        )
        return

    name = " ".join(ctx.args).strip()
    d = user_dir(uid)
    voice_dir = d / name

    if voice_dir.exists() and voice_dir.is_dir():
        if name.lower() == "my_voice":
            try:
                (d / ".deleted_my_voice").touch()
            except Exception:
                pass
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
            if matched.name.lower() == "my_voice":
                try:
                    (d / ".deleted_my_voice").touch()
                except Exception:
                    pass
            shutil.rmtree(matched, ignore_errors=True)
            await update.message.reply_text(f"🗑 Voice *{matched.name}* has been deleted.", parse_mode="Markdown")
        else:
            await update.message.reply_text(
                f"❌ Voice *{name}* not found. Use `/voices` to see your saved voices.",
                parse_mode="Markdown",
            )


def main():
    print(f"============================================================")
    print(f"       VoiceCraft Telegram Bot (Audio Controls Enabled)     ")
    print(f"============================================================")
    allowed = get_allowed_user_ids()
    max_w = get_max_words()
    max_u = get_max_users()
    print(f"[VoiceCraft Bot] Max Words: {max_w} | Max Users: {max_u}")
    if allowed:
        print(f"[VoiceCraft Bot] Whitelist: {allowed}")
    else:
        print(f"[VoiceCraft Bot] Open capacity mode (capped at {max_u} users)")
    print(f"[VoiceCraft Bot] Listening for voice messages and text...")

    app = Application.builder().token(BOT_TOKEN.strip()).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("voices", voices_cmd))
    app.add_handler(CommandHandler("audios", audios_cmd))
    app.add_handler(CommandHandler("clear_audios", clear_audios_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(CommandHandler("restart", restart_cmd))
    app.add_handler(CommandHandler("id", id_cmd))

    # Callbacks
    app.add_handler(CallbackQueryHandler(on_voice_select, pattern=r"^voice:"))
    app.add_handler(CallbackQueryHandler(on_del_audio, pattern=r"^del_audio:"))
    app.add_handler(CallbackQueryHandler(on_save_audio, pattern=r"^save_audio:"))
    app.add_handler(CallbackQueryHandler(on_saved_done, pattern=r"^saved_done:"))

    # Media and Text
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.VIDEO_NOTE | filters.Document.AUDIO, on_audio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.run_polling()


if __name__ == "__main__":
    main()
