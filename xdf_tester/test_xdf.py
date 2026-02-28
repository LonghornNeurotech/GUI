"""
XDF File Inspector
------------------
Usage:
    python test_xdf.py path/to/file.xdf
    python test_xdf.py          # auto-finds the most recent XDF in ~/Documents/EEG_Recordings
    python test_xdf.py --verify # run built-in format verification and exit
"""

import sys
import os
import glob
import struct
import io
import pyxdf
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from datetime import datetime, timezone


# ── helpers ───────────────────────────────────────────────────────────────────

def find_latest_xdf():
    default_dir = os.path.expanduser("~/Documents/EEG_Recordings")
    files = glob.glob(os.path.join(default_dir, "*.xdf"))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def stream_duration(stream):
    ts = stream["time_stamps"]
    if ts is None or len(ts) == 0:
        return 0.0
    return float(ts[-1] - ts[0])


def stream_srate(stream):
    try:
        return float(stream["info"]["nominal_srate"][0])
    except Exception:
        return 0.0


def channel_labels(stream):
    try:
        channels = stream["info"]["desc"][0]["channels"][0]["channel"]
        return [ch["label"][0] for ch in channels]
    except Exception:
        n = int(stream["info"]["channel_count"][0])
        return [f"Ch{i+1}" for i in range(n)]


# ── built-in format verifier ─────────────────────────────────────────────────

def _encode_varlen(value):
    if value <= 0xFF:
        return struct.pack('<BB', 1, value)
    elif value <= 0xFFFFFFFF:
        return struct.pack('<B', 4) + struct.pack('<I', value)
    else:
        return struct.pack('<B', 8) + struct.pack('<Q', value)


def _write_chunk(buf, tag, content):
    if isinstance(content, str):
        content = content.encode('utf-8')
    payload_len = 2 + len(content)
    buf.write(_encode_varlen(payload_len))
    buf.write(struct.pack('<H', tag))
    buf.write(content)


def verify_format():
    """Write a minimal 2-stream XDF (EEG + Markers) and read it back with pyxdf."""
    import tempfile
    print("=" * 62)
    print("  XDF FORMAT VERIFICATION")
    print("=" * 62)

    buf = io.BytesIO()
    buf.write(b'XDF:')

    # FileHeader
    _write_chunk(buf, 1, '<?xml version="1.0"?><info><version>1.0</version></info>')

    # EEG StreamHeader (2 channels, 250 Hz, float32)
    eeg_hdr = (
        '<?xml version="1.0"?><info>'
        '<name>EEG_verify_Trial0001</name>'
        '<type>EEG</type>'
        '<channel_count>2</channel_count>'
        '<nominal_srate>250</nominal_srate>'
        '<channel_format>float32</channel_format>'
        '<channels>'
        '<channel><label>C3</label><type>EEG</type><unit>microvolts</unit></channel>'
        '<channel><label>C4</label><type>EEG</type><unit>microvolts</unit></channel>'
        '</channels>'
        '</info>'
    )
    _write_chunk(buf, 2, struct.pack('<I', 1) + eeg_hdr.encode())

    # Marker StreamHeader (1 channel, string, irregular)
    mk_hdr = (
        '<?xml version="1.0"?><info>'
        '<name>Markers_verify_Trial0001</name>'
        '<type>Markers</type>'
        '<channel_count>1</channel_count>'
        '<nominal_srate>0</nominal_srate>'
        '<channel_format>string</channel_format>'
        '</info>'
    )
    _write_chunk(buf, 2, struct.pack('<I', 2) + mk_hdr.encode())

    # EEG Samples: 5 samples, 2 channels
    eeg_ts = [1.0 + i * 0.004 for i in range(5)]
    sbuf = bytearray()
    sbuf += struct.pack('<I', 1)
    sbuf += _encode_varlen(5)
    for i, ts in enumerate(eeg_ts):
        sbuf += struct.pack('<Bd', 8, ts)
        sbuf += struct.pack('<2f', float(i * 10), float(i * 10 + 1))
    _write_chunk(buf, 3, bytes(sbuf))

    # Marker Samples: 2 markers
    mk_events = [(1.002, 'LEFT'), (1.010, 'REST')]
    mbuf = bytearray()
    mbuf += struct.pack('<I', 2)
    mbuf += _encode_varlen(len(mk_events))
    for ts, label in mk_events:
        enc = label.encode('utf-8')
        mbuf += struct.pack('<Bd', 8, ts)
        mbuf += _encode_varlen(len(enc))   # varlen prefix, NOT uint32
        mbuf += enc
    _write_chunk(buf, 3, bytes(mbuf))

    # StreamFooters
    eeg_ftr = (
        f'<?xml version="1.0"?><info>'
        f'<first_timestamp>{eeg_ts[0]}</first_timestamp>'
        f'<last_timestamp>{eeg_ts[-1]}</last_timestamp>'
        f'<sample_count>5</sample_count>'
        f'</info>'
    )
    _write_chunk(buf, 6, struct.pack('<I', 1) + eeg_ftr.encode())

    mk_ftr = (
        f'<?xml version="1.0"?><info>'
        f'<first_timestamp>{mk_events[0][0]}</first_timestamp>'
        f'<last_timestamp>{mk_events[-1][0]}</last_timestamp>'
        f'<sample_count>{len(mk_events)}</sample_count>'
        f'</info>'
    )
    _write_chunk(buf, 6, struct.pack('<I', 2) + mk_ftr.encode())

    # Write to temp file and read back
    buf.seek(0)
    with tempfile.NamedTemporaryFile(suffix='.xdf', delete=False) as f:
        f.write(buf.read())
        fname = f.name

    try:
        streams, _ = pyxdf.load_xdf(fname)
    finally:
        os.unlink(fname)

    passed = True
    for s in streams:
        name = s['info']['name'][0]
        ts   = s['time_stamps']
        data = s['time_series']
        n    = len(ts) if ts is not None else 0
        print(f"\n  {name}")
        print(f"    samples : {n}")

        if 'EEG' in name:
            expected_n = 5
            ok_n = n == expected_n
            print(f"    count   : {'OK' if ok_n else 'FAIL'} (expected {expected_n}, got {n})")
            if n > 0:
                ok_v = np.allclose(data[0], [0.0, 1.0], atol=1e-4)
                print(f"    values  : {'OK' if ok_v else 'FAIL'} (first sample {data[0]})")
                if not ok_n or not ok_v:
                    passed = False
            else:
                passed = False

        elif 'Markers' in name:
            expected_n = 2
            ok_n = n == expected_n
            print(f"    count   : {'OK' if ok_n else 'FAIL'} (expected {expected_n}, got {n})")
            if n > 0:
                labels = [row[0] for row in data]
                ok_l = labels == ['LEFT', 'REST']
                print(f"    labels  : {'OK' if ok_l else 'FAIL'} {labels}")
                if not ok_n or not ok_l:
                    passed = False
            else:
                passed = False

    print()
    if passed:
        print("  RESULT: ALL CHECKS PASSED ✓")
    else:
        print("  RESULT: SOME CHECKS FAILED ✗")
    print("=" * 62)
    return passed


