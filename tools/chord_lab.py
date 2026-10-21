#!/usr/bin/env python3
"""
chord_lab - harmony tools for Ableton Live 11 sets.

    python3 chord_lab.py analyze     <set.als>
    python3 chord_lab.py transpose   <set.als> --to Am            [--out new.als]
    python3 chord_lab.py transpose   <set.als> --semitones -3     [--keep TRACK]
    python3 chord_lab.py progressions --key Fm [--genre house] [--mid out.mid]
    python3 chord_lab.py voicing     --key Fm --chords "i VI III VII" --mid out.mid

`analyze`      key of the set plus the chord under every bar
`transpose`    moves the whole set to another key WITHOUT moving percussion,
               and warns about notes that leave a usable range
`progressions` progressions that work in a key, with roman numerals
`voicing`      turns a progression into playable chord MIDI with voice leading

Percussion tracks are detected and left alone throughout. Transposing a kick
from pad 36 to pad 33 does not change its pitch - it selects a different,
probably empty, pad.
"""

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import als_lib as A

PC = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
FLAT = {'Db': 'C#', 'Eb': 'D#', 'Gb': 'F#', 'Ab': 'G#', 'Bb': 'A#'}
PRETTY = {'C#': 'Db', 'D#': 'Eb', 'G#': 'Ab', 'A#': 'Bb'}

MAJ_SCALE = [0, 2, 4, 5, 7, 9, 11]
MIN_SCALE = [0, 2, 3, 5, 7, 8, 10]

CHORD_TYPES = {
    (0, 4, 7): '', (0, 3, 7): 'm', (0, 3, 6): 'dim', (0, 4, 8): 'aug',
    (0, 2, 7): 'sus2', (0, 5, 7): 'sus4',
    (0, 4, 7, 10): '7', (0, 3, 7, 10): 'm7', (0, 4, 7, 11): 'maj7',
    (0, 3, 7, 11): 'mMaj7', (0, 3, 6, 10): 'm7b5', (0, 4, 7, 9): '6',
    (0, 3, 7, 9): 'm6', (0, 2, 4, 7): 'add9', (0, 3, 5, 7): 'm(add11)',
    (0, 2, 3, 7): 'm(add9)', (0, 2, 3, 7, 10): 'm9', (0, 2, 4, 7, 10): '9',
    (0, 2, 5, 7): 'sus2sus4', (0, 4, 5, 7): 'add11',
}

ROMAN_MAJ = ['I', 'ii', 'iii', 'IV', 'V', 'vi', 'vii°']
ROMAN_MIN = ['i', 'ii°', 'III', 'iv', 'v', 'VI', 'VII']

# progressions as scale degrees (0-based) with quality forced by the mode
PROGRESSIONS = {
    'house': [
        ('i VI III VII', [0, 5, 2, 6], 'the classic - carries forever, never wrong'),
        ('i iv VI v',    [0, 3, 5, 4], 'more melancholic, more movement'),
        ('i VII VI VII', [0, 6, 5, 6], 'hypnotic, good for long loops'),
        ('i III VII iv', [0, 2, 6, 3], 'deep house, soft descent'),
    ],
    'pop': [
        ('I V vi IV',    [0, 4, 5, 3], 'the most-used progression of all'),
        ('vi IV I V',    [5, 3, 0, 4], 'the same, but starts sad'),
        ('I vi IV V',    [0, 5, 3, 4], '50s turnaround, very singable'),
        ('IV I V vi',    [3, 0, 4, 5], 'opens up, good for a pre-chorus'),
    ],
    'trap': [
        ('i VI III VII', [0, 5, 2, 6], 'dark and stable'),
        ('i i VI VII',   [0, 0, 5, 6], 'two bars on the tonic, then a fall'),
        ('i VII VI v',   [0, 6, 5, 4], 'descending, very dark'),
    ],
    'lofi': [
        ('i7 IV7 VII7 III7', [0, 3, 6, 2], 'jazzy sevenths, warm'),
        ('ii7 V7 I7 VI7',    [1, 4, 0, 5], 'ii-V-I, the jazz core'),
        ('i VI ii V',        [0, 5, 1, 4], 'soft, circles around itself'),
    ],
    'techno': [
        ('i i i VII', [0, 0, 0, 6], 'almost static - movement comes from the sound'),
        ('i VI i VII', [0, 5, 0, 6], 'minimal, but with pull'),
    ],
}


