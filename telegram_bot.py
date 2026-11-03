"""
Telegram Voice Studio Bot
Claude-style minimal, calm, and polite interface.
Zero emojis, clean typography, single-message status flow, Hindi transliteration.
"""

import asyncio
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

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

import messages
import voice_style

BOT_TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN or BOT_TOKEN.strip() == "your_telegram_bot_token_here":
    print("Error: Telegram bot token is missing. Configure it in .env or the web studio.")
    sys.exit(1)

DATA = BASE_DIR / "bot_data"
DATA.mkdir(exist_ok=True)

MAX_REF_SECONDS = 15
DEFAULT_SEC_PER_CHAR = 0.35

gpu_lock = asyncio.Lock()
sec_per_char = DEFAULT_SEC_PER_CHAR
_whisper = None
_tts_model = None


# ---------------------------------------------------------------- Settings Helpers ---
def reload_env():
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
    uids = set()
    if DATA.exists():
        for p in DATA.iterdir():
            if p.is_dir() and p.name.isdigit():
                uids.add(int(p.name))
    return uids


def get_user_lang(uid: int) -> str:
    lang_file = user_dir(uid) / ".lang"
    if lang_file.exists():
        try:
            val = lang_file.read_text(encoding="utf-8").strip()
            if val:
                return val
        except Exception:
            pass
    return os.getenv("TELEGRAM_DEFAULT_LANG", "hi").strip() or "hi"


def set_user_lang(uid: int, lang_code: str):
    lang_file = user_dir(uid) / ".lang"
    try:
        lang_file.write_text(lang_code.strip().lower(), encoding="utf-8")
    except Exception:
        pass


def is_authorized(uid: int) -> bool:
    allowed = get_allowed_user_ids()
    if allowed and uid in allowed:
        return True
    if allowed and uid not in allowed:
        return False

    max_users = get_max_users()
    active_users = get_active_user_ids()

    if uid in active_users:
        return True
    if max_users > 0 and len(active_users) >= max_users:
        return False
    return True


async def check_auth(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else 0
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
            messages.BOT_CAPACITY_REACHED.format(max_users=max_users)
        )
        return False

    await msg.reply_text(
        messages.BOT_ACCESS_RESTRICTED.format(uid=uid)
    )
    return False


def get_ffmpeg_exe() -> str:
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
    d = user_dir(uid)
    default_src = BASE_DIR / "voices" / "my_voice.wav"
    user_my_voice = d / "my_voice"
    deleted_marker = d / ".deleted_my_voice"

    if default_src.exists() and not user_my_voice.exists() and not deleted_marker.exists():
        try:
            user_my_voice.mkdir(parents=True, exist_ok=True)
            to_wav(default_src, user_my_voice / "ref.wav", max_seconds=15)
            try:
                txt = transcribe(user_my_voice / "ref.wav", language="hi")
            except Exception:
                txt = "Reference voice sample"
            (user_my_voice / "ref.txt").write_text(txt or "Reference voice sample", encoding="utf-8")
        except Exception:
            pass

    voices = []
    if d.exists():
        for item in sorted(d.iterdir()):
            if item.is_dir() and item.name != "audios" and (item / "ref.wav").exists():
                voices.append(item.name)
    return voices


def to_wav(src: Path, dst: Path, max_seconds: int = MAX_REF_SECONDS):
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


def transcribe(wav: Path, language: str = "hi") -> str:
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel("base", compute_type="int8")
    try:
        segments, _ = _whisper.transcribe(str(wav), language=language)
        return " ".join(s.text.strip() for s in segments).strip()
    except Exception:
        # Fallback to auto-detect language
        segments, _ = _whisper.transcribe(str(wav))
        return " ".join(s.text.strip() for s in segments).strip()


def minimal_progress_bar(pct: int, width: int = 14) -> str:
    filled = max(0, min(width, int(width * pct / 100)))
    return "|" * filled + "." * (width - filled) + f"  {pct}%"


def fmt_time(sec: float) -> str:
    sec = max(1, int(round(sec)))
    return f"{sec}s" if sec < 60 else f"{sec // 60}m {sec % 60}s"


# ------------------------------------------------------- MODEL CONNECTION ---
def get_tts_model():
    global _tts_model
    if _tts_model is None:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        device = "cuda" if torch.cuda.is_available() else "cpu"
        t3_model = os.getenv("CHATTERBOX_MULTILINGUAL_T3_MODEL", "v3")
        print(f"Loading TTS model ({t3_model}) on {device}...")
        _tts_model = ChatterboxMultilingualTTS.from_pretrained(device, t3_model=t3_model)
        if hasattr(_tts_model, "eval"):
            _tts_model.eval()
        print("TTS Model loaded successfully.")
    return _tts_model


