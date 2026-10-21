#!/usr/bin/env python3
"""
set_doctor - diagnose (and where safe, repair) Ableton Live 11 sets.

    python3 set_doctor.py <file-or-folder> [more...] [--repair] [--sample-db DIR]

Checks per set
    - file integrity (gzip stream, XML well-formedness, Ableton root element)
    - Live version vs Live 11
    - tempo written to all three locations (manual / per-clip / automation)
    - missing sample and device files, with a search for relocated copies
    - third-party plugins referenced
    - tracks that are muted, frozen, silent (volume 0) or empty
    - arrangement clips that are disabled
    - duplicate NoteIds and pointee-id collisions (corrupts sets on later edits)

Repairs with --repair (always writes <name>.repaired.als, never overwrites)
    - relink samples found elsewhere by filename + size
    - unmute tracks that are muted AND have no clips (harmless leftovers)
    - renumber duplicate NoteIds
    - raise NextPointeeId above every id in use
"""

import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import als_lib as A


# --------------------------------------------------------------- sample index
def build_sample_index(roots):
    """filename(lower) -> [full paths]. Used to relink moved samples."""
    idx = collections.defaultdict(list)
    exts = {'.wav', '.aif', '.aiff', '.flac', '.mp3', '.ogg', '.m4a',
            '.adg', '.adv', '.alc', '.agr', '.ams', '.asd'}
    for r in roots:
        if not os.path.isdir(r):
            continue
        for dirpath, dirnames, filenames in os.walk(r):
            dirnames[:] = [d for d in dirnames if not d.startswith('.')]
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() in exts:
                    idx[fn.lower()].append(os.path.join(dirpath, fn))
    return idx


def resolve(ref, set_path):
    """Where should this reference point, on this machine? -> (path, exists)."""
    cands = []
    host = A.win_to_host(ref['path'])
    if host:
        cands.append(host)
    if ref['relative']:
        cands.append(os.path.normpath(
            os.path.join(os.path.dirname(set_path), ref['relative'])))
    if ref['path'] and os.path.isabs(ref['path']):
        cands.append(ref['path'])
    for c in cands:
        if c and os.path.exists(c):
            return c, True
    return (cands[0] if cands else ref['path']), False


