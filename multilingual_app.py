import base64
import datetime
import gc
import io
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

# Ensure UTF-8 output encoding on Windows consoles
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv, set_key
import numpy as np
import soundfile as sf
import torch
import gradio as gr

# Load environment & YAML configuration
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH, override=True)

from config import load_config, save_config
APP_CONFIG = load_config()

from chatterbox.mtl_tts import ChatterboxMultilingualTTS, SUPPORTED_LANGUAGES

# --- Directories & Paths ---
VOICES_DIR = BASE_DIR / "voices"
OUTPUTS_DIR = BASE_DIR / "outputs"
VOICES_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
MY_VOICE_PATH = VOICES_DIR / "my_voice.wav"

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
T3_MODEL = os.getenv("CHATTERBOX_MULTILINGUAL_T3_MODEL", "v3")

# Optimize CPU threads if running on CPU
if DEVICE == "cpu":
    try:
        cores = os.cpu_count() or 4
        torch.set_num_threads(max(1, cores - 2))
    except Exception:
        pass

print(f"[VoiceCraft] Device: {DEVICE} | Model: {T3_MODEL}")

# --- Global Model Initialization ---
MODEL = None
BOT_PROCESS: subprocess.Popen | None = None


def get_or_load_model() -> ChatterboxMultilingualTTS:
    """Loads the ChatterboxMultilingualTTS model if not already in memory."""
    global MODEL
    if MODEL is None:
        print("[VoiceCraft] Loading ChatterboxMultilingualTTS model into memory...")
        try:
            MODEL = ChatterboxMultilingualTTS.from_pretrained(DEVICE, t3_model=T3_MODEL)
            if hasattr(MODEL, "to") and str(MODEL.device) != DEVICE:
                MODEL.to(DEVICE)
            if hasattr(MODEL, "eval"):
                MODEL.eval()
            print(f"[VoiceCraft] Model loaded successfully on {getattr(MODEL, 'device', DEVICE)}")
        except Exception as e:
            print(f"[VoiceCraft] Error loading model: {e}")
            raise
    return MODEL


COND_PATH = VOICES_DIR / "my_voice.cond.pt"

# Pre-load model & cached voice conditionals on startup
try:
    _init_model = get_or_load_model()
    if MY_VOICE_PATH.exists():
        try:
            if COND_PATH.exists() and COND_PATH.stat().st_mtime >= MY_VOICE_PATH.stat().st_mtime:
                print(f"[VoiceCraft] Loading precomputed conditionals from {COND_PATH.name}...")
                _init_model.conds = torch.load(str(COND_PATH), map_location=getattr(_init_model, "device", DEVICE), weights_only=False)
                print("[VoiceCraft] Precomputed voice conditionals loaded successfully.")
            else:
                print(f"[VoiceCraft] Pre-caching voice conditionals from {MY_VOICE_PATH.name}...")
                _init_model.prepare_conditionals(str(MY_VOICE_PATH))
                if hasattr(_init_model, "conds") and _init_model.conds is not None:
                    torch.save(_init_model.conds, str(COND_PATH))
                    print(f"[VoiceCraft] Saved voice conditionals to {COND_PATH.name}.")
                print("[VoiceCraft] Saved voice conditionals cached successfully.")
        except Exception as ve_err:
            print(f"[VoiceCraft] Note: Saved voice pre-cache notice: {ve_err}")
except Exception as e:
    print(f"[VoiceCraft] Warning: Failed to pre-warm model at startup: {e}")


def split_text_into_chunks(text: str, max_chars: int = 250) -> list[str]:
    """
    Split text into sentence/clause chunks under max_chars for natural speech synthesis.
    Supports English, Hindi (।), East Asian (。), and multilingual punctuation.
    """
    text = text.strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    all_sentences = []

    sentence_pattern = re.compile(r"([^.!?।。\n]+[.!?।。\n]*)")

    for para in paragraphs:
        parts = sentence_pattern.findall(para)
        if not parts:
            parts = [para]
        for part in parts:
            part = part.strip()
            if part:
                all_sentences.append(part)

    chunks = []
    current_chunk = ""

    for sent in all_sentences:
        if len(sent) > max_chars:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""

            sub_parts = re.split(r"([,;:\s]+)", sent)
            sub_chunk = ""
            for sp in sub_parts:
                if len(sub_chunk) + len(sp) <= max_chars:
                    sub_chunk += sp
                else:
                    if sub_chunk.strip():
                        chunks.append(sub_chunk.strip())
                    sub_chunk = sp
            if sub_chunk.strip():
                chunks.append(sub_chunk.strip())
        else:
            if not current_chunk:
                current_chunk = sent
            elif len(current_chunk) + 1 + len(sent) <= max_chars:
                current_chunk += " " + sent
            else:
                chunks.append(current_chunk.strip())
                current_chunk = sent

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def read_audio_file(file_path: str | Path):
    """
    Reads audio in virtually any format (.wav, .m4a, .mp3, .flac, .aac, .ogg)
    using soundfile or PyAV, converting to mono float32 at 24000 Hz.
    """
    file_path = str(file_path)
    try:
        data, sr = sf.read(file_path)
        if len(data.shape) > 1:
            data = np.mean(data, axis=1)
        return data.astype(np.float32), sr
    except Exception:
        import av
        container = av.open(file_path)
        resampler = av.AudioResampler(format="s16", layout="mono", rate=24000)
        frames = []
        for frame in container.decode(audio=0):
            frames.extend(resampler.resample(frame))
        frames.extend(resampler.resample(None))
        data = np.concatenate([f.to_ndarray() for f in frames], axis=1).squeeze(0) / 32768.0
        return data.astype(np.float32), 24000