def voicecraft_generate(ref_wav: str, ref_text: str, text: str, out_wav: str, lang: str = "hi"):
    import urllib.request
    import json

    server_port = os.getenv("SERVER_PORT", "7860")
    server_host = os.getenv("SERVER_HOST", "127.0.0.1")
    server_url = f"http://{server_host}:{server_port}"

    # 1. Local server dispatch
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
                                return
                    except Exception:
                        pass
    except Exception:
        pass

    # 2. Standalone fallback
    import hinglish_pipeline
    model = get_tts_model()
    if lang == "mixed" or hinglish_pipeline.is_hinglish(text):
        hinglish_pipeline.generate_mixed(text, ref_wav, out_wav, model=model)
        return

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


# --------------------------------------------------------------- Handlers ---
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    await update.message.reply_text(messages.BOT_START)


async def id_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else 0
    await update.message.reply_text(f"User ID: {uid}")


async def status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    uid = update.effective_user.id
    max_w = get_max_words()
    cur_lang = get_user_lang(uid)
    voices = get_user_voices(uid)
    audios = list(user_audios_dir(uid).glob("*.wav"))

    lang_display = "Hindi" if cur_lang == "hi" else ("English" if cur_lang == "en" else cur_lang)
    txt = messages.BOT_STATUS.format(
        voice_count=len(voices),
        audio_count=len(audios),
        max_words=max_w,
        language=lang_display
    )
    await update.message.reply_text(txt)