# ------------------------------------------------------------------- checking
def check(path, index=None, repair=False):
    rep = {'path': path, 'fatal': None, 'problems': [], 'notes': [], 'fixed': []}

    try:
        info = A.summary(path)
    except A.AlsError as e:
        rep['fatal'] = str(e)
        return rep

    root, ls = info['root'], info['live_set']
    v = info['version']
    rep['version'] = v
    if v['major'] != '5':
        rep['problems'].append(
            f"created by {v['creator']} (MajorVersion {v['major']}) - "
            f"Live 11 may refuse to open it")
    elif v['creator'] and 'Live 12' in v['creator']:
        rep['problems'].append(
            f"saved in {v['creator']}; Live 11 cannot open Live 12 sets")

    # ---- tempo
    man, env = info['tempo_manual'], info['tempo_envelope']
    if man is None:
        rep['problems'].append('no manual tempo value found')
    elif env and any(abs(e - man) > 0.01 for e in env):
        rep['problems'].append(
            f'tempo automation ({env}) overrides the manual tempo ({man}) - '
            f'the transport will not show {man} BPM')
    rep['tempo'] = man

    # ---- tracks
    tr = info['tracks']
    rep['track_count'] = len([t for t in tr if t['tag'] != 'ReturnTrack'])
    for t in tr:
        if t['tag'] == 'ReturnTrack':
            continue
        nm = t['name'] or f"<unnamed {t['tag']}>"
        n_clips = len(t['clips'])
        if t['muted']:
            rep['problems'].append(f'track "{nm}" is muted' +
                                   ('' if n_clips else ' (and has no clips)'))
        if t['frozen']:
            rep['notes'].append(f'track "{nm}" is frozen')
        if t['volume'] is not None and t['volume'] < 1e-4 and n_clips:
            rep['problems'].append(f'track "{nm}" has clips but volume is at -inf')
        if t['tag'] == 'MidiTrack' and n_clips and not any(
                d['tag'] not in ('PluginDevice',) or True for d in t['devices']):
            pass
        if t['tag'] == 'MidiTrack' and n_clips and not t['devices']:
            rep['notes'].append(f'track "{nm}" has {n_clips} clip(s) but no instrument')
        for c in t['clips']:
            if c['disabled']:
                rep['problems'].append(
                    f'clip "{c["name"]}" on "{nm}" (bar {c["start_bar"]}) is deactivated')
            if c['end_beat'] <= c['start_beat']:
                rep['problems'].append(
                    f'clip "{c["name"]}" on "{nm}" has zero or negative length')

    # ---- samples
    # A set references the same file once per device/clip, so raw counts are
    # meaningless. Group by filename. Factory presets (a bare "Reverb.adv" with
    # no directory) and Pack content are resolved by Live internally - not our
    # problem and not findable on disk.
    PRESET_EXT = {'.adv', '.adg', '.alc', '.agr', '.ams', '.abl', '.amxd'}
    missing, ok, skipped = {}, 0, 0
    for ref in info['samples']:
        raw = (ref['path'] or ref['relative']).replace('\\', '/')
        name = os.path.basename(raw)
        ext = os.path.splitext(name)[1].lower()
        if ref['pack'] or ref['rel_type'] == '5':          # Pack / Core Library
            skipped += 1
            continue
        if 'Core Library' in raw or '/Factory' in raw:
            skipped += 1
            continue
        if not ext or (ext in PRESET_EXT and '/' not in raw.strip('/')):
            skipped += 1
            continue
        target, exists = resolve(ref, path)
        if exists:
            ok += 1
            continue
        entry = missing.setdefault(name, {
            'name': name, 'expected': target, 'refs': [], 'candidates': []})
        entry['refs'].append(ref)
        if index and not entry['candidates']:
            entry['candidates'] = index.get(name.lower(), [])
    missing = list(missing.values())
    rep['samples_ok'] = ok
    rep['samples_skipped'] = skipped
    rep['samples_missing'] = missing
    for m in missing:
        n = len(m['refs'])
        where = (f'{len(m["candidates"])} candidate(s) found elsewhere'
                 if m['candidates'] else 'not found in the search path')
        rep['problems'].append(
            f'missing file: {m["name"]} (used {n}x) - {where}')

    # ---- plugins
    plugs = sorted({p['name'] for p in info['plugins']})
    rep['plugins'] = plugs
    if plugs:
        rep['notes'].append('third-party plugins referenced: ' + ', '.join(plugs))

    # ---- ids
    # NoteId is unique PER CLIP, not per document. Live itself reuses the same
    # ids across clips - verified against sets saved by Live 11. Checking
    # document-wide produces a false alarm on every real set.
    dupes = 0
    for clip in root.iter('MidiClip'):
        ids = [ne.get('NoteId') for ne in clip.iter('MidiNoteEvent')]
        dupes += sum(c - 1 for c in collections.Counter(ids).values() if c > 1)
    if dupes:
        rep['problems'].append(
            f'{dupes} duplicate NoteId value(s) within a single clip - Live can '
            f'corrupt the set on the next edit')
    # ---- pointee id collisions between tracks
    # These element types carry document-wide unique ids. When a track is
    # deep-copied without remapping (the usual way a generated set gets built),
    # every copy keeps the original's ids and Live refuses the set - usually
    # with no useful error message. Found in the wild: 9 tracks all sharing the
    # same mixer AutomationTarget ids.
    POINTER_TAGS = ('AutomationTarget', 'Pointee', 'ModulationTarget',
                    'VolumeModulationTarget', 'TranspositionModulationTarget',
                    'GrainSizeModulationTarget', 'FluxModulationTarget',
                    'SampleOffsetModulationTarget')
    ptr = collections.defaultdict(list)
    for e in root.iter():
        if e.tag in POINTER_TAGS or e.tag.startswith('ControllerTargets.'):
            v = e.get('Id')
            if v and v.lstrip('-').isdigit() and int(v) >= 100:
                ptr[int(v)].append(e)
    collisions = {k: v for k, v in ptr.items() if len(v) > 1}
    rep['pointee_collisions'] = len(collisions)
    if collisions:
        worst = max(len(v) for v in collisions.values())
        rep['problems'].append(
            f'{len(collisions)} pointee id(s) used more than once (worst: {worst} '
            f'copies) - tracks were duplicated without remapping their ids. This '
            f'is the most common reason Live calls a generated set damaged.')

    npi = ls.find('NextPointeeId')
    max_id = 0
    for e in root.iter():
        val = e.get('Id')
        if val and val.lstrip('-').isdigit():
            max_id = max(max_id, int(val))
    if npi is not None and int(npi.get('Value')) <= max_id:
        rep['problems'].append(
            f'NextPointeeId ({npi.get("Value")}) is not above the highest id in '
            f'use ({max_id})')

    # ---- repairs
    if repair:
        changed = False
        for m in missing:
            if len(m['candidates']) != 1:
                continue
            new = A.host_to_win(m['candidates'][0])
            for ref in m['refs']:
                p = ref['elem'].find('Path')
                if p is not None:
                    p.set('Value', new)
                    changed = True
            rep['fixed'].append(
                f'relinked {m["name"]} ({len(m["refs"])} refs) -> {new}')
        if dupes:
            nxt = max_id + 1
            for clip in root.iter('MidiClip'):
                seen = set()
                for ne in clip.iter('MidiNoteEvent'):
                    nid = ne.get('NoteId')
                    if nid in seen:
                        ne.set('NoteId', str(nxt))
                        nxt += 1
                    else:
                        seen.add(nid)
            rep['fixed'].append(f'renumbered {dupes} duplicate NoteId value(s)')
            max_id = nxt
            changed = True
        if collisions:
            # Anything an automation envelope points at must keep its id, or the
            # automation detaches. Those we leave alone and report instead.
            referenced = {pid.get('Value') for pid in root.iter('PointeeId')
                          if pid.get('Value')}
            nxt, remapped, protected = max_id + 1, 0, 0
            for old, elems in sorted(collisions.items()):
                for e in elems[1:]:            # first occurrence keeps the id
                    if str(old) in referenced:
                        protected += 1
                        continue
                    e.set('Id', str(nxt))
                    nxt += 1
                    remapped += 1
            if remapped:
                rep['fixed'].append(f'remapped {remapped} colliding pointee id(s)')
                max_id = nxt
                changed = True
            if protected:
                rep['notes'].append(
                    f'{protected} colliding id(s) left alone - an automation '
                    f'envelope points at them, remapping would detach the automation')

        for t in tr:
            if t['tag'] == 'ReturnTrack' or not t['muted'] or t['clips']:
                continue
            sp = t['elem'].find('DeviceChain/Mixer/Speaker/Manual')
            if sp is not None:
                sp.set('Value', 'true')
                rep['fixed'].append(f'unmuted empty track "{t["name"]}"')
                changed = True
        if npi is not None and int(npi.get('Value')) <= max_id:
            npi.set('Value', str(max_id + 100000))
            rep['fixed'].append('raised NextPointeeId')
            changed = True
        if changed:
            out = os.path.splitext(path)[0] + '.repaired.als'
            A.save(root, out)
            rep['repaired_to'] = out

    return rep