def save_voice_sample(audio_path: str | None):
    """
    Saves the recorded or uploaded audio into voices/my_voice.wav
    as a clean 16-bit PCM mono WAV file.
    """
    if not audio_path or not os.path.exists(audio_path):
        raise gr.Error("Please upload or record a voice sample before clicking 'Save my voice'.")

    try:
        audio_data, sample_rate = read_audio_file(audio_path)
        sf.write(str(MY_VOICE_PATH), audio_data, sample_rate, subtype="PCM_16")

        model = get_or_load_model()
        model.prepare_conditionals(str(MY_VOICE_PATH))

        return str(MY_VOICE_PATH), f"✅ Voice loaded: {MY_VOICE_PATH.name} (stored permanently in voices/)"
    except Exception as e:
        raise gr.Error(f"Failed to save voice sample: {str(e)}")


# --- Audio Processing & In-Memory Stitching Utilities ---

def normalize_chunk_loudness(chunk: np.ndarray, target_peak: float = 0.95) -> np.ndarray:
    """Normalize peak loudness of an in-memory chunk to maintain consistent volume without clipping."""
    max_val = np.max(np.abs(chunk))
    if max_val > 1e-4:
        return (chunk * (target_peak / max_val)).astype(np.float32)
    return chunk.astype(np.float32)


def chunk_to_base64_wav(chunk: np.ndarray, sr: int) -> str:
    """Encodes an in-memory float32 audio chunk into a base64 WAV data URL for live browser streaming."""
    buf = io.BytesIO()
    normalized = normalize_chunk_loudness(chunk, target_peak=0.95)
    sf.write(buf, normalized, sr, format="WAV", subtype="PCM_16")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:audio/wav;base64,{b64}"


def join_audio_chunks(
    chunks: list[np.ndarray],
    sr: int,
    pause_ms: int = 200,
    crossfade_ms: int = 30,
) -> np.ndarray:
    """
    Joins in-memory audio chunks into ONE continuous stream:
    - Normalizes loudness consistently across chunks
    - Smooth crossfade transitions (20-50 ms) to prevent clicks or DC offsets
    - Configurable natural silence pause between sentences
    - Soft clipping limiter to guarantee peak never clips
    """
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    if len(chunks) == 1:
        return normalize_chunk_loudness(chunks[0])

    normalized_chunks = [normalize_chunk_loudness(c) for c in chunks]
    crossfade_samples = int(sr * (crossfade_ms / 1000.0))
    pause_samples = int(sr * (pause_ms / 1000.0))

    processed = []
    for c in normalized_chunks:
        item = c.copy()
        if len(item) > 2 * crossfade_samples and crossfade_samples > 0:
            fade_in = np.linspace(0.0, 1.0, crossfade_samples, dtype=np.float32)
            fade_out = np.linspace(1.0, 0.0, crossfade_samples, dtype=np.float32)
            item[:crossfade_samples] *= fade_in
            item[-crossfade_samples:] *= fade_out
        processed.append(item)

    silence = np.zeros(pause_samples, dtype=np.float32) if pause_samples > 0 else np.zeros(0, dtype=np.float32)
    stitched = []
    for i, c in enumerate(processed):
        stitched.append(c)
        if i < len(processed) - 1 and len(silence) > 0:
            stitched.append(silence)

    final = np.concatenate(stitched)
    peak = np.max(np.abs(final))
    if peak > 0.98:
        final = final * (0.95 / peak)
    return final.astype(np.float32)