async def on_audio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    msg = update.message
    media = msg.voice or msg.audio or msg.video_note or msg.document
    uid = update.effective_user.id
    d = user_dir(uid)

    status_msg = await msg.reply_text(messages.BOT_RECEIVING_AUDIO)
    temp_raw = d / "_temp_raw"
    temp_wav = d / "_temp_ref.wav"
    f = await media.get_file()
    await f.download_to_drive(temp_raw)

    await status_msg.edit_text(messages.BOT_PROCESSING_AUDIO)
    try:
        to_wav(temp_raw, temp_wav)
    except Exception:
        await status_msg.edit_text(messages.BOT_ERROR_AUDIO_QUALITY)
        return

    await status_msg.edit_text(messages.BOT_ANALYZING_VOICE)
    try:
        ref_text = await asyncio.to_thread(transcribe, temp_wav, "hi")
    except Exception:
        ref_text = "Reference voice"

    if not ref_text or not ref_text.strip():
        ref_text = "Reference voice"

    ctx.user_data["pending_voice"] = {
        "wav": str(temp_wav),
        "text": ref_text,
        "status_msg_id": status_msg.message_id
    }

    transcript_preview = f"\n\n_{ref_text[:90]}_" if ref_text else ""
    await status_msg.edit_text(
        f"{messages.BOT_ASK_VOICE_NAME}{transcript_preview}",
        parse_mode="Markdown"
    )


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    uid = update.effective_user.id
    text = update.message.text.strip()
    d = user_dir(uid)

    # 1. Naming a voice sample
    if "pending_voice" in ctx.user_data:
        pending = ctx.user_data.pop("pending_voice")
        voice_name = re.sub(r"[^\w\s-]", "", text).strip()
        voice_name = re.sub(r"\s+", " ", voice_name)[:25]
        if not voice_name:
            ctx.user_data["pending_voice"] = pending
            await update.message.reply_text("Please enter a name to save this voice.")
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
            messages.BOT_VOICE_SAVED.format(name=voice_name)
        )
        return

    # 2. Check Word Limit
    words = text.split()
    max_words = get_max_words()
    if len(words) > max_words:
        await update.message.reply_text(
            messages.BOT_TEXT_TOO_LONG.format(max_words=max_words)
        )
        return

    # 3. Check for saved voices
    voices = get_user_voices(uid)
    if not voices:
        await update.message.reply_text(messages.BOT_NO_VOICES)
        return

    # Auto-detect text type and transliterate Roman Hindi / Hinglish to Devanagari
    import hinglish_pipeline
    is_mixed = hinglish_pipeline.is_hinglish(text)
    text_type = voice_style.detect_text_type(text)
    clean_text, style = voice_style.clean_text_for_tts(text)

    if is_mixed:
        target_lang = "mixed"
    elif text_type in ("roman_hindi", "hinglish"):
        clean_text = voice_style.transliterate_to_devanagari(clean_text)
        target_lang = "hi"
    elif text_type == "devanagari":
        target_lang = "hi"
    else:
        target_lang = "en"

    # Store in context
    ctx.user_data["pending_text"] = clean_text
    ctx.user_data["detected_style"] = style
    ctx.user_data["target_lang"] = target_lang

    # Present voices in clean rows (maximum 3 buttons per row)
    keyboard = []
    row = []
    for v in voices:
        row.append(InlineKeyboardButton(v, callback_data=f"voice:{v}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    preview = f"_{clean_text[:80]}..._" if len(clean_text) > 80 else f"_{clean_text}_"
    await update.message.reply_text(
        f"{preview}\n\n{messages.BOT_CHOOSE_VOICE}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def on_voice_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_authorized(query.from_user.id):
        await query.edit_message_text("Access restricted.")
        return

    uid = query.from_user.id
    voice_name = query.data.split("voice:", 1)[1]
    d = user_dir(uid)
    voice_dir = d / voice_name

    if not (voice_dir / "ref.wav").exists():
        await query.edit_message_text(messages.BOT_VOICE_NOT_FOUND)
        return

    text = ctx.user_data.get("pending_text", "")
    style = ctx.user_data.get("detected_style", "natural")
    target_lang = ctx.user_data.get("target_lang", "hi")

    if not text and query.message and query.message.text:
        msg_text = query.message.text
        if "_" in msg_text:
            try:
                text = msg_text.split("_", 1)[1].split("_", 1)[0].strip()
            except Exception:
                pass

    if not text:
        await query.edit_message_text("Please send your text again.")
        return

    audio_id = f"{int(time.time())}_{re.sub(r'[^a-zA-Z0-9]', '', voice_name)[:8]}"
    audios_dir = user_audios_dir(uid)
    raw_wav = audios_dir / f"{audio_id}_raw.wav"
    out_wav = audios_dir / f"{audio_id}.wav"
    out_ogg = audios_dir / f"{audio_id}.ogg"
    meta_txt = audios_dir / f"{audio_id}.txt"

    global sec_per_char
    estimate = max(4, len(text) * sec_per_char)
    queued_note = f"\n\n{messages.BOT_GENERATING_QUEUED}" if gpu_lock.locked() else ""

    progress_line = minimal_progress_bar(0)
    await query.edit_message_text(
        f"Generating  {progress_line}  About {fmt_time(estimate)} left{queued_note}"
    )

    ref_wav = str(voice_dir / "ref.wav")
    ref_text = (voice_dir / "ref.txt").read_text(encoding="utf-8") if (voice_dir / "ref.txt").exists() else "Reference"

    async with gpu_lock:
        start_t = time.time()
        job = asyncio.create_task(
            asyncio.to_thread(voicecraft_generate, ref_wav, ref_text, text, str(raw_wav), target_lang)
        )

        last = -1
        while not job.done():
            await asyncio.sleep(2)
            pct = min(95, int((time.time() - start_t) / estimate * 100))
            if pct != last:
                last = pct
                left = max(1, estimate - (time.time() - start_t))
                progress_line = minimal_progress_bar(pct)
                try:
                    await query.edit_message_text(
                        f"Generating  {progress_line}  About {fmt_time(left)} left"
                    )
                except Exception:
                    pass

        try:
            await job
        except Exception:
            await query.edit_message_text(messages.BOT_ERROR_GENERIC)
            return

        took = time.time() - start_t
        sec_per_char = 0.7 * sec_per_char + 0.3 * (took / max(1, len(text)))

    # Apply mood/style audio post-processing
    voice_style.apply_audio_style(raw_wav, out_wav, style=style)
    if raw_wav.exists() and raw_wav != out_wav:
        try:
            raw_wav.unlink()
        except Exception:
            pass

    try:
        meta_txt.write_text(f"{voice_name}:::{text}", encoding="utf-8")
    except Exception:
        pass

    # Update single message to "Ready."
    try:
        await query.edit_message_text(messages.BOT_DONE)
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

    # Plain text buttons: Save and Delete
    audio_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Save", callback_data=f"save_audio:{audio_id}"),
            InlineKeyboardButton("Delete", callback_data=f"del_audio:{audio_id}"),
        ]
    ])

    caption_text = f"{voice_name}: {text[:140]}"
    try:
        if converted_ogg and out_ogg.exists():
            with open(out_ogg, "rb") as fh:
                await query.message.reply_voice(fh, caption=caption_text, reply_markup=audio_markup)
        else:
            with open(out_wav, "rb") as fh:
                await query.message.reply_audio(
                    fh,
                    filename=f"{voice_name}.wav",
                    title=f"{voice_name}",
                    caption=caption_text,
                    reply_markup=audio_markup,
                )
    except Exception as send_err:
        await query.message.reply_text(f"Could not send audio: {send_err}")


