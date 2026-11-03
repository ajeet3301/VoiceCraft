import argparse
import datetime
import json
import os
from pathlib import Path
import platform
import re
import sys
import time

# Ensure UTF-8 console output
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import numpy as np
import psutil
import soundfile as sf
import torch

from chatterbox.mtl_tts import ChatterboxMultilingualTTS

TEST_CASES = {
    "en": {
        "short": "The quick brown fox jumps over the lazy dog.",
        "medium": (
            "Artificial intelligence and neural speech synthesis have rapidly transformed how we "
            "communicate across different languages and cultures, providing realistic voice cloning "
            "capabilities for creators, educators, and developers around the world today."
        ),
        "long": (
            "Voice cloning technology represents a significant leap forward in generative artificial intelligence. "
            "By analyzing just a few seconds of clean speech audio, advanced neural models can capture the unique "
            "pitch, rhythm, timbre, and vocal characteristics of a speaker. In this system, text is broken down into "
            "phonetic representations and language tokens, which guide an autoregressive transformer to generate semantic "
            "speech codes. These intermediate tokens are then synthesized into raw audio waveforms by a high-fidelity "
            "neural vocoder. While traditional text-to-speech systems sounded robotic and unnatural, modern multilingual "
            "models allow smooth cross-lingual synthesis, enabling a person's digital voice to speak fluently in English, "
            "Hindi, Spanish, French, and dozens of other languages. Responsible deployment and watermarking techniques "
            "ensure that synthetic audio remains identifiable, transparent, and ethically aligned while empowering "
            "accessible communication tools worldwide."
        ),
    },
    "hi": {
        "short": "नमस्ते, यह मेरी आवाज़ में हिंदी का एक छोटा परीक्षण वाक्य है।",
        "medium": (
            "कृत्रिम बुद्धिमत्ता और बहुभाषी वाक् संश्लेषण ने हमारे संवाद करने के तरीके को पूरी तरह से बदल दिया है। "
            "यह तकनीक किसी भी व्यक्ति की आवाज़ को समझकर कई अन्य भाषाओं में स्वाभाविक रूप से बोलने में सक्षम बनाती है।"
        ),
        "long": (
            "आवाज़ की क्लोनिंग तकनीक कृत्रिम बुद्धिमत्ता के क्षेत्र में एक बहुत बड़ी क्रांति बनकर उभरी है। "
            "कुछ ही सेकंड की साफ़ आवाज़ के नमूने से यह तकनीक किसी भी वक्ता के स्वर, बोलने के ढंग और उच्चारण की विशेषताओं को समझ लेती है। "
            "इसके बाद जब भी कोई लिखित पाठ दिया जाता है, तो यह प्रणाली शब्दों को छोटे-छोटे वाक्यों में बाँटकर उनके लिए ध्वनि संकेत तैयार करती है। "
            "आधुनिक बहुभाषी मॉडल न केवल अंग्रेज़ी, बल्कि हिंदी और अन्य भारतीय भाषाओं में भी अत्यंत स्वाभाविक और स्पष्ट आवाज़ उत्पन्न कर सकते हैं। "
            "यह तकनीक शिक्षा, मनोरंजन और संचार के क्षेत्र में नई संभावनाओं के द्वार खोल रही है। इसके साथ ही, सुरक्षा और प्रामाणिकता "
            "बनाए रखने के लिए डिजिटल वॉटरमार्किंग का उपयोग किया जाता है, जिससे यह सुनिश्चित होता है कि आवाज़ का उपयोग ज़िम्मेदारी "
            "और पारदर्शिता के साथ हो।"
        ),
    },
}


def get_hardware_info():
    info = {
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "cpu": platform.processor(),
        "cpu_count_logical": os.cpu_count(),
        "cpu_count_physical": psutil.cpu_count(logical=False),
        "total_ram_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "cuda_available": torch.cuda.is_available(),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "None (CPU only)",
        "torch_version": torch.__version__,
        "torch_threads": torch.get_num_threads(),
        "torch_interop_threads": torch.get_num_interop_threads(),
    }
    return info


def split_text_into_chunks(text: str, max_chars: int = 250) -> list[str]:
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


