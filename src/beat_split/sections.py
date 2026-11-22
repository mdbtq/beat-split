"""Section starts: beats where the music clearly re-enters after a break or an
interlude, so the beat count can restart there.

Per beat, the spectrum is summarised in 24 log-energy bands. A checkerboard
novelty curve (Foote 2000) over the beat-by-beat self-similarity marks beats
where the texture changes. A change is a section start when the beats after it
are clearly fuller than the beats before it: a break or interlude ending, not
one beginning. Break starts are left out on purpose; they are often a single
hit followed by silence, and their exact beat is hard to pin down.

The novelty peak itself is not always the section's first beat: a drum
lead-in into the section is already a texture change, so the peak can land on
the lead-in. Sections start on a bar line, so each start is moved to the
nearest bar line, counted from the first downbeat. For a peak halfway between
two bar lines, the count is worked back from the next section start: the bar
line from which a whole number of phrases (4 bars) fits up to it wins. Starts
are resolved from the end of the track, so the next one is already placed.
Without that evidence the later bar line wins, as the peak is typically a
lead-in (drums, or stabs at the end of a break). A section start off the bar
grid (an odd bar) is never found; restart the count by hand there.
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
PHRASE_BARS = 4        # bars per phrase, for working a start back from the next one


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


def section_starts(features: np.ndarray, downbeat: int = 0, bar: int = 4) -> list[int]:
    """0-based beat indices where a fuller section starts, on the bar grid of
    `bar` beats through the 0-based `downbeat`."""
    side = NOVELTY_BEATS
    nov = novelty(features, side)
    median = np.median(nov)
    threshold = max(MIN_NOVELTY, median + PEAK_MADS * np.median(np.abs(nov - median)))
    peaks = [i for i in range(side, len(features) - side)
             if nov[i] >= threshold
             and nov[i] >= nov[max(0, i - PEAK_RADIUS):i + PEAK_RADIUS + 1].max()
             and lift(features, i) >= MIN_LIFT]
    starts: list[int] = []
    for i in reversed(peaks):   # from the end, so the next start is already placed
        nxt = starts[-1] if starts else None
        starts.append(snap_to_bar(i, len(features), downbeat, bar, nxt, bar * PHRASE_BARS))
    return sorted(set(starts))


def lift(features: np.ndarray, beat: int, side: int = NOVELTY_BEATS) -> float:
    """How much fuller (log10 energy) the `side` beats from `beat` are than those before."""
    return float(features[beat:beat + side].mean() - features[max(0, beat - side):beat].mean())


def snap_to_bar(beat: int, n_beats: int, downbeat: int, bar: int,
                next_start: int | None = None, phrase: int = 16) -> int:
    """Move a section start to the nearest bar line. Halfway between two, take
    the one a whole number of phrases before `next_start`, else the later one."""
    earlier = beat - (beat - downbeat) % bar
    later = earlier + bar
    if earlier == beat or later >= n_beats:
        return earlier
    if 2 * (beat - earlier) != bar:
        return earlier if 2 * (beat - earlier) < bar else later
    if next_start is not None:
        fits = [c for c in (later, earlier) if (next_start - c) % phrase == 0]
        if len(fits) == 1:
            return fits[0]
    return later


def detect(audio: Audio, beats: np.ndarray, downbeat: int = 0, bar: int = 4) -> list[int]:
    if len(beats) <= 2 * NOVELTY_BEATS:
        return []
    return section_starts(beat_features(audio, beats), downbeat, bar)
