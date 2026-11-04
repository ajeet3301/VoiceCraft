---
title: Voice Studio
emoji: 🎙️
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# 🎙️ VoiceCraft

> **High-Fidelity Multilingual Voice Cloning Studio & Telegram Bot**  
> Powered by Chatterbox Multilingual TTS V3, Gradio, and Python.

---

## ✨ Features

- **⚡ 2-Step Workflow**: Upload or record a short voice sample (10–20 seconds) once, save it, and synthesize in your cloned voice forever.
- **🌐 23 Supported Languages**: High-accuracy synthesis across English, Hindi (`hi`), Spanish (`es`), French (`fr`), German (`de`), Japanese (`ja`), Chinese (`zh`), Russian (`ru`), Italian (`it`), and 14 more.
- **⚡ In-Memory Real-Time Audio Streaming**: Long texts are split into sentence chunks and synthesized one by one in RAM. Each chunk plays in the browser immediately as it is ready via an in-memory HTML5 queue player — hear audio in seconds without waiting for long texts to finish!
- **📁 Clean Single-File Output**: Chunks are kept **strictly in memory** (never written to disk, not even as temporary files). When all chunks finish, they are seamlessly stitched into **exactly ONE final continuous master file**: `outputs/<timestamp>.wav`.
- **🎛️ Acoustic Stitching & Normalization**:
  - **Loudness Normalization**: Consistent peak volume across all sentences to eliminate volume jumps.
  - **Natural Inter-Sentence Pause**: Configurable pause (default 200 ms) between sentences.
  - **Smooth Crossfade**: 20–50 ms boundary transitions to prevent clicks, DC offsets, or pops.
- **🛑 Instant Stop Button**: Stops generation immediately, cancels model execution, and frees CPU/GPU RAM.
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

## 🖥️ Modern Web Studio Interface

VoiceCraft features a modern, responsive web studio designed for speed, simplicity, and flexibility:

| Tab | Purpose |
| :--- | :--- |
| **🎙️ Studio** | Primary voice cloning & real-time streaming speech synthesis. Drag & drop audio, live word/char counters, language selector with flag icons, and instant sentence streaming. |
| **📦 Batch Clips** | Generate multiple voice clips at once. Dynamically add/remove clips, paste multi-line scripts, generate all in memory, preview individually, and download a `.zip` archive. |
| **📜 History** | Complete local archive of generated audio from `outputs/`. Instant waveform playback, search filter, duration/file-size badges, open folder, and one-click deletion. |
| **⚙️ Settings & Bot** | Telegram bot control center (start/stop/status), token management, localhost port configuration, and advanced generation defaults. |

### ⌨️ Keyboard Shortcuts
- **`Ctrl + Enter`**: Start voice generation immediately from any text field.
- **`Escape`**: Cancel active generation and stop playback.
- **`Dark / Light Mode`**: Instant toggle via top-right theme switch (persists in `localStorage`).

---

## 🚀 Quick Start

### 1. One-Click Launch (Windows)
Double-click `run.bat` in the project root folder.  
It activates the virtual environment, configures environment variables, starts the server, and launches your default browser at `http://127.0.0.1:7860`.

### 2. Manual Launch
```bash
# Activate your virtual environment
.\.venv\Scripts\activate

# Launch VoiceCraft Studio Server
python server.py
```

### ⚙️ Advanced Audio & Streaming Configuration

Accessible under the collapsed **Advanced Audio & Streaming Controls** accordion:
* `Stream Playback`: Toggle in-memory real-time browser streaming (Default: `True`).
* `Inter-sentence Pause (ms)`: Natural silence inserted between sentences (Default: `200 ms`).
* `Crossfade Window (ms)`: Boundary smoothing window between sentence joins (Default: `30 ms`).
* `Keep Partial Audio on Cancel`: Save partial stitched audio if generation is stopped halfway (Default: `False` — discards chunks and saves nothing).
* `Exaggeration`: Speech expressiveness (Default: `0.5`).
* `CFG Weight`: Guidance weight (`0.5` default, `0.0` halves compute time on CPU).
* `Temperature`: Variation and randomness (Default: `0.8`).

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
├── multilingual_app.py   # Main Gradio Web Studio with in-memory streaming & single-file output
├── telegram_bot.py       # Telegram bot runner with voice synthesis
├── config.py             # YAML & environment configuration helper
├── config.yaml           # Audio, streaming, and generation settings
├── run.bat               # One-click Windows launch script
├── benchmark.py          # Performance & generation benchmarking suite
├── .env.example          # Template environment configuration
├── .env                  # Private local configuration (ignored by git)
├── .gitignore            # Git exclusion rules (protects credentials & audio)
├── pyproject.toml        # Project dependencies and packaging
├── voices/               # Stored reference voice samples (my_voice.wav)
└── outputs/              # Timestamped final continuous audio files (<timestamp>.wav)
```

---

## 🛡️ Security & Privacy Notice

- **Zero Chunk Clutter**: Chunk audio files are never written to disk or temporary folders.
- **Your Voice & Outputs**: Audio recordings in `voices/` and generated outputs in `outputs/` are ignored by git and will never be pushed to GitHub.
- **API Keys**: All bot tokens and private settings reside exclusively in `.env`, which is strictly excluded from version control.

---

## 📜 License

This project is licensed under the Apache 2.0 License. See [LICENSE](LICENSE) for details.
