"""Chunk planning and cutting. Pure functions on beat times and sample arrays."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from bpm_lock.audio_io import Audio

MIN_LEAD_IN = 0.001  # seconds; a shorter lead-in is folded into the first chunk


@dataclass(frozen=True)
class Chunk:
    index: int          # 0 = lead-in before the first start beat, then 1, 2, ...
    start: float        # seconds
    end: float          # seconds
    first_beat: int     # 1-based beat number of its first beat; 0 for the lead-in
    beats: int          # beats it contains (0 for the lead-in)

    @property
    def is_lead_in(self) -> bool:
        return self.index == 0


def plan(beats: np.ndarray, duration: float, size: int, starts: list[int]) -> list[Chunk]:
    """Cut every `size` beats, counting from each start beat (0-based indices).

    Every start beat begins a new count, so a break with an odd number of beats
    can be followed by a fresh start. The chunk before a start beat ends there
    and may be shorter than `size`, as may the last chunk; the last chunk runs
    to the end of the file. Audio before the first start beat is the lead-in.
    Consecutive chunks cover the file without gaps or overlap.
    """
    if size < 1:
        raise ValueError("beats per chunk must be at least 1")
    starts = sorted(set(starts)) or [0]
    if starts[0] < 0 or starts[-1] >= len(beats):
        raise ValueError(f"start beats must lie between 1 and {len(beats)}")

    firsts: list[int] = []
    for k, start in enumerate(starts):
        stop = starts[k + 1] if k + 1 < len(starts) else len(beats)
        firsts += range(start, stop, size)

    chunks = []
    lead_in_end = float(beats[firsts[0]])
    has_lead_in = lead_in_end >= MIN_LEAD_IN
    if has_lead_in:
        chunks.append(Chunk(0, 0.0, lead_in_end, 0, 0))
    for n, first in enumerate(firsts):
        nxt = firsts[n + 1] if n + 1 < len(firsts) else len(beats)
        start = float(beats[first]) if n or has_lead_in else 0.0
        end = float(beats[nxt]) if nxt < len(beats) else duration
        chunks.append(Chunk(n + 1, start, end, first + 1, nxt - first))
    return chunks


def cut(audio: Audio, chunk: Chunk, fade_ms: float = 0.0) -> Audio:
    """The samples of one chunk. Boundaries round to the nearest sample, so
    consecutive chunks share each boundary and concatenate to the original."""
    a = round(chunk.start * audio.sample_rate)
    b = min(round(chunk.end * audio.sample_rate), audio.frames)
    samples = audio.samples[:, a:b].copy()
    fade = min(int(fade_ms * audio.sample_rate / 1000), samples.shape[1] // 2)
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade, endpoint=False, dtype=samples.dtype)
        samples[:, :fade] *= ramp
        samples[:, -fade:] *= ramp[::-1]
    return Audio(samples, audio.sample_rate)
