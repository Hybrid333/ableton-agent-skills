# Ableton Agent Skills

**Nine agent skills and six Python tools that let an LLM agent read, build, diagnose and mix Ableton Live sets.**

![Python](https://img.shields.io/badge/Python-3.9+-3776ab?style=flat-square)
![Ableton Live](https://img.shields.io/badge/Ableton_Live-11-000?style=flat-square)
![Agent Skills](https://img.shields.io/badge/format-Agent_Skills_(SKILL.md)-d97757?style=flat-square)
![License: MIT](https://img.shields.io/badge/License-MIT-blue?style=flat-square)

An `.als` file is just gzip-compressed XML, so an agent *can* work with it directly, but the format has traps that fail silently. Tempo hides in three places. Drum Racks ignore General-MIDI percussion. Copied tracks share IDs, so Live calls the set corrupt. These skills pack those lessons into instructions an agent follows, plus tested tools it runs.

Each `SKILL.md` follows the Agent Skills format (YAML frontmatter + instructions). It works with Claude (Claude Code, the Claude apps, the Agent SDK) and any agent that loads skill folders. The tools under `tools/` are plain Python and also run on their own from a terminal.

## The skills

| Skill | What the agent can do with it |
|---|---|
| [ableton-als-engineering](skills/ableton-als-engineering/SKILL.md) | Read and generate `.als` sets from code: clone a donor set, write tracks, clips, notes, tempo and locators, verify before handing over |
| [ableton-midi-in-live](skills/ableton-midi-in-live/SKILL.md) | Write multitrack MIDI and import it into a *running* Live via computer use: browser import, bar-offset fix, tempo, named locators, plus a token-cost playbook for GUI work |
| [ableton-track-from-reference](skills/ableton-track-from-reference/SKILL.md) | Go from "build me something like X" to a full arrangement: bass hook, drums, chords, topline, density-driven dynamics |
| [ableton-arrangement-doctor](skills/ableton-arrangement-doctor/SKILL.md) | Explain why a loop isn't a song: sections, density curve, climax position, key, low-end collisions, dead bars |
| [ableton-set-doctor](skills/ableton-set-doctor/SKILL.md) | Diagnose and repair sets that won't open: colliding pointee IDs, missing samples/plugins, tempo conflicts, truncated files |
| [chord-and-key-lab](skills/chord-and-key-lab/SKILL.md) | Read chords bar by bar, transpose a whole set *without moving the drums*, suggest progressions by genre, voice-lead chords to MIDI |
| [finish-the-track](skills/finish-the-track/SKILL.md) | Score every unfinished set by how close it is to done and name the 2–3 to finish next, each with one concrete step |
| [ableton-mix-analysis](skills/ableton-mix-analysis/SKILL.md) | Measurement-driven mixing: inventory levels and devices from the set, render, compute LUFS/true peak/crest/spectrum, change only what the data justifies |
| [mix-check](skills/mix-check/SKILL.md) | Compare a bounce with a commercial reference, loudness-matched, and turn the differences into mix instructions |

## The tools

| Tool | Needs | Does |
|---|---|---|
| `als_lib.py` | stdlib | Shared `.als` reader: tracks, clips, notes, tempo (all three places), locators, file refs, plugin refs, diagnostics for broken files |
| `set_doctor.py` | stdlib | Checks one set or a whole folder; `--repair` remaps colliding IDs and relinks samples to `<name>.repaired.als`, never the original |
| `arrangement_doctor.py` | numpy | Section table, density sparkline, key detection, findings |
| `chord_lab.py` | stdlib | `analyze` · `transpose` · `progressions` · `voicing` |
| `finish_the_track.py` | stdlib | Ranks a library of sets by completion and prints next steps |
| `mix_check.py` | numpy, scipy, soundfile, pyloudnorm, matplotlib | LUFS (BS.1770), true peak, crest, loudness range, 7-band balance, stereo and mono checks, reference comparison |

```bash
pip install -r tools/requirements.txt     # only mix_check / arrangement_doctor need these
cd tools
python3 set_doctor.py "My Song.als"
python3 arrangement_doctor.py "My Song.als"
python3 chord_lab.py transpose "My Song.als" --to Am
python3 chord_lab.py voicing --key Fm --chords "i VI III VII" --mid chords.mid
python3 finish_the_track.py ~/Music
python3 mix_check.py mix.wav --ref reference.wav --plot spectrum.png
```

Running the tools somewhere other than the Windows machine that owns the sets (WSL, a VM, an agent sandbox with a mounted folder)? Set `ALS_HOST_ROOT` to where `Documents/Ableton` is mounted and `ALS_WIN_ROOT` to the matching Windows path, so recorded sample paths resolve and repaired paths are written back correctly.

## What it looks like

`arrangement_doctor.py` on a 116-bar generated set:

```
140 BPM   116 bars   3:18   7 tracks
key: F minor   (alternative reading: G# major; decided by opening bass note (profile preferred the relative key))
percussion tracks (excluded from key + low-end checks): 01 DRUMS  Kick+Snare, 02 HATS + PERC

sections (locators):
    bar  len name           trk  n/bar   vel
      1    8 Intro            6   14.6  89.8
      9   16 Verse 1          6   26.4  87.0
     25    8 Pre 1            6   39.2  78.1
     33   16 Chorus 1         7   52.9  89.7
     ...
density curve (bar 1 -> 116):
  |  .--========*+*#%%%%%%%%======***#%%%%%%%%@::--%%%%%%%@--- |

findings:
  [WARN] "03 BASS  (main hook)" and "04 SUB" both play below MIDI 48 in 53 shared bars - expect a muddy low end unless one is filtered or sidechained
```

`chord_lab.py transpose` on the same set: the drums stay on their pads, and the result passes `set_doctor.py` with no findings.

```
detected root: F -> A = +4 semitones
258 pitches moved by +4 semitones
untouched (percussion / --keep): 01 DRUMS  Kick+Snare, 02 HATS + PERC
```

`chord_lab.py voicing --key Fm --chords "i VI III VII"`: inversions chosen so that neighbouring chords move as little as possible:

```
  bar   1  Fm       Ab2 C3 F3
  bar   2  Db       Ab2 Db3 F3
  bar   3  Ab       Ab2 C3 Eb3
  bar   4  Eb       G2 Bb2 Eb3
```

## Lessons baked in

These are the traps that cost real debugging time and are now written into the skills:

- **Tempo lives in three places:** the manual value, per-clip references and an automation envelope. If you set only the first, Live keeps the donor's BPM.
- **Default Drum Racks only cover MIDI 36–51.** GM shaker (70) or cowbell (56) play silently with no warning, so percussion always goes on pads 36/37/38.
- **Deep-copied tracks share pointee IDs.** Live then refuses the set without a useful message. In one real case, remapping 1,248 IDs fixed it.
- **NoteId is unique per clip, not per document.** A document-wide check raises false alarms on every real set (verified on 45 sets).
- **Relative major/minor can't be separated by pitch profile.** The opening bass note decides, and the alternative reading is always shown.
- **Transposing a whole set moves the kick off its pad.** Percussion is detected by name and pitch range and left alone.
- **GUI automation cost grows quadratically** with the number of steps, because every old screenshot is resent. So generate files first and click once.

## Honest limits

The agent can't hear. These skills measure structure, pitch, loudness and spectrum, and they say so up front. Timbre, groove and whether a vocal sits are judged by ears. `ableton-midi-in-live` was written against Live 11 on Windows with the German UI (English labels given alongside). Coordinates and labels may differ on other setups.

## Install as skills

Copy (or symlink) the folders under `skills/` into your agent's skills directory, for example `~/.claude/skills/` for Claude Code. Copy `tools/` somewhere the agent can run Python and adjust the `cd tools` lines if needed.

## License

[MIT](LICENSE). Built by [Leo](https://github.com/Hybrid333), a producer and vocalist who makes electronic music as *The Hybrid*, with Claude as a pair-programming partner.
