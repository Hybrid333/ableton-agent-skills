#!/usr/bin/env python3
"""
finish_the_track - which of my unfinished sets is closest to done?

    python3 finish_the_track.py <folder> [<folder> ...] [--all] [--json out.json]
    python3 finish_the_track.py <folder> --top 5

Scores every .als on how finished it is and ranks them. The point is not the
number - it is the shortlist at the end: the three sets where the least work
stands between you and a finished track.

Scoring (0-100)
    30  arrangement    length in bars + does the set of playing tracks change
    25  instruments    share of clip-bearing tracks that actually have one
    15  structure      locators, and sections of sensible length
    15  production     automation envelopes with real data, master chain devices
    15  output         a bounce exists next to the project

Blockers are listed separately and do not lower the score - a set can be 90%
done and still not open because a sample is missing. That is a different
problem from being unfinished.

Versioned duplicates ("Track [2020-06-03 121210].als") are grouped; only the
newest of each group is ranked.
"""

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import als_lib as A

AUDIO_EXT = {'.wav', '.mp3', '.aiff', '.aif', '.flac', '.m4a', '.ogg'}
VERSION_RE = re.compile(r'\s*\[\d{4}-\d{2}-\d{2} \d+\]\s*$')

# Bought template and demo projects score high (they are finished by definition)
# and would crowd out the user's own unfinished tracks in the shortlist.
TEMPLATE_MARKERS = ('template', 'demo', 'microtemplate', 'micro template',
                    'pml ', 'pml-', 'pmlx', 'sinee', 'essential elements',
                    'melodic elements', 'chord generator', 'kick suite')


def looks_like_template(name, path=''):
    n = name.lower()
    p = path.replace('\\', '/').lower()
    if '/templates/' in p or '/factory packs/' in p:
        return True
    return any(m in n for m in TEMPLATE_MARKERS)


STAGES = [
    (85, 'finished',     'only polish left'),
    (65, 'mix',          'arrangement done, sound missing'),
    (45, 'arrangement',  'structure there, sounds incomplete'),
    (25, 'loop',         'the idea works but only repeats'),
    (0,  'sketch',       'a few bars, nothing more'),
]


def base_name(path):
    """'Track [2020-06-03 121210].als' -> 'Track'"""
    stem = os.path.splitext(os.path.basename(path))[0]
    return VERSION_RE.sub('', stem).strip()


def find_bounce(set_path, stem):
    """Any audio file near the project that looks like a render of this set."""
    folder = os.path.dirname(set_path)
    hits = []
    for root in (folder, os.path.dirname(folder)):
        if not os.path.isdir(root):
            continue
        try:
            entries = os.listdir(root)
        except OSError:
            continue
        for fn in entries:
            name, ext = os.path.splitext(fn)
            if ext.lower() not in AUDIO_EXT:
                continue
            if stem.lower()[:12] in name.lower():
                hits.append(os.path.join(root, fn))
    return hits