def render_stream_player_html(
    gen_id: str,
    data_url: str | None = None,
    chunk_idx: int = 0,
    total_chunks: int = 1,
    is_final: bool = False,
    is_preparing: bool = False,
) -> str:
    """Renders the HTML/JS queue player that streams and plays chunks back-to-back without gap or disk I/O."""
    if is_preparing:
        return f"""
        <div class="vc-stream-box" style="margin-top:8px; padding:12px; background:rgba(30,41,59,0.7); border:1px solid #3b82f6; border-radius:10px;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <strong style="color:#60a5fa; font-size:13px;">⚡ Live Audio Stream</strong>
            <span style="background:#eab308; color:#000; padding:2px 8px; border-radius:12px; font-size:11px; font-weight:600;">⏳ Synthesizing Chunk 1...</span>
          </div>
          <p style="font-size:12px; color:#94a3b8; margin:6px 0 0 0;">First audio chunk will play automatically in your browser the moment it is ready in memory.</p>
        </div>
        """

    is_final_js = "true" if is_final else "false"
    safe_data_url = data_url or ""

    return f"""
    <div class="vc-stream-box" style="margin-top:8px; padding:12px; background:rgba(30,41,59,0.7); border:1px solid #3b82f6; border-radius:10px;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
        <strong style="color:#60a5fa; font-size:13px;">⚡ Live Audio Stream (In-Memory)</strong>
        <span id="vc-stream-badge" style="background:#2563eb; color:#fff; padding:2px 8px; border-radius:12px; font-size:11px; font-weight:600;">
          Streaming chunk {chunk_idx + 1} of {total_chunks}
        </span>
      </div>
      <p id="vc-stream-desc" style="font-size:12px; color:#94a3b8; margin:0 0 8px 0;">Playing chunks back-to-back in RAM (zero temporary files written to disk).</p>
      <audio id="vc-live-audio" controls autoplay style="width:100%; height:36px; border-radius:6px; outline:none;"></audio>
    </div>
    <script>
    (function() {{
      window._vcStreamState = window._vcStreamState || {{
        id: null,
        queue: [],
        currentIndex: -1
      }};
      const state = window._vcStreamState;
      const genId = "{gen_id}";
      if (state.id !== genId) {{
        state.id = genId;
        state.queue = [];
        state.currentIndex = -1;
      }}
      const newChunk = "{safe_data_url}";
      const isFinal = {is_final_js};
      const total = {total_chunks};
      const audioEl = document.getElementById("vc-live-audio");

      if (newChunk && newChunk.startsWith("data:audio") && !state.queue.includes(newChunk)) {{
        state.queue.push(newChunk);
      }}

      function playNext() {{
        if (state.currentIndex + 1 < state.queue.length) {{
          state.currentIndex++;
          audioEl.src = state.queue[state.currentIndex];
          audioEl.play().catch(e => console.log("Stream audio play:", e));
          const badge = document.getElementById("vc-stream-badge");
          if (badge) badge.innerText = `Playing chunk ${{state.currentIndex + 1}} / ${{total}}`;
        }} else if (isFinal) {{
          const badge = document.getElementById("vc-stream-badge");
          if (badge) {{
            badge.innerText = "Stream Complete";
            badge.style.background = "#10b981";
          }}
          const desc = document.getElementById("vc-stream-desc");
          if (desc) desc.innerText = `All ${{total}} streamed chunks played! Master continuous audio is ready below.`;
        }}
      }}

      audioEl.onended = function() {{
        playNext();
      }};

      if (audioEl.paused && state.currentIndex < state.queue.length - 1) {{
        playNext();
      }}
    }})();
    </script>
    """


# --- Core Speech Generation Engine (Streaming & In-Memory Single File) ---

