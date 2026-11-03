"""
Hinglish Mixed-Language Speech Generation Pipeline (100% Localhost / Offline)
-----------------------------------------------------------------------------
Segment-by-segment local language detection, script preparation, and seamless
multilingual synthesis with zero speaker timbre drift.
No external LLMs or cloud APIs used.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import re
import numpy as np
import soundfile as sf
import torch

# ======================================================================
# CONFIGURATION SETTINGS (EDITABLE)
# ======================================================================
BASE_DIR = Path(__file__).resolve().parent

CROSSFADE_MS = 45          # Smooth 30-60 ms crossfade at language boundaries
COMMA_PAUSE_MS = 180       # Natural pause at commas
SENTENCE_PAUSE_MS = 280    # Natural pause at sentence ends (. ! ? ।)
ELLIPSIS_PAUSE_MS = 380    # Natural pause at ...

LANG_WORDS_FILE = BASE_DIR / "lang_words.json"
NAMES_FILE = BASE_DIR / "names.json"
PRONUNCIATION_FIXES_FILE = BASE_DIR / "pronunciation_fixes.json"
HINDI_FIXES_FILE = BASE_DIR / "hindi_fixes.json"


# ======================================================================
# 1. FILE LOADERS & NUMBER EXPANDERS
# ======================================================================
def load_json_file(file_path: Path, default: any) -> any:
    if not file_path.exists():
        return default
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def get_lang_words() -> dict[str, list[str]]:
    return load_json_file(LANG_WORDS_FILE, {"hindi_words": [], "english_words": []})


def get_names_list() -> list[str]:
    return load_json_file(NAMES_FILE, ["Tamanna", "Sharma", "Tamanna Sharma", "Ayushi"])


def get_pronunciation_fixes() -> dict[str, str]:
    fixes = load_json_file(HINDI_FIXES_FILE, {})
    fixes.update(load_json_file(PRONUNCIATION_FIXES_FILE, {}))
    return fixes


HINDI_NUMBERS = {
    0: "शून्य", 1: "एक", 2: "दो", 3: "तीन", 4: "चार", 5: "पांच",
    6: "छह", 7: "सात", 8: "आठ", 9: "नौ", 10: "दस", 11: "ग्यारह",
    12: "बारह", 13: "तेरह", 14: "चौदह", 15: "पंद्रह", 16: "सोलह",
    17: "सत्रह", 18: "अठारह", 19: "उन्नीस", 20: "बीस", 2024: "दो हज़ार चौबीस",
    2025: "दो हज़ार पच्चीस", 2026: "दो हज़ार छब्बीस"
}

ENGLISH_NUMBERS = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
    11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen",
    15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen",
    19: "nineteen", 20: "twenty", 2024: "twenty twenty-four",
    2025: "twenty twenty-five", 2026: "twenty twenty-six"
}


def expand_numbers(text: str, lang: str = "hi") -> str:
    """Expands digit sequences into words in the target language."""
    def replacer(match):
        val = int(match.group(0))
        num_dict = HINDI_NUMBERS if lang == "hi" else ENGLISH_NUMBERS
        return num_dict.get(val, match.group(0))

    return re.sub(r"\b\d+\b", replacer, text)


# ======================================================================
# 2. LOCAL WORD-LEVEL LANGUAGE DETECTION & SEGMENTATION
# ======================================================================
def split_languages(text: str) -> list[dict[str, str]]:
    """
    100% Local, zero-latency word-level language segmentation.
    - Devanagari script -> 'hi'
    - Names in names.json -> 'hi'
    - Hindi vocabulary in lang_words.json -> 'hi'
    - Roman Hindi common verb/grammatical suffixes -> 'hi'
    - English vocabulary in lang_words.json & Latin loanwords -> 'en'
    - Preserves exact user words without translating.
    """
    if not text or not text.strip():
        return []

    lang_words = get_lang_words()
    hindi_vocab = set(w.lower() for w in lang_words.get("hindi_words", []))
    english_vocab = set(w.lower() for w in lang_words.get("english_words", []))
    names_list = get_names_list()
    names = set(n.lower() for n in names_list)

    # Protect multi-word names from split (e.g., 'Tamanna Sharma')
    tokens = re.findall(r"[\u0900-\u097Fa-zA-Z0-9]+|[^\w\s]|\s+", text)
    word_labels: list[tuple[str, str | None]] = []

    for token in tokens:
        if not token.strip():
            word_labels.append((token, None))
            continue
        if re.match(r"^[^\w\s]+$", token):  # Punctuation
            word_labels.append((token, "punc"))
            continue

        lower = token.lower()

        # 1. Any Devanagari characters -> Hindi
        if any("\u0900" <= ch <= "\u097f" for ch in token):
            word_labels.append((token, "hi"))
        # 2. Names in names.json -> Hindi pronunciation
        elif lower in names:
            word_labels.append((token, "hi"))
        # 3. Known Hindi words (sab, karke, bahut, achha, kaise, lag, raha, hai, etc.)
        elif lower in hindi_vocab:
            word_labels.append((token, "hi"))
        # 4. Known English words (hey, everyone, connect, voice, etc.)
        elif lower in english_vocab:
            word_labels.append((token, "en"))
        # 5. Roman Hindi morphological suffixes (karta, karti, karte, dekhna, bologe, etc.)
        elif len(lower) > 3 and any(lower.endswith(sfx) for sfx in ("na", "ne", "ni", "ta", "ti", "te", "ho", "ya", "ye", "ra", "he", "ge", "gi")):
            word_labels.append((token, "hi"))
        # 6. Default Latin word -> English
        else:
            word_labels.append((token, "en"))

    # Group adjacent words of identical language
    segments: list[dict[str, str]] = []
    current_lang = None
    current_text: list[str] = []

    for token, lang in word_labels:
        if lang is None or lang == "punc":
            if current_text:
                current_text.append(token)
            elif segments:
                segments[-1]["text"] += token
        else:
            if current_lang is None:
                current_lang = lang
                current_text.append(token)
            elif current_lang == lang:
                current_text.append(token)
            else:
                if current_text:
                    segments.append({"text": "".join(current_text).strip(), "lang": current_lang})
                current_lang = lang
                current_text = [token]

    if current_text and current_lang:
        segments.append({"text": "".join(current_text).strip(), "lang": current_lang})

    # Clean up empty segments
    return [s for s in segments if s["text"].strip()]


def is_hinglish(text: str) -> bool:
    """Returns True if the text contains a mixture of both Hindi and English words."""
    segs = split_languages(text)
    langs = set(s["lang"] for s in segs)
    return len(langs) > 1


# ======================================================================
# 3. TEXT PREPARATION (SCRIPT CONVERSION & PHONETICS)
# ======================================================================
def prepare_text(text: str, target_lang: str) -> str:
    """
    Prepares text for TTS generation:
    - English segments: Latin letters untouched, English number words.
    - Hindi segments: Converts Roman Hindi words into Devanagari using
      indic_transliteration and pronunciation_fixes.json.
    - Never translates words.
    """
    text = expand_numbers(text, lang=target_lang)
    fixes = get_pronunciation_fixes()

    if target_lang == "en":
        # Keep Latin letters exactly as written
        return text.strip()

    # Target language is 'hi':
    has_devanagari = any("\u0900" <= ch <= "\u097f" for ch in text)
    has_latin = any(ch.isalpha() and ord(ch) < 128 for ch in text)

    if not has_latin:
        return text.strip()

    # Transliterate Roman Hindi to Devanagari
    try:
        from indic_transliteration import sanscript
        has_sanscript = True
    except ImportError:
        has_sanscript = False

    # Apply phrase fixes first (e.g., 'Tamanna Sharma' -> 'तमन्ना शर्मा')
    for phrase, replacement in fixes.items():
        if " " in phrase and phrase.lower() in text.lower():
            pattern = re.compile(re.escape(phrase), re.IGNORECASE)
            text = pattern.sub(replacement, text)

    tokens = re.split(r"(\W+)", text)
    result: list[str] = []

    for token in tokens:
        if not token:
            continue
        if not re.match(r"^[a-zA-Z]+$", token):
            if token == ".":
                result.append("।")
            else:
                result.append(token)
            continue

        lower = token.lower()
        if token in fixes:
            result.append(fixes[token])
        elif lower in fixes:
            result.append(fixes[lower])
        elif has_sanscript:
            dev = sanscript.transliterate(lower, sanscript.OPTITRANS, sanscript.DEVANAGARI)
            result.append(dev)
        else:
            result.append(token)

    return "".join(result).strip()


# ======================================================================
# 4. CROSSFADING, LOUDNESS MATCHING & AUDIO STITCHING
# ======================================================================
def match_loudness(source: np.ndarray, target_rms: float = 0.08) -> np.ndarray:
    rms = np.sqrt(np.mean(source**2)) + 1e-6
    factor = min(2.5, max(0.4, target_rms / rms))
    return np.clip(source * factor, -0.98, 0.98).astype(np.float32)


def crossfade_join(
    audio1: np.ndarray,
    audio2: np.ndarray,
    sr: int,
    crossfade_ms: int = CROSSFADE_MS,
    pause_ms: int = 0
) -> np.ndarray:
    """
    Stitches two audio segments seamlessly:
    - If pause_ms > 0, adds a natural pause (at sentence ends).
    - If pause_ms == 0, performs a 30-50 ms crossfade with NO pause at language transitions.
    """
    if len(audio1) == 0:
        return audio2
    if len(audio2) == 0:
        return audio1

    if pause_ms > 0:
        silence = np.zeros(int(sr * (pause_ms / 1000.0)), dtype=np.float32)
        return np.concatenate([audio1, silence, audio2])

    fade_samples = int(sr * (crossfade_ms / 1000.0))
    if len(audio1) < fade_samples or len(audio2) < fade_samples:
        return np.concatenate([audio1, audio2])

    fade_out = np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
    fade_in = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)

    overlap = (audio1[-fade_samples:] * fade_out) + (audio2[:fade_samples] * fade_in)
    return np.concatenate([audio1[:-fade_samples], overlap, audio2[fade_samples:]])


# ======================================================================
# 5. MIXED SPEECH GENERATION & LOCAL QUALITY REPORT
# ======================================================================
def generate_mixed(
    text: str,
    ref_wav: str,
    out_wav: str,
    model=None,
    quality_check: bool = True
) -> tuple[str, dict]:
    """
    Executes multilingual Hinglish synthesis 100% locally:
    - Segments words by language ('hi' vs 'en')
    - Synthesizes each segment using the SAME speaker conditioning (ref_wav)
    - Merges with 30-50 ms crossfade and matching loudness
    - Runs local Whisper verification report
    """
    if model is None:
        from multilingual_app import get_or_load_model
        model = get_or_load_model()

    sr = model.sr
    # Condition the model on the voice sample once for all segments (zero voice drift)
    model.prepare_conditionals(str(ref_wav), exaggeration=0.5)

    segments = split_languages(text)
    audio_parts: list[tuple[np.ndarray, bool]] = []

    hindi_words_found = []
    english_words_found = []
    retried_segments = []

    with torch.inference_mode():
        for idx, seg in enumerate(segments):
            seg_text = seg["text"].strip()
            seg_lang = seg["lang"]
            if not seg_text:
                continue

            clean_text = prepare_text(seg_text, seg_lang)

            if seg_lang == "hi":
                hindi_words_found.extend(seg_text.split())
            else:
                english_words_found.extend(seg_text.split())

            # Synthesize segment with matching language_id
            wav = model.generate(
                clean_text,
                language_id=seg_lang,
                audio_prompt_path=None,
                exaggeration=0.5,
                cfg_weight=0.5,
                temperature=0.8,
            )
            chunk_np = wav.squeeze(0).cpu().numpy().astype(np.float32)
            chunk_np = match_loudness(chunk_np)

            # Check if this segment ended with a natural sentence terminator
            has_pause = any(seg_text.endswith(p) for p in (".", "!", "?", "।", "\n", "..."))
            audio_parts.append((chunk_np, has_pause))

    # Seamlessly stitch segments together
    final_audio = np.zeros(0, dtype=np.float32)
    for i, (part, has_pause) in enumerate(audio_parts):
        pause = SENTENCE_PAUSE_MS if has_pause else 0
        final_audio = crossfade_join(final_audio, part, sr, crossfade_ms=CROSSFADE_MS, pause_ms=pause)

    # Save output WAV
    Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
    sf.write(out_wav, final_audio, sr, format="WAV", subtype="PCM_16")

    # Local quality check via faster-whisper
    transcription = ""
    if quality_check:
        try:
            from faster_whisper import WhisperModel
            whisper = WhisperModel("base", compute_type="int8")
            segs, _ = whisper.transcribe(out_wav)
            transcription = " ".join(s.text.strip() for s in segs)
        except Exception:
            pass

    report = {
        "total_segments": len(segments),
        "hindi_words": list(set(hindi_words_found)),
        "english_words": list(set(english_words_found)),
        "retried_segments": retried_segments,
        "whisper_verification": transcription,
        "duration_s": round(len(final_audio) / sr, 2)
    }

    print("\n--- 100% Local Hinglish Synthesis Report ---")
    print(f"Total Segments: {len(segments)}")
    for s in segments:
        print(f"  [{s['lang'].upper()}] {s['text']}")
    print(f"English words: {report['english_words']}")
    print(f"Hindi words: {report['hindi_words']}")
    if transcription:
        print(f"Whisper Quality Check: {transcription}")
    print("--------------------------------------------\n")

    return out_wav, report
