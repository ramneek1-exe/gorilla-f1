"""Control experiment: the same F1 values with perfectly regular timestamps.

Usage (from the project folder):

    python -m scripts.synthetic_control

The Gorilla paper's data arrives at fixed intervals, so 96% of its timestamps
cost one bit. F1 samples arrive about every 240 ms but irregularly. This
control keeps every real value and sample count but replaces each lap's
timestamps with an exact 240 ms grid, which recreates the paper's
conditions. Comparing it with the real data isolates the cost of irregular
timestamps. Results go to results/experiments/7_synthetic_control.csv.
"""

import csv
import os

from gorilla.block import PER_CHANNEL, SHARED, encode_block
from gorilla.dataset import list_datasets, load_laps
from gorilla.timestamps import BUCKET_NAMES

from .experiments import OUT_DIR, short_name

INTERVAL_MS = 240  # the median gap between samples in the real data


def regular(timestamps):
    return [timestamps[0] + INTERVAL_MS * i for i in range(len(timestamps))]

# encode every lap in both layouts and total the sizes and timestamp stats.
def measure(laps, make_timestamps):
    totals = {SHARED: 0, PER_CHANNEL: 0, "time_bits": 0, "samples": 0}
    buckets = {b: 0 for b in BUCKET_NAMES}
    for lap in laps:
        ts = make_timestamps(lap.timestamps)
        for layout in (SHARED, PER_CHANNEL):
            _, st = encode_block(ts, lap.channels, layout)
            totals[layout] += st["total_bytes"]
            if layout == SHARED:
                totals["time_bits"] += st["streams"]["_time"]
                for b, n in st["time"].items():
                    buckets[b] += n
        totals["samples"] += len(ts)
    totals["zero_pct"] = 100.0 * buckets["zero"] / sum(buckets.values())
    return totals


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    rows, sums = [], {}
    for path, meta in list_datasets():
        _, laps = load_laps(path)
        points = sum(len(lap.timestamps) for lap in laps) * len(laps[0].channels)
        for label, fn in (("real timestamps", lambda t: t), ("regular 240 ms", regular)):
            m = measure(laps, fn)
            s = sums.setdefault(label, {"points": 0, SHARED: 0, PER_CHANNEL: 0, "time_bits": 0, "samples": 0, "zero": 0.0})
            s["points"] += points
            for k in (SHARED, PER_CHANNEL, "time_bits", "samples"):
                s[k] += m[k]
            s["zero"] += m["zero_pct"] * m["samples"]
            rows.append([short_name(meta), label, f"{m['time_bits'] / m['samples']:.2f}", f"{m['zero_pct']:.1f}",
                         f"{m[PER_CHANNEL] / points:.3f}", f"{m[SHARED] / points:.3f}"])
        print(f"{short_name(meta)} done")
    for label, s in sums.items():
        rows.append(["All races", label, f"{s['time_bits'] / s['samples']:.2f}", f"{s['zero'] / s['samples']:.1f}",
                     f"{s[PER_CHANNEL] / s['points']:.3f}", f"{s[SHARED] / s['points']:.3f}"])
    with open(os.path.join(OUT_DIR, "7_synthetic_control.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["race", "timestamps", "bits_per_timestamp", "one_bit_pct",
                    "paper_layout_bytes_per_point", "shared_layout_bytes_per_point"])
        w.writerows(rows)
    print("\nAll races:")
    print(f"  {'timestamps':<16} {'bits/ts':>8} {'1-bit %':>8} {'paper layout':>13} {'shared':>8}")
    for r in rows[-2:]:
        print(f"  {r[1]:<16} {r[2]:>8} {r[3]:>8} {r[4]:>13} {r[5]:>8}")


if __name__ == "__main__":
    main()