def generate_speech_stream(
    text: str,
    language_code: str,
    audio_input_path: str | None,
    exaggeration: float = 0.5,
    cfg_weight: float = 0.5,
    temperature: float = 0.8,
    stream_playback: bool = True,
    pause_between_chunks_ms: int = 200,
    crossfade_ms: int = 30,
    keep_partial_on_cancel: bool = False,
    progress=gr.Progress(track_tqdm=True),
):
    """
    Generator function that:
    1. Splits text into sentence chunks and synthesizes chunk by chunk.
    2. Keeps chunks ONLY IN MEMORY (tensors/numpy arrays); zero chunk files written to disk.
    3. Streams each chunk to the browser in real time via an in-memory base64 queue player.
    4. When all chunks finish, joins them into ONE continuous audio file (.\outputs\<timestamp>.wav).
    5. Frees GPU/CPU memory after generation.
    6. If cancelled, discards chunks (unless keep_partial_on_cancel is True).
    """
    if not text or not text.strip():
        raise gr.Error("Please enter some text to speak.")

    chosen_voice_path = None
    if MY_VOICE_PATH.exists():
        chosen_voice_path = str(MY_VOICE_PATH)
    elif audio_input_path and os.path.exists(audio_input_path):
        chosen_voice_path = audio_input_path
    else:
        raise gr.Error("Please save your voice first (or upload/record a voice sample in Section 1).")

    chunks = split_text_into_chunks(text, max_chars=250)
    if not chunks:
        raise gr.Error("No valid text found to synthesize.")

    model = get_or_load_model()
    gen_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    chunks_in_memory: list[np.ndarray] = []
    sr = model.sr

    # Yield initial preparing state
    initial_html = render_stream_player_html(gen_id, is_preparing=True) if stream_playback else ""
    yield initial_html, None, None, f"⏳ Initializing voice conditionals & synthesizing {len(chunks)} chunks..."

    try:
        model.prepare_conditionals(chosen_voice_path, exaggeration=float(exaggeration))

        with torch.inference_mode():
            for idx, chunk in enumerate(chunks):
                if progress:
                    progress((idx + 1) / len(chunks), desc=f"Synthesizing sentence {idx+1}/{len(chunks)}...")
                print(f"[VoiceCraft] Synthesizing [{idx + 1}/{len(chunks)}]: '{chunk[:50]}...'")

                wav = model.generate(
                    chunk,
                    language_id=language_code,
                    audio_prompt_path=None,
                    exaggeration=float(exaggeration),
                    cfg_weight=float(cfg_weight),
                    temperature=float(temperature),
                )
                chunk_np = wav.squeeze(0).cpu().numpy().astype(np.float32)
                chunks_in_memory.append(chunk_np)

                # Prepare in-memory base64 stream chunk
                if stream_playback:
                    chunk_data_url = chunk_to_base64_wav(chunk_np, sr)
                    stream_html = render_stream_player_html(
                        gen_id=gen_id,
                        data_url=chunk_data_url,
                        chunk_idx=idx,
                        total_chunks=len(chunks),
                        is_final=False,
                    )
                else:
                    stream_html = ""

                status_msg = f"⚡ **Streaming chunk {idx + 1} of {len(chunks)}** in memory..."
                yield stream_html, None, None, status_msg

        # All chunks generated in memory: Stitch into ONE continuous audio
        print(f"[VoiceCraft] Joining {len(chunks_in_memory)} chunks into single continuous audio...")
        final_audio = join_audio_chunks(
            chunks_in_memory,
            sr,
            pause_ms=int(pause_between_chunks_ms),
            crossfade_ms=int(crossfade_ms),
        )

        # Save EXACTLY ONE continuous file: .\outputs\<timestamp>.wav
        output_filename = f"{gen_id}.wav"
        output_filepath = OUTPUTS_DIR / output_filename
        sf.write(str(output_filepath), final_audio, sr, subtype="PCM_16")
        print(f"[VoiceCraft] Saved single continuous file: {output_filepath}")

        # Final stream player state
        if stream_playback:
            final_stream_html = render_stream_player_html(
                gen_id=gen_id,
                data_url=None,
                chunk_idx=len(chunks) - 1,
                total_chunks=len(chunks),
                is_final=True,
            )
        else:
            final_stream_html = ""

        duration_sec = len(final_audio) / sr
        info_badge = (
            f"✨ **Generation Complete**: Single file saved to `outputs/{output_filename}` | "
            f"Chunks: **{len(chunks_in_memory)}** | Duration: **{duration_sec:.1f}s** | Rate: **{sr} Hz**"
        )

        # Yield single master continuous file to Gradio Audio player and Download button
        yield final_stream_html, str(output_filepath), str(output_filepath), info_badge

    except GeneratorExit:
        print("[VoiceCraft] Generation was cancelled by user.")
        if keep_partial_on_cancel and chunks_in_memory:
            print("[VoiceCraft] Saving partial audio because keep_partial_on_cancel is True...")
            partial_audio = join_audio_chunks(chunks_in_memory, sr, pause_ms=int(pause_between_chunks_ms), crossfade_ms=int(crossfade_ms))
            partial_file = OUTPUTS_DIR / f"{gen_id}_partial.wav"
            sf.write(str(partial_file), partial_audio, sr, subtype="PCM_16")
            yield "", str(partial_file), str(partial_file), f"⚠️ Cancelled: Partial audio saved to `outputs/{partial_file.name}`"
        else:
            print("[VoiceCraft] Generation stopped: Discarding in-memory chunks (zero files written to disk).")
            yield "", None, None, "🛑 Generation stopped cleanly. Memory freed."
        raise
    except Exception as e:
        print(f"[VoiceCraft] Error during speech synthesis: {e}")
        yield "", None, None, f"❌ Speech synthesis error: {str(e)}"
        raise gr.Error(f"Speech synthesis error: {str(e)}")
    finally:
        # Free memory and clean tensors
        del chunks_in_memory
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def generate_speech(
    text: str,
    language_code: str,
    audio_input_path: str | None = None,
    exaggeration: float = 0.5,
    cfg_weight: float = 0.5,
    temperature: float = 0.8,
    stream_playback: bool = False,
    pause_between_chunks_ms: int = 200,
    crossfade_ms: int = 30,
    keep_partial_on_cancel: bool = False,
    progress=None,
):
    """
    Synchronous wrapper for callers (such as telegram_bot.py or benchmark.py).
    Iterates through the stream generator and returns the final continuous result:
    (output_filepath, output_filepath, info_badge).
    """
    final_result = (None, None, "No output generated.")
    for res in generate_speech_stream(
        text=text,
        language_code=language_code,
        audio_input_path=audio_input_path,
        exaggeration=exaggeration,
        cfg_weight=cfg_weight,
        temperature=temperature,
        stream_playback=stream_playback,
        pause_between_chunks_ms=pause_between_chunks_ms,
        crossfade_ms=crossfade_ms,
        keep_partial_on_cancel=keep_partial_on_cancel,
        progress=progress,
    ):
        # res is: (stream_html, audio_file, download_file, info_badge)
        if res[1] is not None:
            final_result = (res[1], res[2], res[3])
    return final_result


