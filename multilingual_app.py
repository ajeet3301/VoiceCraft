import datetime
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

# Load environment configuration
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH, override=True)

from chatterbox.mtl_tts import ChatterboxMultilingualTTS, SUPPORTED_LANGUAGES

# --- Directories & Paths ---
VOICES_DIR = BASE_DIR / "voices"
OUTPUTS_DIR = BASE_DIR / "outputs"
VOICES_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
MY_VOICE_PATH = VOICES_DIR / "my_voice.wav"

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
T3_MODEL = os.getenv("CHATTERBOX_MULTILINGUAL_T3_MODEL", "v3")

# Set CPU threading optimization if running on CPU
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
    """Loads the ChatterboxMultilingualTTS model if not already loaded."""
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


# Pre-load model & cached voice conditionals on startup
try:
    _init_model = get_or_load_model()
    if MY_VOICE_PATH.exists():
        try:
            print(f"[VoiceCraft] Pre-caching voice conditionals from {MY_VOICE_PATH.name}...")
            _init_model.prepare_conditionals(str(MY_VOICE_PATH))
            print("[VoiceCraft] Saved voice conditionals cached successfully.")
        except Exception as ve_err:
            print(f"[VoiceCraft] Note: Saved voice pre-cache notice: {ve_err}")
except Exception as e:
    print(f"[VoiceCraft] Warning: Failed to pre-warm model at startup: {e}")


def split_text_into_chunks(text: str, max_chars: int = 250) -> list[str]:
    """
    Split text into sentence/clause chunks under max_chars for natural speech synthesis.
    Supports English, Hindi (।), and all other multilingual punctuation marks.
    """
    text = text.strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    all_sentences = []

    # Match sentences ending with ., !, ?, Hindi Purna Viram (।), or East Asian (。)
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

        # Update model cached conditionals
        model = get_or_load_model()
        model.prepare_conditionals(str(MY_VOICE_PATH))

        return str(MY_VOICE_PATH), f"✅ Voice loaded: {MY_VOICE_PATH.name} (stored permanently in voices/)"
    except Exception as e:
        raise gr.Error(f"Failed to save voice sample: {str(e)}")


def generate_speech(
    text: str,
    language_code: str,
    audio_input_path: str | None,
    exaggeration: float = 0.5,
    cfg_weight: float = 0.5,
    temperature: float = 0.8,
    progress=gr.Progress(track_tqdm=True),
):
    """
    Synthesize text into speech using the cloned voice.
    Handles long text by splitting into sentences, generating each chunk,
    and joining them into a single audio file with natural pauses.
    Saves timestamped outputs to ./outputs/
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

    try:
        model.prepare_conditionals(chosen_voice_path, exaggeration=float(exaggeration))

        generated_segments = []
        sr = model.sr
        silence = np.zeros(int(0.2 * sr), dtype=np.float32)

        with torch.inference_mode():
            for idx, chunk in enumerate(chunks):
                if progress:
                    progress((idx + 1) / len(chunks), desc=f"Synthesizing sentence {idx+1}/{len(chunks)}...")
                print(f"[VoiceCraft] Synthesizing [{idx + 1}/{len(chunks)}]: '{chunk[:60]}...' (Lang: {language_code})")
                wav = model.generate(
                    chunk,
                    language_id=language_code,
                    audio_prompt_path=None,
                    exaggeration=float(exaggeration),
                    cfg_weight=float(cfg_weight),
                    temperature=float(temperature),
                )
                wav_np = wav.squeeze(0).cpu().numpy()
                generated_segments.append(wav_np)

        full_audio_list = []
        for i, seg in enumerate(generated_segments):
            full_audio_list.append(seg)
            if i < len(generated_segments) - 1:
                full_audio_list.append(silence)

        full_audio = np.concatenate(full_audio_list)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"voicecraft_{language_code}_{timestamp}.wav"
        output_filepath = OUTPUTS_DIR / output_filename
        sf.write(str(output_filepath), full_audio, sr, subtype="PCM_16")
        print(f"[VoiceCraft] Saved output: {output_filepath}")

        duration_sec = len(full_audio) / sr
        info_badge = f"✨ **Generation Complete**: `{output_filename}` | Duration: **{duration_sec:.1f}s** | Rate: **{sr} Hz**"

        return str(output_filepath), str(output_filepath), info_badge
    except gr.Error:
        raise
    except Exception as e:
        print(f"[VoiceCraft] Error during speech synthesis: {e}")
        raise gr.Error(f"Speech synthesis error: {str(e)}")


def generate_batch_speech(
    batch_text: str,
    language_code: str,
    audio_input_path: str | None,
    exaggeration: float = 0.5,
    cfg_weight: float = 0.5,
    temperature: float = 0.8,
    progress=gr.Progress(track_tqdm=True),
):
    """
    Generates multiple audio clips from text lines submitted together.
    Returns list of files and a downloadable zip archive.
    """
    lines = [line.strip() for line in batch_text.split("\n") if line.strip()]
    if not lines:
        raise gr.Error("Please enter at least one line of text to synthesize.")

    generated_files = []
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    for i, line in enumerate(lines):
        if progress:
            progress(i / len(lines), desc=f"Processing clip {i+1}/{len(lines)}: '{line[:30]}...'")
        audio_path, _, _ = generate_speech(
            text=line,
            language_code=language_code,
            audio_input_path=audio_input_path,
            exaggeration=exaggeration,
            cfg_weight=cfg_weight,
            temperature=temperature,
            progress=None,
        )
        generated_files.append(audio_path)

    # Create zip archive of all generated clips
    zip_path = OUTPUTS_DIR / f"voicecraft_batch_{timestamp}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in generated_files:
            zf.write(f, arcname=Path(f).name)

    summary_text = f"✅ Batch Complete: Generated **{len(generated_files)} audio clips** successfully!"
    return generated_files, str(zip_path), summary_text


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
    """Returns the current runtime status of the Telegram bot background process."""
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

    python_exe = sys.executable

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
    if BOT_PROCESS is None or BOT_PROCESS.poll() is not None:
        BOT_PROCESS = None
        return "⚪ Telegram Bot is already stopped."

    try:
        BOT_PROCESS.terminate()
        try:
            BOT_PROCESS.wait(timeout=3)
        except subprocess.TimeoutExpired:
            BOT_PROCESS.kill()
        BOT_PROCESS = None
        return "⚪ **Telegram Bot stopped successfully.**"
    except Exception as e:
        BOT_PROCESS = None
        return f"Error stopping bot: {e}"


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
    margin-bottom: 1.5rem;
}
.main-header h1 {
    font-size: 2.2rem;
    font-weight: 800;
    background: linear-gradient(135deg, #4f46e5 0%, #06b6d4 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 0.3rem;
}
.sub-header {
    color: #64748b;
    font-size: 1.05rem;
}
.card {
    border-radius: 12px;
    padding: 1rem;
    background-color: var(--background-fill-secondary);
    border: 1px solid var(--border-color-primary);
}
.badge-ready {
    color: #10b981;
    font-weight: 600;
}
"""

