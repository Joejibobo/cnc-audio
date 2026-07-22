import wave

import numpy as np

from packages.engine.models import ClipEvent, ExportSettings, Timeline
from packages.renderer.renderer import read_wav_float32, render_timeline, write_wav_float32


def test_renderer_writes_16_bit_stereo_and_scales_overload(tmp_path):
    source_path = tmp_path / "source.wav"
    output_path = tmp_path / "output.wav"
    frame_count = 4410
    ramp = np.linspace(0.1, 0.8, frame_count, dtype=np.float32)
    source = np.column_stack((ramp, ramp))
    write_wav_float32(str(source_path), source)

    event = ClipEvent(
        type="clip",
        asset_id="asset-a",
        position_seconds=0.0,
        source_start_seconds=0.0,
        source_end_seconds=0.1,
    )
    timeline = Timeline(events=[event, event], total_duration_seconds=0.1)
    settings = ExportSettings(normalize_output=False, true_peak_limit_dbtp=-1.0)

    render_timeline(
        timeline,
        {"asset-a": str(source_path)},
        str(output_path),
        settings,
    )

    with wave.open(str(output_path), "rb") as rendered:
        assert rendered.getframerate() == 44100
        assert rendered.getnchannels() == 2
        assert rendered.getsampwidth() == 2

    audio = read_wav_float32(str(output_path))
    expected_limit = 10 ** (-1.0 / 20.0)
    peak = float(np.max(np.abs(audio)))
    assert expected_limit - 0.001 <= peak <= expected_limit + 0.001