def generate_batch_speech_stream(
    batch_text: str,
    language_code: str,
    audio_input_path: str | None,
    exaggeration: float = 0.5,
    cfg_weight: float = 0.5,
    temperature: float = 0.8,
    stream_playback: bool = True,
    pause_between_chunks_ms: int = 200,
    crossfade_ms: int = 30,
    progress=gr.Progress(track_tqdm=True),
):
    """
    Batch generation: Each submitted line is synthesized, chunks are kept in memory,
    and exactly ONE final .wav per clip is saved to outputs/.
    Returns final file list and a downloadable zip archive containing ONLY the final clips.
    """
    lines = [line.strip() for line in batch_text.split("\n") if line.strip()]
    if not lines:
        raise gr.Error("Please enter at least one line of text to synthesize.")

    generated_final_files = []
    batch_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    for i, line in enumerate(lines):
        if progress:
            progress(i / len(lines), desc=f"Processing clip {i+1}/{len(lines)}: '{line[:30]}...'")

        # Synthesize clip using generator in memory
        clip_file = None
        for res in generate_speech_stream(
            text=line,
            language_code=language_code,
            audio_input_path=audio_input_path,
            exaggeration=exaggeration,
            cfg_weight=cfg_weight,
            temperature=temperature,
            stream_playback=stream_playback,
            pause_between_chunks_ms=pause_between_chunks_ms,
            crossfade_ms=crossfade_ms,
            keep_partial_on_cancel=False,
            progress=None,
        ):
            if res[1] is not None:
                clip_file = res[1]

        if clip_file and os.path.exists(clip_file):
            generated_final_files.append(clip_file)

        status_txt = f"⚡ Batch Progress: Completed **{len(generated_final_files)} of {len(lines)} clips**."
        yield generated_final_files, None, status_txt

    # Create zip containing ONLY the final saved clips
    zip_path = OUTPUTS_DIR / f"{batch_timestamp}_batch.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in generated_final_files:
            zf.write(f, arcname=Path(f).name)

    summary_text = f"✅ Batch Complete: Generated **{len(generated_final_files)} clips** into `outputs/`!"
    yield generated_final_files, str(zip_path), summary_text


# --- Settings & Telegram Bot Management ---

def save_env_settings(host: str, port: str, token: str, default_lang: str):
    """Safely updates .env configuration without exposing secrets to git."""
    try:
        ENV_PATH.touch(exist_ok=True)
        set_key(str(ENV_PATH), "SERVER_HOST", host.strip() or "127.0.0.1")
        set_key(str(ENV_PATH), "SERVER_PORT", port.strip() or "7860")
        set_key(str(ENV_PATH), "TELEGRAM_BOT_TOKEN", token.strip() if token else "")
        set_key(str(ENV_PATH), "TELEGRAM_DEFAULT_LANG", default_lang.strip() or "en")
        load_dotenv(ENV_PATH, override=True)
        return "✅ Settings saved successfully to `.env` (Private & Ignored by Git)!"
    except Exception as e:
        return f"❌ Error saving settings: {str(e)}"


def get_telegram_bot_status() -> str:
    """Returns runtime status of the Telegram bot background process."""
    global BOT_PROCESS
    if BOT_PROCESS is not None and BOT_PROCESS.poll() is None:
        return "🟢 **Status: RUNNING** (Listening for Telegram messages)"

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or token == "your_telegram_bot_token_here":
        return "⚠️ **Status: STOPPED** (Telegram Bot Token is missing or not configured)"
    return "⚪ **Status: STOPPED**"


