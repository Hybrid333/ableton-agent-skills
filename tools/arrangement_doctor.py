#!/usr/bin/env python3
"""
arrangement_doctor - structural analysis of an Ableton Live 11 set.

    python3 arrangement_doctor.py <set.als> [--bars-per-line 8] [--json out.json]

Answers the question "why is this a loop and not a song?" from the data in the
set itself. Nothing here is a matter of taste - every finding is a measurable
property of the arrangement.

What it measures
    - song length, section boundaries (from locators, or auto-detected)
    - which tracks are active in which section
    - note density and mean velocity per bar -> the dynamic curve
    - the climax bar, and whether it lands where a drop usually goes
    - key, via Krumhansl-Schmuckler correlation over the pitch-class histogram
    - notes that fall outside the detected scale, per track
    - low-end collisions (two tracks both playing below MIDI 48 at once)
    - empty bars inside the arrangement
    - section lengths that are not multiples of 4 bars
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import als_lib as A

PC = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# Krumhansl-Schmuckler key profiles
MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

MAJ_SCALE = [0, 2, 4, 5, 7, 9, 11]
MIN_SCALE = [0, 2, 3, 5, 7, 8, 10]

LOW_PITCH = 48          # below C2 counts as low end
DRUM_PITCHES = set(range(35, 60))


# ------------------------------------------------------------------ gathering
def collect(path):
    root, ls = A.load(path)
    tempo, _ = A.tempo(ls)
    tempo = tempo or 120.0
    tr = [t for t in A.tracks(ls) if t['tag'] != 'ReturnTrack']

    events = []          # (track_index, bar, pitch, vel, dur_beats)
    max_beat = 0.0
    for i, t in enumerate(tr):
        for c in t['clips']:
            max_beat = max(max_beat, c['end_beat'])
            if c['disabled']:
                continue
            if c['tag'] != 'MidiClip':
                # audio clip: count as sustained activity across its bars
                for b in range(c['start_bar'], c['end_bar']):
                    events.append((i, b, None, 100, 4.0))
                continue
            span = c['end_beat'] - c['start_beat']
            for n in c['notes']:
                if n['time'] >= span:
                    continue            # note lives past the clip end, not audible
                abs_beat = c['start_beat'] + n['time']
                events.append((i, int(abs_beat // 4) + 1, n['pitch'],
                               n['vel'], n['dur']))
    bars = max(1, int(np.ceil(max_beat / 4)))
    return {
        'path': path, 'tempo': tempo, 'tracks': tr,
        'events': events, 'bars': bars,
        'locators': A.locators(ls),
    }


def is_drum_track(track, evs):
    pitches = {p for (_, _, p, _, _) in evs if p is not None}
    if not pitches:
        return False
    name = (track['name'] or '').lower()
    if any(k in name for k in ('drum', 'kick', 'snare', 'hat', 'perc', 'clap')):
        return True
    return pitches and pitches <= DRUM_PITCHES and len(pitches) <= 8


# -------------------------------------------------------------------- metrics
def drum_track_set(d):
    """Indices of tracks that are percussion. Their pitches are pad numbers,
    not musical notes - they must be kept out of key detection and out of the
    low-end collision check, or a kick on pad 36 reads as a bass note."""
    by_track = {}
    for (i, b, p, v, dur) in d['events']:
        by_track.setdefault(i, []).append((i, b, p, v, dur))
    return {i for i, evs in by_track.items()
            if is_drum_track(d['tracks'][i], evs)}


def analyse(d):
    n_tr, bars = len(d['tracks']), d['bars']
    drums = drum_track_set(d)
    d['drums'] = drums
    density = np.zeros((n_tr, bars + 1))
    velsum = np.zeros((n_tr, bars + 1))
    for (i, b, p, v, dur) in d['events']:
        if 1 <= b <= bars:
            density[i, b] += 1
            velsum[i, b] += v
    active = density > 0

    per_bar = density.sum(axis=0)
    mean_vel = np.divide(velsum.sum(axis=0), np.maximum(density.sum(axis=0), 1))

    # sections
    if len(d['locators']) >= 2:
        marks = [(l['name'], l['bar']) for l in d['locators']]
        source = 'locators'
    else:
        marks, prev = [], None
        for b in range(1, bars + 1):
            sig = tuple(active[:, b])
            if sig != prev and any(sig):
                marks.append((f'bar {b}', b))
                prev = sig
        # merge segments shorter than 4 bars into the previous one
        merged = []
        for nm, b in marks:
            if merged and b - merged[-1][1] < 4:
                continue
            merged.append((nm, b))
        marks, source = merged, 'auto-detected (no locators in the set)'

    sections = []
    for k, (nm, b) in enumerate(marks):
        end = marks[k + 1][1] if k + 1 < len(marks) else bars + 1
        length = end - b
        if length <= 0 or b > bars:
            continue        # e.g. a trailing "End" marker
        sl = slice(b, min(end, bars + 1))
        act = [d['tracks'][i]['name'] or f'track {i+1}'
               for i in range(n_tr) if active[:, sl][i].any()]
        dens = float(density[:, sl].sum() / max(length, 1))
        vsum = velsum[:, sl].sum()
        dcount = density[:, sl].sum()
        sections.append({
            'name': nm, 'start_bar': b, 'end_bar': end - 1, 'length': length,
            'active_tracks': act, 'n_active': len(act),
            'notes_per_bar': round(dens, 1),
            'mean_velocity': round(float(vsum / dcount), 1) if dcount else 0.0,
        })

    # key
    hist = np.zeros(12)
    for (i, b, p, v, dur) in d['events']:
        if p is None or i in drums:
            continue
        hist[p % 12] += max(dur, 0.25)
    key = None
    if hist.sum() > 0:
        scored = []
        for root_pc in range(12):
            rolled = np.roll(hist, -root_pc)
            for mode, prof in (('major', MAJ), ('minor', MIN)):
                scored.append((float(np.corrcoef(rolled, prof)[0, 1]), root_pc, mode))
        scored.sort(reverse=True)
        r, root_pc, mode = scored[0]
        # Relative major/minor share a pitch set, so the correlation barely
        # separates them. Break the tie on the bass: the lowest notes in the
        # set almost always sit on the tonic.
        rel = ((root_pc + 3) % 12, 'major') if mode == 'minor' else \
              ((root_pc - 3) % 12, 'minor')
        rel_score = next((s for s in scored if s[1] == rel[0] and s[2] == rel[1]), None)
        # A relative major/minor pair shares its pitch set, so the profile
        # correlation cannot separate them - and on root-and-fifth electronic
        # material it reliably picks the major. The opening bass note is the
        # stronger signal for which of the two is the tonic, so it wins.
        opener = None
        for bar in range(1, bars + 1):
            cand = [p for (i, b, p, v, du) in d['events']
                    if b == bar and p is not None and i not in drums]
            if cand:
                opener = min(cand) % 12
                break
        decided = 'pitch-class profile'
        if opener is not None and opener == rel[0] and opener != root_pc:
            r, root_pc, mode = rel_score
            decided = 'opening bass note (profile preferred the relative key)'
        elif opener is not None and opener == root_pc:
            decided = 'pitch-class profile + opening bass note agree'
        key = {'root': PC[root_pc], 'mode': mode, 'confidence': round(r, 2),
               'pcs': (MAJ_SCALE if mode == 'major' else MIN_SCALE),
               'alternative': f'{PC[rel[0]]} {rel[1]}' if decided.startswith('pitch')
                              else f'{PC[scored[0][1]]} {scored[0][2]}',
               'decided_by': decided}

    return {'density': density, 'active': active, 'per_bar': per_bar,
            'mean_vel': mean_vel, 'sections': sections, 'section_source': source,
            'key': key, 'hist': hist}


def findings(d, m):
    out = []
    bars, secs = d['bars'], m['sections']
    n_tr = len(d['tracks'])

    # 1. loop, not song
    sigs = {tuple(m['active'][:, b]) for b in range(1, bars + 1)
            if m['active'][:, b].any()}
    if len(sigs) <= 2:
        out.append(('CRITICAL',
                    f'the set of playing tracks changes only {len(sigs)} time(s) '
                    f'across {bars} bars - this is a loop, not an arrangement. '
                    f'Mute tracks in the verses and bring them back in the chorus.'))

    # 2. dynamic range across sections
    if len(secs) >= 3:
        dens = [s['notes_per_bar'] for s in secs if s['length'] >= 4]
        if dens and max(dens) > 0:
            spread = (max(dens) - min(dens)) / max(dens)
            if spread < 0.25:
                out.append(('WARN',
                            f'note density is nearly flat across sections '
                            f'(spread {spread:.0%}). Nothing lifts. Aim for the '
                            f'busiest section to be at least 1.5x the sparsest.'))

    # 3. climax position
    if bars >= 16 and m['per_bar'].max() > 0:
        peak = int(np.argmax(m['per_bar']))
        pos = peak / bars
        if pos < 0.18:
            out.append(('WARN', f'the busiest bar is bar {peak} ({pos:.0%} in) - '
                                f'the track peaks almost immediately and has '
                                f'nowhere left to go.'))
        elif pos > 0.92:
            out.append(('INFO', f'the busiest bar is bar {peak} ({pos:.0%} in) - '
                                f'very late. Fine for a build-to-end, otherwise '
                                f'move the climax earlier.'))

    # 4. irregular section lengths
    odd = [s for s in secs if s['length'] % 4 and s['length'] >= 2]
    for s in odd:
        out.append(('WARN', f'section "{s["name"]}" is {s["length"]} bars - not a '
                            f'multiple of 4. Intentional? Otherwise it will feel '
                            f'like a stumble.'))

    # 5. empty bars inside the arrangement
    inside = m['per_bar'][1:bars + 1]
    nz = np.nonzero(inside)[0]
    if len(nz):
        gaps, run = [], 0
        for b in range(nz[0], nz[-1] + 1):
            if inside[b] == 0:
                run += 1
            else:
                if run >= 2:
                    gaps.append((b - run + 1, run))
                run = 0
        for start, ln in gaps:
            out.append(('WARN', f'{ln} silent bar(s) from bar {start+1} in the '
                                f'middle of the arrangement'))

    # 6. low-end collisions
    low_by_track = {}
    for (i, b, p, v, dur) in d['events']:
        if p is not None and p < LOW_PITCH and i not in d.get('drums', set()):
            low_by_track.setdefault(i, set()).add(b)
    lows = list(low_by_track.items())
    for a in range(len(lows)):
        for bx in range(a + 1, len(lows)):
            overlap = lows[a][1] & lows[bx][1]
            if len(overlap) >= 8:
                na = d['tracks'][lows[a][0]]['name']
                nb = d['tracks'][lows[bx][0]]['name']
                out.append(('WARN',
                            f'"{na}" and "{nb}" both play below MIDI {LOW_PITCH} '
                            f'in {len(overlap)} shared bars - expect a muddy low '
                            f'end unless one is filtered or sidechained'))

    # 7. out-of-key notes
    if m['key'] and m['key']['confidence'] > 0.6:
        root = PC.index(m['key']['root'])
        allowed = {(root + s) % 12 for s in m['key']['pcs']}
        per_track = {}
        for (i, b, p, v, dur) in d['events']:
            if p is None or i in d.get('drums', set()):
                continue
            per_track.setdefault(i, [0, 0])
            per_track[i][1] += 1
            if p % 12 not in allowed:
                per_track[i][0] += 1
        for i, (bad, tot) in per_track.items():
            if tot >= 20 and bad / tot > 0.15:
                out.append(('INFO',
                            f'"{d["tracks"][i]["name"]}": {bad}/{tot} notes '
                            f'({bad/tot:.0%}) sit outside '
                            f'{m["key"]["root"]} {m["key"]["mode"]}. Colour or mistake?'))

    # 8. tracks that never play
    for i in range(n_tr):
        if not m['active'][i].any():
            out.append(('INFO', f'"{d["tracks"][i]["name"]}" contains no audible '
                                f'notes at all'))
    return out


# --------------------------------------------------------------------- output
def sparkline(vals, width=60):
    chars = ' .:-=+*#%@'
    if vals.max() <= 0:
        return ' ' * width
    idx = np.linspace(0, len(vals) - 1, width).astype(int)
    v = vals[idx] / vals.max()
    return ''.join(chars[min(int(x * (len(chars) - 1)), len(chars) - 1)] for x in v)


def render(d, m, f):
    mins = d['bars'] * 4 / d['tempo']
    print('=' * 78)
    print(f'{os.path.basename(d["path"])}')
    print('=' * 78)
    print(f'{d["tempo"]:g} BPM   {d["bars"]} bars   {int(mins)}:{int(mins%1*60):02d}   '
          f'{len(d["tracks"])} tracks')
    if m['key']:
        print(f'key: {m["key"]["root"]} {m["key"]["mode"]}   '
              f'(alternative reading: {m["key"]["alternative"]}; '
              f'decided by {m["key"]["decided_by"]})')
    if d.get('drums'):
        print('percussion tracks (excluded from key + low-end checks): '
              + ', '.join(d['tracks'][i]['name'] for i in sorted(d['drums'])))
    print(f'\nsections ({m["section_source"]}):')
    print(f'  {"bar":>5} {"len":>4} {"name":<14} {"trk":>3} {"n/bar":>6} {"vel":>5}  active')
    for s in m['sections']:
        act = ', '.join(s['active_tracks'][:4])
        if len(s['active_tracks']) > 4:
            act += f' +{len(s["active_tracks"])-4}'
        print(f'  {s["start_bar"]:>5} {s["length"]:>4} {s["name"][:14]:<14} '
              f'{s["n_active"]:>3} {s["notes_per_bar"]:>6} {s["mean_velocity"]:>5}  {act}')

    print(f'\ndensity curve (bar 1 -> {d["bars"]}):')
    print('  |' + sparkline(m['per_bar'][1:]) + '|')

    print('\nfindings:')
    if not f:
        print('  none - structurally this holds up')
    order = {'CRITICAL': 0, 'WARN': 1, 'INFO': 2}
    for lvl, msg in sorted(f, key=lambda x: order[x[0]]):
        print(f'  [{lvl}] {msg}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('set')
    ap.add_argument('--json')
    args = ap.parse_args()

    d = collect(args.set)
    m = analyse(d)
    f = findings(d, m)
    render(d, m, f)

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump({'tempo': d['tempo'], 'bars': d['bars'],
                       'key': m['key'], 'sections': m['sections'],
                       'findings': [{'level': l, 'msg': msg} for l, msg in f]},
                      fh, indent=2, ensure_ascii=False)
        print(f'\njson -> {args.json}')


if __name__ == '__main__':
    main()
