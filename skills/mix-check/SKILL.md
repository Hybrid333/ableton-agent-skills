---
name: mix-check
description: "Measure a bounce and compare it, loudness-matched, with a commercial reference track — LUFS, true peak, crest, 7-band frequency balance, stereo width, mono compatibility — and translate the difference into concrete mix instructions. Use for 'how does my mix sound', 'too quiet', 'too much bass', 'compare with track X', 'mastering check', 'is this release-ready', or whenever an audio file should be assessed."
---

# Mix Check — reference comparison

Measures a bounce and puts it **loudness-matched** next to a commercial reference.
Covers what a reference plugin like Metric AB or a spectrum comparison tool does.

Tool: [`tools/mix_check.py`](../../tools/mix_check.py)

```bash
pip install numpy scipy soundfile pyloudnorm matplotlib

cd tools
PYTHONDONTWRITEBYTECODE=1 python3 mix_check.py "mix.wav" --ref "reference.wav" \
    --plot spectrum.png --json mix.json

# no reference: just measure
PYTHONDONTWRITEBYTECODE=1 python3 mix_check.py "mix.wav"
```

In a fresh agent sandbox the packages are usually missing — put the `pip` line
first every time (`--break-system-packages` where the system Python needs it).
`ffmpeg` is used automatically for mp3/m4a/ogg if installed.

**The first `--plot` run is slow** — matplotlib builds its font cache and can hit
a 45 s timeout. Warm it up once:

```bash
python3 -c "import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot"
```

---

## Why loudness matching isn't optional

People hear louder as better. Without LUFS matching the louder file always wins
the A/B, and any statement about frequency balance is worthless. The script
therefore computes every band comparison as **share of total energy**, not
absolute level. Tell the user so — it explains why a 6 dB bass boost shows up as
"2.8 dB more bass share": the boost also raises total energy, so the relative
share rises less. That's the honest number for a balance comparison, not a bug.

---

## What is measured

| Value | Target | Meaning |
|---|---|---|
| Integrated LUFS | −14 to −9 for streaming | overall loudness |
| True peak | ≤ −1.0 dBTP | oversampled; catches inter-sample peaks that clip after mp3 encoding |
| Crest factor | relative to the reference | lower = harder compressed/limited |
| Loudness range | | how much loudness varies over time |
| 7 bands | sub / bass / low-mid / mid / hi-mid / highs / air | energy share in % |
| Correlation, side/mid | | stereo width |
| Mono low loss | > −2 dB | how much low end disappears on mono fold → phase problems |

---

## Choosing a reference

- **Same genre, same era.** A 2015 master has different loudness from a current one.
- **At least 30 seconds** from the densest part of the reference, not the intro —
  otherwise you compare your chorus with their intro.
- **Lossless if possible.** A 128 kbps mp3 has nothing above 16 kHz and distorts
  the air band.
- Ask the user for the reference instead of guessing one. If they have none: ask
  for the genre and suggest two or three concrete tracks.

---

## Translating the result

The raw table isn't an answer. Sort by urgency:

1. **CRITICAL first** — true peak above −0.3 dBTP means it clips after encoding,
   however good the rest is.
2. **Crest difference** — "7 dB flatter than the reference" concretely means:
   back off the limiter or loosen bus compression.
3. **Bands with ≥ 3 dB deviation**, with frequency and an EQ suggestion. Under
   1.5 dB isn't reported at all — that's noise, not signal.
4. **Last**: what the user should do next, in one sentence.

Always say what is **not** measured: transient quality, timbre, whether the
vocals sit, whether the mix works musically. The tool measures balance and
level, not taste.

---

## Works with

- `ableton-arrangement-doctor` for structure before the mix
- `ableton-mix-analysis` for track levels and devices from the `.als` — this
  skill works on the finished bounce, that one inside the set