# ── metadata printer ──────────────────────────────────────────────────────────

def print_metadata(path, streams, header):
    size_kb = os.path.getsize(path) / 1024
    print("=" * 62)
    print("  XDF FILE INSPECTOR")
    print("=" * 62)
    print(f"  File   : {os.path.abspath(path)}")
    print(f"  Size   : {size_kb:.1f} KB")
    print(f"  Streams: {len(streams)}")
    print()

    for i, s in enumerate(streams):
        info = s["info"]
        name      = info["name"][0]
        stype     = info["type"][0]
        n_ch      = int(info["channel_count"][0])
        srate     = stream_srate(s)
        ts        = s["time_stamps"]
        data      = s["time_series"]
        n_samples = len(ts) if ts is not None and len(ts) > 0 else 0
        dur       = stream_duration(s)
        fmt       = info.get("channel_format", ["?"])[0]

        print(f"  Stream {i+1}: {name}")
        print(f"    Type          : {stype}")
        print(f"    Channels      : {n_ch}")
        print(f"    Format        : {fmt}")
        print(f"    Nominal srate : {srate} Hz")
        print(f"    Samples       : {n_samples}")
        print(f"    Duration      : {dur:.3f} s")

        if n_samples > 0:
            t0 = datetime.fromtimestamp(ts[0], tz=timezone.utc)
            t1 = datetime.fromtimestamp(ts[-1], tz=timezone.utc)
            print(f"    First stamp   : {ts[0]:.6f}  ({t0.strftime('%H:%M:%S.%f')[:-3]} UTC)")
            print(f"    Last stamp    : {ts[-1]:.6f}  ({t1.strftime('%H:%M:%S.%f')[:-3]} UTC)")

        if stype in ("EEG", "eeg") and data is not None and n_samples > 0:
            arr = np.array(data, dtype=float)
            print(f"    Value range   : [{arr.min():.2f}, {arr.max():.2f}]  µV (assumed)")

        if stype in ("Markers", "markers") and data is not None and n_samples > 0:
            events = list(zip(ts, [row[0] for row in data]))
            print(f"    Markers ({len(events)}):")
            for t, label in events:
                rel = t - ts[0]
                print(f"      +{rel:7.3f}s  {label}")

        labels = channel_labels(s)
        if n_ch <= 20:
            print(f"    Ch labels     : {labels}")
        else:
            print(f"    Ch labels     : {labels[:8]} … {labels[-4:]}")

        print()


