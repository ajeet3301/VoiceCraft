import asyncio
import base64
import datetime
import gc
import io
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

# Ensure UTF-8 console output
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv
import numpy as np
import soundfile as sf
import torch
import uvicorn
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
STATIC_DIR = BASE_DIR / "static"
OUTPUTS_DIR = BASE_DIR / "outputs"
VOICES_DIR = BASE_DIR / "voices"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
VOICES_DIR.mkdir(parents=True, exist_ok=True)
MY_VOICE_PATH = VOICES_DIR / "my_voice.wav"

load_dotenv(ENV_PATH, override=True)

# Import existing core functions & models
from config import load_config, save_config
from multilingual_app import (
    get_or_load_model,
    read_audio_file,
    split_text_into_chunks,
    normalize_chunk_loudness,
    join_audio_chunks,
    chunk_to_base64_wav,
    get_telegram_bot_status,
    start_telegram_bot,
    stop_telegram_bot,
    save_env_settings,
    DEVICE,
    T3_MODEL,
    SUPPORTED_LANGUAGES,
)

app = FastAPI(title="VoiceCraft Studio", version="2.0.0")

# Mount outputs for direct audio playback & download
app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")

# Global generation state & cancel tokens
CURRENT_GENERATION_ID = None
CANCEL_REQUESTED = False


# --- Helper Data Models ---
class GenerateRequest(BaseModel):
    text: str
    voice_path: str | None = None
    language: str = "hi"
    exaggeration: float = 0.5
    cfg_weight: float = 0.5
    temperature: float = 0.8
    seed: int | None = None
    pause_ms: int = 200
    crossfade_ms: int = 30
    stream_playback: bool = True
    keep_partial: bool = False


class BatchItem(BaseModel):
    id: str
    text: str


class BatchGenerateRequest(BaseModel):
    items: list[BatchItem]
    language: str = "hi"
    exaggeration: float = 0.5
    cfg_weight: float = 0.5
    temperature: float = 0.8
    seed: int | None = None
    pause_ms: int = 200
    crossfade_ms: int = 30


# --- API Routes ---

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse("<h3>VoiceCraft static files not found.</h3>", status_code=404)


@app.get("/api/status")
async def get_system_status():
    """Returns runtime model status, hardware info, and voice configuration."""
    model_loaded = True  # Model is cached/loaded on demand
    has_voice = MY_VOICE_PATH.exists()
    voice_duration = 0.0
    if has_voice:
        try:
            info = sf.info(str(MY_VOICE_PATH))
            voice_duration = round(info.duration, 1)
        except Exception:
            pass

    cores = os.cpu_count() or 4
    device_name = f"NVIDIA GPU ({torch.cuda.get_device_name(0)})" if DEVICE == "cuda" else f"CPU ({cores} Logical Cores)"

    return {
        "status": "generating" if CURRENT_GENERATION_ID else "ready",
        "device": DEVICE,
        "device_name": device_name,
        "model_version": f"Multilingual {T3_MODEL.upper()}",
        "torch_version": torch.__version__,
        "has_voice": has_voice,
        "voice_filename": MY_VOICE_PATH.name if has_voice else None,
        "voice_duration_s": voice_duration,
        "telegram_status": get_telegram_bot_status(),
        "config": load_config(),
    }


@app.get("/api/voice/status")
async def get_voice_status():
    """Returns saved reference voice details and duration check."""
    if not MY_VOICE_PATH.exists():
        return {"has_voice": False, "message": "No voice sample saved yet."}

    try:
        info = sf.info(str(MY_VOICE_PATH))
        duration = round(info.duration, 2)
        warning = None
        if duration < 5.0:
            warning = "Sample is shorter than 5 seconds. 10–20 seconds recommended for best quality."
        elif duration > 30.0:
            warning = "Sample is longer than 30 seconds. First 20–30 seconds will be used for conditioning."

        return {
            "has_voice": True,
            "filename": MY_VOICE_PATH.name,
            "duration_s": duration,
            "samplerate": info.samplerate,
            "channels": info.channels,
            "warning": warning,
            "audio_url": "/api/voice/audio",
        }
    except Exception as e:
        return {"has_voice": False, "error": str(e)}


