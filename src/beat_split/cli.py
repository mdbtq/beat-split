"""Command line interface: beat-split analyze|split <files> [options]."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np

from bpm_lock import audio_io

from . import __version__, beatmap, splitter, tempomap
from .beatmap import BeatMap

FORMATS = ("wav", "flac", "aiff", "mp3", "m4a", "ogg")
MAX_DURATION_MISMATCH = 0.05  # seconds a file may differ from the map's source
MERGE_GAP = 2     # rebuilt runs at most this many beats apart are listed as one
MIN_LISTED = 4    # shorter rebuilt runs are counted, not listed


def _clock(seconds: float) -> str:
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:06.3f}"


def _parse_start(value: str, beat_map: BeatMap) -> int:
    """'33' is beat 33; '1:02.5' or '62.5' is the beat nearest to that time."""
    if value.isdigit():
        beat = int(value)
        if not 1 <= beat <= len(beat_map.beats):
            raise ValueError(f"--start {value}: the map has beats 1-{len(beat_map.beats)}")
        return beat - 1
    try:
        minutes, _, seconds = value.rpartition(":")
        t = float(seconds) + 60 * float(minutes or 0)
    except ValueError:
        raise ValueError(f"--start {value}: expected a beat number or a time such as 1:02.5")
    return beat_map.nearest_beat(t)


def _rebuilt_stretches(m: BeatMap) -> tuple[list[tuple[int, int]], int]:
    """Rebuilt runs worth checking: runs closer than MERGE_GAP beats are joined,
    and runs shorter than MIN_LISTED beats (tracker hiccups) are only counted."""
    merged: list[tuple[int, int]] = []
    for first, last in m.rebuilt_runs():
        if merged and first - merged[-1][1] - 1 <= MERGE_GAP:
            merged[-1] = (merged[-1][0], last)
        else:
            merged.append((first, last))
    shown = [r for r in merged if r[1] - r[0] + 1 >= MIN_LISTED]
    return shown, len(merged) - len(shown)


def _overview(name: str, m: BeatMap) -> str:
    lines = [f"{name}: {m.tempo:.2f} BPM, {len(m.beats)} beats, "
             f"first beat {_clock(m.beats[0])}, last beat {_clock(m.beats[-1])}, "
             f"cuts {m.offset * 1000:+.0f} ms from the tracked beats, "
             f"bars of {m.bar} from beat {m.downbeat + 1}"]
    if m.beats[0] >= splitter.MIN_LEAD_IN:
        lines.append(f"  lead-in          {_clock(0)}-{_clock(m.beats[0])}")
    shown, hidden = _rebuilt_stretches(m)
    rows = [(first, f"  rebuilt  {first + 1:>4}-{last + 1:<4} {_clock(m.beats[first])}-"
                    f"{_clock(m.beats[last])}  fill or break: beats placed at the "
                    f"surrounding tempo") for first, last in shown]
    rows += [(i, f"  section  {i + 1:>4}      {_clock(m.beats[i])}  "
                 f"{' ' * 10}new section: the count restarts here") for i in m.sections]
    lines += [text for _, text in sorted(rows)]
    if hidden:
        lines.append(f"  ({hidden} shorter rebuilt stretches of 1-{MIN_LISTED - 1} beats "
                     f"not listed; all beats are in the map)")
    return "\n".join(lines)


def _analyse(path: Path, args) -> BeatMap:
    downbeat = (args.downbeat or 1) - 1
    beat_map = beatmap.analyse(audio_io.read(path), path.name, args.bpm, args.hint,
                               downbeat, args.bar or 4)
    out = beatmap.default_path(path)
    beatmap.save(beat_map, out)
    print(_overview(path.name, beat_map))
    print(f"  beat map: {out}")
    return beat_map


def cmd_analyze(args) -> int:
    failed = 0
    for path in args.files:
        try:
            _analyse(path, args)
        except Exception as exc:  # report and continue with the next file
            print(f"{path}: {exc}", file=sys.stderr)
            failed += 1
    return 1 if failed else 0


def _grid_differs(m: BeatMap, args) -> bool:
    """--downbeat or --bar given and not what the map was analysed with."""
    return bool((args.downbeat and args.downbeat - 1 != m.downbeat)
                or (args.bar and args.bar != m.bar))


def _map_for(path: Path, args) -> BeatMap:
    if args.map:
        m = beatmap.load(args.map)
        if _grid_differs(m, args):
            raise ValueError(f"{args.map.name} was analysed with bars of {m.bar} from beat "
                             f"{m.downbeat + 1}; analyse the mix again with --downbeat/--bar")
        return m
    existing = beatmap.default_path(path)
    if existing.exists() and not args.reanalyze:
        try:
            m = beatmap.load(existing)
        except beatmap.FormatError:
            print(f"{existing.name}: written by an older version, analysing again")
        else:
            if not _grid_differs(m, args):
                return m
            print(f"{existing.name}: other --downbeat/--bar, analysing again")
    return _analyse(path, args)


def _split_one(path: Path, args) -> None:
    beat_map = _map_for(path, args)
    audio = audio_io.read(path)
    if abs(audio.duration - beat_map.duration) > MAX_DURATION_MISMATCH:
        raise ValueError(f"is {audio.duration:.3f} s long, but the beat map of "
                         f"{beat_map.source} covers {beat_map.duration:.3f} s")
    starts = [_parse_start(s, beat_map) for s in args.start] or [beat_map.downbeat]
    sections = [] if args.no_sections else [i for i in beat_map.sections if i > min(starts)]
    chunks = splitter.plan(beat_map.beats, audio.duration, args.beats, starts + sections)

    ext = f".{args.format}" if args.format else path.suffix
    out_dir = args.out_dir or path.parent / f"{path.stem}_beats{args.beats}"
    if args.out_dir and len(args.files) > 1:
        out_dir = out_dir / path.stem
    width = max(3, len(str(chunks[-1].index)))
    written = set()
    for chunk in chunks:
        dst = out_dir / f"{path.stem}_{chunk.index:0{width}d}{ext}"
        audio_io.write(dst, splitter.cut(audio, chunk, args.fade))
        written.add(dst)
    # chunks of an earlier split of this file into the same folder would mix in
    stale = re.compile(rf"{re.escape(path.stem)}_\d{{3,}}{re.escape(ext)}")
    for old in out_dir.iterdir():
        if old not in written and stale.fullmatch(old.name):
            old.unlink()

    print(f"{path.name}: {len(chunks)} chunks of {args.beats} beats -> {out_dir}")
    for chunk in chunks:
        if chunk.is_lead_in:
            label = "lead-in"
        else:
            label = f"beats {chunk.first_beat}-{chunk.first_beat + chunk.beats - 1}"
            if chunk.beats != args.beats:
                label += f" ({chunk.beats} beats)"
            if chunk.first_beat - 1 in sections:
                label += "  new section"
        print(f"  {chunk.index:0{width}d}  {_clock(chunk.start)}-{_clock(chunk.end)}  {label}")


def cmd_split(args) -> int:
    failed = 0
    for path in args.files:
        try:
            _split_one(path, args)
        except Exception as exc:  # report and continue with the next file
            print(f"{path}: {exc}", file=sys.stderr)
            failed += 1
    return 1 if failed else 0


def _export_one(path: Path, args) -> None:
    beat_map = _map_for(path, args)
    data, beats = tempomap.export(beat_map, args.smooth)
    out = (args.out_dir or path.parent) / f"{path.stem}.tempo.mid"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    bpm = 60 / np.diff(beats[beat_map.downbeat:])
    markers = len(tempomap.marker_beats(beat_map))
    print(f"{path.name}: tempo map {bpm.min():.1f}-{bpm.max():.1f} BPM over "
          f"{len(beats) - beat_map.downbeat} beats, bars of {beat_map.bar} from beat "
          f"{beat_map.downbeat + 1}, {markers} section markers -> {out}")
    if args.reaper:
        script = out.with_name(f"{path.stem}.markers.lua")
        script.write_text(tempomap.reaper_script(beat_map, beats))
        print(f"  REAPER project markers: {script}")


def cmd_export(args) -> int:
    failed = 0
    for path in args.files:
        try:
            _export_one(path, args)
        except Exception as exc:  # report and continue with the next file
            print(f"{path}: {exc}", file=sys.stderr)
            failed += 1
    return 1 if failed else 0


def _add_tracking(p: argparse.ArgumentParser) -> None:
    p.add_argument("-b", "--bpm", type=float, help="known tempo; narrows detection to ±10%%")
    p.add_argument("--hint", type=float, default=120.0,
                   help="detection prior when --bpm is not given (default 120)")
    p.add_argument("--downbeat", type=int, metavar="BEAT",
                   help="beat number of the first downbeat (default 1); bar lines for "
                        "section starts are counted from it, and split counts from it")
    p.add_argument("--bar", type=int, metavar="BEATS",
                   help="beats per bar (default 4); section starts land on bar lines")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="beat-split", description="Split audio tracks into chunks of a fixed number of beats.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    an = sub.add_parser("analyze", help="detect all beats and write <file>.beats.json")
    an.add_argument("files", nargs="+", type=Path)
    _add_tracking(an)
    an.set_defaults(func=cmd_analyze)

    sp = sub.add_parser("split", help="cut files into chunks of N beats")
    sp.add_argument("files", nargs="+", type=Path)
    sp.add_argument("-n", "--beats", type=int, required=True, help="beats per chunk")
    sp.add_argument("-s", "--start", action="append", default=[], metavar="BEAT|TIME",
                    help="beat to start counting from: a beat number (33) or a time "
                         "(1:02.5) that snaps to the nearest beat; repeat to restart "
                         "the count by hand (default: the downbeat, beat 1)")
    sp.add_argument("--no-sections", action="store_true",
                    help="ignore the section starts in the beat map; count straight through")
    sp.add_argument("-m", "--map", type=Path,
                    help="beat map to use for all files, e.g. the mix's map for its stems")
    sp.add_argument("--reanalyze", action="store_true",
                    help="track again even if <file>.beats.json exists")
    sp.add_argument("-o", "--out-dir", type=Path,
                    help="output folder (default: <name>_beats<N> next to the input)")
    sp.add_argument("-f", "--format", choices=FORMATS, help="output format (default: as input)")
    sp.add_argument("--fade", type=float, default=0.0, metavar="MS",
                    help="fade in/out at each cut (default 0: chunks join back losslessly)")
    _add_tracking(sp)
    sp.set_defaults(func=cmd_split)

    ex = sub.add_parser("export", help="write a MIDI tempo map with section markers for a DAW")
    ex.add_argument("files", nargs="+", type=Path)
    ex.add_argument("-m", "--map", type=Path, help="beat map to use instead of <file>.beats.json")
    ex.add_argument("--reanalyze", action="store_true",
                    help="track again even if <file>.beats.json exists")
    ex.add_argument("-o", "--out-dir", type=Path,
                    help="output folder (default: next to the input, <name>.tempo.mid)")
    ex.add_argument("--smooth", type=int, default=tempomap.SMOOTH_BEATS, metavar="BEATS",
                    help="beats in the tempo smoothing window (default 17; 0 = follow every "
                         "detected beat, including its jitter)")
    ex.add_argument("--reaper", action="store_true",
                    help="also write <name>.markers.lua, a ReaScript that adds the section "
                         "markers as REAPER project markers")
    _add_tracking(ex)
    ex.set_defaults(func=cmd_export)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
