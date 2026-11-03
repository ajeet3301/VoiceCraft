# 🎙️ VoiceCraft

> **High-Fidelity Multilingual Voice Cloning Studio & Telegram Bot**  
> Powered by Chatterbox Multilingual TTS V3, Gradio, and Python.

---

## ✨ Features

- **⚡ 2-Step Workflow**: Upload or record a short voice sample (10–20 seconds) once, save it, and synthesize in your cloned voice forever.
- **🌐 23 Supported Languages**: High-accuracy synthesis across English, Hindi (`hi`), Spanish (`es`), French (`fr`), German (`de`), Japanese (`ja`), Chinese (`zh`), Russian (`ru`), Italian (`it`), and 14 more.
- **🚀 Long-Form Audio & Sentence Chunking**: Seamlessly splits long texts and paragraphs at punctuation boundaries, synthesizes each clause, and stitches them with natural pauses.
- **📦 Batch Generation**: Submit multiple sentences at once, preview every clip individually, and download all generated files in a single `.zip` archive.
- **🤖 Telegram Bot Integration**: Integrated Telegram bot that replies to messages with real-time voice notes using your cloned voice.
- **🛡️ Secure `.env` Manager**: Local settings manager to store localhost parameters and your Telegram Bot token safely. Ignored by git to ensure private keys are never exposed.
- **🔒 Responsible Audio**: Resemble Perth digital watermarking enabled by default.

---

## 🚀 Quick Start

### 1. One-Click Launch (Windows)
Double-click `run.bat` in the project root folder.  
It automatically activates the virtual environment, configures environment variables, starts the server, and launches your default browser at `http://127.0.0.1:7860`.

### 2. Manual Launch
```bash
# Activate your virtual environment
.\.venv\Scripts\activate

# Launch VoiceCraft
python multilingual_app.py
```

---

## 🖥️ Web Studio Interface

VoiceCraft provides a clean, two-page interface:

### Tab 1: 🎙️ VoiceCraft Studio
1. **Your Voice**:
   - Upload any audio file (`.wav`, `.m4a`, `.mp3`, `.flac`) or record directly from your microphone.
   - Click **Save my voice** to store your voice permanently in `voices/my_voice.wav`.
2. **Text to Speak**:
   - **Single Mode**: Enter any text, select your target language (default: English, with Hindi and 21 others), and click **🔊 Generate Speech**.
   - **Batch Mode**: Paste multiple sentences (one per line) and click **⚡ Generate All Clips** to produce all audio files at once.
3. **Outputs**:
   - Embedded audio player for instant playback.
   - Master `.wav` download button and timestamped outputs saved to `./outputs/`.
   - Batch zip archive for downloading all clips at once.

### Tab 2: ⚙️ Settings & Telegram Bot
- **Environment Manager**: Set `SERVER_HOST`, `SERVER_PORT`, default language, and your `TELEGRAM_BOT_TOKEN`.
- **Safe Storage**: Saved directly to a local `.env` file that is kept strictly on your machine and blocked from git.
- **Control Center**: Start and stop your Telegram bot directly from the web interface.

---

## 🤖 Telegram Bot Setup

1. Open Telegram and search for **[@BotFather](https://t.me/BotFather)**.
2. Send `/newbot` and follow the prompts to choose a display name and username (e.g. `MyVoiceCraftBot`).
3. Copy the **HTTP API token** provided by BotFather.
4. In the VoiceCraft Web Studio, open the **⚙️ Settings & Telegram Bot** tab.
5. Paste the token into the **Telegram Bot Token** field and click **💾 Save .env Settings**.
6. Click **🚀 Start Telegram Bot**.
7. In Telegram, search for your bot and send any message — it will reply with audio in your cloned voice!

### Bot Commands:
- `/start` - Welcome message & bot overview.
- `/lang <code>` - Change target synthesis language (e.g. `/lang hi` for Hindi, `/lang en` for English).
- `/status` - Check active model, voice status, and language settings.
- `/help` - View supported language codes and usage instructions.

---

## 🗂️ Project Structure

```text
VoiceCraft/
├── multilingual_app.py   # Main Gradio Web Studio with 2-page tab layout
├── telegram_bot.py       # Telegram bot runner with voice synthesis
├── run.bat               # One-click Windows launch script
├── benchmark.py          # Performance & generation benchmarking suite
├── .env.example          # Template environment configuration
├── .env                  # Private local configuration (ignored by git)
├── .gitignore            # Git exclusion rules (protects credentials & audio)
├── pyproject.toml        # Project dependencies and packaging
├── voices/               # Stored reference voice samples (my_voice.wav)
└── outputs/              # Timestamped generated speech output files
```

---

## 🛡️ Security & Privacy Notice

- **Your Voice & Outputs**: Audio recordings in `voices/` and generated outputs in `outputs/` are ignored by git and will never be pushed to GitHub.
- **API Keys**: All bot tokens and private settings reside exclusively in `.env`, which is strictly excluded from version control.

---

## 📜 License

This project is licensed under the Apache 2.0 License. See [LICENSE](LICENSE) for details.
