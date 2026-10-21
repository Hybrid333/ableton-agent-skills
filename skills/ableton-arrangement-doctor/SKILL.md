---
name: ableton-arrangement-doctor
description: "Analyze the structure of an Ableton set and explain, with evidence, why the loop isn't becoming a song — sections, density curve, climax position, key, low-end collisions, dead bars — and deliver concrete MIDI additions. Use for 'my track doesn't go anywhere', 'something's missing', 'how do I build this out', 'check the arrangement', 'why is this boring', or when a half-finished set should be assessed."
---

# Ableton Arrangement Doctor

Structural analysis of a Live 11 set. Answers "why is this a loop and not a song"
from measurable properties — not from taste.

Tool: [`tools/arrangement_doctor.py`](../../tools/arrangement_doctor.py)
(needs `als_lib.py` next to it and `numpy`).

```bash
cd tools
PYTHONDONTWRITEBYTECODE=1 python3 arrangement_doctor.py "path/Track.als"
PYTHONDONTWRITEBYTECODE=1 python3 arrangement_doctor.py "path/Track.als" --json a.json
```

---

## What is measured

- **Sections** — from the locators, otherwise detected automatically where the
  set of playing tracks changes
- **Active tracks per section**
- **Note density and mean velocity per bar** → the dynamics curve, printed as a
  sparkline
- **Climax bar** and where it sits as a percentage of the piece
- **Key** via Krumhansl-Schmuckler on the pitch-class histogram
- **Out-of-key notes** per track
- **Low-end collisions** — two tracks below MIDI 48 at the same time
- **Dead bars** in the middle of the arrangement
- **Section lengths** that aren't a multiple of 4

---

## Three traps real data exposed

**Percussion tracks must be excluded from key and low-end checks.**
A kick on pad 36 is not a bass note in C. Without filtering, every set reports
six "low-end collisions" between drums, hats, bass and sub. The script detects
drum tracks by name *and* by all pitches sitting in the pad range 35–59 with few
distinct values.

**The profile can't separate relative major/minor pairs.**
F minor and A♭ major share the same notes. On root-and-fifth-heavy electronic
material the correlation profile reliably favours the major one — on an F-minor
track, A♭ major scored 0.84 against F minor's 0.68. So the **lowest
non-percussion note in the first bar** decides, and the script says what decided
it. The alternative is always printed too — for unusual pieces it may be right.

**An "End" locator creates a section of length 0.** Sections with length ≤ 0 or
starting after the last bar are dropped.

---

## How to use the result

The raw output is a diagnosis, not an answer. The user wants to know what to change.

1. **CRITICAL findings first.** "The set of playing tracks changes only twice in
   116 bars" means there is no arrangement, just a loop with locators on top.
   That's the most important statement; everything else is cosmetic.
2. **Then read the dynamics curve.** A sparkline that's the same height
   everywhere is why it's boring. Rule of thumb: the densest section should have
   at least 1.5× the density of the thinnest.
3. **Propose a concrete change with bar numbers.** Not "more variation" but
   "bars 49–60: mute hats and chords, keep only bass and kick — then the chorus
   from bar 69 lands".
4. **If the user wants, build the addition as MIDI right away** and import it
   with `ableton-midi-in-live`. That's the real value: diagnosis plus a
   ready-made fix.

---

## What the tool can't do

- It doesn't listen. A set of audio clips without MIDI only yields clip coverage,
  no note density. Then `mix-check` on the bounce is the better tool.
- It doesn't know genre conventions. "Climax at 92%" is right for a build-up
  track and wrong for a pop song — that's your call.
- Out-of-key notes are often intentional. Report them as INFO, never as errors.
