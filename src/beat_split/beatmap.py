"""Beat map: every beat of a track, detected once and stored as JSON next to it.

Splitting reads the map instead of tracking again, so the map can be inspected
first (intro, fills, breaks) and reused for files that share the timing, such
as the stems of the analysed mix.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import signal
from bpm_lock.audio_io import Audio
from bpm_lock.beats import DynamicProgrammingBeatTracker, TrackerConfig

FORMAT = 1
SUFFIX = ".beats.json"
NARROW = 1.10   # tracking range around a given tempo, as in bpm-lock


@dataclass(frozen=True)
class BeatMap:
    source: str             # file name of the analysed audio
    duration: float         # seconds
    tempo: float            # global tempo estimate (BPM)
    beats: np.ndarray       # beat times in seconds, ascending
    reliable: np.ndarray    # bool per beat; False where a fill or break was rebuilt
    offset: float = 0.0     # seconds added to the tracked beats to reach the attacks

    def rebuilt_runs(self) -> list[tuple[int, int]]:
        """(first, last) 0-based beat indices of each stretch rebuilt by the tracker."""
        runs, start = [], None
        for i, ok in enumerate(self.reliable):
            if not ok and start is None:
                start = i
            elif ok and start is not None:
                runs.append((start, i - 1))
                start = None
        if start is not None:
            runs.append((start, len(self.reliable) - 1))
        return runs

    def nearest_beat(self, seconds: float) -> int:
        return int(np.argmin(np.abs(self.beats - seconds)))

    def to_dict(self) -> dict:
        return {"format": FORMAT, "source": self.source, "duration": round(self.duration, 6),
                "tempo": round(self.tempo, 3), "offset": round(self.offset, 4),
                "beats": [round(float(t), 6) for t in self.beats],
                "reliable": [bool(r) for r in self.reliable]}

    @classmethod
    def from_dict(cls, data: dict) -> "BeatMap":
        if data.get("format") != FORMAT:
            raise ValueError(f"unsupported beat map format: {data.get('format')!r}")
        beats = np.asarray(data["beats"], dtype=float)
        reliable = np.asarray(data.get("reliable", [True] * len(beats)), dtype=bool)
        if len(beats) != len(reliable):
            raise ValueError("beat map: 'beats' and 'reliable' differ in length")
        if len(beats) == 0 or np.any(np.diff(beats) <= 0):
            raise ValueError("beat map: 'beats' must be a non-empty, ascending list")
        return cls(data["source"], float(data["duration"]), float(data["tempo"]), beats, reliable,
                   float(data.get("offset", 0.0)))


def default_path(audio_path: Path) -> Path:
    return audio_path.with_name(audio_path.name + SUFFIX)


def save(beat_map: BeatMap, path: Path) -> None:
    path.write_text(json.dumps(beat_map.to_dict(), indent=1) + "\n")


def load(path: Path) -> BeatMap:
    return BeatMap.from_dict(json.loads(path.read_text()))


def analyse(audio: Audio, source: str, bpm: float | None = None,
            hint: float = 120.0) -> BeatMap:
    """Track every beat with bpm-lock's tracker and move it onto the attack.

    The tracked hit positions (`repaired`) are used, not the smoothed tempo
    curve, which can sit up to ~30 ms off a hit. The tracker places hits a
    track-dependent 0-40 ms before the attack, so that lag is measured and added
    (see `attack_offset`); the stored beats are the cut points.
    """
    if bpm:
        config = TrackerConfig(bpm_hint=bpm, bpm_min=bpm / NARROW, bpm_max=bpm * NARROW)
    else:
        config = TrackerConfig(bpm_hint=hint)
    mono = audio.mono()
    result = DynamicProgrammingBeatTracker(config).track(mono, audio.sample_rate)
    beats = result.repaired
    offset = attack_offset(mono, audio.sample_rate, beats[result.reliable])
    beats = beats + offset
    keep = (beats >= 0) & (beats < audio.duration)
    return BeatMap(source, audio.duration, float(result.tempo), beats[keep],
                   result.reliable[keep], offset)


ATTACK_WINDOW = (0.05, 0.10)   # seconds searched before/after a tracked beat
ATTACK_RANGE = (-0.03, 0.045)  # offsets outside this are measurement errors
ATTACK_MARGIN = 0.005          # cut this far before the measured attack


def attack_offset(mono: np.ndarray, sample_rate: int, beats: np.ndarray) -> float:
    """Seconds to add to tracked beats so cuts land just before the attacks.

    Averages the log energy (above 200 Hz, 1 ms frames) around the reliable
    beats and takes its steepest rise as the attack. Everything leans early: a
    cut a few ms early only moves some tail of the previous beat into the
    chunk, a late one splits an attack. So the attack is measured on all beats
    and on the even and odd beats separately (on dense mixes they can disagree
    by tens of ms) and the earliest is used, minus a margin, clamped.
    """
    sos = signal.butter(2, 200, "highpass", fs=sample_rate, output="sos")
    energy = signal.sosfiltfilt(sos, mono) ** 2
    hop = sample_rate / 1000
    frames = int(len(energy) / hop)
    edges = np.round(np.arange(frames + 1) * hop).astype(int)
    log_e = np.log10(np.add.reduceat(energy, edges[:-1]) / np.diff(edges) + 1e-10)

    before, after = (int(w * 1000) for w in ATTACK_WINDOW)
    centres = np.round(beats * 1000).astype(int)
    centres = centres[(centres > before) & (centres < frames - after)]
    if len(centres) < 16:
        return 0.0

    def attack(subset: np.ndarray) -> float:
        average = np.mean([log_e[c - before:c + after] for c in subset], axis=0)
        return (int(np.argmax(np.diff(average))) + 1 - before) / 1000

    earliest = min(attack(centres), attack(centres[::2]), attack(centres[1::2]))
    return float(np.clip(earliest - ATTACK_MARGIN, *ATTACK_RANGE))
