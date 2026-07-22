"""Data models mirroring the .cnc project JSON schema."""
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class AnalysisResult:
    """Optional per-asset analysis data. All fields include a confidence score."""
    bpm: Optional[dict] = None    # {"value": float, "confidence": float}
    key: Optional[dict] = None    # {"value": str,   "confidence": float}
    lufs: Optional[float] = None  # Integrated loudness (LUFS)
    energy: Optional[float] = None  # Normalized energy [0, 1]


@dataclass
class Asset:
    """A registered audio clip. The source file is never modified."""
    id: str
    name: str
    path: str                         # Relative to the .cnc file
    hash: str                         # sha256:... for integrity verification
    duration_seconds: float
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    format: Optional[str] = None      # e.g. "wav", "mp3"
    weight: float = 1.0               # Selection probability weight
    tags: List[str] = field(default_factory=list)
    analysis: Optional[AnalysisResult] = None


@dataclass
class ClipDuration:
    min_seconds: float
    max_seconds: float


@dataclass
class RepetitionParams:
    max_per_clip: Optional[int] = None  # None = unlimited
    min_gap_clips: int = 0              # Soft preference
    allow_consecutive: bool = False
    no_repeat_sections: bool = True     # Enforce non-overlapping source regions
    repeat_decay: float = 0.0           # [0,1] decay factor per repeat


@dataclass
class CrossfadeParams:
    enabled: bool = True
    min_seconds: float = 0.1
    max_seconds: float = 2.0
    probability: float = 0.8


@dataclass
class SilenceParams:
    enabled: bool = False
    probability: float = 0.3
    min_seconds: float = 0.2
    max_seconds: float = 2.0


@dataclass
class GainParams:
    normalize: bool = False
    target_lufs: float = -18.0
    max_gain_db: float = 12.0
    random_variation_db: float = 0.0


@dataclass
class SelectionParams:
    # "uniform" | "weighted" | "sequential"
    distribution: str = "uniform"
    chaos: float = 1.0  # 0 = most constrained, 1 = most random


@dataclass
class Parameters:
    target_duration_seconds: float
    clip_duration: ClipDuration
    repetition: RepetitionParams = field(default_factory=RepetitionParams)
    crossfade: CrossfadeParams = field(default_factory=CrossfadeParams)
    silence: SilenceParams = field(default_factory=SilenceParams)
    gain: GainParams = field(default_factory=GainParams)
    selection: SelectionParams = field(default_factory=SelectionParams)
    # "trim_last" | "fade_last" | "pad_silence" | "fill_random_clip" | "extend_last_clip"
    duration_rule: str = "fade_last"


@dataclass
class ClipEvent:
    """A clip placed on the timeline. All adjustments are non-destructive."""
    type: str  # always "clip"
    asset_id: str
    position_seconds: float      # Start of this event in the output track
    source_start_seconds: float  # Which part of the source file to use
    source_end_seconds: float
    gain_db: float = 0.0         # Applied at render time
    fade_in_seconds: float = 0.0
    fade_out_seconds: float = 0.0
    locked: bool = False         # Preserved during reroll


@dataclass
class SilenceEvent:
    type: str  # always "silence"
    position_seconds: float
    duration_seconds: float
    locked: bool = False


@dataclass
class Timeline:
    events: List  # List[ClipEvent | SilenceEvent], ordered by position_seconds
    total_duration_seconds: float


@dataclass
class ExportSettings:
    format: str = "wav"           # v0.2.1 renderer supports WAV only
    sample_rate: int = 44100
    bit_depth: int = 16
    normalize_output: bool = True
    target_output_lufs: float = -14.0  # Reserved for future measured LUFS support
    true_peak_limit_dbtp: float = -1.0  # Used as a sample-peak ceiling in v0.2.1


@dataclass
class Project:
    version: str
    project: dict  # {"name": str, "created_at": str, ...}
    assets: List[Asset]
    parameters: Parameters
    seed: str
    timeline: Optional[Timeline] = None
    export: ExportSettings = field(default_factory=ExportSettings)
