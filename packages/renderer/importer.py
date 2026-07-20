"""Audio import utilities: probe duration, convert any format to standard WAV."""
import json
import os
import subprocess
from pathlib import Path
from typing import Optional

FFMPEG_SEARCH_PATHS = [
    r"C:\Users\meirn\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.2-full_build\bin",
    r"C:\Program Files\ffmpeg\bin",
    r"C:\Program Files\ffmpeg-8.1.2-full_build\bin",
]


def find_tool(name: str) -> str:
    """Find ffmpeg or ffprobe — checks PATH first, then known install dirs."""
    import shutil
    found = shutil.which(name)
    if found:
        return found
    for base in FFMPEG_SEARCH_PATHS:
        candidate = os.path.join(base, name + ".exe")
        if os.path.isfile(candidate):
            return candidate
    raise RuntimeError(
        f"'{name}' not found. Install FFmpeg and ensure it's on your PATH.\n"
        f"Searched: {FFMPEG_SEARCH_PATHS}"
    )


def get_ffmpeg() -> str:
    return find_tool("ffmpeg")


def get_ffprobe() -> str:
    return find_tool("ffprobe")


def probe_duration(file_path: str) -> float:
    """Return the duration of any audio/video file in seconds using ffprobe."""
    ffprobe = get_ffprobe()
    result = subprocess.run(
        [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            file_path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    duration = data.get("format", {}).get("duration")
    if duration is None:
        raise ValueError(f"Could not read duration from '{file_path}'")
    return float(duration)


def probe_info(file_path: str) -> dict:
    """Return format + stream info for a file."""
    ffprobe = get_ffprobe()
    result = subprocess.run(
        [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration,size,format_name:stream=codec_type,sample_rate,channels",
            "-of", "json",
            file_path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def convert_to_standard_wav(src: str, dst: str) -> None:
    """Convert any audio/video to 44100 Hz stereo 16-bit WAV for rendering.
    For video files, only the audio track is extracted (-vn flag).
    """
    ffmpeg = get_ffmpeg()
    result = subprocess.run(
        [
            ffmpeg, "-y",
            "-i", src,
            "-vn",
            "-ar", "44100",
            "-ac", "2",
            "-acodec", "pcm_s16le",
            dst,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg conversion failed for '{src}':\n{result.stderr}"
        )
