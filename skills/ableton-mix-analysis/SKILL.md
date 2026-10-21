---
name: "ableton-mix-analysis"
description: "Measure and improve the mix or master of an Ableton project — inventory track levels/devices from the .als, render a reference WAV, compute LUFS, true peak, crest factor and spectral balance in code, then apply data-justified changes and a harvested master chain. Use when asked to mix, master, analyze loudness, check spectral balance, or diagnose a mix."
---

# Ableton Mix & Master Analysis

Measurement-driven mixing. Pairs with the `ableton-als-engineering` skill, which
covers the `.als` format itself.

**State the limitation first.** You cannot hear the audio. Mixing is ear-driven —
whether a vocal is too bright, whether kick and bass fight, whether it grooves.
Inserting a generic EQ-compressor-limiter chain blind is not mixing and can make
a track worse. What you *can* do is measure precisely and act only on what the
numbers justify. Say this to the user before starting, and offer the choice
between measure-then-correct, a fast standard chain, and analyze-only.

---

## Step 1 — Inventory the set (no GUI needed)

Read the `.als` directly. This alone often reveals the problem.

```python
import gzip, math
import xml.etree.ElementTree as ET

r = ET.fromstring(gzip.open('Track.als','rb').read())
ls = r.find('LiveSet')

def db(v): return '-inf' if v <= 0 else f'{20*math.log10(v):+.1f}'

for tr in ls.find('Tracks'):
    nm  = tr.find('Name/EffectiveName').get('Value')
    vol = float(tr.find('DeviceChain/Mixer/Volume/Manual').get('Value'))
    pan = float(tr.find('DeviceChain/Mixer/Pan/Manual').get('Value'))
    on  = tr.find('DeviceChain/Mixer/Speaker/Manual').get('Value')   # 'false' = muted
    devs = tr.find('DeviceChain/DeviceChain/Devices')
    print(tr.tag, nm, db(vol), pan, on, [d.tag for d in devs] if devs is not None else [])

mt = ls.find('MasterTrack')
print('MASTER', [d.tag for d in mt.find('DeviceChain/DeviceChain/Devices')])
```

Note `Volume/Manual` is a **linear gain**, not dB — convert with `20*log10(v)`.

Red flags to report: empty master chain, muted tracks the user forgot about,
tracks at 0.0 dB with nothing on them, wildly inconsistent fader levels.

## Step 2 — Find a master chain to harvest

Stock Ableton effects have **no sample references**, so unlike instruments they
transplant safely between projects. Search the user's own projects for a chain
they already like:

```python
import glob, os, collections
files = sorted(glob.glob('*.als'), key=lambda f: -os.path.getmtime(f))[:35]
hit = collections.defaultdict(list)
for f in files:
    r = ET.fromstring(gzip.open(f,'rb').read())
    d = r.find('LiveSet/MasterTrack/DeviceChain/DeviceChain/Devices')
    if d is not None and len(d):
        hit[tuple(x.tag for x in d)].append(f)
```

A typical usable result: `['SpectrumAnalyzer','Eq8','GlueCompressor','Limiter']`.
Deep-copy that chain into the target set's master `Devices` node.

**Cap the scan to ~35 files.** Parsing hundreds of `.als` files times out.

## Step 3 — Render a reference WAV

`Ctrl+Shift+R` opens Audio/Video Export. Confirm before rendering:

- Gerenderte Spur / Rendered Track = **Master**
- Rendering-Start `1.1.1`, Länge = full arrangement
- **Normalisieren = Aus** — normalization destroys the loudness measurement
- Bit-Tiefe 32, WAV

Render to a folder that is actually mounted, not the project folder if that
folder is unreachable.

### Known failure mode

A Windows shell notification flyout (weather, alerts — `Shellhost`) can steal
focus and hold it. Symptoms: Ableton's title bar stays dimmed, clicks and even
`Escape` do nothing, and the export's save dialog never appears. Clicking the
title bar does not recover it.

