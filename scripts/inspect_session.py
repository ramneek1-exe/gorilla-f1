"""Compress every lap of a saved race and print a summary.

Usage (from the project folder):

    python -m scripts.inspect_session              pick a race from a menu
    python -m scripts.inspect_session FILE         use a specific data file

Races are read from data/ (see scripts/export_session.py), so this runs
offline and needs no login.
"""

import argparse
import os
import statistics

from gorilla.block import PER_CHANNEL, SHARED, decode_block, encode_block
from gorilla.dataset import load_laps
from gorilla.timestamps import BUCKET_NAMES
from gorilla.values import float_to_bits

from .menu import choose_dataset, describe

RAW_BYTES_PER_POINT = 16  # 8-byte timestamp + 8-byte value, as in the paper


def pct(part, whole):
    return 100.0 * part / whole if whole else 0.0


def same_bits(a, b):
    return len(a) == len(b) and all(float_to_bits(x) == float_to_bits(y) for x, y in zip(a, b))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", nargs="?", help="a dataset file in data/ (optional)")
    args = parser.parse_args()

    path = args.file if args.file else choose_dataset()[0]
    print(f"\nLoading {os.path.relpath(path)} ...")
    meta, laps = load_laps(path)

    channels = list(laps[0].channels)
    samples = sum(len(lap.timestamps) for lap in laps)
    points = samples * len(channels)
    gaps = [b - a for lap in laps for a, b in zip(lap.timestamps, lap.timestamps[1:])]

    print(f"\nSession:   {describe(meta)}")
    print(f"Drivers:   {len({lap.driver for lap in laps})}")
    print(f"Laps:      {len(laps)}")
    print(f"Samples:   {samples:,} per channel, {len(channels)} channels ({', '.join(channels)})")
    print(f"Points:    {points:,} (timestamp, value) pairs")
    print(f"Gap between samples (ms): min {min(gaps)}, median {statistics.median(gaps):g}, "
          f"95th pct {sorted(gaps)[int(len(gaps) * 0.95)]}, max {max(gaps)}")

    results = {}
    for layout in (SHARED, PER_CHANNEL):
        total_bytes, payload_bits, ok = 0, 0, True
        value_stats = {c: {k: {"count": 0, "bits": 0} for k in ("first", "repeat", "reuse", "new")} for c in channels}
        time_stats = {b: 0 for b in BUCKET_NAMES}
        time_bits = 0
        for lap in laps:
            block, st = encode_block(lap.timestamps, lap.channels, layout)
            total_bytes += st["total_bytes"]
            time_bits += st["streams"].get("_time", 0)
            payload_bits += st["payload_bits"]
            for c in channels:
                for case, s in st["values"][c].items():
                    value_stats[c][case]["count"] += s["count"]
                    value_stats[c][case]["bits"] += s["bits"]
            for b, n in st["time"].items():
                time_stats[b] += n
            ts, decoded = decode_block(block)
            ok = ok and ts == lap.timestamps and all(same_bits(decoded[c], lap.channels[c]) for c in channels)
        results[layout] = (total_bytes, payload_bits, ok, value_stats, time_stats, time_bits)

    print("\nLossless check (every lap decoded back identically):")
    for layout, (_, _, ok, _, _, _) in results.items():
        print(f"  {layout:<12} {'PASS' if ok else 'FAIL'}")

    raw = points * RAW_BYTES_PER_POINT
    print("\nSize of the whole session")
    print(f"  {'layout':<12} {'bytes':>12} {'bytes/point':>12} {'vs raw':>8}")
    print(f"  {'raw':<12} {raw:>12,} {RAW_BYTES_PER_POINT:>12.2f} {'1.0x':>8}")
    for layout, (total_bytes, _, _, _, _, _) in results.items():
        print(f"  {layout:<12} {total_bytes:>12,} {total_bytes / points:>12.2f} {raw / total_bytes:>7.1f}x")
    print("  (paper: 1.37 bytes/point, about 12x)")

    _, _, _, value_stats, time_stats, time_bits = results[SHARED]
    print("\nValues by channel (identical in both layouts)")
    print(f"  {'channel':<10} {'bits/value':>10} {'repeat':>8} {'reuse':>8} {'new':>8} {'avg reuse':>10} {'avg new':>9}")
    for c in channels:
        s = value_stats[c]
        n = sum(x["count"] for x in s.values())
        bits = sum(x["bits"] for x in s.values())
        changed = n - s["first"]["count"]
        avg = lambda case: s[case]["bits"] / s[case]["count"] if s[case]["count"] else 0.0
        print(f"  {c:<10} {bits / n:>10.2f} {pct(s['repeat']['count'], changed):>7.1f}% "
              f"{pct(s['reuse']['count'], changed):>7.1f}% {pct(s['new']['count'], changed):>7.1f}% "
              f"{avg('reuse'):>10.1f} {avg('new'):>9.1f}")
    print("  (paper: 51% repeat, 30% reuse averaging 26.6 bits, 19% new averaging 36.9 bits)")

    total_dods = sum(time_stats.values())
    print(f"\nTimestamps (shared layout): {time_bits / samples:.2f} bits per sample")
    print("  share of each delta-of-delta bucket:")
    for b in BUCKET_NAMES:
        print(f"  {b:<8} {pct(time_stats[b], total_dods):>6.1f}%")
    print("  (paper: about 96% in the zero bucket)")


if __name__ == "__main__":
    main()
