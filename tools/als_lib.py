"""
als_lib - shared reader/writer for Ableton Live Set (.als) files.

Target: Ableton Live 11 (MajorVersion 5, MinorVersion 11.0_436).
An .als is gzip-compressed XML. Everything here is stdlib only.

Used by set_doctor.py, arrangement_doctor.py and any generator script.
"""

import gzip
import os
import re
import xml.etree.ElementTree as ET

XML_DECL = b'<?xml version="1.0" encoding="UTF-8"?>\n'

TRACK_TAGS = ('MidiTrack', 'AudioTrack', 'GroupTrack', 'ReturnTrack')


# ---------------------------------------------------------------- load / save
class AlsError(Exception):
    """Raised with a human-readable diagnosis of why a set won't load."""


def read_raw(path):
    """Return the decompressed XML bytes, diagnosing common failure modes."""
    if not os.path.exists(path):
        raise AlsError(f'file does not exist: {path}')
    size = os.path.getsize(path)
    if size == 0:
        raise AlsError('file is 0 bytes - nothing was ever written')

    with open(path, 'rb') as fh:
        head = fh.read(4)

    if head[:2] == b'\x1f\x8b':
        try:
            with gzip.open(path, 'rb') as fh:
                return fh.read()
        except (EOFError, OSError) as e:
            raise AlsError(
                f'gzip stream is truncated or corrupt ({e}). The file was most '
                f'likely cut off mid-write - by a crash, a full disk, or a '
                f'cloud-sync client copying it while Live was saving.')
    if head[:1] == b'<':
        # uncompressed XML - Live writes gzip, but it opens plain XML too
        with open(path, 'rb') as fh:
            return fh.read()
    raise AlsError(
        f'not an Ableton set: starts with {head!r}, expected gzip (1f 8b) or "<". '
        f'File size {size} bytes.')


def load(path):
    """-> (root_element, live_set_element). Raises AlsError with a diagnosis."""
    data = read_raw(path)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise AlsError(f'XML is malformed at {e.position}: {e}')
    if root.tag != 'Ableton':
        raise AlsError(f'root element is <{root.tag}>, expected <Ableton>')
    ls = root.find('LiveSet')
    if ls is None:
        raise AlsError('no <LiveSet> element - this is not a Live Set '
                       '(a .adg device rack has the same wrapper)')
    return root, ls


def save(root, path):
    """Write with the exact XML declaration Live itself uses.

    ElementTree's default (single quotes, lowercase utf-8) has been observed to
    make Live report the set as damaged. Do not skip this.
    """
    body = ET.tostring(root, encoding='utf-8', xml_declaration=False)
    with gzip.open(path, 'wb') as fh:
        fh.write(XML_DECL + body + b'\n')


def version(root):
    return {
        'creator': root.get('Creator'),
        'major': root.get('MajorVersion'),
        'minor': root.get('MinorVersion'),
        'schema_changes': root.get('SchemaChangeCount'),
    }


def _v(parent, path, default=None):
    n = parent.find(path) if path else parent
    if n is None:
        return default
    return n.get('Value', default)


# ------------------------------------------------------------------- tempo
def tempo(live_set):
    """Return (manual_bpm, [envelope_bpm_values]).

    Tempo lives in up to three places. If an automation envelope targets the
    tempo, the envelope wins and Live ignores the manual value.
    """
    manual, targets = None, set()
    for t in live_set.iter('Tempo'):
        mn = t.find('Manual')
        if mn is not None:
            manual = float(mn.get('Value'))
            at = t.find('AutomationTarget')
            if at is not None and at.get('Id'):
                targets.add(at.get('Id'))
    env_vals = []
    for env in live_set.iter('AutomationEnvelope'):
        pid = env.find('EnvelopeTarget/PointeeId')
        if pid is None or pid.get('Value') not in targets:
            continue
        ev = env.find('Automation/Events')
        if ev is None:
            continue
        for e in ev:
            if e.get('Value') is not None:
                env_vals.append(float(e.get('Value')))
    return manual, env_vals


def set_tempo(live_set, bpm):
    """Write bpm to all three locations."""
    targets = set()
    for t in live_set.iter('Tempo'):
        mn = t.find('Manual')
        if mn is not None:
            mn.set('Value', str(bpm))
            at = t.find('AutomationTarget')
            if at is not None and at.get('Id'):
                targets.add(at.get('Id'))
        elif t.get('Value') is not None:
            t.set('Value', str(bpm))
    for env in live_set.iter('AutomationEnvelope'):
        pid = env.find('EnvelopeTarget/PointeeId')
        if pid is None or pid.get('Value') not in targets:
            continue
        ev = env.find('Automation/Events')
        if ev is not None:
            for e in ev:
                if e.get('Value') is not None:
                    e.set('Value', str(bpm))


