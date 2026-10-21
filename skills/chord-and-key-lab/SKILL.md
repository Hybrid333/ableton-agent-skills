---
name: chord-and-key-lab
description: "Harmony tools for Ableton — read the key and chords of a set, transpose a whole set to another key without the drums moving, suggest chord progressions for a key and genre, and generate voice-led voicings as MIDI. Use for 'what chords are these', 'change the key', 'transpose', 'progression for', 'fitting progression', 'voicings', or whenever harmony is the topic."
---

# Chord & Key Lab

Harmony work on Live 11 sets. Tool: [`tools/chord_lab.py`](../../tools/chord_lab.py)
(needs `als_lib.py`, otherwise stdlib only).

```bash
cd tools
export PYTHONDONTWRITEBYTECODE=1

python3 chord_lab.py analyze "Track.als"
python3 chord_lab.py transpose "Track.als" --to Am [--out new.als] [--keep "track name"]
python3 chord_lab.py transpose "Track.als" --semitones -3
python3 chord_lab.py progressions --key Fm [--genre house|pop|trap|lofi|techno]
python3 chord_lab.py voicing --key Fm --chords "i VI III VII" --bars 2 --mid chords.mid
```

---

## `analyze` — what is actually playing

Prints the chord, bass note and note count per bar, plus the most common chords.
Percussion tracks are detected and skipped.

A `?` after the name means no exact match, the closest reading. On real chord
material you get clean names — on one house set: `Am7 · G7 · Dm · C`, no question
marks.

**Two things made the result usable:**

**The bass decides the root.** Without that hint every stacked triad has several
equal readings and the answer flips between related chords — Fm and A♭6 contain
the same notes. If the bass plays F, it's Fm. Before this, the same bar read as
`Cm7` one time and `Abadd9` the next.

**Notes are weighted by how long they sound.** A 16th passing note isn't part of
the harmony. Without weighting every bar reads as a sus or add chord because a
melody note sneaks in. Pitch classes under 12% of the bar's duration are dropped.

---

## `transpose` — the real time-saver

Moves **all** MIDI notes in a set and leaves **percussion alone**.

That's the point: a kick sits on pad 36. Transposed by +4, it lands on pad 40 —
a different, usually empty pad. The pitch doesn't change; the sound disappears.
Exactly that happens when you select everything in Live and shift it up.

Percussion is detected by track name (kick, snare, hat, perc, clap, tom, rim,
shaker, crash, ride) **and** by all pitches sitting in the pad range 35–59 with
few distinct values. `--keep "track name"` covers special cases.

`--to Am` works out the interval itself — via the lowest non-percussion note in
the first bar, because the root almost always sits there. It always takes the
shorter way (max. 6 semitones).

**Always tell the user:** samplers, slicers and pitched audio clips do **not**
follow the transposition. They have to be adjusted in Live. The tool only
rewrites MIDI pitches.

The original is never overwritten — without `--out` you get `Track (+4).als`.
Run `set_doctor.py` over it afterwards; checked on a real set: 258 pitches moved,
drums untouched, note counts identical, no findings.

---

## `progressions` — sequences that carry

First shows all diatonic chords of the key with degree symbols, then proven
progressions per genre — house, pop, trap, lofi, techno — each with one line on
what it's good for.

Not a substitute for trying things. Use it as a starting point and to show the
degree logic instead of just throwing chord names around.

---

## `voicing` — voice leading instead of block chords

Takes a degree sequence (`i VI III VII`, sevenths as `i7 IV7`) and picks
inversions so neighbouring chords move as little as possible, plus a bass note
two octaves down. Output as standard MIDI.

Example F minor, `i VI III VII`:

```
Fm   Ab2 C3  F3
Db   Ab2 Db3 F3      <- Ab and F stay put
Ab   Ab2 C3  Eb3
Eb   G2  Bb2 Eb3
```

That's the difference between "sounds like MIDI" and "sounds like someone
playing piano".

Import the `.mid` with `ableton-midi-in-live`.

---

## Works with

- `ableton-arrangement-doctor` detects the key of a whole set; this tool the
  chords bar by bar
- `ableton-track-from-reference` uses the progressions while building
- after every `transpose`, run `ableton-set-doctor` once
