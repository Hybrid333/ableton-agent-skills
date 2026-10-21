---
name: ableton-midi-in-live
description: "Get generated music straight into a running Ableton Live 11 set — write multitrack MIDI, import it through Live's browser, fix the bar offset, set tempo and named locators. Use when a track, arrangement or beat should be built 'directly in Ableton', when MIDI should be loaded into an open set, or when someone just says 'build me a track like X'."
---

# Getting music into Ableton Live

A proven route for getting a fully generated arrangement into a **running**
Ableton Live 11 set on Windows, driven by an agent with computer-use (screenshots,
clicks, keys). UI labels are given in English with the German UI in brackets.

Ground rule: **generate as much as possible as files, click as little as
possible.** One drag of a multitrack MIDI file replaces hundreds of GUI actions.
The cost reasoning at the end is the real reason for this workflow.

---

## Short version

1. Generate the music in Python (patterns as code, not by hand).
2. Write **one** multitrack MIDI file (SMF format 1), plus one stem per track.
3. Put the file in a folder the host machine can reach.
4. In Live: add that folder to the browser, drag the file into the Arrangement
   **once** → Live creates one named MIDI track per MIDI track.
5. Fix the bar offset, set tempo, set locators.
6. **Do not save** unless the user explicitly asks.

Building an `.als` directly is the weaker route: Live rejects a malformed set
without a useful error, and you only find out when the user opens it. MIDI
import always works. Build the `.als` as a bonus if you like (see
`ableton-als-engineering`), but don't rely on it.

---

## Steps 1–2: Generate

A structure that holds up:

- one small function per instrument (`drums()`, `hats()`, `bass()`, …)
- notes as tuples `(step, pitch, len_steps, velocity)`, 16 steps per bar
- sections as a list `(name, start_bar, length_bars)`
- **deduplicate** at the end: one note per `(step, pitch)`, otherwise
  overlapping accent patterns stack into double notes

Put percussion **always** on pads 36/37/38. Ableton's default Drum Rack only
covers 36–51; General-MIDI pitches like shaker 70 or cowbell 56 are silent with
no warning. One track per percussion family (kick/snare/clap | hats/perc).

Multitrack MIDI writer with no dependencies:

```python
import struct

def vlq(n):
    b = [n & 0x7F]; n >>= 7
    while n: b.append((n & 0x7F) | 0x80); n >>= 7
    return bytes(reversed(b))

def _mtrk(d): return b'MTrk' + struct.pack('>I', len(d)) + bytes(d)

def write_multitrack_mid(path, tracks, tpq=480, bpm=140, spb=4):
    """tracks: [(name, [(step, pitch, len_steps, vel), ...]), ...]
    spb = steps per beat (4 = 16ths)."""
    chunks = []
    t0 = bytearray()
    t0 += vlq(0) + b'\xff\x03' + vlq(4) + b'Song'
    t0 += vlq(0) + b'\xff\x51\x03' + struct.pack('>I', int(60_000_000 / bpm))[1:]
    t0 += vlq(0) + b'\xff\x58\x04' + bytes([4, 2, 24, 8])
    t0 += vlq(0) + b'\xff\x2f\x00'
    chunks.append(_mtrk(t0))

    for ch, (name, notes) in enumerate(tracks):
        ev = []
        for (step, pitch, ln, vel) in notes:
            on = int(round(step / spb * tpq))
            off = on + max(1, int(round(ln / spb * tpq)))
            ev.append((on, 1, 0x90, pitch, int(max(1, min(127, vel)))))
            ev.append((off, 0, 0x80, pitch, 64))
        ev.sort(key=lambda e: (e[0], e[1]))
        d = bytearray()
        nm = name.encode('utf-8')[:120]
        d += vlq(0) + b'\xff\x03' + vlq(len(nm)) + nm
        last = 0
        for (t, _, status, pitch, vel) in ev:
            d += vlq(t - last) + bytes([status | (ch % 16), pitch, vel]); last = t
        d += vlq(0) + b'\xff\x2f\x00'
        chunks.append(_mtrk(d))

    with open(path, 'wb') as fh:
        fh.write(b'MThd' + struct.pack('>IHHH', 6, 1, len(chunks), tpq))
        for c in chunks: fh.write(c)
```

Read it back before handing over: `note_on == note_off`, velocity 1–127,
`MThd`/`MTrk` headers, expected track count and names.