@app.get("/api/voice/audio")
async def get_voice_audio():
    """Streams the saved reference voice file."""
    if not MY_VOICE_PATH.exists():
        raise HTTPException(status_code=404, detail="Voice file not found.")
    return FileResponse(str(MY_VOICE_PATH), media_type="audio/wav")


@app.post("/api/voice/upload")
async def upload_voice(file: UploadFile = File(...)):
    """Receives uploaded audio, validates duration, and saves as reference voice."""
    temp_path = VOICES_DIR / f"temp_upload_{int(time.time())}_{file.filename}"
    try:
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # Convert to 24 kHz mono float32 WAV
        data, sr = read_audio_file(temp_path)
        duration = len(data) / sr

        # Save to permanent reference path
        sf.write(str(MY_VOICE_PATH), data, sr, subtype="PCM_16")

        # Update model cached conditionals
        try:
            model = get_or_load_model()
            model.prepare_conditionals(str(MY_VOICE_PATH))
        except Exception as ce:
            print(f"[VoiceCraft] Notice: Model conditionals update: {ce}")

        warning = None
        if duration < 5.0:
            warning = "Sample is shorter than 5s. 10–20s of clear speech produces best results."
        elif duration > 30.0:
            warning = "Sample exceeds 30s. VoiceCraft will use the sample's primary speech characteristics."

        return {
            "status": "success",
            "filename": MY_VOICE_PATH.name,
            "duration_s": round(duration, 2),
            "samplerate": sr,
            "warning": warning,
            "message": f"✅ Voice loaded: {round(duration, 1)}s sample saved successfully!",
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to process audio: {str(e)}")
    finally:
        if temp_path.exists():
            temp_path.unlink()


@app.post("/api/generate/stop")
async def stop_generation():
    """Signals cancellation to the currently running generation loop."""
    global CANCEL_REQUESTED
    CANCEL_REQUESTED = True
    return {"status": "ok", "message": "Cancellation signal sent."}


@app.post("/api/generate/stream")
async def generate_speech_endpoint(req: GenerateRequest):
    """
    Server-Sent Events (SSE) streaming speech synthesis endpoint:
    - Splits text into sentence chunks
    - Generates chunk by chunk strictly IN MEMORY
    - Streams in-memory base64 WAV chunks to the browser in real time
    - Joins chunks into EXACTLY ONE final continuous file in outputs/
    """
    global CURRENT_GENERATION_ID, CANCEL_REQUESTED

    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="Please enter text to synthesize.")
    ref_voice = Path(req.voice_path) if req.voice_path and Path(req.voice_path).exists() else MY_VOICE_PATH
    if not ref_voice.exists():
        raise HTTPException(status_code=400, detail="Please save your voice sample first.")

    gen_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    CURRENT_GENERATION_ID = gen_id
    CANCEL_REQUESTED = False

    chunks = split_text_into_chunks(req.text, max_chars=250)
    if not chunks:
        raise HTTPException(status_code=400, detail="No valid sentences found in input.")

    async def sse_generator():
        global CURRENT_GENERATION_ID, CANCEL_REQUESTED
        start_time = time.perf_counter()
        chunks_in_memory: list[np.ndarray] = []

        try:
            # Yield metadata start event
            yield f"event: start\ndata: {json.dumps({'gen_id': gen_id, 'total_chunks': len(chunks), 'chunks': chunks})}\n\n"

            # Set manual seed if requested
            if req.seed is not None and req.seed >= 0:
                torch.manual_seed(int(req.seed))

            model = get_or_load_model()
            sr = model.sr
            model.prepare_conditionals(str(ref_voice), exaggeration=float(req.exaggeration))

            with torch.inference_mode():
                for idx, chunk_text in enumerate(chunks):
                    # Check cancellation
                    if CANCEL_REQUESTED:
                        print(f"[VoiceCraft] Generation {gen_id} cancelled by user.")
                        if req.keep_partial and chunks_in_memory:
                            partial_audio = join_audio_chunks(chunks_in_memory, sr, req.pause_ms, req.crossfade_ms)
                            partial_name = f"{gen_id}_partial.wav"
                            partial_path = OUTPUTS_DIR / partial_name
                            sf.write(str(partial_path), partial_audio, sr, subtype="PCM_16")
                            yield f"event: cancelled\ndata: {json.dumps({'status': 'cancelled', 'saved_partial': True, 'audio_url': f'/outputs/{partial_name}'})}\n\n"
                        else:
                            yield f"event: cancelled\ndata: {json.dumps({'status': 'cancelled', 'saved_partial': False})}\n\n"
                        return

                    # Synthesize chunk
                    wav = model.generate(
                        chunk_text,
                        language_id=req.language,
                        audio_prompt_path=None,
                        exaggeration=float(req.exaggeration),
                        cfg_weight=float(req.cfg_weight),
                        temperature=float(req.temperature),
                    )
                    chunk_np = wav.squeeze(0).cpu().numpy().astype(np.float32)
                    chunks_in_memory.append(chunk_np)

                    # Encode chunk to base64 WAV in memory for streaming playback
                    b64_url = chunk_to_base64_wav(chunk_np, sr) if req.stream_playback else None
                    elapsed = round(time.perf_counter() - start_time, 1)

                    chunk_payload = {
                        "chunk_index": idx,
                        "total_chunks": len(chunks),
                        "text": chunk_text,
                        "audio_b64": b64_url,
                        "elapsed_s": elapsed,
                    }
                    yield f"event: chunk\ndata: {json.dumps(chunk_payload)}\n\n"
                    await asyncio.sleep(0.01)

            # Check if cancelled before writing final file
            if CANCEL_REQUESTED:
                yield f"event: cancelled\ndata: {json.dumps({'status': 'cancelled', 'saved_partial': False})}\n\n"
                return

            # All chunks finished: Stitch into ONE continuous audio file
            final_audio = join_audio_chunks(
                chunks_in_memory,
                sr,
                pause_ms=req.pause_ms,
                crossfade_ms=req.crossfade_ms,
            )

            # Save EXACTLY ONE file: .\outputs\<timestamp>.wav
            output_filename = f"{gen_id}.wav"
            output_filepath = OUTPUTS_DIR / output_filename
            sf.write(str(output_filepath), final_audio, sr, subtype="PCM_16")

            total_duration = len(final_audio) / sr
            total_time = time.perf_counter() - start_time
            words_count = len(req.text.split())

            complete_payload = {
                "status": "complete",
                "filename": output_filename,
                "audio_url": f"/outputs/{output_filename}",
                "duration_s": round(total_duration, 2),
                "generation_time_s": round(total_time, 2),
                "word_count": words_count,
                "chunks_count": len(chunks),
                "samplerate": sr,
            }
            yield f"event: complete\ndata: {json.dumps(complete_payload)}\n\n"

        except Exception as e:
            print(f"[VoiceCraft] Error in generation stream: {e}")
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        finally:
            CURRENT_GENERATION_ID = None
            CANCEL_REQUESTED = False
            del chunks_in_memory
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    return StreamingResponse(sse_generator(), media_type="text/event-stream")


