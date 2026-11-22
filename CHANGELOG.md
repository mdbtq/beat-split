# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [0.5.0] - 2026-11-22

### Added
- `export --reaper`: also writes `<name>.markers.lua`, a ReaScript that adds
  the section markers as REAPER project markers (REAPER keeps a MIDI file's
  markers inside the MIDI item), relative to the selected item's start.

## [0.4.0] - 2026-11-22

### Added
- `beat-split export`: writes `<name>.tempo.mid`, a MIDI tempo map with a
  tempo change on every beat (smoothed over `--smooth` beats, default 17), the
  time signature, a pickup bar for the audio before the first downbeat, and a
  marker at the downbeat and at each section start, so a DAW's grid follows the
  recording.

## [0.3.1] - 2026-11-22

### Fixed
- A section start halfway between two bar lines is worked back from the next
  section start: the bar line from which a whole number of 4-bar phrases fits
  up to it wins (later bar line otherwise). It used to fall back to the earlier
  bar line whenever the music was already full there, which put a chorus whose
  drums come in later 4 beats too early. Maps from 0.3.0 keep their old
  section starts until analysed again (`--reanalyze`).

## [0.3.0] - 2026-11-22

### Added
- `--downbeat BEAT` and `--bar BEATS` (`analyze` and `split`): the bar grid
  that section starts are placed on. `split` counts from the downbeat by
  default. Both are stored in the beat map.

### Changed
- Section starts land on a bar line. A drum lead-in into a section no longer
  starts the new chunk: a detected start halfway between two bar lines goes to
  the later one, so the lead-in stays at the end of the chunk before.
- Beat map format 3 adds `downbeat` and `bar`. `split` analyses files again
  whose map is older or was made with another `--downbeat`/`--bar`.

## [0.2.0] - 2026-11-20

### Added
- Section starts: `analyze` detects beats where the music clearly re-enters
  after a break or an interlude and lists them; `split` restarts the count
  there, so the chunk before ends early instead of mixing the interlude with
  the next section. Chunks that start a section are marked `new section`.
- `--no-sections` to count straight through.

### Changed
- Beat map format 2 adds `sections` (beat numbers, editable). `split` analyses
  files again whose map is format 1; `--map` with a format 1 map is rejected.

## [0.1.0] - 2026-11-20

### Added
- `beat-split analyze`: detects every beat with bpm-lock's tracker and writes
  `<file>.beats.json`. Prints the tempo, the lead-in and the stretches the
  tracker rebuilt (fills, breaks) with their beat numbers.
- `beat-split split -n N`: cuts files into chunks of N beats. Chunk `000` is
  the lead-in; `--start` (beat number or time, repeatable) begins a new count;
  shorter chunks before a start and at the end are kept and reported.
- Cut points are moved onto the attacks: the tracker's per-track offset is
  measured and applied, leaning early so no attack is split.
- `--map` applies one beat map to several files (stems of the analysed mix);
  files whose length differs from the map's source are rejected.
- Without `--fade` the chunks join back into the original sample for sample.
- `-o`, `-f`, `--fade`, `--reanalyze`, `--bpm`, `--hint`.
