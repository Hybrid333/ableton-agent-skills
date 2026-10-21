#!/usr/bin/env python3
"""
mix_check - measure a bounce and compare it against a commercial reference.

    python3 mix_check.py mix.wav --ref reference.wav [--plot out.png] [--json out.json]
    python3 mix_check.py mix.wav                      # measure only, no comparison

Everything is loudness-matched before comparison. Without that the louder file
always sounds "better" and every spectral judgement is worthless.

Requires:  pip install --break-system-packages numpy scipy soundfile pyloudnorm
ffmpeg is used automatically for mp3/m4a/ogg input.

Measures
    integrated LUFS, short-term max LUFS, loudness range
    true peak (4x oversampled), sample peak, crest factor
    spectral balance in 7 bands, as a share of total energy
    stereo correlation and side/mid ratio, overall and per band
    mono-compatibility (how much low end survives a mono fold-down)
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

BANDS = [
    ('sub',      20,    60),
    ('bass',     60,   120),
    ('low-mid', 120,   350),
    ('mid',     350,  2000),
    ('hi-mid', 2000,  6000),
    ('highs',  6000, 12000),
    ('air',   12000, 20000),
]


# --------------------------------------------------------------------- input
def load_audio(path):
    """-> (samples float32 [n, ch], samplerate). Converts via ffmpeg if needed."""
    import soundfile as sf
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.wav', '.flac', '.aif', '.aiff', '.ogg'):
        try:
            x, sr = sf.read(path, always_2d=True, dtype='float64')
            return x, sr
        except Exception:
            pass
    tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
    tmp.close()
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', path,
                    '-c:a', 'pcm_f32le', tmp.name], check=True)
    x, sr = sf.read(tmp.name, always_2d=True, dtype='float64')
    os.unlink(tmp.name)
    return x, sr


# ---------------------------------------------------------------- measuring
def true_peak_db(x, sr, oversample=4):
    """Upsample and take the peak. Catches inter-sample peaks that a plain
    sample-peak reading misses - the reason 'my mix is at -0.1 dB' still
    clips after mp3 encoding."""
    from scipy.signal import resample_poly
    peak = 0.0
    for ch in range(x.shape[1]):
        up = resample_poly(x[:, ch], oversample, 1)
        peak = max(peak, float(np.max(np.abs(up))))
    return 20 * np.log10(peak) if peak > 0 else -np.inf


def band_energy(x, sr):
    """Share of total energy per band, from a single FFT of the whole file."""
    mono = x.mean(axis=1)
    n = 1 << 16
    hop = n // 2
    if len(mono) < n:
        mono = np.pad(mono, (0, n - len(mono)))
    win = np.hanning(n)
    acc = np.zeros(n // 2 + 1)
    frames = 0
    for start in range(0, len(mono) - n + 1, hop):
        seg = mono[start:start + n] * win
        acc += np.abs(np.fft.rfft(seg)) ** 2
        frames += 1
    if frames == 0:
        return {b[0]: 0.0 for b in BANDS}, None
    acc /= frames
    freqs = np.fft.rfftfreq(n, 1 / sr)
    total = acc[(freqs >= 20) & (freqs <= 20000)].sum()
    out = {}
    for name, lo, hi in BANDS:
        sel = (freqs >= lo) & (freqs < hi)
        out[name] = float(acc[sel].sum() / total) if total > 0 else 0.0
    return out, (freqs, acc)


def stereo_stats(x, sr):
    if x.shape[1] < 2:
        return {'correlation': 1.0, 'side_mid_db': -np.inf, 'mono': True}
    L, R = x[:, 0], x[:, 1]
    mid, side = (L + R) / 2, (L - R) / 2
    denom = np.sqrt((L ** 2).sum() * (R ** 2).sum())
    corr = float((L * R).sum() / denom) if denom > 0 else 1.0
    m, s = np.sqrt((mid ** 2).mean()), np.sqrt((side ** 2).mean())
    return {'correlation': round(corr, 3),
            'side_mid_db': round(20 * np.log10(s / m), 2) if m > 0 and s > 0 else -np.inf,
            'mono': False}


def mono_low_loss_db(x, sr, cutoff=200):
    """How much low end disappears in mono. Big loss = out-of-phase bass."""
    if x.shape[1] < 2:
        return 0.0
    from scipy.signal import butter, sosfilt
    sos = butter(4, cutoff, 'low', fs=sr, output='sos')
    st = sosfilt(sos, x.mean(axis=1) * 0 + (x[:, 0] + x[:, 1]) / 2)
    each = sosfilt(sos, x[:, 0]) , sosfilt(sos, x[:, 1])
    e_mono = np.sqrt((st ** 2).mean())
    e_st = np.sqrt(((each[0] ** 2).mean() + (each[1] ** 2).mean()) / 2)
    if e_st <= 0 or e_mono <= 0:
        return 0.0
    return round(20 * np.log10(e_mono / e_st), 2)


def measure(path):
    import pyloudnorm as pyln
    x, sr = load_audio(path)
    meter = pyln.Meter(sr)
    lufs = float(meter.integrated_loudness(x))

    # short-term (3 s) loudness for the range and the max
    win = int(3 * sr)
    st = []
    for start in range(0, max(len(x) - win, 1), win // 2):
        seg = x[start:start + win]
        if len(seg) < win // 2:
            break
        try:
            v = float(meter.integrated_loudness(seg))
            if np.isfinite(v):
                st.append(v)
        except Exception:
            pass
    st = np.array(st) if st else np.array([lufs])

    sample_peak = float(np.max(np.abs(x))) if len(x) else 0.0
    rms = float(np.sqrt((x ** 2).mean()))
    bands, spec = band_energy(x, sr)

    return {
        'path': path,
        'seconds': round(len(x) / sr, 1),
        'samplerate': sr,
        'channels': x.shape[1],
        'lufs_integrated': round(lufs, 2),
        'lufs_short_max': round(float(st.max()), 2),
        'loudness_range': round(float(np.percentile(st, 95) - np.percentile(st, 10)), 2),
        'sample_peak_db': round(20 * np.log10(sample_peak), 2) if sample_peak > 0 else -np.inf,
        'true_peak_db': round(true_peak_db(x, sr), 2),
        'crest_db': round(20 * np.log10(sample_peak / rms), 2) if rms > 0 else 0.0,
        'bands': bands,
        'stereo': stereo_stats(x, sr),
        'mono_low_loss_db': mono_low_loss_db(x, sr),
        '_spec': spec,
    }


# --------------------------------------------------------------- comparison
def compare(mix, ref):
    """Loudness-matched deltas, in plain language."""
    out = []
    d_l = mix['lufs_integrated'] - ref['lufs_integrated']
    out.append(('loudness',
                f'{mix["lufs_integrated"]} LUFS vs {ref["lufs_integrated"]} LUFS '
                f'({d_l:+.1f} dB). Comparison below is loudness-matched.'))

    if mix['true_peak_db'] > -0.3:
        out.append(('CRITICAL',
                    f'true peak {mix["true_peak_db"]:+.2f} dBTP - will clip after '
                    f'lossy encoding. Streaming platforms want -1.0 dBTP.'))
    elif mix['true_peak_db'] > -1.0:
        out.append(('WARN', f'true peak {mix["true_peak_db"]:+.2f} dBTP - above the '
                            f'-1.0 dBTP that Spotify/Apple ask for.'))

    d_c = mix['crest_db'] - ref['crest_db']
    if d_c < -2:
        out.append(('WARN',
                    f'crest factor {mix["crest_db"]:.1f} dB vs {ref["crest_db"]:.1f} dB '
                    f'({d_c:+.1f}). Your mix is flatter than the reference - you are '
                    f'compressing or limiting harder than they did.'))
    elif d_c > 3:
        out.append(('INFO',
                    f'crest factor {mix["crest_db"]:.1f} dB vs {ref["crest_db"]:.1f} dB '
                    f'({d_c:+.1f}). More dynamic than the reference - room for glue '
                    f'compression if you want it denser.'))

    for name, lo, hi in BANDS:
        a, b = mix['bands'][name], ref['bands'][name]
        if b <= 0 and a <= 0:
            continue
        d = 10 * np.log10((a + 1e-12) / (b + 1e-12))
        if abs(d) < 1.5:
            continue
        lvl = 'WARN' if abs(d) >= 3 else 'INFO'
        word = 'more' if d > 0 else 'less'
        out.append((lvl, f'{name} ({lo}-{hi} Hz): {abs(d):.1f} dB {word} energy '
                         f'than the reference'))

    if not mix['stereo']['mono'] and not ref['stereo']['mono']:
        dc = mix['stereo']['correlation'] - ref['stereo']['correlation']
        if mix['stereo']['correlation'] < 0.2:
            out.append(('WARN', f'stereo correlation {mix["stereo"]["correlation"]} - '
                                f'very wide, check mono compatibility'))
        elif abs(dc) > 0.25:
            word = 'wider' if dc < 0 else 'narrower'
            out.append(('INFO', f'noticeably {word} than the reference '
                                f'(correlation {mix["stereo"]["correlation"]} vs '
                                f'{ref["stereo"]["correlation"]})'))

    if mix['mono_low_loss_db'] < -2:
        out.append(('WARN', f'{abs(mix["mono_low_loss_db"]):.1f} dB of low end is lost '
                            f'in mono - the bass has phase problems. Make everything '
                            f'below 120 Hz mono.'))
    return out


# ------------------------------------------------------------------- output
def render(m, ref=None, findings=None):
    def block(x, label):
        print(f'\n{label}: {os.path.basename(x["path"])}')
        print(f'  {x["seconds"]}s  {x["samplerate"]} Hz  '
              f'{"stereo" if x["channels"] > 1 else "mono"}')
        print(f'  integrated   {x["lufs_integrated"]:>8.2f} LUFS')
        print(f'  short max    {x["lufs_short_max"]:>8.2f} LUFS')
        print(f'  range        {x["loudness_range"]:>8.2f} LU')
        print(f'  true peak    {x["true_peak_db"]:>8.2f} dBTP')
        print(f'  crest        {x["crest_db"]:>8.2f} dB')
        if not x['stereo']['mono']:
            print(f'  correlation  {x["stereo"]["correlation"]:>8.3f}   '
                  f'side/mid {x["stereo"]["side_mid_db"]:.1f} dB')
        print('  spectrum:')
        for name, lo, hi in BANDS:
            pct = x['bands'][name] * 100
            print(f'    {name:<8} {lo:>5}-{hi:<5} Hz  {pct:5.1f}%  '
                  + '#' * int(pct / 1.5))

    print('=' * 78)
    block(m, 'MIX')
    if ref:
        block(ref, 'REFERENCE')
    if findings:
        print('\nfindings (loudness-matched):')
        order = {'CRITICAL': 0, 'WARN': 1, 'INFO': 2, 'loudness': 3}
        for lvl, msg in sorted(findings, key=lambda f: order.get(f[0], 9)):
            tag = '' if lvl == 'loudness' else f'[{lvl}] '
            print(f'  {tag}{msg}')


def plot(m, ref, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for x, lbl, style in ((m, 'mix', '-'), (ref, 'reference', '--')):
        if not x or x['_spec'] is None:
            continue
        f, a = x['_spec']
        sel = (f >= 20) & (f <= 20000)
        db = 10 * np.log10(a[sel] + 1e-20)
        db -= db.max()
        # smooth in log-frequency for readability
        k = 129
        db = np.convolve(db, np.ones(k) / k, mode='same')
        ax.semilogx(f[sel], db, style, label=lbl, linewidth=1.2)
    ax.set_xlim(20, 20000)
    ax.set_ylim(-80, 5)
    ax.grid(True, which='both', alpha=0.3)
    ax.set_xlabel('Hz')
    ax.set_ylabel('dB (normalised)')
    ax.legend()
    ax.set_title('spectral balance')
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    print(f'\nplot -> {out}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mix')
    ap.add_argument('--ref')
    ap.add_argument('--plot')
    ap.add_argument('--json')
    args = ap.parse_args()

    m = measure(args.mix)
    r = measure(args.ref) if args.ref else None
    f = compare(m, r) if r else None
    render(m, r, f)
    if args.plot and r:
        plot(m, r, args.plot)
    if args.json:
        def clean(x):
            return {k: v for k, v in x.items() if not k.startswith('_')}
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump({'mix': clean(m), 'reference': clean(r) if r else None,
                       'findings': [{'level': a, 'msg': b} for a, b in (f or [])]},
                      fh, indent=2)
        print(f'json -> {args.json}')


if __name__ == '__main__':
    main()