Do not loop on retries. After two attempts, tell the user plainly that the
desktop is holding focus and ask them to dismiss the notification or click
Export themselves. Everything downstream depends on this one render.

## Step 4 — Measure

`numpy` is available; `scipy` and `soundfile` may not be. Parse WAV manually —
handle format code 3 (32-bit float, what Ableton exports), plus 16/24/32-bit int.

```python
if code == 3 and bits == 32: a = np.frombuffer(raw,'<f4')
elif bits == 16: a = np.frombuffer(raw,'<i2').astype(np.float32)/32768
elif bits == 24:
    u = np.frombuffer(raw,np.uint8).reshape(-1,3).astype(np.int32)
    v = u[:,0] | (u[:,1]<<8) | (u[:,2]<<16)
    a = (np.where(v & 0x800000, v - 0x1000000, v)).astype(np.float32)/8388608
```

Compute:

| Metric | How | Read it as |
|--------|-----|------------|
| Integrated LUFS | BS.1770: K-weighting, 400 ms blocks / 100 ms hop, −10 LU relative gate | Streaming target ≈ −14; club/loud ≈ −9 to −7 |
| True peak | max abs (oversample ×4 for real ISP) | Master ceiling −1.0 dBTP |
| Crest factor | peak − RMS | >20 dB very dynamic/unprocessed; <8 dB overcompressed |
| Spectral balance | Welch-style averaged FFT, % energy per band | See bands below |
| Stereo correlation | corr(L,R) | Near −1 means mono-compatibility problems |

Bands: sub 20–60, bass 60–120, low-mid 120–250, mid 250–500, upper-mid 500–2k,
presence 2–6k, brilliance 6–12k, air 12–20k.

Interpretation notes that have proved useful:

- **Low-mid (120–250 Hz) above ~20 %** on a vocal usually means proximity-effect
  mud — a candidate for a shelf cut, not a guess.
- A percussion loop showing **~0 % below 250 Hz** is a stick/shaker layer, not a
  drum loop. If nothing else supplies low end, the mix has no foundation — that
  is an arrangement problem, not an EQ problem.
- Compare stems against each other before touching anything. Two vocal takes with
  very different band profiles need matching before bus processing.

## Step 5 — Apply only what the data justifies

Safe, fully programmatic edits:

- **Fader / pan**: write `DeviceChain/Mixer/Volume/Manual` (linear gain).
- **Master chain**: deep-copy a harvested chain onto the master `Devices` node.
- **EQ8 band edits**: each band has `Freq`, `Gain`, `Q`, `Mode`, `IsOn` under its
  `ParameterA` / `ParameterB` nodes — read an existing instance to learn the
  layout before writing.

Leave the user's existing per-track EQ, compression and vocal chains alone unless
they explicitly asked for a full mix. Those encode ear decisions you cannot verify.

## Step 6 — Prove it

Re-render after the changes and print a before/after table of every metric. A
master pass that does not move LUFS, true peak and crest in the intended
direction did not work — say so rather than declaring success.

---

## Gotchas

- **Splice samples** live under `AppData/Local/SpliceSettings/modified/<hash>/`
  and in a separate `Splice - <name>/Samples/packs/...` tree — usually outside any
  mountable folder. Project-local audio is under `Samples/Recorded` and
  `Samples/Processed/Consolidate`.
- `C:\Users\<user>\Documents` cannot be mounted directly (it overlaps a protected
  location). Mount the specific project subfolder instead.
- Sample paths live at `AudioClip/SampleRef/FileRef/Path` (a `<Path Value="..."/>`
  element), **not** a `Name` element.
- Analyzing raw source files is not the same as analyzing the mix — track EQ,
  compression and VSTs change everything. Use stems for mix decisions, the
  rendered master for mastering decisions, and never conflate the two in a report.

