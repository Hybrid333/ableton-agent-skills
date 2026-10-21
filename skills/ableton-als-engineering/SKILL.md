---
name: "ableton-als-engineering"
description: "Read, generate, or edit Ableton Live Set (.als) files programmatically — build arrangements, MIDI clips, tracks, tempo and locators from code, or inspect/repair an existing set. Use whenever an .als file is an input or output, when the user wants a track/arrangement/MIDI generated into Ableton, or when driving the Ableton GUI on screen."
---

# Ableton .als Engineering

Programmatically reading, generating, and editing Ableton Live Sets.

An `.als` file is **gzip-compressed XML**. That makes it fully scriptable — but
the schema is version-specific and has several traps that produce silently wrong
results (or files Live refuses to open). Follow the workflow below.

---

## Core principle: clone a donor, never write XML blind

Do **not** hand-author `.als` XML from scratch. The schema is large, version-
specific, and Live is unforgiving about missing elements. Instead:

1. Find an existing `.als` on the user's machine created by **their** Live version.
2. Use it as the document skeleton (root attributes, `LiveSet`, `MasterTrack`,
   `PreHearTrack`, `ReturnTrack`s, and the ~60 `LiveSet` config children).
3. Grab one **empty `MidiTrack`** from it as a track prototype; deep-copy it once
   per part you need.
4. Grab a **`MidiClip` that contains notes** (possibly from a different set) as a
   clip prototype; deep-copy and rewrite its note data.

This guarantees schema validity for the exact installed version.

### Finding donors

```bash
# bounded depth — a full-tree find over a music folder can take minutes
find <music-dir> -maxdepth 3 -iname "*.als" | head -20
```

Then rank candidates by size and track layout; **the smallest set with an empty
`MidiTrack` is the best skeleton donor**:

```python
import gzip, glob, os
import xml.etree.ElementTree as ET
for f in glob.glob('*/*.als') + glob.glob('*/*/*.als'):
    d = gzip.open(f, 'rb').read()
    r = ET.fromstring(d)
    kinds = [c.tag for c in r.find('LiveSet/Tracks')]
    print(len(d), r.get('Creator'), os.path.basename(f), kinds)
```

Check the donor's Live version before relying on it:

```
<Ableton MajorVersion="5" MinorVersion="11.0_436"
         SchemaChangeCount="7" Creator="Ableton Live 11.1" .../>
```

Never use a donor from a *newer* Live version than the target.

---

## Document structure

```
Ableton
└── LiveSet
    ├── NextPointeeId          # bump above every Id you create
    ├── Tracks
    │   ├── MidiTrack / AudioTrack / GroupTrack ...
    │   └── ReturnTrack ...    # return tracks must stay LAST in Tracks
    ├── MasterTrack            # holds the tempo + its automation envelopes
    ├── Locators/Locators      # arrangement section markers
    └── ~60 further config children (keep them from the donor)
```

Arrangement clips for a MIDI track live at:

```
MidiTrack/DeviceChain/MainSequencer/ClipTimeable/ArrangerAutomation/Events
```

Instruments and effects live at a **different** `DeviceChain`, nested one level
deeper — do not confuse the two:

```
MidiTrack/DeviceChain/DeviceChain/Devices
```

Notes inside a clip are grouped by pitch:

```
MidiClip/Notes/KeyTracks/KeyTrack/
    ├── Notes/MidiNoteEvent Time Duration Velocity VelocityDeviation
    │                       OffVelocity Probability IsEnabled NoteId
    └── MidiKey Value="<pitch>"
```

One `KeyTrack` per distinct pitch, each with its own `MidiKey`.

---

## The four traps

### 1. Tempo lives in THREE places

Setting `<Manual>` alone is **not enough**. If an automation envelope targets the
tempo's `AutomationTarget` id, that envelope wins and the transport silently
keeps the donor's BPM. Write all three:

```python
tempo_target_ids = set()
for tempo in live_set.iter("Tempo"):
    mn = tempo.find("Manual")
    if mn is not None:
        mn.set("Value", str(BPM))                    # 1. manual value
        at = tempo.find("AutomationTarget")
        if at is not None and at.get("Id"):
            tempo_target_ids.add(at.get("Id"))
    elif tempo.get("Value") is not None:
        tempo.set("Value", str(BPM))                 # 2. per-clip tempo reference

for env in live_set.iter("AutomationEnvelope"):      # 3. tempo automation envelope
    pid = env.find("EnvelopeTarget/PointeeId")
    if pid is None or pid.get("Value") not in tempo_target_ids:
        continue
    events = env.find("Automation/Events")
    if events is not None:
        for ev in events:
            if ev.get("Value") is not None:
                ev.set("Value", str(BPM))
```

### 2. Drum Racks only cover pads 36–51

Ableton's default Drum Rack exposes **16 pads, C1–D#2 (MIDI 36–51)**. General-MIDI
percussion pitches such as shaker=70, clave=75, cowbell=56 land on empty pads and
are **completely silent** — with no error or warning.