def run_benchmark(
    voice_path: str = "voices/my_voice.wav",
    output_json: str = "benchmarks/baseline.json",
    t3_model: str = "v3",
    cfg_weight: float = 0.5,
    exaggeration: float = 0.5,
    temperature: float = 0.8,
    use_cond_cache: bool = False,
    cond_cache_path: str = "voices/my_voice.cond.pt",
    apply_eval_inference_mode: bool = False,
    num_threads: int | None = None,
    tag: str = "baseline",
):
    print("=" * 70)
    print(f"       CHATTERBOX TTS BENCHMARK - {tag.upper()}")
    print("=" * 70)

    if num_threads:
        torch.set_num_threads(num_threads)

    hw = get_hardware_info()
    print(f"OS: {hw['os']}")
    print(f"CPU: {hw['cpu']} ({hw['cpu_count_physical']} physical, {hw['cpu_count_logical']} logical cores)")
    print(f"RAM: {hw['total_ram_gb']} GB total")
    print(f"Device: {'CUDA (' + hw['gpu_name'] + ')' if hw['cuda_available'] else 'CPU'}")
    print(f"PyTorch: {hw['torch_version']} (Threads: {torch.get_num_threads()}, Interop: {torch.get_num_interop_threads()})")
    print("-" * 70)

    process = psutil.Process()
    device = "cuda" if torch.cuda.is_available() else "cpu"

    # Step 1: Measure Model Loading
    print("[1/3] Loading Chatterbox Multilingual TTS model...")
    t_load_start = time.perf_counter()
    model = ChatterboxMultilingualTTS.from_pretrained(device, t3_model=t3_model)
    if hasattr(model, "to") and str(model.device) != device:
        model.to(device)
    if apply_eval_inference_mode:
        if hasattr(model.t3, "eval"):
            model.t3.eval()
        if hasattr(model.s3gen, "eval"):
            model.s3gen.eval()
        if hasattr(model.ve, "eval"):
            model.ve.eval()
    model_load_time = round(time.perf_counter() - t_load_start, 3)
    print(f"      Model load time: {model_load_time:.2f} s")

    # Step 2: Voice Prep
    print("[2/3] Processing reference voice conditioning...")
    t_voice_start = time.perf_counter()
    if use_cond_cache and os.path.exists(cond_cache_path):
        print(f"      Loading cached conditionals from {cond_cache_path}...")
        model.conds = torch.load(cond_cache_path, map_location=device, weights_only=False)
        voice_prep_time = round(time.perf_counter() - t_voice_start, 3)
        print(f"      Voice cache load time: {voice_prep_time:.3f} s")
    else:
        model.prepare_conditionals(voice_path, exaggeration=exaggeration)
        voice_prep_time = round(time.perf_counter() - t_voice_start, 3)
        print(f"      Voice conditioning prep time: {voice_prep_time:.2f} s")
        if use_cond_cache:
            print(f"      Saving conditionals to {cond_cache_path}...")
            torch.save(model.conds, cond_cache_path)

    # Step 3: Run Test Matrix
    print("[3/3] Running generation tests across languages and text lengths...")
    results = {
        "timestamp": datetime.datetime.now().isoformat(),
        "tag": tag,
        "hardware": hw,
        "model_load_time_s": model_load_time,
        "voice_prep_time_s": voice_prep_time,
        "benchmarks_dir": "benchmarks",
        "cases": {},
    }

    Path("benchmarks").mkdir(parents=True, exist_ok=True)

    for lang in ["en", "hi"]:
        for length in ["short", "medium", "long"]:
            test_text = TEST_CASES[lang][length]
            word_count = len(test_text.split())
            char_count = len(test_text)
            case_key = f"{lang}_{length}"
            print(f"\n---> Testing {lang.upper()} [{length}] (~{word_count} words, {char_count} chars)...")

            chunks = split_text_into_chunks(test_text, max_chars=250)
            print(f"     Split into {len(chunks)} chunk(s).")

            # Reset peak memory stats
            if torch.cuda.is_available():
                torch.cuda.reset_peak_memory_stats()
            mem_before = process.memory_info().rss

            t_gen_start = time.perf_counter()
            first_chunk_time = None
            generated_segments = []
            silence = np.zeros(int(0.2 * model.sr), dtype=np.float32)

            for idx, chunk in enumerate(chunks):
                t_chunk_start = time.perf_counter()
                if apply_eval_inference_mode:
                    with torch.inference_mode():
                        wav = model.generate(
                            chunk,
                            language_id=lang,
                            audio_prompt_path=None,
                            exaggeration=exaggeration,
                            cfg_weight=cfg_weight,
                            temperature=temperature,
                        )
                else:
                    wav = model.generate(
                        chunk,
                        language_id=lang,
                        audio_prompt_path=None,
                        exaggeration=exaggeration,
                        cfg_weight=cfg_weight,
                        temperature=temperature,
                    )
                chunk_time = time.perf_counter() - t_chunk_start
                if first_chunk_time is None:
                    first_chunk_time = round(chunk_time, 3)
                    print(f"     Chunk 1 generated in {chunk_time:.2f}s (Time to First Audio)")
                else:
                    print(f"     Chunk {idx + 1}/{len(chunks)} generated in {chunk_time:.2f}s")
                wav_np = wav.squeeze(0).cpu().numpy()
                generated_segments.append(wav_np)

            full_audio_list = []
            for i, seg in enumerate(generated_segments):
                full_audio_list.append(seg)
                if i < len(generated_segments) - 1:
                    full_audio_list.append(silence)
            full_audio = np.concatenate(full_audio_list)
            total_gen_time = round(time.perf_counter() - t_gen_start, 3)

            audio_duration = round(len(full_audio) / model.sr, 2)
            rtf = round(total_gen_time / max(audio_duration, 0.001), 3)

            # Peak RAM & VRAM
            mem_after = process.memory_info().rss
            peak_ram_mb = round(max(mem_before, mem_after) / (1024**2), 1)
            peak_vram_mb = round(torch.cuda.max_memory_allocated() / (1024**2), 1) if torch.cuda.is_available() else 0.0

            # Save generated wav for quality inspection
            wav_path = f"benchmarks/{tag}_{lang}_{length}.wav"
            sf.write(wav_path, full_audio, model.sr, subtype="PCM_16")

            case_data = {
                "language": lang,
                "length": length,
                "words": word_count,
                "chars": char_count,
                "chunks": len(chunks),
                "first_chunk_time_s": first_chunk_time,
                "total_gen_time_s": total_gen_time,
                "audio_duration_s": audio_duration,
                "real_time_factor": rtf,
                "peak_ram_mb": peak_ram_mb,
                "peak_vram_mb": peak_vram_mb,
                "output_wav": wav_path,
            }
            results["cases"][case_key] = case_data
            print(f"     Results: Gen Time={total_gen_time:.2f}s | Audio={audio_duration:.2f}s | RTF={rtf:.2f}x | Peak RAM={peak_ram_mb}MB")

    # Save to JSON
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n[Saved] Detailed benchmark results saved to {output_json}")

    # Print Summary Table
    print("\n" + "=" * 90)
    print(f"{'Test Case':<12} | {'Words':<6} | {'Chunks':<6} | {'First Chunk':<12} | {'Total Gen':<10} | {'Audio Len':<10} | {'RTF':<8} | {'Peak RAM':<10}")
    print("-" * 90)
    for k, v in results["cases"].items():
        print(
            f"{k:<12} | {v['words']:<6} | {v['chunks']:<6} | {v['first_chunk_time_s']:>10.2f}s | {v['total_gen_time_s']:>8.2f}s | {v['audio_duration_s']:>8.2f}s | {v['real_time_factor']:>6.2f}x | {v['peak_ram_mb']:>8.1f}MB"
        )
    print("=" * 90)
    print(f"Model Load Time: {model_load_time:.2f}s  |  Voice Prep Time: {voice_prep_time:.2f}s")
    print("=" * 90)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chatterbox TTS Benchmark")
    parser.add_argument("--output", type=str, default="benchmarks/baseline.json")
    parser.add_argument("--tag", type=str, default="baseline")
    parser.add_argument("--use-cond-cache", action="store_true")
    parser.add_argument("--apply-eval", action="store_true")
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument("--cfg-weight", type=float, default=0.5)
    args = parser.parse_args()

    run_benchmark(
        output_json=args.output,
        tag=args.tag,
        use_cond_cache=args.use_cond_cache,
        apply_eval_inference_mode=args.apply_eval,
        num_threads=args.threads,
        cfg_weight=args.cfg_weight,
    )