If you do build an `.als`: Live writes the XML declaration exactly as
`<?xml version="1.0" encoding="UTF-8"?>`. ElementTree's variant (single quotes,
lowercase `utf-8`) has made Live report a set as corrupt. Prepend it yourself:

```python
body = ET.tostring(root, encoding='utf-8', xml_declaration=False)
xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + body + b'\n'
```

---

## Step 3: Make the file reachable

Sandbox paths do not exist on the user's machine. The file must sit in a
folder that is shared with the host, e.g. `C:\Users\<you>\Documents\Ableton\<Project>\`.
Always type the **Windows path** into Live's dialogs.

---

## Steps 4–6: Driving Live

Request access for **Ableton Live** *and* **Explorer**. Explorer is needed to
bring Live to the front via the taskbar; otherwise the frontmost-app check blocks
every click.

### Bring Live to the front

`open_application` often isn't enough. Screenshot, zoom on the taskbar, click
the Live icon. The first keystroke of a sequence is almost always lost (the
agent's own window still has keyboard focus), so **start every batch with a
click inside Live's window**, never with a key.

### View and tempo

`Tab` toggles Session/Arrangement. Tempo: double-click the tempo field top left,
`ctrl+a`, type the value, `Return`.

### Add the folder to the browser

Scroll the sidebar down to **Places → "Add Folder…"** [Orte → „Ordner hinzufügen…"].
In the dialog click into the **Folder:** field, type the full Windows path,
`Return` (navigates into it), `Return` again (confirms). Scroll again — the new
entry appears in the Places list.

### Import

Drag the multitrack `.mid` from the file list into the Arrangement. **Don't**
use `left_click_drag` — Live often doesn't register it. Instead:

```
mouse_move(file) → left_mouse_down → 3–4 intermediate positions → wait 1s → left_mouse_up
```

Target: left half of the Arrangement, first track. Live creates every track with
its name.

### Fix the bar offset (it almost always happens)

The drop typically lands on **bar 2**. Check the status bar at the bottom: it
shows the selection start (`Start: 2.1.1 …`). Fix: click into a clip →
`ctrl+a` → `Left`. With the grid at 1 bar, one keypress is enough. Afterwards
the insert marker reads `1.1.1`.

### Show the whole piece

In the overview strip, drag the right edge of the highlighted area to the right
border. Measure again afterwards — pixels per bar change.

### Set locators

Per section: double-click the position field → type the bar number →
`Return` → click **Set** (above the locator strip on the right).

This fails occasionally — **count** after the pass and add missing bars one by
one. On success the button turns into **Del**.

### Naming locators — the dangerous part

`ctrl+r` renames **whatever is selected**. If all clips are still selected, it
renames *every clip* to one name at once. That has wrecked a set before. Rules:

- Click the locator arrow first, then `ctrl+r`. A click next to it keeps the old
  selection active → the wrong thing gets renamed.
- Type names **without spaces** (`Chorus1`, not `Chorus 1`). If the text doesn't
  land in the input field, a space starts playback.
- After **every** rename, `zoom` on the locator strip to check.
- A click near an already named locator hits its widened label. After two failed
  attempts: stop, leave the default name, tell the user to rename it. Retrying
  costs more than it's worth.
- A click never opens a confirmation dialog. If something was renamed by
  mistake: `ctrl+z`, then `zoom` to see what came back. Undo order isn't always
  what you expect, so check after each undo.

### Finish

**Don't save.** The title stays `Untitled*` on purpose; the user saves.

---

## Always tell the user what's left for them

- Load instruments (the tracks are deliberately empty).
- Pad mapping: 36 / 37 / 38 per drum track.
- The import creates **one continuous clip per track**, not one clip per section.
  For separate clips: put the position on a locator, select the clips, `ctrl+e`.

---

## Cost discipline

Each screenshot costs ~1,500–2,000 tokens, and the full history including old
screenshots is resent on every further step. GUI cost therefore grows
quadratically with the step count, not linearly. Rough figure: a ~30-step GUI
session costs three to four times a complete file generation.

So:

- Generate everything first, then import in **one** GUI session.
- Batch many actions per call instead of single calls.
- `zoom` on small regions instead of full screenshots for checks.
- Don't do fine work (single renames, loading instruments, mixing) through the
  GUI — hand it to the user; it's two clicks for them and expensive for you.
- If a GUI action misses twice: report the state instead of guessing on.