Fix: give each percussion family its own track and pack its sounds onto the
bottom row (36, 37, 38). Any kit the user drops on the track then plays
immediately with no remapping.

### 3. Clip times are absolute; note times are relative

- `MidiClip` `Time`, `CurrentStart`, `CurrentEnd` → **absolute arrangement beats**
- `MidiNoteEvent` `Time` → **relative to the clip start**, i.e. `0 .. (end-start)`

`Time` and `CurrentStart` must be identical. Verify by round-tripping an existing
set before trusting the convention.

### 4. Ids must be unique and NextPointeeId must clear them

Every `NoteId` in the document must be unique. Track `Id`s and clip `Id`s must not
collide. After building, raise `LiveSet/NextPointeeId` above everything you
allocated, or Live may reuse ids and corrupt the set on the next edit.

---

## Writing the file

```python
xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
with gzip.open(out_path, "wb") as fh:
    fh.write(xml)
```

Set locators so the arrangement is navigable:

```python
loc = live_set.find("Locators/Locators")
for child in list(loc):
    loc.remove(child)
for i, (start_bar, _, name) in enumerate(sections):
    L = ET.SubElement(loc, "Locator")
    L.set("Id", str(i))
    for tag, val in (("LomId", "0"), ("Time", start_bar * 4),
                     ("Name", name), ("Annotation", ""),
                     ("IsSongStart", "true" if i == 0 else "false")):
        ET.SubElement(L, tag).set("Value", str(val))
```

Put an instrument hint in each track's `Name/Annotation` — it shows in Live's
Info Text panel and tells the user what to load.

---

## Always verify before handing over

Re-open the generated file and assert. This catches nearly every mistake:

```python
r = ET.fromstring(gzip.open(out, 'rb').read())          # gzip + XML parse
# tempo actually applied (all three locations)
# per track: clip count, note count, bar ranges
# every note Time within 0..(CurrentEnd-CurrentStart)
# every Velocity in 1..127
# NoteId values unique across the document
# locator names present
```

Then **open it in Live on screen** and confirm the title bar, the transport BPM,
track names and clip contents. Structural validity does not prove Live is happy.

### Also export MIDI stems

Write a plain `.mid` per track alongside the `.als`. Standard MIDI is a
guaranteed-importable fallback if the set ever fails to load, and it lets the
work move to another DAW. Verify stems by parsing them back and checking
note-on count == note-off count.

---

## Driving the Ableton GUI

Use the GUI only for things the file format cannot do — loading instruments,
auditioning, final tweaks. It is slow and focus-sensitive.

**What works reliably:**

| Goal | Action |
|------|--------|
| Open a set | Click into Live's window first, then `ctrl+o`, click the filename field, type the **full absolute path**, `Return` |
| Confirm the open dialog | If `Return` on the file list does nothing, click the filename field and press `Return` again |
| Open the clip/MIDI editor | Select a clip, then `shift+Tab` |
| Confirm a clip loaded correctly | The status bar shows `<name> Start: 65.1.1 Ende: 97.1.1 Länge: 32.0.0` — exact bar positions |
| Verify tempo | Read the transport BPM field, top-left |

**Pitfalls:**

- **Claude's own window keeps focus** on the first keystroke. Click inside Live
  before any `key` action, or the batch fails at action 1.
- **The Windows shell (`Shellhost`) steals focus** unpredictably and blocks input
  with a "not in the allowed applications" error. Re-screenshot and re-focus Live
  via the taskbar; do not blind-retry.
- **Clicks on the left browser category list** (Sounds / Drums / Instruments) are
  unreliable and can minimise Live or leak keystrokes to the desktop. Prefer the
  browser **search field**, or skip GUI loading entirely.
- **Clicking track headers** can toggle automation lanes or arm record. Check the
  title bar for the `*` modified marker afterwards, and reopen without saving if
  the state got dirty.
- A `left_click` at the wrong spot can start playback. Watch the transport.

---

## Do not transplant devices between unrelated projects

It is technically possible to deep-copy a `DrumGroupDevice`, `Operator`, or
`UltraAnalog` from another `.als` into a generated track. **Usually a bad idea:**

- Drum Racks and Simplers reference samples by absolute *and* relative path.
  Copied into a new project folder they commonly arrive as **missing media**.
- Presets carry the sound design of their source project — a techno lead
  transplanted onto a marimba part is worse than an empty track.

Prefer leaving instrument slots empty with a clear per-track loading guide
(track name + `Annotation` + a README table mapping note ranges to suggested
devices). Only transplant when the donor device is genuinely the sound wanted
and its samples resolve from a shared library location.

---

## Deliverable checklist

- `<Name>.als` — verified to open in the user's Live version
- `MIDI Stems/*.mid` — one per track, validated
- The generator script, parameterised and re-runnable (expose a `--seed` for
  variations; keep pattern functions small and one-per-instrument)
- A README with the arrangement map, note-range → instrument table, the pad
  mapping, and how to re-run

