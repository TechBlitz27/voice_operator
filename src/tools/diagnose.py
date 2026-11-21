"""Audio and STT Diagnostic Tool for Voice Operator v1.

Provides subcommands to inspect audio hardware, record native vs 16kHz pipeline audio,
measure live frame RMS/peak and Silero speech probability, and run offline Whisper STT.

Usage:
    python -m src.tools.diagnose devices
    python -m src.tools.diagnose record --device <id> --seconds 10 --out file.wav
    python -m src.tools.diagnose levels --device <id>
    python -m src.tools.diagnose transcribe file.wav
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import sounddevice as sd


# ==============================================================================
# Helper Functions: Device Classification & Audio Processing
# ==============================================================================

def classify_device(name: str, host_api_name: str) -> str:
    """Classify device connection as Bluetooth, USB, built-in array, or wired."""
    combined = f"{name} {host_api_name}".lower()

    # 1. Bluetooth indicators
    bt_indicators = (
        "bluetooth", "bth", "bthhfenum", "hands-free", "rfcomm",
        "wireless", "buds", "airpods", "a2dp", "jbl", "boat",
        "realme", "galaxy", "sony"
    )
    if any(k in combined for k in bt_indicators):
        return "Bluetooth"

    # 2. USB indicators
    if "usb" in combined:
        return "USB"

    # 3. Built-in microphone array
    array_indicators = ("array", "built-in", "internal")
    if any(k in combined for k in array_indicators):
        return "built-in array"

    # 4. Standard wired analog codec (Realtek, 3.5mm jack, headphones, mic, speaker)
    return "wired"


def resolve_device(device_spec: Optional[str]) -> Optional[int]:
    """Resolve a device index or name substring to an integer device ID."""
    if device_spec is None:
        return None
    spec_str = str(device_spec).strip()
    if spec_str.isdigit():
        return int(spec_str)
    
    spec_lower = spec_str.lower()
    devices = sd.query_devices()
    matches = [i for i, d in enumerate(devices) if spec_lower in d["name"].lower()]
    if not matches:
        raise ValueError(f"No audio device matches '{device_spec}'. Run 'devices' subcommand to list.")
    if len(matches) > 1:
        # Prefer an input-capable device if searching for input
        in_matches = [i for i in matches if devices[i].get("max_input_channels", 0) > 0]
        if len(in_matches) == 1:
            return in_matches[0]
        print(f"[WARN] Multiple devices match '{device_spec}': {matches}. Using device {matches[0]}.",
              file=sys.stderr)
    return matches[0]


def resample_to_16k_mono(audio_data: np.ndarray, native_rate: int) -> np.ndarray:
    """Pipeline resampling matching SounddeviceAudio logic (16 kHz mono int16).

    Uses scipy.signal.resample_poly for anti-aliased downsampling,
    matching the production SounddeviceAudio._audio_callback pipeline.
    """
    import math
    import scipy.signal as sps

    data = np.asarray(audio_data, dtype=np.float32)
    # Downmix to mono: average channels for multi-channel arrays (not channel 0 only)
    if data.ndim == 2:
        if data.shape[1] > 1:
            data = np.mean(data, axis=1)
        else:
            data = data[:, 0]
    else:
        data = data.reshape(-1)

    # Anti-aliased resampling using resample_poly (matches production pipeline)
    target_rate = 16000
    if native_rate != target_rate:
        g = math.gcd(target_rate, native_rate)
        up = target_rate // g
        down = native_rate // g
        data = sps.resample_poly(data, up, down).astype(np.float32)

    # Convert float32 [-1.0, 1.0] to int16 [-32768, 32767]
    if data.dtype == np.float32 or data.dtype == np.float64:
        data = (data * 32767.0).clip(-32768, 32767)
    return np.asarray(data, dtype=np.int16)


# ==============================================================================
# Subcommand 1: devices
# ==============================================================================

def cmd_devices(args: argparse.Namespace) -> int:
    """List every input and output device with details and connection type."""
    try:
        raw_devices = sd.query_devices()
        host_apis = sd.query_hostapis()
    except Exception as e:
        print(f"Error querying audio devices: {e}", file=sys.stderr)
        return 1

    try:
        default_in, default_out = sd.default.device
    except Exception:
        default_in, default_out = -1, -1

    print("\n" + "=" * 105)
    print("VOICE OPERATOR v1 - AUDIO DEVICE DIAGNOSTICS")
    print("=" * 105)
    header = (
        f"{'ID':>3}  {'Type':<7} {'Name':<36} {'Host API':<18} "
        f"{'Rate (Hz)':<10} {'Channels':<10} {'Connection':<14}"
    )
    print(header)
    print("-" * 105)

    for idx, d in enumerate(raw_devices):
        in_ch = int(d.get("max_input_channels", 0))
        out_ch = int(d.get("max_output_channels", 0))
        rate = int(d.get("default_samplerate", 0))
        api_idx = int(d.get("hostapi", 0))
        api_name = host_apis[api_idx]["name"] if api_idx < len(host_apis) else "Unknown"

        if in_ch > 0 and out_ch > 0:
            dev_type = "In/Out"
            channels_str = f"{in_ch}in/{out_ch}out"
        elif in_ch > 0:
            dev_type = "Input"
            channels_str = f"{in_ch} in"
        elif out_ch > 0:
            dev_type = "Output"
            channels_str = f"{out_ch} out"
        else:
            dev_type = "None"
            channels_str = "0"

        conn_type = classify_device(d["name"], api_name)

        marker = ""
        if idx == default_in and idx == default_out:
            marker = " [DEF IN/OUT]"
        elif idx == default_in:
            marker = " [DEF IN]"
        elif idx == default_out:
            marker = " [DEF OUT]"

        name_display = d["name"]
        if len(name_display) > 34:
            name_display = name_display[:31] + "..."

        row = (
            f"{idx:>3}  {dev_type:<7} {name_display:<36} {api_name:<18} "
            f"{rate:<10} {channels_str:<10} {conn_type:<14}{marker}"
        )
        print(row)

    print("-" * 105)
    print(f"Total devices: {len(raw_devices)} | Default Input: {default_in} | Default Output: {default_out}\n")
    return 0


# ==============================================================================
# Subcommand 2: record
# ==============================================================================

def cmd_record(args: argparse.Namespace) -> int:
    """Capture raw audio at native rate and save 16 kHz mono pipeline version."""
    dev_id = resolve_device(args.device)
    try:
        if dev_id is not None:
            dev_info = sd.query_devices(dev_id)
        else:
            dev_info = sd.query_devices(kind="input")
            dev_id = dev_info.get("index", None)
    except Exception as e:
        print(f"Failed to query recording device: {e}", file=sys.stderr)
        return 1

    native_rate = int(dev_info.get("default_samplerate", 44100))
    channels = int(dev_info.get("max_input_channels", 1))
    if channels <= 0:
        channels = 1
    # Cap capture channels to 2 for recording simplicity if device reports many
    rec_channels = min(channels, 2)
    seconds = float(args.seconds)

    print(f"\n[RECORD] Device: [{dev_id}] {dev_info['name']}")
    print(f"[RECORD] Native format: {native_rate} Hz, {rec_channels} channel(s)")
    print(f"[RECORD] Recording for {seconds:.1f} seconds... Speak now.")

    try:
        raw_frames = sd.rec(
            int(seconds * native_rate),
            samplerate=native_rate,
            channels=rec_channels,
            dtype="float32",
            device=dev_id
        )
        sd.wait()
    except Exception as e:
        print(f"Recording error: {e}", file=sys.stderr)
        return 1

    print("[RECORD] Capture completed. Processing audio...")

    # 1. Save raw audio at native rate
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    raw_int16 = (raw_frames * 32767.0).clip(-32768, 32767).astype(np.int16)
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(rec_channels)
        wf.setsampwidth(2)
        wf.setframerate(native_rate)
        wf.writeframes(raw_int16.tobytes())

    # 2. Save 16 kHz mono version produced by project pipeline
    pipeline_int16 = resample_to_16k_mono(raw_frames, native_rate)
    stem = out_path.stem
    parent = out_path.parent
    pipeline_out_16k = parent / f"{stem}_16k.wav"
    pipeline_out_16khz = parent / f"{stem}_16khz.wav"

    with wave.open(str(pipeline_out_16k), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(pipeline_int16.tobytes())

    # Also write 16khz copy for convenience
    with wave.open(str(pipeline_out_16khz), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(pipeline_int16.tobytes())

    print("\nSaved audio comparison files:")
    print(f"  1. Native Raw:  {out_path} ({native_rate} Hz, {rec_channels} ch, {out_path.stat().st_size} bytes)")
    print(f"  2. 16kHz Mono:  {pipeline_out_16k} (16000 Hz, 1 ch, {pipeline_out_16k.stat().st_size} bytes)")
    print("These two files can now be compared by ear to evaluate resampling quality.\n")
    return 0


# ==============================================================================
# Subcommand 3: levels
# ==============================================================================

def cmd_levels(args: argparse.Namespace) -> int:
    """Print live RMS, peak, and Silero speech probability per frame for 10 s."""
    dev_id = resolve_device(args.device)
    seconds = float(getattr(args, "seconds", 10.0))

    try:
        if dev_id is not None:
            dev_info = sd.query_devices(dev_id)
        else:
            dev_info = sd.query_devices(kind="input")
            dev_id = dev_info.get("index", None)
    except Exception as e:
        print(f"Failed to query device: {e}", file=sys.stderr)
        return 1

    native_rate = int(dev_info.get("default_samplerate", 16000))
    print(f"\n[LEVELS] Monitoring device [{dev_id}] {dev_info['name']}")
    print(f"[LEVELS] Native rate: {native_rate} Hz | Duration: {seconds:.1f} s")
    print(f"[LEVELS] Frame size: 512 samples (32 ms @ 16 kHz)")
    print("-" * 75)
    print(f"{'Time':<10} {'RMS':<10} {'Peak':<8} {'Silero VAD Prob':<18} {'State':<10}")
    print("-" * 75)

    # Initialize Silero VAD for frame-by-frame speech probability
    from src.adapters.silero_vad import SileroVAD
    try:
        vad = SileroVAD()
        vad_available = True
    except Exception:
        vad_available = False
        print("[WARN] Silero VAD could not be loaded. Probabilities will show 0.0.", file=sys.stderr)

    frame_len_native = max(1, int(round(512 * native_rate / 16000)))
    total_frames = int(round(seconds * native_rate / frame_len_native))

    all_rms = []
    all_peaks = []
    speech_frame_count = 0

    try:
        with sd.InputStream(device=dev_id, channels=1, samplerate=native_rate,
                            blocksize=frame_len_native, dtype="float32") as stream:
            start_time = time.time()
            for frame_idx in range(total_frames):
                indata, overflowed = stream.read(frame_len_native)
                elapsed = time.time() - start_time
                if elapsed > seconds:
                    break

                # Pipeline conversion to 16 kHz int16 / normalized float32
                frame_16k_int16 = resample_to_16k_mono(indata, native_rate)
                if len(frame_16k_int16) < 512:
                    frame_16k_int16 = np.pad(frame_16k_int16, (0, 512 - len(frame_16k_int16)))
                elif len(frame_16k_int16) > 512:
                    frame_16k_int16 = frame_16k_int16[:512]

                data_f64 = frame_16k_int16.astype(np.float64)
                rms = float(np.sqrt(np.mean(data_f64 ** 2)))
                peak = int(np.max(np.abs(frame_16k_int16)))
                all_rms.append(rms)
                all_peaks.append(peak)

                # Compute Silero VAD probability using the production SileroVAD class
                prob = 0.0
                if vad_available:
                    try:
                        prob = vad.get_speech_prob(frame_16k_int16.tobytes())
                    except Exception:
                        prob = 0.0

                is_speech_flag = prob > 0.4
                if is_speech_flag:
                    speech_frame_count += 1
                state_str = "SPEECH" if is_speech_flag else "silence"

                time_str = f"{elapsed:05.2f}s"
                print(f"{time_str:<10} {rms:<10.1f} {peak:<8} {prob:<18.3f} {state_str:<10}")

    except Exception as e:
        print(f"Error reading levels stream: {e}", file=sys.stderr)
        return 1

    print("-" * 75)
    avg_rms = np.mean(all_rms) if all_rms else 0.0
    max_peak = max(all_peaks) if all_peaks else 0
    speech_pct = (speech_frame_count / max(1, len(all_rms))) * 100.0
    print(f"Summary: Avg RMS: {avg_rms:.1f} | Max Peak: {max_peak} | Speech Frames: {speech_pct:.1f}%\n")
    return 0


# ==============================================================================
# Subcommand 4: transcribe
# ==============================================================================

def cmd_transcribe(args: argparse.Namespace) -> int:
    """Run real offline Whisper STT on file.wav and print segment metrics."""
    wav_path = Path(args.file)
    if not wav_path.exists():
        print(f"Error: audio file '{wav_path}' does not exist.", file=sys.stderr)
        return 1

    print(f"\n[STT] Loading audio file: {wav_path}")
    try:
        with wave.open(str(wav_path), "rb") as wf:
            n_ch = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            rate = wf.getframerate()
            n_frames = wf.getnframes()
            raw_bytes = wf.readframes(n_frames)
    except Exception as e:
        print(f"Failed to read WAV file: {e}", file=sys.stderr)
        return 1

    duration = n_frames / rate if rate > 0 else 0.0
    print(f"[STT] File properties: {rate} Hz, {n_ch} ch, {sampwidth*8}-bit, duration: {duration:.2f} s")

    # Convert to 16 kHz mono float32 for faster-whisper
    if sampwidth == 2:
        audio_arr = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        audio_arr = np.frombuffer(raw_bytes, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        audio_arr = np.frombuffer(raw_bytes, dtype=np.uint8).astype(np.float32) / 128.0 - 1.0

    if n_ch > 1:
        audio_arr = audio_arr.reshape(-1, n_ch)[:, 0]

    if rate != 16000:
        import math
        import scipy.signal as sps
        g = math.gcd(16000, rate)
        up = 16000 // g
        down = rate // g
        audio_arr = sps.resample_poly(audio_arr, up, down).astype(np.float32)

    # Initialize WhisperModel
    print("[STT] Loading faster-whisper model (offline local weights)...")
    try:
        from faster_whisper import WhisperModel
        model_size = getattr(args, "model", "base")
        local_model_path = os.path.join("models", f"whisper-{model_size}")
        if os.path.exists(local_model_path):
            model = WhisperModel(local_model_path, device="cpu", compute_type="int8")
        else:
            model = WhisperModel(model_size, device="cpu", compute_type="int8", local_files_only=True)
    except Exception as e:
        print(f"Error loading faster-whisper: {e}", file=sys.stderr)
        return 1

    t0 = time.time()
    try:
        lang = getattr(args, "language", None)
        segments_gen, info = model.transcribe(
            audio_arr,
            beam_size=5,
            language=lang,
            condition_on_previous_text=False,
            vad_filter=False
        )
        segments = list(segments_gen)
        elapsed = time.time() - t0
    except Exception as e:
        print(f"Transcription error: {e}", file=sys.stderr)
        return 1

    full_text = " ".join(s.text.strip() for s in segments if s.text.strip()).strip()

    print("\n" + "=" * 80)
    print("WHISPER SPEECH RECOGNITION RESULTS")
    print("=" * 80)
    print(f"Transcribed Text:      '{full_text}'")
    print(f"Detected Language:     {info.language}")
    print(f"Language Probability:  {info.language_probability:.4f}")
    print(f"Inference Latency:     {elapsed:.3f} s")
    print("-" * 80)
    print(f"{'Segment':<9} {'Time Window (s)':<18} {'avg_logprob':<14} {'no_speech_prob':<16} {'Text'}")
    print("-" * 80)

    for idx, seg in enumerate(segments):
        time_window = f"{seg.start:05.2f} - {seg.end:05.2f}"
        print(
            f"#{idx + 1:<8} {time_window:<18} {seg.avg_logprob:<14.4f} "
            f"{seg.no_speech_prob:<16.4f} '{seg.text.strip()}'"
        )

    print("=" * 80 + "\n")
    return 0


# ==============================================================================
# CLI Main Entry Point
# ==============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.tools.diagnose",
        description="Audio hardware and speech diagnostic utility for Voice Operator v1."
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Diagnostic subcommands")

    # 1. devices
    p_devices = subparsers.add_parser("devices", help="List all input and output devices with classification.")
    p_devices.set_defaults(func=cmd_devices)

    # 2. record
    p_record = subparsers.add_parser("record", help="Capture native raw and 16 kHz pipeline audio.")
    p_record.add_argument("--device", help="Device index or name substring (default: system input).")
    p_record.add_argument("--seconds", type=float, default=10.0, help="Duration in seconds (default: 10).")
    p_record.add_argument("--out", required=True, help="Output WAV filename.")
    p_record.set_defaults(func=cmd_record)

    # 3. levels
    p_levels = subparsers.add_parser("levels", help="Print live RMS, peak, and Silero VAD probability.")
    p_levels.add_argument("--device", help="Device index or name substring (default: system input).")
    p_levels.add_argument("--seconds", type=float, default=10.0, help="Monitoring duration (default: 10).")
    p_levels.set_defaults(func=cmd_levels)

    # 4. transcribe
    p_transcribe = subparsers.add_parser("transcribe", help="Run real offline STT and print segment metrics.")
    p_transcribe.add_argument("file", help="Path to WAV audio file.")
    p_transcribe.add_argument("--model", default="base", help="Whisper model size (default: base).")
    p_transcribe.add_argument("--language", default=None, help="Force language (e.g. en, hi).")
    p_transcribe.set_defaults(func=cmd_transcribe)

    args = parser.parse_args()
    if not args.subcommand:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