# ------------------------------------------------------------------ helpers
def parse_key(s):
    """'Fm' 'F minor' 'Ab' 'C#maj' -> (pitch_class, 'minor'|'major')"""
    s = s.strip()
    mode = 'minor' if ('m' in s[1:].lower() and 'maj' not in s.lower()) else 'major'
    root = s[:2] if len(s) > 1 and s[1] in '#b' else s[:1]
    root = root[0].upper() + root[1:].lower().replace('B', 'b')
    root = FLAT.get(root, root)
    if root not in PC:
        raise SystemExit(f'unknown key: {s}')
    return PC.index(root), mode


def name_pc(pc):
    return PRETTY.get(PC[pc % 12], PC[pc % 12])


def is_drum_track(track):
    pitches = {n['pitch'] for c in track['clips'] for n in c['notes']}
    name = (track['name'] or '').lower()
    if any(k in name for k in ('drum', 'kick', 'snare', 'hat', 'perc', 'clap',
                               'tom', 'rim', 'shaker', 'crash', 'ride')):
        return True
    if not pitches:
        return False
    return pitches <= set(range(35, 60)) and len(pitches) <= 8


def detect_chord(pcs, bass_pc=None):
    """Best chord name for a set of pitch classes.

    The bass note decides the root. Without that hint every stack of thirds has
    several equally valid readings and the answer flips between relative
    chords - Fm and Ab6 contain the same notes, but if the bass plays F it is
    an Fm. Verified against a set whose bass line was known.
    """
    if len(pcs) < 3:
        return None
    roots = list(pcs)
    if bass_pc is not None:
        roots = [bass_pc] + [p for p in pcs if p != bass_pc]

    best = None
    for i, root in enumerate(roots):
        rel = tuple(sorted((p - root) % 12 for p in pcs))
        penalty = 0 if (bass_pc is not None and root == bass_pc) else 3
        if rel in CHORD_TYPES:
            if penalty == 0:
                return name_pc(root) + CHORD_TYPES[rel]
            if best is None or penalty < best[0]:
                best = (penalty, name_pc(root) + CHORD_TYPES[rel], True)
        for tpl, suffix in CHORD_TYPES.items():
            missing = len(set(tpl) - set(rel))
            extra = len(set(rel) - set(tpl))
            cost = missing * 2 + extra + penalty
            if best is None or cost < best[0]:
                best = (cost, name_pc(root) + suffix, False)
    if best is None or best[0] > 5:
        return None
    return best[1] if best[2] else f'{best[1]}?'


