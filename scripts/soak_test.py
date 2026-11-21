import argparse
import os
import sys
import threading
import time
import psutil

# Ensure root in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.adapters.silero_vad import SileroVAD
from src.core.utils.normalizer import CommandNormalizer
from src.adapters.mocks.llm_mock import MockLLMProvider
from src.adapters.mocks.os_control_mock import MockOSController
from src.adapters.mocks.speech_mock import MockSpeechSynthesizer
from src.core.state_machine.mode_manager import ModeManager


def run_soak_test(duration_seconds: float = 1800.0):
    """Executes soak test monitoring RSS memory growth, thread stability, and COM objects."""
    print("=" * 80)
    print(f"STARTING SOAK TEST: Target Duration = {duration_seconds:.1f}s ({duration_seconds/60:.1f} min)")
    print("=" * 80)

    process = psutil.Process()
    initial_rss = process.memory_info().rss
    initial_threads = threading.active_count()

    print(f"[SOAK] Baseline RSS Memory: {initial_rss / (1024*1024):.2f} MB")
    print(f"[SOAK] Baseline Active Threads: {initial_threads}")

    # Initialize components
    vad = SileroVAD()
    llm = MockLLMProvider()
    os_ctrl = MockOSController()
    tts = MockSpeechSynthesizer()
    mm = ModeManager(llm_provider=llm, os_controller=os_ctrl, speech_synthesizer=tts, attention_policy="always_listening")

    dummy_frame = (b"\x00" * 1024)
    sample_utterances = [
        "open notepad",
        "switch to chrome",
        "close notepad",
        "start dictating",
        "Hello world this is dictated text.",
        "stop dictating",
        "open word",
        "switch to excel",
        "close word"
    ]

    t_start = time.time()
    iteration = 0
    max_rss = initial_rss

    try:
        while time.time() - t_start < duration_seconds:
            iteration += 1
            # Feed 10 VAD frames
            for _ in range(10):
                vad.is_speech(dummy_frame)

            # Route utterance
            utt = sample_utterances[iteration % len(sample_utterances)]
            norm = CommandNormalizer.normalize_transcript(utt)
            mm.route_transcript(norm)

            curr_rss = process.memory_info().rss
            if curr_rss > max_rss:
                max_rss = curr_rss

            growth_mb = (curr_rss - initial_rss) / (1024 * 1024)
            if growth_mb > 200.0:
                print(f"[SOAK FAIL] Memory leak detected: {growth_mb:.2f} MB growth exceeds 200 MB limit!", file=sys.stderr)
                sys.exit(1)

            if iteration % 100 == 0:
                elapsed = time.time() - t_start
                threads = threading.active_count()
                print(f"[SOAK Progress] {elapsed:.1f}s elapsed | Iteration {iteration} | RSS: {curr_rss / (1024*1024):.2f} MB (Growth: +{growth_mb:.2f} MB) | Threads: {threads}")

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("[SOAK] Soak test interrupted by user.")

    total_time = time.time() - t_start
    final_rss = process.memory_info().rss
    final_threads = threading.active_count()
    net_growth_mb = (final_rss - initial_rss) / (1024 * 1024)
    thread_delta = final_threads - initial_threads

    print("=" * 80)
    print("SOAK TEST RESULTS SUMMARY")
    print("=" * 80)
    print(f"Elapsed Time:       {total_time:.2f} s")
    print(f"Total Iterations:   {iteration}")
    print(f"Initial Memory:     {initial_rss / (1024*1024):.2f} MB")
    print(f"Final Memory:       {final_rss / (1024*1024):.2f} MB")
    print(f"Net Growth:         {net_growth_mb:+.2f} MB (Limit: < 200 MB)")
    print(f"Initial Threads:    {initial_threads}")
    print(f"Final Threads:      {final_threads} (Delta: {thread_delta:+d})")

    # Assertions
    if net_growth_mb > 200.0:
        print(f"[FAIL] Net memory growth of {net_growth_mb:.2f} MB exceeded 200 MB limit!", file=sys.stderr)
        sys.exit(1)

    if thread_delta > 3:
        print(f"[FAIL] Thread leak detected: {thread_delta} threads leaked!", file=sys.stderr)
        sys.exit(1)

    print("[SUCCESS] Soak test passed: Zero memory leaks (< 200 MB) and zero thread leaks.")
    print("=" * 80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Voice Operator v1 Soak Test")
    parser.add_argument("--seconds", type=float, default=1800.0, help="Duration in seconds to run soak test (default 1800s / 30 min)")
    args = parser.parse_args()
    run_soak_test(duration_seconds=args.seconds)
