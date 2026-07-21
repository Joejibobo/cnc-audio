"""WAV renderer: mixes a CNC Audio timeline into an output WAV file.

Uses numpy for efficient audio mixing. Each clip is placed at its exact
position_seconds in a float32 mixing buffer. Crossfades work naturally
because overlapping clips are summed together with their respective fades
already applied. No temporary files are created.

Source WAV files must be 44100 Hz stereo 16-bit PCM
(produced by importer.py at asset-import time).
"""
import os
import wave
from typing import Dict

import numpy as np

from ..engine.models import ClipEvent, ExportSettings, Timeline

SAMPLE_RATE = 44100


def read_wav_float32(path: str) -> np.ndarray:
    """Read a 44100 Hz stereo WAV file into a float32 (N, 2) array."""
    with wave.open(path, "rb") as wf:
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    if sample_width == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sample_width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {sample_width} bytes in '{path}'")

    if n_channels == 1:
        data = np.column_stack([data, data])
    else:
        data = data.reshape(-1, n_channels)
        if n_channels > 2:
            data = data[:, :2]

    return data


def write_wav_float32(path: str, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    """Write a float32 (N, 2) stereo array to a 16-bit WAV file."""
    clipped = np.clip(audio, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def render_timeline(
    timeline: Timeline,
    asset_wav_paths: Dict[str, str],
    output_path: str,
    export: ExportSettings,
    master_fade_in: float = 0.0,
    master_fade_out: float = 0.0,
) -> None:
    """
    Render a Timeline to a WAV file.

    Clips are mixed at their exact position_seconds in a float32 buffer.
    Crossfades work automatically: overlapping clips with opposing fades
    are summed together in the buffer. No temp files.
    """
    total_samples = int(timeline.total_duration_seconds * SAMPLE_RATE) + SAMPLE_RATE
    buffer = np.zeros((total_samples, 2), dtype=np.float32)
    audio_cache: Dict[str, np.ndarray] = {}

    for event in timeline.events:
        if event.type != "clip":
            continue

        wav_path = asset_wav_paths.get(event.asset_id)
        if not wav_path or not os.path.isfile(wav_path):
            raise FileNotFoundError(
                f"WAV for asset '{event.asset_id}' not found at '{wav_path}'. Re-import the asset."
            )

        if event.asset_id not in audio_cache:
            audio_cache[event.asset_id] = read_wav_float32(wav_path)
        audio = audio_cache[event.asset_id]

        src_start = int(event.source_start_seconds * SAMPLE_RATE)
        src_end   = int(event.source_end_seconds   * SAMPLE_RATE)
        src_end   = min(src_end, len(audio))
        src_start = min(src_start, src_end)

        segment = audio[src_start:src_end].copy()
        if len(segment) == 0:
            continue

        gain_linear = 10.0 ** (event.gain_db / 20.0)
        segment *= gain_linear

        if event.fade_in_seconds > 0:
            n = min(int(event.fade_in_seconds * SAMPLE_RATE), len(segment))
            segment[:n] *= np.linspace(0.0, 1.0, n, dtype=np.float32)[:, np.newaxis]

        if event.fade_out_seconds > 0:
            n = min(int(event.fade_out_seconds * SAMPLE_RATE), len(segment))
            segment[-n:] *= np.linspace(1.0, 0.0, n, dtype=np.float32)[:, np.newaxis]

        pos = int(event.position_seconds * SAMPLE_RATE)
        end = pos + len(segment)

        if pos >= len(buffer):
            continue
        if end > len(buffer):
            segment = segment[:len(buffer) - pos]
            end = len(buffer)

        buffer[pos:end] += segment

    exact_samples = int(timeline.total_duration_seconds * SAMPLE_RATE)
    buffer = buffer[:exact_samples]

    # Master fade in / out applied to the full mixed buffer
    if master_fade_in and master_fade_in > 0:
        n = min(int(master_fade_in * SAMPLE_RATE), len(buffer))
        if n > 0:
            buffer[:n] *= np.linspace(0.0, 1.0, n, dtype=np.float32)[:, np.newaxis]

    if master_fade_out and master_fade_out > 0:
        n = min(int(master_fade_out * SAMPLE_RATE), len(buffer))
        if n > 0:
            buffer[-n:] *= np.linspace(1.0, 0.0, n, dtype=np.float32)[:, np.newaxis]

    if export.normalize_output:
        peak = float(np.max(np.abs(buffer)))
        target_linear = 10.0 ** (export.target_output_lufs / 20.0 + 1.0)
        if peak > 0:
            buffer = buffer * min(target_linear / peak, 1.0)

    limit = 10.0 ** (export.true_peak_limit_dbtp / 20.0)
    np.clip(buffer, -limit, limit, out=buffer)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    write_wav_float32(output_path, buffer)