# ------------------------------------------------------------------ analyze
def cmd_analyze(args):
    root, ls = A.load(args.set)
    tracks = [t for t in A.tracks(ls) if t['tag'] != 'ReturnTrack']
    pitched = [t for t in tracks if not is_drum_track(t)]
    tempo, _ = A.tempo(ls)

    by_bar = {}
    for t in pitched:
        for c in t['clips']:
            span = c['end_beat'] - c['start_beat']
            for n in c['notes']:
                if n['time'] >= span:
                    continue
                b = int((c['start_beat'] + n['time']) // 4) + 1
                by_bar.setdefault(b, []).append((n['pitch'], max(n['dur'], 0.125)))
    if not by_bar:
        print('no played notes found outside percussion')
        return

    print(f'{os.path.basename(args.set)}   {tempo:g} BPM')
    print('percussion (skipped): ' +
          ', '.join(t['name'] for t in tracks if is_drum_track(t)))
    print()

    bars = sorted(by_bar)
    seq = []
    for b in bars:
        # Weight pitch classes by how long they sound. A 16th passing note is
        # not part of the harmony; without this every bar reads as a sus or
        # add chord because one melody note sneaks in.
        weight = {}
        for (p, d) in by_bar[b]:
            weight[p % 12] = weight.get(p % 12, 0) + d
        total = sum(weight.values())
        pcs = sorted(pc for pc, w in weight.items() if w >= 0.12 * total)
        if len(pcs) < 3:
            pcs = sorted(weight, key=lambda k: -weight[k])[:4]
        low = min(p for (p, d) in by_bar[b])
        seq.append((b, detect_chord(sorted(pcs), low % 12) or '-',
                    name_pc(low), len(by_bar[b])))

    # collapse runs of the same chord
    print(f'{"bar":>6}  {"chord":<10} {"bass":<5} notes')
    run_start, run_chord = seq[0][0], seq[0][1]
    for i, (b, ch, bass, n) in enumerate(seq):
        nxt = seq[i + 1][1] if i + 1 < len(seq) else None
        if ch != nxt:
            rng = f'{run_start}' if run_start == b else f'{run_start}-{b}'
            print(f'{rng:>6}  {ch:<10} {bass:<5} {n}')
            if i + 1 < len(seq):
                run_start, run_chord = seq[i + 1][0], nxt

    counts = {}
    for _, ch, _, _ in seq:
        if ch != '-':
            counts[ch] = counts.get(ch, 0) + 1
    print('\nmost common chords: ' + ', '.join(
        f'{c} ({n}x)' for c, n in sorted(counts.items(), key=lambda x: -x[1])[:6]))


# ---------------------------------------------------------------- transpose
def cmd_transpose(args):
    root, ls = A.load(args.set)
    tracks = [t for t in A.tracks(ls) if t['tag'] != 'ReturnTrack']

    if args.to:
        # work out the current key the cheap way: lowest note of the first bar
        pitched = [t for t in tracks if not is_drum_track(t)]
        first = None
        for b in range(1, 400):
            cand = [n['pitch'] for t in pitched for c in t['clips']
                    for n in c['notes']
                    if int((c['start_beat'] + n['time']) // 4) + 1 == b]
            if cand:
                first = min(cand) % 12
                break
        if first is None:
            raise SystemExit('no notes found - cannot work out the target key')
        target, _mode = parse_key(args.to)
        semis = (target - first) % 12
        if semis > 6:
            semis -= 12
        print(f'detected root: {name_pc(first)} -> {name_pc(target)} '
              f'= {semis:+d} semitones')
    else:
        semis = args.semitones

    keep = {k.lower() for k in (args.keep or [])}
    moved, skipped, out_of_range = 0, [], []
    for t in tracks:
        if is_drum_track(t) or (t['name'] or '').lower() in keep:
            skipped.append(t['name'])
            continue
        for c in t['clips']:
            kts = c['elem'].find('Notes/KeyTracks')
            if kts is None:
                continue
            for kt in kts:
                mk = kt.find('MidiKey')
                if mk is None:
                    continue
                old = int(mk.get('Value'))
                new = old + semis
                if not 0 <= new <= 127:
                    out_of_range.append((t['name'], old, new))
                    new = max(0, min(127, new))
                mk.set('Value', str(new))
                moved += 1

    out = args.out or os.path.splitext(args.set)[0] + f' ({semis:+d}).als'
    A.save(root, out)
    print(f'{moved} pitches moved by {semis:+d} semitones')
    if skipped:
        print('untouched (percussion / --keep): ' + ', '.join(x for x in skipped if x))
    if out_of_range:
        print(f'WARNING: {len(out_of_range)} note(s) outside 0-127, clamped')
    print(f'-> {out}')
    print('\nRemember: samplers and slicers do not follow the transposition '
          'automatically. Re-pitch audio clips and Simpler instruments '
          'in Live yourself.')


# ------------------------------------------------------------- progressions
def degrees_to_chords(root_pc, mode, degrees, sevenths=False):
    scale = MIN_SCALE if mode == 'minor' else MAJ_SCALE
    out = []
    for d in degrees:
        r = (root_pc + scale[d % 7]) % 12
        third = (scale[(d + 2) % 7] - scale[d % 7]) % 12
        fifth = (scale[(d + 4) % 7] - scale[d % 7]) % 12
        tones = [0, third, fifth]
        if sevenths:
            tones.append((scale[(d + 6) % 7] - scale[d % 7]) % 12)
        quality = CHORD_TYPES.get(tuple(sorted(tones)), '')
        out.append({'root': r, 'name': name_pc(r) + quality, 'tones': tones,
                    'degree': d})
    return out


def cmd_progressions(args):
    root_pc, mode = parse_key(args.key)
    romans = ROMAN_MIN if mode == 'minor' else ROMAN_MAJ
    genres = [args.genre] if args.genre else list(PROGRESSIONS)
    print(f'key: {name_pc(root_pc)} {mode}')
    print('diatonic chords: ' + '  '.join(
        f'{romans[i]}={c["name"]}' for i, c in
        enumerate(degrees_to_chords(root_pc, mode, range(7)))))
    print()
    for g in genres:
        if g not in PROGRESSIONS:
            continue
        print(f'--- {g}')
        for label, degs, note in PROGRESSIONS[g]:
            ch = degrees_to_chords(root_pc, mode, degs, sevenths='7' in label)
            print(f'  {label:<20} {" - ".join(c["name"] for c in ch):<28} {note}')
        print()


# ------------------------------------------------------------------ voicing
def voice_lead(chords, center=60, low=48, high=76):
    """Pick inversions so consecutive chords move as little as possible."""
    out, prev = [], None
    for c in chords:
        best = None
        for inv in range(3):
            tones = c['tones'][inv:] + [t + 12 for t in c['tones'][:inv]]
            for oct_shift in (-12, 0, 12):
                notes = [c['root'] + t + oct_shift for t in tones]
                while min(notes) < low:
                    notes = [n + 12 for n in notes]
                while max(notes) > high:
                    notes = [n - 12 for n in notes]
                base = center if prev is None else sum(prev) / len(prev)
                cost = sum(abs(n - base) for n in notes) / len(notes)
                if prev is not None:
                    cost += sum(min(abs(n - p) for p in prev) for n in notes)
                if best is None or cost < best[0]:
                    best = (cost, notes)
        out.append(sorted(best[1]))
        prev = out[-1]
    return out


def write_mid(path, events, tpq=480, bpm=120, name='chords'):
    def vlq(n):
        b = [n & 0x7F]
        n >>= 7
        while n:
            b.append((n & 0x7F) | 0x80)
            n >>= 7
        return bytes(reversed(b))

    ev = []
    for (beat, pitch, dur_beats, vel) in events:
        on = int(round(beat * tpq))
        off = on + max(1, int(round(dur_beats * tpq)))
        ev.append((on, 1, 0x90, pitch, vel))
        ev.append((off, 0, 0x80, pitch, 64))
    ev.sort(key=lambda e: (e[0], e[1]))

    d = bytearray()
    nm = name.encode()[:100]
    d += vlq(0) + b'\xff\x03' + vlq(len(nm)) + nm
    d += vlq(0) + b'\xff\x51\x03' + struct.pack('>I', int(60_000_000 / bpm))[1:]
    last = 0
    for (t, _, st, p, v) in ev:
        d += vlq(t - last) + bytes([st, p, v])
        last = t
    d += vlq(0) + b'\xff\x2f\x00'
    with open(path, 'wb') as fh:
        fh.write(b'MThd' + struct.pack('>IHHH', 6, 0, 1, tpq))
        fh.write(b'MTrk' + struct.pack('>I', len(d)) + bytes(d))


def cmd_voicing(args):
    root_pc, mode = parse_key(args.key)
    romans = ROMAN_MIN if mode == 'minor' else ROMAN_MAJ
    lookup = {r.lower().rstrip('°7'): i for i, r in enumerate(romans)}
    degs, sevenths = [], False
    for tok in args.chords.split():
        t = tok.lower().rstrip('°')
        if t.endswith('7'):
            sevenths, t = True, t[:-1]
        if t not in lookup:
            raise SystemExit(f'unbekannte Stufe: {tok} (erlaubt: {romans})')
        degs.append(lookup[t])

    chords = degrees_to_chords(root_pc, mode, degs, sevenths)
    voiced = voice_lead(chords)
    events = []
    for i, notes in enumerate(voiced):
        for p in notes:
            events.append((i * args.bars * 4, p, args.bars * 4 - 0.1, 80))
        events.append((i * args.bars * 4, chords[i]['root'] + 24, args.bars * 4 - 0.1, 95))

    print(f'{name_pc(root_pc)} {mode}   {args.chords}')
    for i, (c, notes) in enumerate(zip(chords, voiced)):
        print(f'  bar {i*args.bars+1:>3}  {c["name"]:<8} '
              f'{" ".join(name_pc(p) + str(p//12-2) for p in notes)}')
    if args.mid:
        write_mid(args.mid, events, bpm=args.bpm, name=f'{args.key} {args.chords}')
        print(f'\n-> {args.mid}')


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)

    a = sub.add_parser('analyze');  a.add_argument('set')
    t = sub.add_parser('transpose')
    t.add_argument('set')
    t.add_argument('--to')
    t.add_argument('--semitones', type=int)
    t.add_argument('--keep', action='append')
    t.add_argument('--out')
    p = sub.add_parser('progressions')
    p.add_argument('--key', required=True)
    p.add_argument('--genre')
    v = sub.add_parser('voicing')
    v.add_argument('--key', required=True)
    v.add_argument('--chords', required=True)
    v.add_argument('--bars', type=int, default=1)
    v.add_argument('--bpm', type=int, default=120)
    v.add_argument('--mid')

    args = ap.parse_args()
    if args.cmd == 'transpose' and not args.to and args.semitones is None:
        raise SystemExit('transpose needs --to KEY or --semitones N')
    {'analyze': cmd_analyze, 'transpose': cmd_transpose,
     'progressions': cmd_progressions, 'voicing': cmd_voicing}[args.cmd](args)


if __name__ == '__main__':
    main()
