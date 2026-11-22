"""Tempo map export: the beat map as a Standard MIDI File (type 0) with a tempo
change on every beat, the time signature and a marker per section, so a DAW's
grid follows a track that was not recorded to a click.

The tick of each beat is fixed (one quarter note per beat); the tempo between
two beats makes that tick land on the beat's time in the audio. Beat times are
smoothed first (bpm-lock's robust local fit) so detection jitter does not make
the grid wobble; the first downbeat keeps its detected time. Audio before the first downbeat becomes a pickup bar of
sixteenth notes, so bar 2 starts exactly on the downbeat.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np
from bpm_lock.beats import robust_smooth

from .beatmap import BeatMap

PPQ = 960                 # ticks per quarter note
MIN_LEAD_IN = 0.001       # seconds; a shorter lead-in is dropped (beat 1 at tick 0)
MAX_TEMPO_US = 0xFFFFFF   # largest tempo a MIDI tempo event can hold (µs per quarter)
SMOOTH_BEATS = 17       # beats in the smoothing window (about 4 bars)


@dataclass(frozen=True)
class Event:
    tick: int
    order: int      # sorts events on the same tick: time signature, tempo, marker
    data: bytes     # meta event: FF type length payload


def _meta(kind: int, payload: bytes) -> bytes:
    return bytes([0xFF, kind]) + _varlen(len(payload)) + payload


def _varlen(value: int) -> bytes:
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append(0x80 | (value & 0x7F))
        value >>= 7
    return bytes(reversed(out))


def _tempo(tick: int, seconds_per_quarter: float) -> Event:
    us = min(max(1, round(seconds_per_quarter * 1e6)), MAX_TEMPO_US)
    return Event(tick, 1, _meta(0x51, us.to_bytes(3, "big")))


def _time_signature(tick: int, numerator: int, denominator: int) -> Event:
    power = denominator.bit_length() - 1
    return Event(tick, 0, _meta(0x58, bytes([numerator, power, 24, 8])))


def _marker(tick: int, text: str) -> Event:
    return Event(tick, 2, _meta(0x06, text.encode("ascii", "replace")))


def smoothed_beats(m: BeatMap, window: int = SMOOTH_BEATS) -> np.ndarray:
    return robust_smooth(m.beats, window) if window > 0 else m.beats.copy()


def build(m: BeatMap, smooth: int = SMOOTH_BEATS) -> tuple[list[Event], np.ndarray]:
    """Meta events for the map, and the beat times they encode (seconds)."""
    beats = smoothed_beats(m, smooth)
    first = m.downbeat
    if len(beats) - first < 2:
        raise ValueError("need at least two beats from the downbeat on")
    beats[first] = m.beats[first]   # the fit is least certain at the edge; bar 2 starts here
    events: list[Event] = []

    lead_in = float(beats[first])
    tick = 0
    if lead_in >= MIN_LEAD_IN:
        sixteenth = (beats[first + 1] - beats[first]) / 4
        count = max(1, round(lead_in / sixteenth))      # pickup length in sixteenths
        full_bars, rest = divmod(count, m.bar * 4)
        if full_bars:
            events.append(_time_signature(0, m.bar, 4))
        if rest:
            events.append(_time_signature(full_bars * m.bar * PPQ, rest, 16))
        events.append(_tempo(0, lead_in / (count / 4)))
        tick = count * PPQ // 4
    events.append(_time_signature(tick, m.bar, 4))

    for i in range(first, len(beats) - 1):
        events.append(_tempo(tick + (i - first) * PPQ, beats[i + 1] - beats[i]))
    starts = [first] + [s for s in m.sections if s > first]
    for n, s in enumerate(starts, 1):
        events.append(_marker(tick + (s - first) * PPQ, f"Section {n} (beat {s + 1})"))

    # collapse tempo events that repeat the previous value
    out: list[Event] = []
    last_tempo = None
    for e in sorted(events, key=lambda e: (e.tick, e.order)):
        if e.data[1] == 0x51:
            if e.data == last_tempo:
                continue
            last_tempo = e.data
        out.append(e)
    return out, beats


def write(events: list[Event], end_tick: int, name: str) -> bytes:
    """A type 0 Standard MIDI File holding `events` and a track name."""
    body = bytearray(b"\x00" + _meta(0x03, name.encode("ascii", "replace")))
    previous = 0
    for e in events:
        body += _varlen(e.tick - previous) + e.data
        previous = e.tick
    body += _varlen(max(0, end_tick - previous)) + _meta(0x2F, b"")
    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, PPQ)
    return header + b"MTrk" + struct.pack(">I", len(body)) + bytes(body)


def export(m: BeatMap, smooth: int = SMOOTH_BEATS) -> tuple[bytes, np.ndarray]:
    events, beats = build(m, smooth)
    return write(events, max(e.tick for e in events) + PPQ, m.source), beats