# ----------------------------------------------------------------- locators
def locators(live_set):
    loc = live_set.find('Locators/Locators')
    if loc is None:
        return []
    out = []
    for L in loc:
        t = float(_v(L, 'Time', 0))
        out.append({'name': _v(L, 'Name', ''), 'beat': t, 'bar': int(t // 4) + 1})
    return sorted(out, key=lambda d: d['beat'])


# ------------------------------------------------------------------- tracks
def _device_names(dev):
    """Readable name for one device element."""
    tag = dev.tag
    user = _v(dev, 'UserName', '') or ''
    if tag == 'PluginDevice':
        for info_tag in ('Vst3PluginInfo', 'VstPluginInfo', 'AuPluginInfo'):
            info = dev.find(f'PluginDesc/{info_tag}')
            if info is not None:
                nm = _v(info, 'Name') or _v(info, 'PlugName') or ''
                if nm:
                    return f'{nm} (plugin)'
        path = _v(dev, 'SourceContext/Value/BranchSourceContext/BrowserContentPath', '')
        if path:
            nm = path.split(':')[-1].replace('%20', ' ')
            return f'{nm} (plugin)'
        return 'unknown plugin'
    return f'{tag}{" - " + user if user else ""}'


def devices_of(track):
    chain = track.find('DeviceChain/DeviceChain/Devices')
    if chain is None:
        return []
    return [{'tag': d.tag, 'name': _device_names(d), 'elem': d} for d in chain]


def notes_of_clip(clip):
    """-> list of dicts with time (beats, relative to clip), dur, pitch, vel."""
    out = []
    kts = clip.find('Notes/KeyTracks')
    if kts is None:
        return out
    for kt in kts:
        mk = kt.find('MidiKey')
        if mk is None:
            continue
        pitch = int(mk.get('Value'))
        nn = kt.find('Notes')
        if nn is None:
            continue
        for ne in nn:
            out.append({
                'pitch': pitch,
                'time': float(ne.get('Time', 0)),
                'dur': float(ne.get('Duration', 0)),
                'vel': int(float(ne.get('Velocity', 100))),
            })
    return sorted(out, key=lambda n: (n['time'], n['pitch']))


def clips_of(track):
    """Arrangement clips only (not session slots)."""
    ev = track.find('DeviceChain/MainSequencer/ClipTimeable/ArrangerAutomation/Events')
    if ev is None:
        ev = track.find('DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events')
    if ev is None:
        return []
    out = []
    for c in ev:
        start = float(_v(c, 'CurrentStart', 0))
        end = float(_v(c, 'CurrentEnd', 0))
        d = {
            'tag': c.tag,
            'name': _v(c, 'Name', ''),
            'start_beat': start,
            'end_beat': end,
            'start_bar': int(start // 4) + 1,
            'end_bar': int(end // 4) + 1,
            'disabled': _v(c, 'Disabled', 'false') == 'true',
            'elem': c,
        }
        if c.tag == 'MidiClip':
            d['notes'] = notes_of_clip(c)
        else:
            d['notes'] = []
        out.append(d)
    return sorted(out, key=lambda x: x['start_beat'])


def tracks(live_set):
    tl = live_set.find('Tracks')
    if tl is None:
        return []
    out = []
    for t in tl:
        if t.tag not in TRACK_TAGS:
            continue
        mixer = t.find('DeviceChain/Mixer')
        speaker = _v(mixer, 'Speaker/Manual', 'true') if mixer is not None else 'true'
        vol = _v(mixer, 'Volume/Manual') if mixer is not None else None
        pan = _v(mixer, 'Pan/Manual') if mixer is not None else None
        out.append({
            'tag': t.tag,
            'id': t.get('Id'),
            'name': _v(t, 'Name/EffectiveName', ''),
            'annotation': _v(t, 'Name/Annotation', ''),
            'color': _v(t, 'Color'),
            'muted': speaker == 'false',
            'frozen': _v(t, 'Freeze', 'false') == 'true',
            'volume': float(vol) if vol not in (None, '') else None,
            'pan': float(pan) if pan not in (None, '') else None,
            'devices': devices_of(t),
            'clips': clips_of(t),
            'elem': t,
        })
    return out


# --------------------------------------------------------------- references
def sample_refs(root):
    """Every audio/device file the set points at."""
    out = []
    for fr in root.iter('FileRef'):
        path = _v(fr, 'Path', '') or ''
        rel = _v(fr, 'RelativePath', '') or ''
        if not path and not rel:
            continue
        out.append({
            'path': path,
            'relative': rel,
            'rel_type': _v(fr, 'RelativePathType', ''),
            'size': _v(fr, 'OriginalFileSize', ''),
            'pack': _v(fr, 'LivePackName', ''),
            'elem': fr,
        })
    return out


def plugin_refs(root):
    out = []
    for dev in root.iter('PluginDevice'):
        out.append({'name': _device_names(dev), 'elem': dev})
    return out


# Where the Windows "Documents/Ableton" folder is visible from the machine running
# these tools. Set ALS_HOST_ROOT when the tools run somewhere else than the
# Windows box itself (WSL, a Linux VM, a sandbox with a mounted folder), e.g.
#   export ALS_HOST_ROOT=/mnt/c/Users/me/Documents/Ableton
# Set ALS_WIN_ROOT to the matching Windows path (used when writing repaired
# paths back into a set). Both are optional.
HOST_ROOT = os.environ.get('ALS_HOST_ROOT', '').rstrip('/')
WIN_ROOT = os.environ.get('ALS_WIN_ROOT', '').replace('\\', '/').rstrip('/')


def win_to_host(path):
    """Map a Windows path recorded in the set to the host mount, if configured."""
    p = (path or '').replace('\\', '/')
    if not HOST_ROOT:
        return p if os.path.exists(p) else None
    m = re.match(r'^[A-Za-z]:/Users/[^/]+/Documents/Ableton/(.*)$', p)
    if m:
        return HOST_ROOT + '/' + m.group(1)
    return None


def host_to_win(path):
    """Inverse of win_to_host, for writing relinked paths back into a set."""
    if HOST_ROOT and WIN_ROOT and path.startswith(HOST_ROOT):
        return WIN_ROOT + path[len(HOST_ROOT):]
    return path


# ------------------------------------------------------------------ summary
def summary(path):
    root, ls = load(path)
    tr = tracks(ls)
    man, env = tempo(ls)
    return {
        'path': path,
        'version': version(root),
        'tempo_manual': man,
        'tempo_envelope': sorted(set(env)) if env else [],
        'tracks': tr,
        'locators': locators(ls),
        'samples': sample_refs(root),
        'plugins': plugin_refs(root),
        'root': root,
        'live_set': ls,
    }