@app.post("/api/batch/stream")
async def batch_generate_endpoint(req: BatchGenerateRequest):
    """Batch synthesis: processes each clip, keeping chunks in memory, and writes one .wav per clip."""
    global CURRENT_GENERATION_ID, CANCEL_REQUESTED

    if not req.items:
        raise HTTPException(status_code=400, detail="No batch items provided.")
    if not MY_VOICE_PATH.exists():
        raise HTTPException(status_code=400, detail="Please save your voice sample first.")

    batch_gen_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    CURRENT_GENERATION_ID = batch_gen_id
    CANCEL_REQUESTED = False

    async def sse_batch():
        global CURRENT_GENERATION_ID, CANCEL_REQUESTED
        model = get_or_load_model()
        sr = model.sr
        model.prepare_conditionals(str(MY_VOICE_PATH), exaggeration=float(req.exaggeration))

        completed_clips = []
        yield f"event: batch_start\ndata: {json.dumps({'batch_id': batch_gen_id, 'total_items': len(req.items)})}\n\n"

        try:
            for idx, item in enumerate(req.items):
                if CANCEL_REQUESTED:
                    yield f"event: cancelled\ndata: {json.dumps({'status': 'cancelled'})}\n\n"
                    return

                text = item.text.strip()
                if not text:
                    continue

                chunks = split_text_into_chunks(text, max_chars=250)
                chunks_in_mem = []

                with torch.inference_mode():
                    for chunk in chunks:
                        if CANCEL_REQUESTED:
                            yield f"event: cancelled\ndata: {json.dumps({'status': 'cancelled'})}\n\n"
                            return

                        wav = model.generate(
                            chunk,
                            language_id=req.language,
                            audio_prompt_path=None,
                            exaggeration=float(req.exaggeration),
                            cfg_weight=float(req.cfg_weight),
                            temperature=float(req.temperature),
                        )
                        chunk_np = wav.squeeze(0).cpu().numpy().astype(np.float32)
                        chunks_in_mem.append(chunk_np)

                # Join chunks into one file for this clip
                final_audio = join_audio_chunks(chunks_in_mem, sr, req.pause_ms, req.crossfade_ms)
                clip_filename = f"{batch_gen_id}_clip_{idx+1}.wav"
                clip_path = OUTPUTS_DIR / clip_filename
                sf.write(str(clip_path), final_audio, sr, subtype="PCM_16")

                clip_info = {
                    "item_id": item.id,
                    "index": idx + 1,
                    "total": len(req.items),
                    "filename": clip_filename,
                    "audio_url": f"/outputs/{clip_filename}",
                    "duration_s": round(len(final_audio) / sr, 1),
                    "text": text,
                }
                completed_clips.append(clip_info)
                yield f"event: clip_done\ndata: {json.dumps(clip_info)}\n\n"

            # Create batch zip archive
            zip_filename = f"{batch_gen_id}_batch.zip"
            zip_path = OUTPUTS_DIR / zip_filename
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for c in completed_clips:
                    fpath = OUTPUTS_DIR / c["filename"]
                    if fpath.exists():
                        zf.write(fpath, arcname=c["filename"])

            yield f"event: batch_complete\ndata: {json.dumps({'zip_url': f'/outputs/{zip_filename}', 'clips': completed_clips})}\n\n"

        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        finally:
            CURRENT_GENERATION_ID = None
            CANCEL_REQUESTED = False
            gc.collect()

    return StreamingResponse(sse_batch(), media_type="text/event-stream")