def score(path):
    r = {'path': path, 'name': base_name(path),
         'mtime': os.path.getmtime(path), 'blockers': [], 'points': {}}
    try:
        root, ls = A.load(path)
    except A.AlsError as e:
        r['fatal'] = str(e)
        r['score'] = 0
        r['stage'] = 'kaputt'
        return r

    tempo, _ = A.tempo(ls)
    tracks = [t for t in A.tracks(ls) if t['tag'] != 'ReturnTrack']
    with_clips = [t for t in tracks if t['clips']]
    locs = A.locators(ls)

    end_beat = max([c['end_beat'] for t in tracks for c in t['clips']] or [0])
    bars = int(end_beat // 4)
    r['bars'] = bars
    r['tempo'] = tempo
    r['minutes'] = round(bars * 4 / tempo, 1) if tempo else 0
    r['tracks'] = len(tracks)
    r['tracks_with_clips'] = len(with_clips)

    # --- 30 arrangement ------------------------------------------------
    p = 0
    p += min(bars / 96, 1.0) * 18          # 96 bars ~ a full arrangement
    sigs = set()
    for t in with_clips:
        for c in t['clips']:
            for b in range(c['start_bar'], min(c['end_bar'], bars + 1)):
                sigs.add((b, t['name']))
    per_bar = {}
    for (b, n) in sigs:
        per_bar.setdefault(b, set()).add(n)
    shapes = {frozenset(v) for v in per_bar.values()}
    r['section_changes'] = len(shapes)
    p += min(len(shapes) / 6, 1.0) * 12    # 6+ distinct textures = real arrangement
    r['points']['arrangement'] = round(p, 1)

    # --- 25 instruments ------------------------------------------------
    inst = [t for t in with_clips if t['devices']]
    r['tracks_with_instrument'] = len(inst)
    p = (len(inst) / len(with_clips) * 25) if with_clips else 0
    r['points']['instruments'] = round(p, 1)

    # --- 15 structure --------------------------------------------------
    p = 0
    if locs:
        p += 8
        named = [l for l in locs if l['name'] and not l['name'].isdigit()]
        p += 4 * min(len(named) / max(len(locs), 1), 1.0)
        lens = [locs[i + 1]['bar'] - locs[i]['bar'] for i in range(len(locs) - 1)]
        if lens and all(l % 4 == 0 for l in lens if l > 0):
            p += 3
    r['locators'] = len(locs)
    r['points']['structure'] = round(p, 1)

    # --- 15 production -------------------------------------------------
    p = 0
    autom = 0
    for env in root.iter('AutomationEnvelope'):
        ev = env.find('Automation/Events')
        if ev is not None and len(list(ev)) > 1:
            autom += 1
    r['automation_lanes'] = autom
    p += min(autom / 6, 1.0) * 8
    master = ls.find('MasterTrack')
    mdev = []
    if master is not None:
        chain = master.find('DeviceChain/DeviceChain/Devices')
        mdev = [d.tag for d in chain] if chain is not None else []
    r['master_devices'] = mdev
    p += min(len(mdev) / 3, 1.0) * 7
    r['points']['production'] = round(p, 1)

    # --- 15 output -----------------------------------------------------
    bounces = find_bounce(path, r['name'])
    r['bounces'] = [os.path.basename(b) for b in bounces]
    r['points']['output'] = 15.0 if bounces else 0.0

    # --- blockers ------------------------------------------------------
    missing = set()
    for ref in A.sample_refs(root):
        raw = (ref['path'] or ref['relative']).replace('\\', '/')
        name = os.path.basename(raw)
        ext = os.path.splitext(name)[1].lower()
        if ref['pack'] or ref['rel_type'] == '5' or 'Core Library' in raw or not ext:
            continue
        if ext in {'.adv', '.adg', '.alc', '.agr', '.ams'} and '/' not in raw.strip('/'):
            continue
        host = A.win_to_host(ref['path'])
        rel = os.path.normpath(os.path.join(os.path.dirname(path), ref['relative'])) \
            if ref['relative'] else None
        if not any(c and os.path.exists(c) for c in (host, rel, ref['path'])):
            missing.add(name)
    if missing:
        r['blockers'].append(f'{len(missing)} missing file(s): '
                             + ', '.join(sorted(missing)[:4])
                             + ('' if len(missing) <= 4 else ' …'))
    if with_clips and len(inst) < len(with_clips):
        n = len(with_clips) - len(inst)
        r['blockers'].append(f'{n} track(s) with notes but no instrument')

    r['score'] = round(sum(r['points'].values()), 1)
    for cut, name, hint in STAGES:
        if r['score'] >= cut:
            r['stage'], r['hint'] = name, hint
            break

    # --- what to do next -----------------------------------------------
    nxt = []
    if r['points']['instruments'] < 20 and with_clips:
        nxt.append(f'load instruments on {len(with_clips) - len(inst)} track(s)')
    if r['points']['arrangement'] < 18:
        if bars < 64:
            nxt.append(f'extend the arrangement (currently {bars} bars)')
        else:
            nxt.append('make sections distinct - almost the same tracks play throughout')
    if not locs:
        nxt.append('set locators for the sections')
    if autom < 3:
        nxt.append('no automation at all - filter, volume, sends')
    if not mdev:
        nxt.append('no master chain')
    if not bounces:
        nxt.append('never bounced')
    r['next'] = nxt
    return r


def collect(folders):
    """Folders, single .als files, or a .txt holding one path per line.

    Walking a mounted network folder is slow - about 40 s for two large music
    folders, which is most of a bash timeout on its own. Build the list once
    with `find` and pass the .txt afterwards:

        find <dirs> -name Backup -prune -o -name "*.als" -print > /tmp/als.txt
        python3 finish_the_track.py /tmp/als.txt
    """
    files = []
    for f in folders:
        if f.lower().endswith('.txt') and os.path.isfile(f):
            with open(f, encoding='utf-8') as fh:
                files += [ln.strip() for ln in fh
                          if ln.strip() and '.repaired.' not in ln]
            continue
        if os.path.isfile(f):
            files.append(f)
            continue
        for dp, dn, fn in os.walk(f):
            dn[:] = [d for d in dn if not d.startswith('.') and d != 'Backup']
            files += [os.path.join(dp, x) for x in fn
                      if x.lower().endswith('.als') and '.repaired.' not in x]
    # "._Name.als" are macOS AppleDouble resource forks that travel with files
    # copied from a Mac. They are not sets and must not be reported as broken.
    return [f for f in files if not os.path.basename(f).startswith('._')]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('folders', nargs='+')
    ap.add_argument('--top', type=int, default=3)
    ap.add_argument('--all', action='store_true', help='also show older versions of the same set')
    ap.add_argument('--include-templates', action='store_true',
                    help='include bought templates and demo projects in the ranking')
    ap.add_argument('--exclude', action='append', default=[],
                    help='regex on the name; matching sets are skipped')
    ap.add_argument('--json')
    args = ap.parse_args()

    files = collect(args.folders)
    if args.exclude:
        pats = [re.compile(p, re.I) for p in args.exclude]
        files = [f for f in files if not any(p.search(f) for p in pats)]
    print(f'{len(files)} set(s) found, scoring …\n')
    rows = []
    for f in files:
        try:
            rows.append(score(f))
        except Exception as e:
            rows.append({'path': f, 'name': base_name(f), 'score': 0,
                         'stage': 'error', 'fatal': f'{type(e).__name__}: {e}',
                         'blockers': [], 'next': [], 'mtime': 0})

    if not args.all:                       # only the newest version per base name
        best = {}
        for r in rows:
            k = r['name'].lower()
            if k not in best or r['mtime'] > best[k]['mtime']:
                best[k] = r
        rows = list(best.values())

    rows.sort(key=lambda r: -r['score'])

    for r in rows:
        r['template'] = looks_like_template(r['name'], r['path'])

    print(f'{"score":>5} {"stage":<12} {"bars":>6} {"tracks":>7} {"instr":>6}  name')
    print('-' * 78)
    for r in rows:
        mark = ' [Template]' if r['template'] else ''
        if r.get('fatal'):
            print(f'{"--":>5} {r["stage"]:<12} {"":>6} {"":>7} {"":>6}  {r["name"]}{mark}')
            continue
        print(f'{r["score"]:>5.1f} {r["stage"]:<12} {r["bars"]:>6} '
              f'{r["tracks_with_clips"]:>7} '
              f'{r["tracks_with_instrument"]}/{r["tracks_with_clips"]:<4}  '
              f'{r["name"]}{mark}')

    ranked = [r for r in rows if not r.get('fatal') and r['score'] < 85
              and (args.include_templates or not r['template'])]
    print(f'\n{"="*78}\nCLOSEST TO DONE — worth your next session\n{"="*78}')
    for r in ranked[:args.top]:
        age = (time.time() - r['mtime']) / 86400
        print(f'\n  {r["name"]}   {r["score"]:.0f}/100 · {r["stage"]} · '
              f'{r["bars"]} bars / {r["minutes"]} min · '
              f'last touched {int(age)} days ago')
        print(f'    {r["path"]}')
        for n in r['next'][:4]:
            print(f'      -> {n}')
        for b in r['blockers']:
            print(f'      !  {b}')

    broken = [r for r in rows if r.get('fatal')]
    if broken:
        print(f'\n{len(broken)} set(s) could not be read:')
        for r in broken:
            print(f'  {r["name"]}: {r["fatal"][:90]}')

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump([{k: v for k, v in r.items()} for r in rows],
                      fh, indent=2, ensure_ascii=False)
        print(f'\njson -> {args.json}')


if __name__ == '__main__':
    main()