with gr.Blocks(title="VoiceCraft - Multilingual Voice Cloning Studio", css=custom_css, theme=gr.themes.Soft()) as demo:
    with gr.Column(elem_classes=["main-header"]):
        gr.Markdown(
            """
            # 🎙️ VoiceCraft
            ### Multilingual Voice Cloning Studio & Telegram Bot
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
                        with gr.TabItem("Single Sentence / Text"):
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

                            with gr.Accordion("⚙️ Advanced Audio Controls", open=False):
                                exaggeration_slider = gr.Slider(
                                    minimum=0.25,
                                    maximum=2.0,
                                    value=0.5,
                                    step=0.05,
                                    label="Exaggeration (0.5 is neutral natural voice)",
                                )
                                cfg_slider = gr.Slider(
                                    minimum=0.0,
                                    maximum=1.0,
                                    value=0.5,
                                    step=0.05,
                                    label="CFG Weight (0.5 standard; 0.0 is 2x faster and great for cross-lingual)",
                                )
                                temp_slider = gr.Slider(
                                    minimum=0.05,
                                    maximum=2.0,
                                    value=0.8,
                                    step=0.05,
                                    label="Temperature (Variation & randomness)",
                                )

                            generate_btn = gr.Button("🔊 Generate Speech", variant="primary", size="lg")

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
                            generate_batch_btn = gr.Button("⚡ Generate All Clips", variant="primary", size="lg")

                # Right Column: Audio Outputs
                with gr.Column(scale=1):
                    gr.Markdown("### 3. Generated Audio Output")
                    audio_info = gr.Markdown(value="*Audio player will update when generation finishes.*")
                    audio_output = gr.Audio(
                        label="Audio Player",
                        type="filepath",
                        interactive=False,
                    )
                    download_output = gr.File(
                        label="Download Master WAV",
                        interactive=False,
                    )

                    gr.Markdown("### Batch Outputs")
                    batch_status_md = gr.Markdown(value="*Submit lines in Batch tab to generate multiple clips at once.*")
                    batch_gallery = gr.Files(label="Generated Batch Clips", interactive=False)
                    batch_zip_output = gr.File(label="Download All Clips (.zip)", interactive=False)

            # Tab 1 Callbacks
            save_voice_btn.click(
                fn=save_voice_sample,
                inputs=[voice_input],
                outputs=[voice_input, voice_status],
            )

            generate_btn.click(
                fn=generate_speech,
                inputs=[
                    text_input,
                    language_dropdown,
                    voice_input,
                    exaggeration_slider,
                    cfg_slider,
                    temp_slider,
                ],
                outputs=[audio_output, download_output, audio_info],
            )

            generate_batch_btn.click(
                fn=generate_batch_speech,
                inputs=[
                    batch_text_input,
                    batch_language_dropdown,
                    voice_input,
                    exaggeration_slider,
                    cfg_slider,
                    temp_slider,
                ],
                outputs=[batch_gallery, batch_zip_output, batch_status_md],
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
    demo.launch(server_name=host, server_port=port, show_error=True)
