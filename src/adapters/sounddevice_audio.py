import math
import os
import queue
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Union

import numpy as np
import scipy.signal as sps
import sounddevice as sd

from src.core.interfaces.audio import AudioSource

AudioDevice = Union[int, str]


def _speak_notification(text: str, synthesizer: Optional[Any] = None) -> None:
    """Announce state change via synthesizer or native Windows SAPI in background."""
    if synthesizer is not None and hasattr(synthesizer, "speak"):
        try:
            synthesizer.speak(text)
            return
        except Exception:
            pass

    def _sapi_worker():
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            voice = win32com.client.Dispatch("SAPI.SpVoice")
            voice.Speak(text)
            pythoncom.CoUninitialize()
        except Exception:
            pass

    threading.Thread(target=_sapi_worker, daemon=True).start()


class SounddeviceAudio(AudioSource):
    """Production audio source with anti-aliased resampling, WASAPI shared mode preference,
    adaptive noise calibration, AGC normalization, and device hot-plug recovery.
    """


    def __init__(
        self,
        sample_rate: int = 16000,
        block_size: int = 512,
        device: Optional[AudioDevice] = None,
        speech_synthesizer: Optional[Any] = None,
        auto_calibrate: bool = True
    ):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.requested_device = device
        self.speech_synthesizer = speech_synthesizer
        self.auto_calibrate = auto_calibrate

        self._stream: Optional[sd.InputStream] = None
        self._audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=128)
        self.device_sample_rate = sample_rate
        self.device_dtype = "float32"
        self.device_channels = 1
        self.active_device: Optional[int] = None
        self.active_device_name: str = "Unknown"

        # Gain & adaptive noise calibration parameters
        self.noise_floor: float = 50.0
        self.speech_threshold: float = 150.0
        self.calibrated: bool = False

        # Mic gating and acoustic discard window
        self._discard_until: float = 0.0
        self._hotplug_lock = threading.Lock()

    def set_speech_synthesizer(self, synthesizer: Any) -> None:
        """Attach synthesizer for spoken hardware notifications."""
        self.speech_synthesizer = synthesizer

    @staticmethod
    def list_input_devices() -> List[Dict[str, Any]]:
        """Return recording-capable devices in display-friendly form."""
        devices = sd.query_devices()
        input_devices = []
        for index, device in enumerate(devices):
            if device.get("max_input_channels", 0) <= 0:
                continue
            host_api = sd.query_hostapis(device["hostapi"])
            input_devices.append({
                "index": index,
                "name": str(device["name"]),
                "channels": int(device["max_input_channels"]),
                "default_sample_rate": int(device["default_samplerate"]),
                "host_api": str(host_api["name"]),
            })
        return input_devices

    def _resolve_requested_device(self) -> Optional[int]:
        """Resolve requested device without ranking devices by name."""
        if self.requested_device is None:
            return None
        if isinstance(self.requested_device, int):
            return self.requested_device
        requested = str(self.requested_device).strip().lower()
        if requested.isdigit():
            return int(requested)

        matches = [d["index"] for d in self.list_input_devices()
                   if requested in d["name"].lower()]
        if not matches:
            raise RuntimeError(f"No recording device matches '{self.requested_device}'. "
                               "Run with --list-audio-devices to see microphones.")
        if len(matches) > 1:
            # Prefer WASAPI match if multiple
            devices = sd.query_devices()
            host_apis = sd.query_hostapis()
            wasapi_matches = [
                idx for idx in matches
                if "wasapi" in host_apis[devices[idx]["hostapi"]]["name"].lower()
            ]
            if len(wasapi_matches) == 1:
                return wasapi_matches[0]
            raise RuntimeError(f"More than one recording device matches '{self.requested_device}': "
                               f"{matches}. Use an index from --list-audio-devices.")
        return matches[0]

    def _get_wasapi_counterpart(self, dev_info: Dict[str, Any]) -> Optional[int]:
        """Look for the WASAPI shared-mode version of the given device name."""
        try:
            name = dev_info.get("name", "")
            host_apis = sd.query_hostapis()
            wasapi_indices = [
                i for i, h in enumerate(host_apis)
                if "wasapi" in h["name"].lower()
            ]
            if not wasapi_indices:
                return None

            for idx, d in enumerate(sd.query_devices()):
                if d.get("max_input_channels", 0) > 0 and d.get("hostapi") in wasapi_indices:
                    # Match by name root
                    if name[:15].lower() in d["name"].lower() or d["name"][:15].lower() in name.lower():
                        return idx
        except Exception:
            pass
        return None

    def _device_config(self, device_index: Optional[int]) -> tuple[int, str, int, int]:
        """Determine rate, dtype, channels, and block size for the target device."""
        try:
            if device_index is not None:
                info = sd.query_devices(device_index)
            else:
                info = sd.query_devices(kind="input")
            default_rate = float(info["default_samplerate"])
            max_channels = int(info.get("max_input_channels", 1))
        except Exception:
            default_rate = float(self.sample_rate)
            max_channels = 1

        rate = int(round(default_rate)) if default_rate >= 8000 else self.sample_rate
        channels = max(1, min(max_channels, 2))  # Capture native mono or stereo array
        blocksize = max(1, int(round(self.block_size * rate / self.sample_rate)))
        return rate, "float32", channels, blocksize

    def _audio_callback(self, indata, frames, time_info, status):
        """Audio callback running at native hardware rate:
        1. Checks discard window (mic gating during/after TTS).
        2. Downmixes multi-channel arrays by averaging channels (not channel 0 only).
        3. Anti-aliased downsamples to 16 kHz using scipy.signal.resample_poly.
        4. Applies automatic gain normalization and peak limiting.
        """
        if status:
            # Device error / disconnection flag
            if "input overflow" not in str(status).lower():
                print(f"[Audio] Stream status warning: {status}")

        # Check discard window (TTS active or post-TTS settling)
        if time.time() < self._discard_until:
            return

        data = np.asarray(indata, dtype=np.float32)

        # 3. Mono mix: average channels for multi-channel arrays
        if data.ndim == 2:
            if data.shape[1] > 1:
                data = np.mean(data, axis=1)
            else:
                data = data[:, 0]
        else:
            data = data.reshape(-1)

        # 1. Anti-aliased resampling using resample_poly
        if self.device_sample_rate != self.sample_rate:
            g = math.gcd(self.sample_rate, self.device_sample_rate)
            up = self.sample_rate // g
            down = self.device_sample_rate // g
            data = sps.resample_poly(data, up, down).astype(np.float32)

        # Convert to int16 amplitude scale [-32768, 32767]
        if self.device_dtype == "float32":
            data = data * 32767.0

        # 4. Gain: Automatic gain normalization to target RMS with limiter
        frame_rms = float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))
        target_rms = 3000.0  # Healthy speech operating level in int16 scale
        if frame_rms > (self.noise_floor * 0.8) and frame_rms > 10.0:
            gain = np.clip(target_rms / max(frame_rms, 1.0), 0.5, 10.0)
            data = data * gain

        # Peak limiter to eliminate distortion
        data = np.clip(data, -32000.0, 32000.0)
        payload = np.asarray(data, dtype=np.int16).tobytes()

        try:
            self._audio_queue.put_nowait(payload)
        except queue.Full:
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._audio_queue.put_nowait(payload)
            except queue.Full:
                pass

    def _open_stream(self, device_index: Optional[int]) -> None:
        """Opens InputStream preferring WASAPI shared mode."""
        rate, dtype, channels, blocksize = self._device_config(device_index)

        extra_settings = None
        try:
            if device_index is not None:
                d_info = sd.query_devices(device_index)
                host_api_name = sd.query_hostapis(d_info["hostapi"])["name"].lower()
                if "wasapi" in host_api_name:
                    extra_settings = sd.WasapiSettings(exclusive=False)
        except Exception:
            extra_settings = None

        stream = sd.InputStream(
            device=device_index,
            samplerate=rate,
            blocksize=blocksize,
            dtype=dtype,
            channels=channels,
            callback=self._audio_callback,
            extra_settings=extra_settings
        )

        self.active_device = device_index
        self.device_sample_rate = rate
        self.device_dtype = dtype
        self.device_channels = channels

        try:
            dev_info = sd.query_devices(device_index) if device_index is not None else sd.query_devices(kind="input")
            self.active_device_name = dev_info.get("name", "Default Input")
        except Exception:
            self.active_device_name = f"Device {device_index}"

        try:
            stream.start()
        except Exception:
            stream.close()
            raise
        self._stream = stream

    def _fallback_input_devices(self) -> List[int]:
        """Return all other input devices in system index order (do NOT rank by name)."""
        input_devs = self.list_input_devices()
        return [d["index"] for d in input_devs if d["index"] != self.active_device]

    def calibrate(self, duration: float = 3.0) -> None:
        """Measure ambient noise floor over 3 seconds and calculate speech threshold."""
        print(f"[Audio] Starting {duration:.1f}s ambient noise floor calibration... (stay quiet)")
        collected_rms = []
        start_time = time.time()
        timeout = duration + 2.0

        while (time.time() - start_time) < duration and (time.time() - start_time) < timeout:
            chunk = self.read_chunk()
            if chunk:
                samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float64)
                if len(samples) > 0:
                    collected_rms.append(float(np.sqrt(np.mean(samples ** 2))))
            time.sleep(0.01)

        if collected_rms:
            # 30th percentile represents steady ambient noise floor
            self.noise_floor = float(np.percentile(collected_rms, 30))
        else:
            self.noise_floor = 50.0

        # Set adaptive speech threshold (noise floor + margin)
        margin = max(120.0, self.noise_floor * 0.6)
        self.speech_threshold = self.noise_floor + margin
        self.calibrated = True
        print(f"[Audio] Calibration complete: noise floor = {self.noise_floor:.1f} RMS, "
              f"speech threshold = {self.speech_threshold:.1f} RMS.")

    def start_stream(self, calibrate: bool = False) -> None:
        """Start microphone capture stream, preferring user selection, then Windows default.
        Falls back to other devices only if opening fails, and announces which device is in use.
        """
        if self._stream is not None:
            self.stop_stream()
        self._audio_queue = queue.Queue(maxsize=128)

        # 2. Device selection: user configured device; otherwise Windows default input device
        requested_index = self._resolve_requested_device()
        target_index = requested_index

        # Prefer WASAPI shared mode counterpart if available
        if target_index is None:
            try:
                def_in = sd.query_devices(kind="input")
                wasapi_idx = self._get_wasapi_counterpart(def_in)
                if wasapi_idx is not None:
                    target_index = wasapi_idx
            except Exception:
                pass

        try:
            self._open_stream(target_index)
            # Say which device is in use
            print(f"[Audio] In use: [{self.active_device}] {self.active_device_name} "
                  f"({self.device_sample_rate} Hz, {self.device_channels} ch).")
        except Exception as error:
            self._stream = None
            if self.requested_device is not None:
                raise RuntimeError(f"Could not open requested input device "
                                   f"'{self.requested_device}': {error}") from error

            # Fall back to others only if opening fails (in system order, not ranked by name)
            fallback_errors = []
            for device_index in self._fallback_input_devices():
                try:
                    self._open_stream(device_index)
                    print(f"[Audio] Default input failed; in use: [{self.active_device}] "
                          f"{self.active_device_name} ({self.device_sample_rate} Hz).")
                    break
                except Exception as fb_err:
                    fallback_errors.append(f"{device_index}: {fb_err}")
            else:
                raise RuntimeError(
                    f"Could not open the Windows default recording device: {error}. "
                    "Fallback to alternative inputs also failed. Run with "
                    "--list-audio-devices and choose with --input-device. "
                    f"Fallback errors: {'; '.join(fallback_errors)}"
                ) from error

        if calibrate and self.auto_calibrate:
            self.calibrate(duration=3.0)

    def flush(self) -> None:
        """Discard all queued audio frames immediately."""
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

    def discard_frames_for(self, duration_sec: float) -> None:
        """Set discard deadline to drop all microphone frames for duration_sec."""
        self._discard_until = max(self._discard_until, time.time() + duration_sec)
        self.flush()

    def handle_device_changed(self) -> None:
        """Handle device removal and hot-plug: reopen stream and speak 'Microphone changed'."""
        with self._hotplug_lock:
            print("[Audio] Hardware event detected: reopening microphone stream...")
            try:
                self.stop_stream()
            except Exception:
                pass

            _speak_notification("Microphone changed.", self.speech_synthesizer)

            try:
                self.start_stream(calibrate=False)
                print(f"[Audio] Microphone changed: switched to [{self.active_device}] {self.active_device_name}.")
            except Exception as e:
                print(f"[Audio] Failed to reopen microphone after change: {e}", file=sys.stderr)

    def read_chunk(self) -> bytes:
        """Read a 16 kHz int16 audio chunk. Detects stream crashes and initiates hot-plug recovery."""
        if not self._stream:
            raise RuntimeError("Audio stream is not running.")

        # Check if stream closed unexpectedly (device unplugged)
        if not self._stream.active:
            self.handle_device_changed()

        try:
            return self._audio_queue.get(timeout=1.0)
        except queue.Empty:
            # Check stream liveness on timeout
            if self._stream and not self._stream.active:
                self.handle_device_changed()
            return b""

    def stop_stream(self) -> None:
        """Stop and close the audio stream."""
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
            print("[Audio] sounddevice stream stopped.")
