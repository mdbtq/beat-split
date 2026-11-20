# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

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
