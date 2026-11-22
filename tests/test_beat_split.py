"""Tests: chunk planning, lossless cutting, beat tracking on a synthetic drum track,
and the CLI end to end (needs ffmpeg on PATH)."""
from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
from bpm_lock import audio_io
from bpm_lock.audio_io import Audio

from beat_split import beatmap, sections, splitter
from beat_split.cli import main

SR = 44100


def drum_track(bpm: float = 128.0, lead_in: float = 1.0, duration: float = 24.0,
               interlude: range = range(0), fill: range = range(0)) -> tuple[Audio, np.ndarray]:
    """Kick on 1+3, snare on 2+4, 8th hats and offbeat bass after a quiet lead-in;
    only soft hats on the 0-based beats in `interlude`, a drums-only 16th-note
    snare fill on those in `fill`.
    Returns (audio, beat times)."""
    rng = np.random.default_rng(1)
    y = np.zeros(int(duration * SR), np.float32)
    n = np.arange(int(0.2 * SR)) / SR
    kick = np.sin(2 * np.pi * (50 + 120 * np.exp(-n * 30)) * n) * np.exp(-n * 12)
    snare = rng.standard_normal(len(n)) * np.exp(-n * 25) * 0.5
    hat = rng.standard_normal(int(0.03 * SR)) * np.exp(-np.arange(int(0.03 * SR)) / SR * 120) * 0.2
    bass = np.sin(2 * np.pi * 55 * n) * np.exp(-n * 8) * 0.4

    def add(x: np.ndarray, at: float) -> None:
        s = int(at * SR)
        e = min(len(y), s + len(x))
        y[s:e] += x[: e - s]

    beats = np.arange(lead_in, duration - 0.5, 60 / bpm)
    for i, t in enumerate(beats):
        if i in interlude:
            add(hat * 0.5, t)
            continue
        if i in fill:
            for k in range(4):
                add(snare * 0.8, t + k * 15 / bpm)
            continue
        add(kick if i % 2 == 0 else snare, t)
        add(hat, t)
        add(hat * 0.6, t + 30 / bpm)
        add(bass, t + 30 / bpm)
    y[: int(lead_in * SR)] += rng.standard_normal(int(lead_in * SR)).astype(np.float32) * 0.002
    stereo = np.stack([y, y * 0.9]) * 0.5
    return Audio(stereo.astype(np.float32), SR), beats


class PlanTest(unittest.TestCase):
    beats = np.arange(1.0, 11.0, 0.5)   # 20 beats, first at 1.0 s

    def test_chunks_cover_file_without_gaps(self):
        chunks = splitter.plan(self.beats, 12.0, 4, [])
        self.assertEqual(chunks[0].start, 0.0)
        self.assertTrue(chunks[0].is_lead_in)
        self.assertEqual(chunks[-1].end, 12.0)
        for a, b in zip(chunks, chunks[1:]):
            self.assertEqual(a.end, b.start)
        self.assertEqual([c.beats for c in chunks[1:]], [4] * 5)
        self.assertEqual([c.first_beat for c in chunks[1:]], [1, 5, 9, 13, 17])

    def test_last_chunk_may_be_partial(self):
        chunks = splitter.plan(self.beats, 12.0, 8, [])
        self.assertEqual([c.beats for c in chunks[1:]], [8, 8, 4])

    def test_start_beat_moves_lead_in(self):
        chunks = splitter.plan(self.beats, 12.0, 4, [2])
        self.assertEqual(chunks[0].end, 2.0)        # lead-in up to beat 3
        self.assertEqual(chunks[1].first_beat, 3)

    def test_second_start_restarts_count(self):
        # beats 1-6 counted from 1, then a fresh count from beat 7 (after a 6-beat bar)
        chunks = splitter.plan(self.beats, 12.0, 4, [0, 6])
        self.assertEqual([(c.first_beat, c.beats) for c in chunks[1:]],
                         [(1, 4), (5, 2), (7, 4), (11, 4), (15, 4), (19, 2)])

    def test_no_lead_in_when_first_beat_at_zero(self):
        chunks = splitter.plan(np.arange(0.0, 4.0, 0.5), 4.0, 4, [])
        self.assertFalse(chunks[0].is_lead_in)
        self.assertEqual(chunks[0].start, 0.0)

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            splitter.plan(self.beats, 12.0, 0, [])
        with self.assertRaises(ValueError):
            splitter.plan(self.beats, 12.0, 4, [len(self.beats)])