def start_telegram_bot(token_input: str | None = None):
    """Starts the Telegram bot in an isolated background subprocess."""
    global BOT_PROCESS
    if BOT_PROCESS is not None and BOT_PROCESS.poll() is None:
        return "🟢 Telegram bot is already running!"

    token = (token_input or os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
    if not token or token == "your_telegram_bot_token_here":
        raise gr.Error("Please enter your Telegram Bot Token and click 'Save Settings' before starting the bot.")

    bot_script = BASE_DIR / "telegram_bot.py"
    if not bot_script.exists():
        raise gr.Error("telegram_bot.py not found in the project root.")

    venv_py = BASE_DIR / ".venv" / "Scripts" / "python.exe"
    python_exe = str(venv_py) if venv_py.exists() else sys.executable

    try:
        env = os.environ.copy()
        env["TELEGRAM_BOT_TOKEN"] = token
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        BOT_PROCESS = subprocess.Popen(
            [python_exe, str(bot_script)],
            cwd=str(BASE_DIR),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return "🟢 **Telegram Bot started successfully!** Open your bot on Telegram and send any text message to test."
    except Exception as e:
        raise gr.Error(f"Failed to start Telegram Bot: {str(e)}")


def stop_telegram_bot():
    """Stops the Telegram bot background subprocess."""
    global BOT_PROCESS
    if BOT_PROCESS is not None:
        try:
            BOT_PROCESS.terminate()
            try:
                BOT_PROCESS.wait(timeout=2)
            except Exception:
                BOT_PROCESS.kill()
        except Exception:
            pass
        BOT_PROCESS = None

    if sys.platform == "win32":
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process -Filter \"CommandLine LIKE '%telegram_bot.py%'\" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
                capture_output=True,
                timeout=5
            )
        except Exception:
            pass

    return "⚪ **Telegram Bot stopped successfully.**"


# --- Language Dropdown Configuration ---
LANG_CHOICES = []
for code, name in sorted(SUPPORTED_LANGUAGES.items(), key=lambda x: (x[0] != "en", x[1])):
    LANG_CHOICES.append((f"{name} ({code})", code))

# --- Initial UI States ---
initial_voice_file = str(MY_VOICE_PATH) if MY_VOICE_PATH.exists() else None
initial_status_text = (
    f"✅ **Voice loaded**: `{MY_VOICE_PATH.name}` (Ready for cloning)"
    if MY_VOICE_PATH.exists()
    else "ℹ️ **No saved voice found**. Upload or record a 10-20s sample below and click **Save my voice**."
)

env_host = os.getenv("SERVER_HOST", "127.0.0.1")
env_port = os.getenv("SERVER_PORT", "7860")
env_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
env_def_lang = os.getenv("TELEGRAM_DEFAULT_LANG", "en")

# --- Custom Styling ---
custom_css = """
.main-header {
    text-align: center;
    margin-bottom: 1.2rem;
}
.main-header h1 {
    font-size: 2.2rem;
    font-weight: 800;
    background: linear-gradient(135deg, #4f46e5 0%, #06b6d4 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 0.2rem;
}
.vc-stream-box {
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
}
"""

with gr.Blocks(title="VoiceCraft - Multilingual Voice Cloning Studio") as demo:
    with gr.Column(elem_classes=["main-header"]):
        gr.Markdown(
            """
            # 🎙️ VoiceCraft
            ### Multilingual Voice Cloning Studio & Live Stream Audio
            """
        )

    with gr.Tabs() as tabs:
        # ==========================================
        # TAB 1: VoiceCraft Studio (Main Studio Page)
        # ==========================================
        with gr.TabItem("🎙️ VoiceCraft Studio", id="studio_tab"):
            with gr.Row():
                # Left Column: Inputs & Controls
                with gr.Column(scale=1):
                    gr.Markdown("### 1. Your Voice")
                    voice_input = gr.Audio(
                        sources=["upload", "microphone"],
                        type="filepath",
                        label="Voice Sample (10-20 seconds of clear speech, WAV/M4A/MP3)",
                        value=initial_voice_file,
                    )
                    save_voice_btn = gr.Button("💾 Save my voice", variant="secondary")
                    voice_status = gr.Markdown(value=initial_status_text)

                    gr.Markdown("### 2. Text to Speak")
                    with gr.Tabs():
                        with gr.TabItem("Single Text (Streaming)"):
                            text_input = gr.Textbox(
                                lines=4,
                                label="Text to synthesize",
                                placeholder="Type or paste the text you want your cloned voice to speak...",
                                value="Hello! Welcome to VoiceCraft. Voice cloning across twenty-three languages made simple.",
                            )
                            language_dropdown = gr.Dropdown(
                                choices=LANG_CHOICES,
                                value="en",
                                label="Language",
                                info="Default: English. Supports Hindi (hi) and 21 other languages.",
                            )

                            with gr.Accordion("⚙️ Advanced Audio & Streaming Controls", open=False):
                                exaggeration_slider = gr.Slider(
                                    minimum=0.25,
                                    maximum=2.0,
                                    value=APP_CONFIG["generation"]["exaggeration"],
                                    step=0.05,
                                    label="Exaggeration (0.5 is neutral natural voice)",
                                )
                                cfg_slider = gr.Slider(
                                    minimum=0.0,
                                    maximum=1.0,
                                    value=APP_CONFIG["generation"]["cfg_weight"],
                                    step=0.05,
                                    label="CFG Weight (0.5 standard; 0.0 is 2x faster and good for cross-lingual)",
                                )
                                temp_slider = gr.Slider(
                                    minimum=0.05,
                                    maximum=2.0,
                                    value=APP_CONFIG["generation"]["temperature"],
                                    step=0.05,
                                    label="Temperature (Variation & randomness)",
                                )
                                stream_playback_chk = gr.Checkbox(
                                    value=APP_CONFIG["audio"]["stream_playback"],
                                    label="Stream Playback (Plays chunks in-memory immediately as generated)",
                                )
                                pause_ms_slider = gr.Slider(
                                    minimum=0,
                                    maximum=600,
                                    value=APP_CONFIG["audio"]["pause_between_chunks_ms"],
                                    step=25,
                                    label="Inter-sentence Pause (ms)",
                                    info="Natural silence added between sentence chunks in the final continuous file.",
                                )
                                crossfade_ms_slider = gr.Slider(
                                    minimum=0,
                                    maximum=100,
                                    value=APP_CONFIG["audio"]["crossfade_ms"],
                                    step=5,
                                    label="Crossfade Window (ms)",
                                    info="Boundary transition smoothing to eliminate pops and clicks.",
                                )
                                keep_partial_chk = gr.Checkbox(
                                    value=APP_CONFIG["audio"]["keep_partial_on_cancel"],
                                    label="Keep Partial Audio on Cancel",
                                    info="If checked, saves partial stitched audio when generation is stopped halfway.",
                                )

                            with gr.Row():
                                generate_btn = gr.Button("🔊 Generate Speech", variant="primary", scale=3, size="lg")
                                stop_btn = gr.Button("🛑 Stop", variant="stop", scale=1, size="lg")

                        with gr.TabItem("Batch Generation (Multiple Clips)"):
                            batch_text_input = gr.Textbox(
                                lines=6,
                                label="Batch Sentences (one sentence per line)",
                                placeholder="Sentence 1: Welcome to our podcast.\nSentence 2: Today we talk about artificial intelligence.\nSentence 3: Thanks for listening!",
                                value="Welcome to our podcast.\nToday we talk about artificial intelligence.\nThanks for listening!",
                            )
                            batch_language_dropdown = gr.Dropdown(
                                choices=LANG_CHOICES,
                                value="en",
                                label="Batch Language",
                            )
                            with gr.Row():
                                generate_batch_btn = gr.Button("⚡ Generate All Clips", variant="primary", scale=3, size="lg")
                                stop_batch_btn = gr.Button("🛑 Stop Batch", variant="stop", scale=1, size="lg")

                # Right Column: Audio Outputs
                with gr.Column(scale=1):
                    gr.Markdown("### 3. Audio Output")
                    # Live in-memory streaming player
                    stream_player_box = gr.HTML(value="")

                    audio_info = gr.Markdown(value="*Status and file details will appear here.*")
                    audio_output = gr.Audio(
                        label="Final Master Audio Player (Single Continuous File)",
                        type="filepath",
                        interactive=False,
                    )
                    download_output = gr.File(
                        label="Download Final WAV (.wav)",
                        interactive=False,
                    )

                    gr.Markdown("### Batch Outputs")
                    batch_status_md = gr.Markdown(value="*Batch files will be listed below when generated.*")
                    batch_gallery = gr.Files(label="Generated Batch Clips", interactive=False)
                    batch_zip_output = gr.File(label="Download All Clips (.zip)", interactive=False)

            # Tab 1 Callbacks
            save_voice_btn.click(
                fn=save_voice_sample,
                inputs=[voice_input],
                outputs=[voice_input, voice_status],
            )

            # Wire up streaming generation with cancellable stop button
            gen_event = generate_btn.click(
                fn=generate_speech_stream,
                inputs=[
                    text_input,
                    language_dropdown,
                    voice_input,
                    exaggeration_slider,
                    cfg_slider,
                    temp_slider,
                    stream_playback_chk,
                    pause_ms_slider,
                    crossfade_ms_slider,
                    keep_partial_chk,
                ],
                outputs=[stream_player_box, audio_output, download_output, audio_info],
            )

            stop_btn.click(
                fn=None,
                cancels=[gen_event],
            )

            # Wire up batch streaming generation with cancellable stop button
            batch_gen_event = generate_batch_btn.click(
                fn=generate_batch_speech_stream,
                inputs=[
                    batch_text_input,
                    batch_language_dropdown,
                    voice_input,
                    exaggeration_slider,
                    cfg_slider,
                    temp_slider,
                    stream_playback_chk,
                    pause_ms_slider,
                    crossfade_ms_slider,
                ],
                outputs=[batch_gallery, batch_zip_output, batch_status_md],
            )

            stop_batch_btn.click(
                fn=None,
                cancels=[batch_gen_event],
            )

        # ==========================================
        # TAB 2: Settings & Telegram Bot (.env Manager)
        # ==========================================
        with gr.TabItem("⚙️ Settings & Telegram Bot", id="settings_tab"):
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### 🛡️ Private Environment Settings (.env)")
                    gr.Markdown(
                        "Your secrets are kept **strictly on your machine** inside `.env`. "
                        "This file is ignored by Git and will **never** be published to GitHub."
                    )
                    cfg_host = gr.Textbox(
                        label="Localhost Server IP",
                        value=env_host,
                        placeholder="127.0.0.1",
                        info="Default is 127.0.0.1 for local access, or 0.0.0.0 to expose on local LAN.",
                    )
                    cfg_port = gr.Textbox(
                        label="Server Port",
                        value=env_port,
                        placeholder="7860",
                        info="Default port is 7860.",
                    )
                    cfg_bot_token = gr.Textbox(
                        label="Telegram Bot Token",
                        value=env_token,
                        type="password",
                        placeholder="123456789:ABCdefGHIjklMNOpqrSTUvwxYZ...",
                        info="Secret token received from @BotFather. Hidden safely from view.",
                    )
                    cfg_default_lang = gr.Dropdown(
                        choices=LANG_CHOICES,
                        value=env_def_lang if env_def_lang in SUPPORTED_LANGUAGES else "en",
                        label="Telegram Bot Default Speech Language",
                        info="The language your bot speaks when receiving messages.",
                    )
                    save_env_btn = gr.Button("💾 Save .env Settings", variant="primary")
                    save_env_status = gr.Markdown(value="")

                with gr.Column(scale=1):
                    gr.Markdown("### 🤖 Telegram Bot Control Center")
                    bot_status_display = gr.Markdown(value=get_telegram_bot_status())

                    with gr.Row():
                        start_bot_btn = gr.Button("🚀 Start Telegram Bot", variant="primary")
                        stop_bot_btn = gr.Button("🛑 Stop Telegram Bot", variant="stop")
                        refresh_bot_btn = gr.Button("🔄 Refresh Status", variant="secondary")

                    bot_action_status = gr.Markdown(value="")

                    gr.Markdown(
                        """
                        ---
                        ### 📋 How to create your Telegram Bot in 1 minute:
                        1. Open Telegram and search for **[@BotFather](https://t.me/BotFather)**.
                        2. Send `/newbot` and follow the prompts to choose a name and username.
                        3. Copy the **HTTP API token** BotFather gives you.
                        4. Paste the token into the **Telegram Bot Token** field on the left.
                        5. Click **Save .env Settings**, then click **🚀 Start Telegram Bot**.
                        6. Search for your bot on Telegram and start chatting in your cloned voice!
                        """
                    )

            # Tab 2 Callbacks
            save_env_btn.click(
                fn=save_env_settings,
                inputs=[cfg_host, cfg_port, cfg_bot_token, cfg_default_lang],
                outputs=[save_env_status],
            )

            start_bot_btn.click(
                fn=start_telegram_bot,
                inputs=[cfg_bot_token],
                outputs=[bot_action_status],
            ).then(
                fn=get_telegram_bot_status,
                outputs=[bot_status_display],
            )

            stop_bot_btn.click(
                fn=stop_telegram_bot,
                outputs=[bot_action_status],
            ).then(
                fn=get_telegram_bot_status,
                outputs=[bot_status_display],
            )

            refresh_bot_btn.click(
                fn=get_telegram_bot_status,
                outputs=[bot_status_display],
            )

if __name__ == "__main__":
    host = os.getenv("SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("SERVER_PORT", "7860"))
    demo.launch(server_name=host, server_port=port, theme=gr.themes.Soft(), css=custom_css, show_error=True)