# ── plotting ──────────────────────────────────────────────────────────────────

def plot_streams(streams):
    eeg_streams    = [s for s in streams
                      if s["info"]["type"][0] in ("EEG", "eeg")
                      and s["time_stamps"] is not None
                      and len(s["time_stamps"]) > 0]
    marker_streams = [s for s in streams
                      if s["info"]["type"][0] in ("Markers", "markers")
                      and s["time_stamps"] is not None
                      and len(s["time_stamps"]) > 0]

    if not eeg_streams:
        print("No EEG samples to plot (0 samples recorded).")
        return

    markers = []
    for ms in marker_streams:
        for t, row in zip(ms["time_stamps"], ms["time_series"]):
            markers.append((t, row[0]))

    for eeg in eeg_streams:
        data  = np.array(eeg["time_series"], dtype=float)
        ts    = np.array(eeg["time_stamps"], dtype=float)
        name  = eeg["info"]["name"][0]
        labels = channel_labels(eeg)
        n_ch  = data.shape[1] if data.ndim == 2 else 1
        t0    = ts[0]
        t_rel = ts - t0

        fig = plt.figure(figsize=(14, max(6, n_ch * 0.6 + 2)))
        fig.suptitle(f"EEG Stream — {name}", fontsize=13, fontweight="bold")

        gs   = gridspec.GridSpec(n_ch, 1, hspace=0)
        axes = [fig.add_subplot(gs[i]) for i in range(n_ch)]

        ch_data = data if data.ndim == 2 else data[:, np.newaxis]
        for i, ax in enumerate(axes):
            sig = ch_data[:, i]
            iqr = np.percentile(sig, 75) - np.percentile(sig, 25)
            scale = iqr * 3 if iqr > 0 else 1.0
            ax.plot(t_rel, sig, lw=0.5, color=f"C{i % 10}")
            ax.set_ylim(-scale, scale)
            ax.set_ylabel(labels[i] if i < len(labels) else f"Ch{i+1}",
                          fontsize=7, rotation=0, labelpad=28, va="center")
            ax.yaxis.set_tick_params(left=False, labelleft=False)
            ax.xaxis.set_visible(i == n_ch - 1)
            for spine in ("top", "right", "left"):
                ax.spines[spine].set_visible(False)

            for mt, mlabel in markers:
                mr = mt - t0
                if t_rel[0] <= mr <= t_rel[-1]:
                    ax.axvline(mr, color="red", lw=0.8, alpha=0.6)
                    if i == 0:
                        ax.text(mr, ax.get_ylim()[1] * 0.85, mlabel,
                                fontsize=5, color="red", rotation=90,
                                va="top", ha="right", clip_on=True)

        axes[-1].set_xlabel("Time (s)")
        plt.tight_layout()

    # Marker timeline
    if markers:
        t0 = eeg_streams[0]["time_stamps"][0]
        t_end = eeg_streams[0]["time_stamps"][-1]
        fig2, ax2 = plt.subplots(figsize=(14, 2.5))
        fig2.suptitle("Marker Timeline", fontsize=12, fontweight="bold")
        unique_labels = list(dict.fromkeys(m[1] for m in markers))
        colors = {lbl: f"C{j % 10}" for j, lbl in enumerate(unique_labels)}
        for mt, mlabel in markers:
            mr = mt - t0
            ax2.axvline(mr, color=colors[mlabel], lw=2, alpha=0.8)
            ax2.text(mr, 0.55, mlabel, fontsize=7, color=colors[mlabel],
                     rotation=90, va="bottom", ha="center", clip_on=True)
        ax2.set_xlim(0, t_end - t0)
        ax2.set_ylim(0, 1)
        ax2.set_xlabel("Time (s)")
        ax2.set_yticks([])
        for spine in ("top", "right", "left"):
            ax2.spines[spine].set_visible(False)
        plt.tight_layout()

    plt.show()


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    if "--verify" in sys.argv:
        ok = verify_format()
        sys.exit(0 if ok else 1)

    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        path = find_latest_xdf()
        if path is None:
            print("No XDF file found in ~/Documents/EEG_Recordings.")
            print("Usage: python test_xdf.py path/to/file.xdf")
            print("       python test_xdf.py --verify")
            sys.exit(1)
        print(f"Auto-selected: {path}\n")

    if not os.path.exists(path):
        print(f"File not found: {path}")
        sys.exit(1)

    with open(path, "rb") as f:
        magic = f.read(4)
    if magic != b"XDF:":
        print(f"WARNING: File does not start with 'XDF:' magic bytes (got {magic!r}).")

    streams, header = pyxdf.load_xdf(path)
    print_metadata(path, streams, header)
    plot_streams(streams)


if __name__ == "__main__":
    main()