class CutTest(unittest.TestCase):
    def test_chunks_concatenate_to_original(self):
        audio, beats = drum_track(duration=8.0)
        chunks = splitter.plan(beats, audio.duration, 3, [])
        joined = np.concatenate([splitter.cut(audio, c).samples for c in chunks], axis=1)
        np.testing.assert_array_equal(joined, audio.samples)

    def test_fade_silences_the_edges(self):
        audio = Audio(np.ones((2, SR), np.float32), SR)
        out = splitter.cut(audio, splitter.Chunk(1, 0.0, 1.0, 1, 4), fade_ms=10)
        self.assertEqual(out.samples[0, 0], 0.0)
        self.assertLess(out.samples[0, -1], 0.01)
        self.assertEqual(out.samples[0, SR // 2], 1.0)


class SectionTest(unittest.TestCase):
    def test_section_starts_after_drum_lead_in(self):
        # 32 beats, a 6-beat interlude (33-38), a 2-beat snare fill (39-40), section from 41
        audio, truth = drum_track(duration=36.0, interlude=range(32, 38), fill=range(38, 40))
        m = beatmap.analyse(audio, "song.wav")
        self.assertEqual(len(m.beats), len(truth))
        self.assertEqual(list(m.sections), [40])
        chunks = splitter.plan(m.beats, audio.duration, 16, [0, *m.sections])
        self.assertEqual([(c.first_beat, c.beats) for c in chunks[1:4]],
                         [(1, 16), (17, 16), (33, 8)])
        self.assertEqual(chunks[4].first_beat, 41)

    def test_snaps_to_nearest_bar_line(self):
        loud = np.ones((40, 3))
        loud[:28] = 0.0                                            # full from beat 29 on
        self.assertEqual(sections.snap_to_bar(29, loud, 0, 4), 28)    # one past a bar line
        self.assertEqual(sections.snap_to_bar(31, loud, 0, 4), 32)    # one before
        self.assertEqual(sections.snap_to_bar(30, loud, 2, 4), 30)    # on the bar from beat 3
        # halfway: the later bar line (lead-in), unless the music is already full there
        self.assertEqual(sections.snap_to_bar(30, loud, 0, 4), 28)
        rising = np.zeros((40, 3))
        rising[32:] = 1.0
        self.assertEqual(sections.snap_to_bar(30, rising, 0, 4), 32)

    def test_steady_track_has_no_sections(self):
        audio, _ = drum_track()
        self.assertEqual(beatmap.analyse(audio, "loop.wav").sections, ())


class BeatMapTest(unittest.TestCase):
    def test_tracks_every_beat_before_its_attack(self):
        audio, truth = drum_track()
        m = beatmap.analyse(audio, "drums.wav")
        self.assertEqual(len(m.beats), len(truth))
        lead = (truth - m.beats) * 1000
        # cuts must land just before each attack, never inside it
        self.assertTrue(np.all(lead > -2), f"cut after attack: {lead.min():.1f} ms")
        self.assertTrue(np.all(lead < 15), f"cut far before attack: {lead.max():.1f} ms")

    def test_round_trip(self):
        m = beatmap.BeatMap("x.wav", 10.0, 120.0, np.array([0.5, 1.0, 1.5]),
                            np.array([True, False, True]), 0.01, (2,))
        data = m.to_dict()
        self.assertEqual(data["sections"], [3])        # stored as beat numbers
        again = beatmap.BeatMap.from_dict(data)
        np.testing.assert_array_equal(again.beats, m.beats)
        self.assertEqual(again.sections, (2,))
        self.assertEqual(again.rebuilt_runs(), [(1, 1)])

    def test_rejects_unsorted_beats(self):
        with self.assertRaises(ValueError):
            beatmap.BeatMap.from_dict({"format": 3, "source": "x", "duration": 2, "tempo": 120,
                                       "beats": [1.0, 0.5]})

    def test_old_format_asks_for_new_analysis(self):
        with self.assertRaises(beatmap.FormatError):
            beatmap.BeatMap.from_dict({"format": 2, "source": "x", "duration": 2, "tempo": 120,
                                       "beats": [0.5, 1.0]})


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class CliTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        audio, self.truth = drum_track()
        self.src = self.dir / "loop.wav"
        audio_io.write(self.src, audio)

    def run_cli(self, *args: str) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(main([str(a) for a in args]), 0)
        return buf.getvalue()

    def test_analyze_then_split_into_bars(self):
        self.run_cli("analyze", self.src)
        self.assertTrue((self.dir / "loop.wav.beats.json").exists())
        out = self.run_cli("split", self.src, "-n", 4)
        files = sorted((self.dir / "loop_beats4").iterdir())
        self.assertEqual(files[0].name, "loop_000.wav")     # lead-in
        self.assertEqual(len(files), 1 + int(np.ceil(len(self.truth) / 4)))
        self.assertIn("lead-in", out)
        # 4 beats at 128 BPM
        bar = audio_io.read(files[2])
        self.assertAlmostEqual(bar.duration, 4 * 60 / 128, delta=0.01)

    def test_shared_map_for_stems(self):
        self.run_cli("analyze", self.src)
        stem = self.dir / "bass.wav"
        shutil.copy(self.src, stem)
        self.run_cli("split", stem, "-n", 16, "--map", self.dir / "loop.wav.beats.json",
                     "-s", "0:05", "-f", "flac")
        files = sorted((self.dir / "bass_beats16").iterdir())
        self.assertTrue(all(f.suffix == ".flac" for f in files))
        self.assertFalse((self.dir / "bass.wav.beats.json").exists())

    def test_resplit_replaces_earlier_chunks(self):
        self.run_cli("split", self.src, "-n", 4)
        keep = self.dir / "loop_beats4" / "notes.txt"
        keep.write_text("mine")
        out = self.run_cli("split", self.src, "-n", 4, "-s", 9)
        chunks = [f for f in (self.dir / "loop_beats4").iterdir() if f.suffix == ".wav"]
        self.assertEqual(len(chunks), len(out.splitlines()) - 1)
        self.assertTrue(keep.exists())

    def test_split_restarts_count_at_section(self):
        audio, _ = drum_track(duration=36.0, interlude=range(32, 38), fill=range(38, 40))
        src = self.dir / "song.wav"
        audio_io.write(src, audio)
        out = self.run_cli("split", src, "-n", 16)
        self.assertIn("beats 33-40 (8 beats)", out)
        self.assertIn("beats 41-56  new section", out)
        out = self.run_cli("split", src, "-n", 16, "--no-sections")
        self.assertIn("beats 33-48", out)

    def test_downbeat_moves_count_and_bar_lines(self):
        out = self.run_cli("split", self.src, "-n", 4, "--downbeat", 3)
        self.assertIn("beats 3-6", out)
        self.assertIn("bars of 4 from beat 3", out)