async def on_del_audio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_authorized(query.from_user.id):
        await query.answer("Access restricted.", show_alert=True)
        return

    uid = query.from_user.id
    audio_id = query.data.split("del_audio:", 1)[1]
    audios_dir = user_audios_dir(uid)

    for ext in (".wav", ".ogg", ".txt"):
        p = audios_dir / f"{audio_id}{ext}"
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass

    try:
        await query.message.delete()
        await query.answer(messages.BOT_AUDIO_DELETED, show_alert=False)
    except Exception:
        try:
            await query.edit_message_caption(caption=messages.BOT_AUDIO_DELETED)
        except Exception:
            pass


async def on_save_audio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_authorized(query.from_user.id):
        await query.answer("Access restricted.", show_alert=True)
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
                InlineKeyboardButton("Saved", callback_data=f"saved_done:{audio_id}"),
                InlineKeyboardButton("Delete", callback_data=f"del_audio:{audio_id}"),
            ]
        ])
        try:
            await query.edit_message_reply_markup(reply_markup=new_markup)
        except Exception:
            pass
        await query.answer(messages.BOT_AUDIO_SAVED, show_alert=True)
    else:
        await query.answer("Audio file not found.", show_alert=True)


async def on_saved_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("This audio is already saved in outputs.", show_alert=False)


async def voices_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    uid = update.effective_user.id
    voices = get_user_voices(uid)
    if not voices:
        await update.message.reply_text(messages.BOT_NO_VOICES)
        return

    lines = ["Saved voices:\n"]
    for idx, name in enumerate(voices, 1):
        v_dir = user_dir(uid) / name
        txt_path = v_dir / "ref.txt"
        transcript = txt_path.read_text(encoding="utf-8")[:50] if txt_path.exists() else ""
        if transcript:
            lines.append(f"{idx}. {name} - _{transcript}_")
        else:
            lines.append(f"{idx}. {name}")

    lines.append("\nUse /delete <name> to remove a voice.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def audios_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    uid = update.effective_user.id
    audios_dir = user_audios_dir(uid)

    txt_files = sorted(audios_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not txt_files:
        await update.message.reply_text("No generated audio found.")
        return

    recent = txt_files[:5]
    await update.message.reply_text(f"Recent audios ({len(txt_files)} total):")

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
                    caption = f"{v_name}: {txt_body[:80]}"
                else:
                    caption = content[:80]
            except Exception:
                pass

        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Save", callback_data=f"save_audio:{stem}"),
                InlineKeyboardButton("Delete", callback_data=f"del_audio:{stem}"),
            ]
        ])

        if ogg_p.exists():
            with open(ogg_p, "rb") as fh:
                await update.message.reply_voice(fh, caption=caption, reply_markup=markup)
        elif wav_p.exists():
            with open(wav_p, "rb") as fh:
                await update.message.reply_audio(fh, filename=f"{stem}.wav", caption=caption, reply_markup=markup)


async def clear_audios_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text(f"Deleted {deleted} cached files.")


async def delete_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return

    uid = update.effective_user.id
    if not ctx.args:
        await update.message.reply_text("Please specify which voice to delete. Example: /delete Tamanna")
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
        await update.message.reply_text(messages.BOT_VOICE_DELETED.format(name=name))
    else:
        await update.message.reply_text(messages.BOT_VOICE_NOT_FOUND)


async def restart_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    await update.message.reply_text("Restarting bot...")
    os.execv(sys.executable, [sys.executable] + sys.argv)


def main():
    print("Starting Telegram Voice Studio Bot...")
    app = Application.builder().token(BOT_TOKEN.strip()).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("voices", voices_cmd))
    app.add_handler(CommandHandler("audios", audios_cmd))
    app.add_handler(CommandHandler("clear_audios", clear_audios_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(CommandHandler("restart", restart_cmd))
    app.add_handler(CommandHandler("id", id_cmd))

    app.add_handler(CallbackQueryHandler(on_voice_select, pattern=r"^voice:"))
    app.add_handler(CallbackQueryHandler(on_del_audio, pattern=r"^del_audio:"))
    app.add_handler(CallbackQueryHandler(on_save_audio, pattern=r"^save_audio:"))
    app.add_handler(CallbackQueryHandler(on_saved_done, pattern=r"^saved_done:"))

    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.VIDEO_NOTE | filters.Document.AUDIO, on_audio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.run_polling()


if __name__ == "__main__":
    main()
