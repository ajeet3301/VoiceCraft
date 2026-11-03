"""
Voice Style and Hindi Processing Engine
---------------------------------------
Handles text type auto-detection, Roman Hindi/Hinglish to Devanagari transliteration,
custom phonetic vocabulary fixes via hindi_fixes.json, and mood-based audio styling.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Literal

# ======================================================================
# CONFIGURATION SETTINGS
# ======================================================================
BASE_DIR = Path(__file__).resolve().parent
HINDI_FIXES_FILE = BASE_DIR / "hindi_fixes.json"

# Audio Style Adjustments (via ffmpeg)
STYLE_SETTINGS = {
    "natural": {
        "tempo": 1.0,
        "pitch_shift": 1.0,
        "volume": 1.0,
        "filter": ""
    },
    "happy": {
        "tempo": 1.06,
        "pitch_shift": 1.02,
        "volume": 1.0,
        "filter": "treble=g=2"
    },
    "excited": {
        "tempo": 1.08,
        "pitch_shift": 1.05,
        "volume": 1.05,
        "filter": "treble=g=3"
    },
    "soft": {
        "tempo": 0.96,
        "pitch_shift": 0.98,
        "volume": 0.88,
        "filter": "lowpass=f=3800"
    },
    "husky": {
        "tempo": 0.98,
        "pitch_shift": 0.96,
        "volume": 1.0,
        "filter": "equalizer=f=250:width_type=o:width=1.5:g=3"
    },
    "whisper": {
        "tempo": 0.95,
        "pitch_shift": 1.0,
        "volume": 0.82,
        "filter": "highpass=f=300,lowpass=f=4200,volume=0.85"
    }
}

# Common Romanized Hindi stop-words for detection
ROMAN_HINDI_LEXICON = {
    "kaise", "kese", "kaisa", "kaisi", "kya", "kyun", "kyon", "kab", "kahan",
    "kaha", "hai", "hain", "ho", "hu", "hoon", "nahi", "nahin", "theek", "thik",
    "accha", "achha", "apna", "apne", "apni", "mera", "meri", "mere", "tera",
    "teri", "tere", "tum", "aap", "hum", "yeh", "woh", "bhai", "dost", "yaar",
    "namaste", "shukriya", "dhanyawad", "khayal", "rakhna", "rakho", "raho",
    "hamesha", "muskurate", "muskuraate", "jaldi", "milte", "baat", "karo", "sun"
}


# ======================================================================
# 1. HINDI FIXES DICTIONARY LOADER
# ======================================================================
def load_hindi_fixes() -> dict[str, str]:
    if not HINDI_FIXES_FILE.exists():
        return {}
    try:
        with open(HINDI_FIXES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ======================================================================
# 2. TEXT TYPE DETECTION
# ======================================================================
TextType = Literal["devanagari", "roman_hindi", "hinglish", "english"]


def detect_text_type(text: str) -> TextType:
    """
    Classifies text as:
    - 'devanagari': Contains native Hindi Devanagari script.
    - 'roman_hindi': Hindi written in Latin script (e.g. 'kaise ho').
    - 'hinglish': Mixed Hindi Romanized + English vocabulary.
    - 'english': Standard English text.
    """
    clean = text.strip()
    if not clean:
        return "english"

    # Check for Devanagari Unicode block (\u0900 - \u097F)
    has_devanagari = any("\u0900" <= ch <= "\u097f" for ch in clean)
    if has_devanagari:
        return "devanagari"

    # Tokenize words for vocabulary matching
    words = re.findall(r"[a-zA-Z]+", clean.lower())
    if not words:
        return "english"

    hindi_count = sum(1 for w in words if w in ROMAN_HINDI_LEXICON)
    ratio = hindi_count / len(words)

    if ratio >= 0.45:
        return "roman_hindi"
    elif hindi_count >= 1:
        return "hinglish"
    else:
        return "english"


# ======================================================================
# 3. TRANSLITERATION TO DEVANAGARI HINDI
# ======================================================================
def transliterate_to_devanagari(text: str) -> str:
    """
    Converts Roman Hindi / Hinglish text to clean Devanagari script.
    - Checks custom hindi_fixes.json first.
    - Uses phonetic indic_transliteration for remaining Hindi words.
    - Preserves English loanwords and standard punctuation.
    """
    fixes = load_hindi_fixes()

    # Pre-clean punctuation
    text = text.replace("...", ", ")

    # Tokenize words and punctuation
    tokens = re.split(r"(\W+)", text)
    result = []

    try:
        from indic_transliteration import sanscript
        has_sanscript = True
    except ImportError:
        has_sanscript = False

    for token in tokens:
        if not token:
            continue
        # Preserve non-word characters
        if not re.match(r"^[a-zA-Z]+$", token):
            # Convert full stop at end of sentence to Hindi purna viram
            if token == ".":
                result.append("।")
            else:
                result.append(token)
            continue

        lower_w = token.lower()

        # 1. Custom fixes dictionary match
        if lower_w in fixes:
            result.append(fixes[lower_w])
            continue

        # 2. Check if word is Roman Hindi
        if lower_w in ROMAN_HINDI_LEXICON and has_sanscript:
            dev = sanscript.transliterate(lower_w, sanscript.OPTITRANS, sanscript.DEVANAGARI)
            result.append(dev)
        elif has_sanscript and (len(lower_w) > 2 and any(lower_w.endswith(sfx) for sfx in ("na", "ta", "ti", "te", "ho", "ya", "ne", "ra"))):
            dev = sanscript.transliterate(lower_w, sanscript.OPTITRANS, sanscript.DEVANAGARI)
            result.append(dev)
        else:
            # Keep as English word
            result.append(token)

    output = "".join(result).strip()
    return output


# ======================================================================
# 4. MOOD AND STYLE DETECTION
# ======================================================================
def detect_mood(text: str) -> str:
    """
    Detects mood from explicit tags [husky]...[/husky], [whisper]...[/whisper],
    or sentiment cues like 'haha', '😂', '!!', '...', 'miss you'.
    """
    lower = text.lower()

    if "[whisper]" in lower or "whisper:" in lower:
        return "whisper"
    if "[husky]" in lower or "husky:" in lower:
        return "husky"
    if "[happy]" in lower or "[excited]" in lower:
        return "happy"
    if "[soft]" in lower:
        return "soft"

    # Contextual sentiment cues
    if "haha" in lower or "😂" in text or "hehey" in lower or "kidding" in lower:
        return "happy"
    if "!!" in text or "hurray" in lower or "wow" in lower:
        return "excited"
    if "miss you" in lower or "sad" in lower or "quiet" in lower or "..." in text:
        return "soft"

    return "natural"


def clean_text_for_tts(text: str) -> tuple[str, str]:
    """
    Strips inline style tags like [husky]...[/husky] and returns (clean_text, style).
    """
    style = detect_mood(text)

    # Remove style tags
    clean = re.sub(r"\[(whisper|husky|happy|soft|excited)\]", "", text, flags=re.IGNORECASE)
    clean = re.sub(r"\[\/(whisper|husky|happy|soft|excited)\]", "", clean, flags=re.IGNORECASE)
    clean = clean.strip()

    return clean, style


# ======================================================================
# 5. AUDIO POST-PROCESSING (FFMPEG)
# ======================================================================
def get_ffmpeg_exe() -> str:
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def apply_audio_style(input_wav: str | Path, output_wav: str | Path, style: str = "natural") -> str:
    """
    Applies subtle tempo, pitch, and tone shaping according to detected style.
    Returns the path to the finalized audio file.
    """
    style = style.lower()
    if style not in STYLE_SETTINGS or style == "natural":
        if str(input_wav) != str(output_wav):
            shutil.copy(input_wav, output_wav)
        return str(output_wav)

    cfg = STYLE_SETTINGS[style]
    ffmpeg = get_ffmpeg_exe()

    # Build audio filter chain
    filters = []
    if cfg["tempo"] != 1.0:
        filters.append(f"atempo={cfg['tempo']}")
    if cfg["volume"] != 1.0:
        filters.append(f"volume={cfg['volume']}")
    if cfg["filter"]:
        filters.append(cfg["filter"])

    filter_str = ",".join(filters) if filters else "anull"

    cmd = [
        ffmpeg, "-y",
        "-i", str(input_wav),
        "-af", filter_str,
        "-ar", "24000",
        str(output_wav)
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return str(output_wav)
    except Exception as e:
        print(f"[VoiceStyle] Audio filter notice ({e}), using unprocessed audio.")
        if str(input_wav) != str(output_wav):
            shutil.copy(input_wav, output_wav)
        return str(output_wav)