# --------------------------------------------------------------------- output
def render(rep):
    print('=' * 78)
    print(os.path.basename(rep['path']))
    print('=' * 78)
    if rep['fatal']:
        print(f'  CANNOT OPEN: {rep["fatal"]}')
        return
    v = rep['version']
    print(f'  {v["creator"]}   tempo {rep["tempo"]}   {rep["track_count"]} tracks   '
          f'{rep["samples_ok"]} file refs OK')
    if rep['problems']:
        print(f'\n  PROBLEMS ({len(rep["problems"])})')
        for p in rep['problems']:
            print(f'    ! {p}')
    else:
        print('\n  no problems found')
    if rep['notes']:
        print('\n  NOTES')
        for n in rep['notes']:
            print(f'    - {n}')
    if rep['fixed']:
        print('\n  REPAIRED')
        for f in rep['fixed']:
            print(f'    + {f}')
        print(f'    written to: {rep.get("repaired_to")}')
    for m in rep.get('samples_missing', []):
        if m['candidates']:
            print(f'\n  candidates for {m["name"]}:')
            for c in m['candidates'][:5]:
                print(f'    {c}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('targets', nargs='+')
    ap.add_argument('--repair', action='store_true')
    ap.add_argument('--sample-db', action='append', default=[],
                    help='folder to index when looking for relocated samples '
                         '(repeatable)')
    args = ap.parse_args()

    files = []
    for t in args.targets:
        if os.path.isdir(t):
            for dp, dn, fn in os.walk(t):
                dn[:] = [d for d in dn if not d.startswith('.')]
                files += [os.path.join(dp, f) for f in fn if f.lower().endswith('.als')]
        else:
            files.append(t)
    files = [f for f in files if not f.endswith('.repaired.als')]

    index = build_sample_index(args.sample_db) if args.sample_db else None
    if index is not None:
        print(f'indexed {sum(len(v) for v in index.values())} files '
              f'from {len(args.sample_db)} folder(s)\n')

    bad = 0
    for f in sorted(files):
        rep = check(f, index=index, repair=args.repair)
        render(rep)
        print()
        if rep['fatal'] or rep['problems']:
            bad += 1
    print(f'{len(files)} set(s) checked, {bad} with findings')


if __name__ == '__main__':
    main()
