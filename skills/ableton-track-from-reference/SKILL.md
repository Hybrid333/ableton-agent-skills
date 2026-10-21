---
name: ableton-track-from-reference
description: "Build a complete arrangement from a named reference track — key, tempo, sections, bassline, drums, chords, topline — generated as multitrack MIDI and imported straight into Ableton. Use for 'build me a track like X', 'song in the style of', 'beat like Y', 'arrangement for a new piece', or when a reference artist and a desired vibe are named."
---

# Track from a reference

From "build me something like X" to a finished arrangement in Ableton. This is
the creative part; import runs through `ableton-midi-in-live`, structural QA
through `ableton-arrangement-doctor`.

---

## First: say the honest thing

**The agent can't hear music.** It can't transcribe a reference track. What it
can do: build a stylistically fitting arrangement from research on the artist
and genre plus the user's description.

That goes at the start, not the end — otherwise the user expects a copy and gets
an interpretation. Offer three routes:

1. **The user dictates the core motif** — "bass: F-F-F-A♭-B♭, eighths,
   syncopated on the and" → transpose and build exactly on it. Best results.
2. **Stylistic build** — following genre conventions, no claim to note-for-note
   match.
3. **The user attaches MIDI or audio** — with MIDI, extract the pattern exactly.

---

## Clarify before building

Ask with structured multiple-choice questions, not free text. Always these four:

- **Bass source** (the three routes above)
- **Key** — with a recommendation. For dark electronic material F minor sits
  well and lies comfortably in most synths' bass register.
- **Scope** — full song skeleton with locators, or just loop building blocks
- **Tempo**, if it can't be derived from the reference

Do one web search first on who the artist is and which genre they work in. It
sharpens the suggestions and stops you building past the style.

---

## A build that has proven itself

**One generator script, one small function per instrument.** Never write notes by
hand. The script stays reproducible and the user can re-run it.

Notes as `(step, pitch, len_steps, velocity)`, 16 steps per bar. Sections as
`(name, start_bar, length_bars)`.

A track layout that works:

| Track | Content |
|---|---|
| 01 DRUMS Kick+Snare | pads 36 / 37 / 38 |
| 02 HATS + PERC | pads 36 / 37 / 38 |
| 03 BASS (main hook) | the hook — the identity of the piece |
| 04 SUB | root an octave lower, long notes |
| 05 CHORDS Keys | |
| 06 LEAD Synth hook | |
| 07 VOCAL TOPLINE (guide) | singing guide to replace |

Percussion **always** on 36/37/38. Ableton's default Drum Rack covers only
36–51 — GM pitches like shaker 70 are silent with no warning. One track per
family.

**The bass hook carries the piece.** One rhythmic cell repeated every bar, only
the root moves with the harmony. That's catchier than a line that changes every
bar. Example from a working track: hits on 16th steps 0, 3, 6, 10, 12, 14 with
root / root / root / fifth / root / octave, harmony cycle i – VI – III – VII.
The verse thins to 3 notes per bar, the pre-chorus holds long notes.

**Dynamics through density, not volume.** Verse ~26 notes/bar, pre ~39, chorus
~53. Then the chorus lifts without anything getting louder.

**Leave instruments empty.** Never transplant devices from other projects —
sample paths break, and a preset from another track rarely fits. Instead put a
loading suggestion per track in its name and `Annotation`.

**Deduplicate at the end:** one note per `(step, pitch)`, otherwise overlapping
accent patterns stack double notes.

---

## Afterwards

1. Write multitrack MIDI and import it via `ableton-midi-in-live`. The drop
   almost always lands on bar 2 — fix it.
2. Run `ableton-arrangement-doctor` on the result. If the density curve is flat
   or the set of playing tracks never changes, the arrangement isn't finished —
   improve it before handing it over.
3. Ship a README: arrangement table with bars, track-to-instrument table, pad
   mapping, the bass cell as notation, how to re-run the script.

---

## What the user does afterwards

Always say this, or they wait for something that isn't coming:

- Load instruments.
- The MIDI import creates **one continuous clip per track**, not clips per
  section. For separate clips: position on the locator, select the clips, `ctrl+e`.
- Don't save — the user does that.
