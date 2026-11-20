# beat-split

Splits audio tracks into chunks of a fixed number of beats: bars, 4-bar
phrases, 16-bar sections. It detects every beat first and stores them in a beat
map, so the intro, fills and breaks can be checked before cutting, and one map
can be applied to the stems of the analysed mix.

Beat tracking comes from [bpm-lock](https://github.com/mdbtq/bpm-lock).

## Requirements

- Python ≥ 3.10 (numpy, scipy and bpm-lock are installed automatically)
- `ffmpeg` / `ffprobe` on PATH (decoding/encoding any format)

## Install

```bash
uv tool install git+https://github.com/mdbtq/beat-split@v0.1.0
```

Or from a local checkout: `make build/install`.

## Usage

```bash
beat-split analyze track.wav                  # detect beats, write track.wav.beats.json
beat-split split track.wav -n 16              # 16-beat chunks (4 bars of 4/4)
beat-split split track.wav -n 4 -s 9          # count from beat 9 (the first downbeat)
beat-split split track.wav -n 16 -s 1 -s 0:42.3   # restart the count after a break
beat-split split stems/*.wav -n 16 -m track.wav.beats.json   # stems, cut like the mix
```

`split` uses `<file>.beats.json` when it exists and analyses the file first
when it does not (`--reanalyze` forces a new analysis).

### 1. Analyse

```
track.wav: 160.43 BPM, 790 beats, first beat 0:00.103, last beat 4:56.109, cuts +8 ms from the tracked beats
  lead-in          0:00.000-0:00.103
  rebuilt   291-296  1:50.407-1:52.266  fill or break: beats placed at the surrounding tempo
  rebuilt   394-401  2:29.123-2:31.743  fill or break: beats placed at the surrounding tempo
  (10 shorter rebuilt stretches of 1-3 beats not listed; all beats are in the map)
  beat map: track.wav.beats.json
```

- `lead-in` – audio before the first beat.
- `rebuilt` – beats numbered 291 to 296, where the tracker found no reliable
  beat (a fill, a break, a pause) and placed beats at the surrounding tempo.
  Check these by ear: if a break holds an odd number of beats, the bar count
  after it is off, and you restart the count there with a second `--start`.
- `cuts ±N ms` – the tracker places beats a little before or after the actual
  attack, depending on the material. That offset is measured per track and
  applied, so every cut lands a few ms before an attack instead of inside one.

The beat map is plain JSON: `beats` (cut points in seconds), `reliable` (false
for rebuilt beats), `tempo`, `offset` and the source's `duration`.

### 2. Split

```
track.wav: 51 chunks of 16 beats -> track_beats16
  000  0:00.000-0:00.103  lead-in
  001  0:00.103-0:06.317  beats 1-16
  002  0:06.317-0:12.513  beats 17-32
  ...
  050  4:54.239-4:59.560  beats 785-790 (6 beats)
```

- Chunk `000` is the lead-in (left out when the first beat is at 0:00).
- Each `--start` begins a new count. The chunk just before it ends there and
  can be shorter, as can the last chunk, which runs to the end of the file.
  Shorter chunks show their beat count.
- `--start` takes a beat number (`33`) or a time (`1:02.5`, `62.5`), which
  snaps to the nearest beat. Use the beat numbers from the analysis.
- Splitting the same file into the same folder again replaces its earlier
  chunks; other files in the folder are left alone.
- Without `--fade` the chunks join back into the original sample for sample.
  `--fade MS` adds a short fade at each cut, for playing chunks on their own.

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
| `-s, --start BEAT\|TIME` | beat 1 | Beat to start counting from; repeat to restart the count |
| `-m, --map FILE` | `<file>.beats.json` | Beat map to use for all files |
| `--reanalyze` | off | Analyse again even if a beat map exists |
| `-o, --out-dir` | `<name>_beats<N>` next to the input | Output folder (one subfolder per file when several are given) |
| `-f, --format` | as input | `wav`, `flac`, `aiff`, `mp3`, `m4a`, `ogg` |
| `--fade MS` | `0` | Fade in/out at each cut |
| `-b, --bpm` | detected | Known tempo; narrows detection to ±10 % (`analyze` and `split`) |
| `--hint` | `120` | Detection prior when `--bpm` is not given |

## Architecture

```
cli ─► beatmap.analyse ─► bpm_lock.beats (tracker) + attack_offset   → BeatMap ⇄ JSON
    └► splitter.plan (beats, starts, size → chunks) ─► splitter.cut ─► bpm_lock.audio_io
```

## Notes

- The tracker does not know where a bar starts. Beat 1 is the first detected
  beat; pick the first downbeat with `--start`.
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

Chunk planning, lossless cutting, and a synthetic drum track on which every cut
must land within 15 ms before its attack. The CLI tests need ffmpeg.

## License

MIT — see [LICENSE](LICENSE).