@app.get("/api/history")
async def get_history():
    """Lists past generated audio files from outputs/ with creation date, size, and duration."""
    files = list(OUTPUTS_DIR.glob("*.wav"))
    history_items = []

    for f in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            stat = f.stat()
            created_at = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            info = sf.info(str(f))
            history_items.append({
                "filename": f.name,
                "created_at": created_at,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "duration_s": round(info.duration, 1),
                "audio_url": f"/outputs/{f.name}",
            })
        except Exception:
            continue

    return {"items": history_items}


@app.delete("/api/history/{filename}")
async def delete_history_item(filename: str):
    """Deletes a specific generated audio file from outputs/."""
    file_path = OUTPUTS_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")

    # Guard against directory traversal
    if file_path.parent != OUTPUTS_DIR:
        raise HTTPException(status_code=400, detail="Invalid path.")

    try:
        file_path.unlink()
        return {"status": "ok", "deleted": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {e}")


@app.post("/api/open-folder")
async def open_outputs_folder():
    """Opens the outputs directory in Windows File Explorer."""
    try:
        if sys.platform == "win32":
            os.startfile(str(OUTPUTS_DIR))
            return {"status": "ok", "path": str(OUTPUTS_DIR)}
        else:
            return {"status": "unsupported", "path": str(OUTPUTS_DIR)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/languages")
async def get_languages():
    """Returns list of supported languages with flag icons."""
    flags = {
        "en": "🇺🇸", "hi": "🇮🇳", "es": "🇪🇸", "fr": "🇫🇷", "de": "🇩🇪",
        "ja": "🇯🇵", "zh": "🇨🇳", "it": "🇮🇹", "ru": "🇷🇺", "pt": "🇵🇹",
        "ar": "🇸🇦", "ko": "🇰🇷", "nl": "🇳🇱", "pl": "🇵🇱", "tr": "🇹🇷",
        "sv": "🇸🇪", "el": "🇬🇷", "cs": "🇨🇿", "da": "🇩🇰", "fi": "🇫🇮",
        "id": "🇮🇩", "vi": "🇻🇳", "uk": "🇺🇦",
    }
    langs = []
    # Hindi first, then English, then rest alphabetically
    for code, name in sorted(SUPPORTED_LANGUAGES.items(), key=lambda x: (x[0] != "hi", x[0] != "en", x[1])):
        flag = flags.get(code, "🌐")
        langs.append({"code": code, "name": name, "flag": flag, "label": f"{flag} {name} ({code})"})
    return {"languages": langs, "default": "hi"}


@app.get("/api/telegram/status")
async def telegram_status():
    return {"status": get_telegram_bot_status(), "token_set": bool(os.getenv("TELEGRAM_BOT_TOKEN"))}


@app.post("/api/telegram/start")
async def telegram_start():
    try:
        msg = start_telegram_bot()
        return {"status": "ok", "message": msg}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/telegram/stop")
async def telegram_stop():
    msg = stop_telegram_bot()
    return {"status": "ok", "message": msg}


class TelegramSettingsRequest(BaseModel):
    host: str = "127.0.0.1"
    port: str = "7860"
    token: str = ""
    allowed_ids: str = ""
    max_words: int = 60
    max_users: int = 1


@app.get("/api/telegram/settings")
async def get_tg_settings():
    load_dotenv(ENV_PATH, override=True)
    return {
        "host": os.getenv("SERVER_HOST", "127.0.0.1"),
        "port": os.getenv("SERVER_PORT", "7860"),
        "token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "allowed_ids": os.getenv("ALLOWED_TELEGRAM_USER_IDS", "8011886933"),
        "max_words": int(os.getenv("TELEGRAM_MAX_WORDS", "60")),
        "max_users": int(os.getenv("TELEGRAM_MAX_USERS", "1")),
    }


@app.post("/api/telegram/save")
async def save_tg_settings(req: TelegramSettingsRequest):
    try:
        from dotenv import set_key
        ENV_PATH.touch(exist_ok=True)
        set_key(str(ENV_PATH), "SERVER_HOST", req.host.strip() or "127.0.0.1")
        set_key(str(ENV_PATH), "SERVER_PORT", req.port.strip() or "7860")
        if req.token:
            set_key(str(ENV_PATH), "TELEGRAM_BOT_TOKEN", req.token.strip())
            set_key(str(ENV_PATH), "BOT_TOKEN", req.token.strip())
        set_key(str(ENV_PATH), "ALLOWED_TELEGRAM_USER_IDS", req.allowed_ids.strip())
        set_key(str(ENV_PATH), "TELEGRAM_MAX_WORDS", str(req.max_words))
        set_key(str(ENV_PATH), "TELEGRAM_MAX_USERS", str(req.max_users))
        load_dotenv(ENV_PATH, override=True)
        return {"status": "ok", "message": "Settings saved to .env"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/telegram/restart")
async def telegram_restart():
    try:
        stop_telegram_bot()
        await asyncio.sleep(1)
        msg = start_telegram_bot()
        return {"status": "ok", "message": f"Bot restarted! {msg}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Serve static assets
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if __name__ == "__main__":
    host = os.getenv("SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("SERVER_PORT", "7860"))
    print(f"============================================================")
    print(f"           VoiceCraft Modern Studio Server                  ")
    print(f"============================================================")
    print(f"  URL: http://{host}:{port}")
    print(f"  Hardware: {DEVICE.upper()} | Model: {T3_MODEL.upper()}")
    print(f"============================================================")
    uvicorn.run("server:app", host=host, port=port, log_level="info", reload=False)
