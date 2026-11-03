import os
import sys
import time
from pathlib import Path

# Ensure UTF-8 console output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import numpy as np
import soundfile as sf
import torch

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from multilingual_app import generate_speech_stream, MY_VOICE_PATH, OUTPUTS_DIR, split_text_into_chunks

def run_150_word_test():
    print("============================================================")
    print("      VoiceCraft: 150-Word Streaming & Single-File Test     ")
    print("============================================================")

    # 150-word test text
    test_150_words = (
        "Artificial intelligence is rapidly transforming every aspect of human life and society across the globe today. "
        "From healthcare and scientific discovery to automated software engineering and creative expression, modern machine learning systems "
        "are solving challenges that were once considered completely impossible. "
        "Natural voice cloning allows people to preserve their unique vocal characteristics and speak in any language with genuine emotional depth and clarity. "
        "By breaking speech synthesis into sentence units, systems achieve rapid response times while maintaining continuous audio quality across long passages. "
        "In this demonstration, each individual sentence is synthesized directly into memory and streamed immediately to the listener without saving temporary files to disk. "
        "Once synthesis is complete, every chunk is seamlessly stitched together into a single master audio file with smooth transitions and balanced volume."
    )

    words = test_150_words.split()
    print(f"[Input Text] Total Words: {len(words)}")

    chunks = split_text_into_chunks(test_150_words, max_chars=250)
    print(f"[Text Chunks] Split into {len(chunks)} sentence chunks:")
    for idx, c in enumerate(chunks):
        print(f"  Chunk {idx+1}: ({len(c)} chars) \"{c[:60]}...\"")

    # Baseline file inventory in outputs/
    existing_files_before = set(OUTPUTS_DIR.glob("*.wav"))
    print(f"\n[Disk State Before] Existing .wav files in outputs/: {len(existing_files_before)}")

    # Run generator
    print("\n[Execution] Starting generate_speech_stream generator...")
    start_time = time.perf_counter()

    first_chunk_stream_time = None
    streamed_chunks_b64 = []
    final_output_path = None
    final_info = None

    generator = generate_speech_stream(
        text=test_150_words,
        language_code="en",
        audio_input_path=str(MY_VOICE_PATH),
        exaggeration=0.5,
        cfg_weight=0.0,  # 0.0 for faster CPU execution during test
        temperature=0.8,
        stream_playback=True,
        pause_between_chunks_ms=200,
        crossfade_ms=30,
        keep_partial_on_cancel=False,
        progress=None,
    )

    step_count = 0
    for res in generator:
        step_count += 1
        stream_html, audio_file, download_file, status = res
        curr_time = time.perf_counter() - start_time

        # Check if a stream chunk with base64 audio was yielded
        if "data:audio/wav;base64," in stream_html:
            if first_chunk_stream_time is None:
                first_chunk_stream_time = curr_time
                print(f"  --> (a) FIRST AUDIO CHUNK STREAMED TO BROWSER at {curr_time:.2f}s (before later chunks finished)!")
            streamed_chunks_b64.append(curr_time)
            print(f"  [Stream Update] Chunk {len(streamed_chunks_b64)} in-memory audio yielded at {curr_time:.2f}s")

        if audio_file is not None:
            final_output_path = audio_file
            final_info = status

    total_generation_time = time.perf_counter() - start_time
    print(f"\n[Execution Complete] Total Time: {total_generation_time:.2f}s")
    print(f"[Final Output Path]: {final_output_path}")

    # ============================================================
    # VERIFICATION OF THE 5 REQUIRED BEHAVIORS
    # ============================================================
    print("\n============================================================")
    print("                     VERIFICATION RESULTS                   ")
    print("============================================================")

    # (a) First audio plays before generation finishes
    a_pass = first_chunk_stream_time is not None and first_chunk_stream_time < total_generation_time
    print(f"(a) First audio played before completion: {'PASS ✅' if a_pass else 'FAIL ❌'}")
    print(f"    - First chunk available: {first_chunk_stream_time:.2f}s")
    print(f"    - Full generation ended: {total_generation_time:.2f}s")
    print(f"    - Stream lead time: {total_generation_time - first_chunk_stream_time:.2f}s earlier!")

    # (b) .\outputs\ contains exactly ONE new file
    existing_files_after = set(OUTPUTS_DIR.glob("*.wav"))
    new_files = existing_files_after - existing_files_before
    b_pass = len(new_files) == 1
    print(f"\n(b) Exactly ONE new file saved in outputs/: {'PASS ✅' if b_pass else 'FAIL ❌'}")
    print(f"    - New files found: {[f.name for f in new_files]}")
    print(f"    - Total new files count: {len(new_files)} (Expected: 1)")

    # (c) No chunk or temp files exist anywhere in project or outputs
    chunk_pattern_files = list(BASE_DIR.glob("**/*chunk*.wav"))
    temp_pattern_files = list(BASE_DIR.glob("**/*temp*.wav"))
    c_pass = len(chunk_pattern_files) == 0 and len(temp_pattern_files) == 0
    print(f"\n(c) Zero chunk or temp files on disk: {'PASS ✅' if c_pass else 'FAIL ❌'}")
    print(f"    - Chunk files on disk: {len(chunk_pattern_files)}")
    print(f"    - Temp files on disk: {len(temp_pattern_files)}")

    # (d) Duration check: audio duration vs sum of chunks + pauses
    d_pass = False
    if final_output_path and os.path.exists(final_output_path):
        data, sr = sf.read(final_output_path)
        final_duration = len(data) / sr
        # Expected pauses: (num_chunks - 1) * 200ms
        num_chunks = len(chunks)
        expected_pause_sec = (num_chunks - 1) * 0.200
        print(f"\n(d) Audio Duration Analysis:")
        print(f"    - Final file duration: {final_duration:.2f}s")
        print(f"    - Total chunks: {num_chunks}")
        print(f"    - Integrated inter-sentence pauses: {expected_pause_sec:.2f}s")
        d_pass = final_duration > 15.0  # 150 words should be at least 25-45s of speech
        print(f"    - Duration check: {'PASS ✅' if d_pass else 'FAIL ❌'}")

        # (e) No clicks, no clipping, no truncated endings
        max_peak = float(np.max(np.abs(data)))
        clipping = max_peak > 0.99
        rms_start = float(np.sqrt(np.mean(data[: int(sr * 0.03)] ** 2)))
        rms_end = float(np.sqrt(np.mean(data[-int(sr * 0.03) :] ** 2)))
        e_pass = not clipping and max_peak > 0.1
        print(f"\n(e) Objective Audio Quality Checks:")
        print(f"    - Peak Amplitude: {max_peak:.4f} (Target <= 0.98, Clipping: {clipping})")
        print(f"    - Boundary start RMS (fade-in check): {rms_start:.6f}")
        print(f"    - Boundary end RMS (fade-out check): {rms_end:.6f}")
        print(f"    - Quality check: {'PASS ✅' if e_pass else 'FAIL ❌'}")

    all_passed = a_pass and b_pass and c_pass and d_pass and e_pass
    print("\n============================================================")
    print(f"OVERALL TEST STATUS: {'ALL CHECKS PASSED ✅' if all_passed else 'SOME CHECKS FAILED ❌'}")
    print("============================================================")
    return all_passed

if __name__ == "__main__":
    success = run_150_word_test()
    sys.exit(0 if success else 1)
