# beat-split

Splits audio tracks into chunks of a fixed number of beats: bars, 4-bar
phrases, 16-bar sections. It detects every beat first and stores them in a beat
map, so the intro, fills and breaks can be checked before cutting, and one map
can be applied to the stems of the analysed mix. Where a new section starts
after a break or an interlude of an odd number of beats, the count restarts
there by itself.

Beat tracking comes from [bpm-lock](https://github.com/mdbtq/bpm-lock).

## Requirements

- Python ≥ 3.10 (numpy, scipy and bpm-lock are installed automatically)
- `ffmpeg` / `ffprobe` on PATH (decoding/encoding any format)

## Install

```bash
uv tool install git+https://github.com/mdbtq/beat-split@v0.2.0
```

Or from a local checkout: `make build/install`.

## Usage

```bash
beat-split analyze track.wav                  # detect beats, write track.wav.beats.json
beat-split split track.wav -n 16              # 16-beat chunks (4 bars of 4/4)
beat-split analyze track.wav --downbeat 3     # beat 1 is a pickup: bars start on beat 3
beat-split split track.wav -n 16 -s 1 -s 0:42.3   # restart the count by hand
beat-split split track.wav -n 16 --no-sections     # count straight through
beat-split split stems/*.wav -n 16 -m track.wav.beats.json   # stems, cut like the mix
```

`split` uses `<file>.beats.json` when it exists and analyses the file first
when it does not (`--reanalyze` forces a new analysis).

### 1. Analyse

```
track.wav: 159.02 BPM, 790 beats, first beat 0:00.097, last beat 4:57.832, cuts +2 ms from the tracked beats, bars of 4 from beat 1
  lead-in          0:00.000-0:00.097
  section    33      0:12.153            new section: the count restarts here
  section    73      0:27.275            new section: the count restarts here
  rebuilt   216-219  1:21.223-1:22.361  fill or break: beats placed at the surrounding tempo
  section   297      1:51.785            new section: the count restarts here
  ...
  (20 shorter rebuilt stretches of 1-3 beats not listed; all beats are in the map)
  beat map: track.wav.beats.json
```

- `lead-in` – audio before the first beat.
- `section` – a beat where the music clearly re-enters after a break or an
  interlude: the beats after it are fuller than the beats before it. `split`
  restarts the count there (see [Section starts](#section-starts)).
- `rebuilt` – beats numbered 216 to 219, where the tracker found no reliable
  beat (a fill, a break, a pause) and placed beats at the surrounding tempo.
- `cuts ±N ms` – the tracker places beats a little before or after the actual
  attack, depending on the material. That offset is measured per track and
  applied, so every cut lands a few ms before an attack instead of inside one.
- `bars of 4 from beat 1` – the bar grid section starts are placed on. Set it
  with `--downbeat BEAT` (the first beat 1 of a bar, when the track starts
  with a pickup) and `--bar BEATS` (3 for 3/4, 6 for 6/8). `split` also counts
  from the downbeat.

The beat map is plain JSON: `beats` (cut points in seconds), `reliable` (false
for rebuilt beats), `sections` (beat numbers of section starts), `downbeat`,
`bar`, `tempo`, `offset` and the source's `duration`. `split` analyses a file
again when its map comes from an older version, or when `--downbeat`/`--bar`
differ from the map.

### 2. Split

```
track.wav: 54 chunks of 16 beats -> track_beats16
  000  0:00.000-0:00.097  lead-in
  001  0:00.097-0:06.137  beats 1-16
  002  0:06.137-0:12.153  beats 17-32
  003  0:12.153-0:18.215  beats 33-48  new section
  004  0:18.215-0:24.257  beats 49-64
  005  0:24.257-0:27.275  beats 65-72 (8 beats)
  006  0:27.275-0:33.301  beats 73-88  new section
  ...
  053  4:57.467-5:01.311  beats 789-790 (2 beats)
```

- Chunk `000` is the lead-in (left out when the first beat is at 0:00).
- Each section start and each `--start` begins a new count. The chunk just
  before it ends there and can be shorter, as can the last chunk, which runs
  to the end of the file. Shorter chunks show their beat count.
- `--start` takes a beat number (`33`) or a time (`1:02.5`, `62.5`), which
  snaps to the nearest beat. Use the beat numbers from the analysis.
- Splitting the same file into the same folder again replaces its earlier
  chunks; other files in the folder are left alone.
- Without `--fade` the chunks join back into the original sample for sample.
  `--fade MS` adds a short fade at each cut, for playing chunks on their own.

### Section starts

Breaks and interludes do not always last a whole number of chunks. In the
example, beats 65-72 are an 8-beat interlude ending in a 2-beat drum lead-in;
counting straight through would put it and the first 8 beats of the next
section in one chunk. Because a new section is detected at beat 73, chunk 005
stops after the lead-in and chunk 006 starts with the section.

A section start falling on the count changes nothing; one off the count
shortens the chunk before it. With `--start`, only section starts after the
first given start are used.

The detection compares the sound of each beat with its neighbours and marks a
beat where the texture changes and the 4 beats after it are clearly fuller (at
least 3 dB) than the 4 before: a break or interlude ending. The start of a
break is not marked. It is often a single hit followed by silence, and its
exact beat is hard to pin down.

That change often begins with a drum lead-in, a beat or two before the
section's first downbeat. Sections start on a bar line, so the detected beat
is moved to the nearest bar line of the bar grid. For one halfway between two
bar lines, the count is worked back from the next section start: the bar line
from which a whole number of 4-bar phrases (16 beats in 4/4) fits up to it
wins. In the example, a chorus whose drums wait one phrase is detected at beat
639; from 641 the count reaches the next section start (689) in exactly 3
phrases, from 637 it does not, so the chorus starts at 641. Without a next
section start to work back from, the later bar line wins, so a lead-in stays
at the end of the chunk before. As a result, a section that starts off the bar
grid, after an odd bar, is not found: restart the count there with `--start`.

Check the result by ear. Remove a wrong section start from `sections` in the
beat map, or add a missed one, and split again. `--no-sections` ignores them all.

### Stems

Cut stems with the beat map of the full mix (`-m`), so all stems get the same
cut points: a bass or pad stem cannot be beat-tracked reliably on its own. The
files must have the same length as the analysed mix (within 50 ms), which holds
for the output of [stem-split](https://github.com/mdbtq/stem-split).

### Equal-length chunks

Chunks follow the played tempo, so in a track without a click their lengths
differ slightly. For chunks of exactly equal length, lock the track to a fixed
tempo with bpm-lock first and split its output.

## Options

| Option | Default | Meaning |
|---|---|---|
| `-n, --beats` | – | Beats per chunk (required for `split`) |
| `-s, --start BEAT\|TIME` | downbeat | Beat to start counting from; repeat to restart the count |
| `--downbeat BEAT` | `1` | First downbeat: start of the bar grid and of the count (`analyze` and `split`) |
| `--bar BEATS` | `4` | Beats per bar for placing section starts (`analyze` and `split`) |
| `--no-sections` | off | Ignore detected section starts; count straight through |
| `-m, --map FILE` | `<file>.beats.json` | Beat map to use for all files |
| `--reanalyze` | off | Analyse again even if a beat map exists |
| `-o, --out-dir` | `<name>_beats<N>` next to the input | Output folder (one subfolder per file when several are given) |
| `-f, --format` | as input | `wav`, `flac`, `aiff`, `mp3`, `m4a`, `ogg` |
| `--fade MS` | `0` | Fade in/out at each cut |
| `-b, --bpm` | detected | Known tempo; narrows detection to ±10 % (`analyze` and `split`) |
| `--hint` | `120` | Detection prior when `--bpm` is not given |

## Architecture

```
cli ─► beatmap.analyse ─► bpm_lock.beats (tracker) + attack_offset
    │                    └► sections.detect (beat novelty + lift)     → BeatMap ⇄ JSON
    └► splitter.plan (beats, starts, size → chunks) ─► splitter.cut ─► bpm_lock.audio_io
```

## Notes

- The tracker does not know where a bar starts. Beat 1 is the first detected
  beat and is taken as the first downbeat; set another with `--downbeat`.
- Tempo detection assumes a duple meter, as in bpm-lock. For tracks with swing
  or an unusual meter, pass `--bpm`.
- mp3, m4a and ogg add encoder padding to each file, so those chunks do not
  join gaplessly. Use `-f wav` or `-f flac` for chunks you will put back
  together or loop.
- On dense mixes (distorted guitars throughout) the attack offset is harder to
  measure. It is then chosen on the early side: a cut a few ms early moves some
  tail of the previous beat into the chunk, a late one would split an attack.

## Tests

```bash
make test/all
```

Chunk planning, lossless cutting, a synthetic drum track on which every cut
must land within 15 ms before its attack, and one with a 6-beat interlude whose
re-entry after a 2-beat drum lead-in must be found on the exact bar line. The CLI tests need ffmpeg.

## License

MIT — see [LICENSE](LICENSE).
