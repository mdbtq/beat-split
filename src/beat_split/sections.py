"""Section starts: beats where the music clearly re-enters after a break or an
interlude, so the beat count can restart there.

Per beat, the spectrum is summarised in 24 log-energy bands. A checkerboard
novelty curve (Foote 2000) over the beat-by-beat self-similarity marks beats
where the texture changes. A change is a section start when the beats after it
are clearly fuller than the beats before it: a break or interlude ending, not
one beginning. Break starts are left out on purpose; they are often a single
hit followed by silence, and their exact beat is hard to pin down.
"""
from __future__ import annotations

import numpy as np
from bpm_lock.audio_io import Audio
from scipy import signal

N_BANDS = 24
BAND_RANGE = (40.0, 10000.0)   # Hz
NOVELTY_BEATS = 4      # beats compared on each side of a candidate
PEAK_RADIUS = 4        # a candidate must be the novelty maximum within ± this many beats
PEAK_MADS = 4.0        # ... and stand this many median absolute deviations above the median
MIN_NOVELTY = 0.5      # ... and above this, so a very repetitive track yields nothing
MIN_LIFT = 0.3         # log10 energy units (3 dB) the beats after must exceed those before


def beat_features(audio: Audio, beats: np.ndarray) -> np.ndarray:
    """(beats, N_BANDS) mean log band energy per beat interval."""
    x = signal.resample_poly(audio.mono(), 1, 2)
    sr = audio.sample_rate / 2
    freqs, times, z = signal.stft(x, sr, nperseg=2048, noverlap=2048 - 512)
    power = np.abs(z) ** 2
    edges = np.geomspace(*BAND_RANGE, N_BANDS + 1)
    bands = np.log10(np.array([power[(freqs >= lo) & (freqs < hi)].sum(0)
                               for lo, hi in zip(edges[:-1], edges[1:])]) + 1e-9)
    bounds = np.append(beats, audio.duration)
    out = np.empty((len(beats), N_BANDS))
    for i in range(len(beats)):
        frames = (times >= bounds[i]) & (times < bounds[i + 1])
        out[i] = bands[:, frames].mean(1) if frames.any() else bands[:, np.argmin(
            np.abs(times - bounds[i]))]
    return out


def novelty(features: np.ndarray, side: int = NOVELTY_BEATS) -> np.ndarray:
    centred = features - features.mean(0)
    centred /= np.linalg.norm(centred, axis=1, keepdims=True) + 1e-9
    sim = centred @ centred.T
    out = np.zeros(len(features))
    for i in range(side, len(features) - side):
        within = (sim[i - side:i, i - side:i].mean() + sim[i:i + side, i:i + side].mean()) / 2
        out[i] = within - sim[i - side:i, i:i + side].mean()
    return out


def section_starts(features: np.ndarray) -> list[int]:
    """0-based beat indices where a fuller section starts."""
    side = NOVELTY_BEATS
    nov = novelty(features, side)
    median = np.median(nov)
    threshold = max(MIN_NOVELTY, median + PEAK_MADS * np.median(np.abs(nov - median)))
    starts = []
    for i in range(side, len(features) - side):
        if nov[i] < threshold or nov[i] < nov[max(0, i - PEAK_RADIUS):i + PEAK_RADIUS + 1].max():
            continue
        lift = features[i:i + side].mean() - features[i - side:i].mean()
        if lift >= MIN_LIFT:
            starts.append(i)
    return starts


def detect(audio: Audio, beats: np.ndarray) -> list[int]:
    return section_starts(beat_features(audio, beats)) if len(beats) > 2 * NOVELTY_BEATS else []
