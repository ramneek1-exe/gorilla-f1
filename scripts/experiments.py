"""Run every experiment on every saved race and write tables and charts.

Usage (from the project folder):

    python -m scripts.experiments

Results go to results/experiments/: one CSV per experiment, the charts as
PNG files, and summary.txt with the headline numbers. The timing
experiments use one race (by default the first in the list); choose another
with --timing-race, using its number from the race menu.

Experiments (see the Gorilla paper, Sections 4.1 and 5):
  1. compression  size of every race in each format, against raw 16 bytes/point
  2. channels     bits per value and the three XOR cases, per channel
  3. timestamps   how often each delta-of-delta bucket is used
  4. block size   compression and lap-query cost with 1 to all laps per block
  5. ablations    what window reuse and delta-of-delta each save
  6. speed        encode/decode throughput and query latency
"""

import argparse
import csv
import gzip
import os
import random
import statistics
import time

from gorilla.block import PER_CHANNEL, SHARED, decode_block, decode_channel, encode_block
from gorilla.dataset import list_datasets, load_laps
from gorilla.store import GORILLA, RAW, Store, encode_raw_block
from gorilla.timestamps import BUCKET_NAMES, BUCKETS
from gorilla.values import ValueEncoder

try:
    from compression import zstd as _zstd  # Python 3.14+

    def zstd_compress(data):
        return _zstd.compress(data, level=19)
except ImportError:
    try:
        import zstandard as _zstandard

        def zstd_compress(data):
            return _zstandard.ZstdCompressor(level=19).compress(data)
    except ImportError:
        zstd_compress = None

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results", "experiments")
RAW_BYTES_PER_POINT = 16
PAPER_BYTES_PER_POINT = 1.37
PAPER_CASES = {"repeat": 51.0, "reuse": 30.0, "new": 19.0}
PAPER_ZERO_BUCKET = 96.0
CASES = ("repeat", "reuse", "new")
BLOCK_SIZES = [1, 2, 5, 10, None]  # laps per block; None = the whole race for each driver

# create a short name for a race.
def short_name(meta):
    event = meta["event"].replace(" Grand Prix", "")
    return f"{event} {meta['year']}"

# calculate percentage.
def pct(part, whole):
    return 100.0 * part / whole if whole else 0.0


# 1-3: compression, channels, timestamps -------------------------------------

# measure the size of one race in every format, plus the encoder statistics.
def measure_race(laps):
    channels = list(laps[0].channels)
    samples = sum(len(lap.timestamps) for lap in laps)
    r = {
        "samples": samples,
        "points": samples * len(channels),
        "raw16": samples * len(channels) * RAW_BYTES_PER_POINT,
        "raw_store": 0, "gzip_lap": 0, "zstd_lap": 0,
        "gorilla_shared": 0, "gorilla_per_channel": 0, "time_bits": 0,
        "values": {c: {k: {"count": 0, "bits": 0} for k in ("first",) + CASES} for c in channels},
        "time": {b: 0 for b in BUCKET_NAMES},
    }
    raw_blocks = []
    for lap in laps:
        raw = encode_raw_block(lap.timestamps, lap.channels)
        raw_blocks.append(raw)
        r["raw_store"] += len(raw)
        r["gzip_lap"] += len(gzip.compress(raw, compresslevel=9))
        if zstd_compress:
            r["zstd_lap"] += len(zstd_compress(raw))

        _, st = encode_block(lap.timestamps, lap.channels, SHARED)
        r["gorilla_shared"] += st["total_bytes"]
        r["time_bits"] += st["streams"]["_time"]
        for c in channels:
            for case, s in st["values"][c].items():
                r["values"][c][case]["count"] += s["count"]
                r["values"][c][case]["bits"] += s["bits"]
        for b, n in st["time"].items():
            r["time"][b] += n

        _, st = encode_block(lap.timestamps, lap.channels, PER_CHANNEL)
        r["gorilla_per_channel"] += st["total_bytes"]

    whole = b"".join(raw_blocks)
    r["gzip_race"] = len(gzip.compress(whole, compresslevel=9))
    r["zstd_race"] = len(zstd_compress(whole)) if zstd_compress else 0
    return r


# 4: block size ----------------------------------------------------------------

# helper function to group laps into blocks.
def group_laps(laps, laps_per_block):
    # Join each driver's consecutive laps into blocks of `laps_per_block` laps.
    by_driver = {}
    for lap in laps:
        by_driver.setdefault(lap.driver, []).append(lap)
    groups = []
    for driver_laps in by_driver.values():
        size = laps_per_block or len(driver_laps)
        for i in range(0, len(driver_laps), size):
            groups.append(driver_laps[i:i + size])
    return groups

# helper function to merge a group of laps.
def merge(group):
    timestamps = [t for lap in group for t in lap.timestamps]
    channels = {c: [v for lap in group for v in lap.channels[c]] for c in group[0].channels}
    return timestamps, channels

# helper function to calculate block size in bytes.
def block_size_bytes(laps, laps_per_block):
    return sum(encode_block(*merge(g), SHARED)[1]["total_bytes"] for g in group_laps(laps, laps_per_block))

# helper function to calculate block size in milliseconds.
def block_size_query_ms(laps, laps_per_block, rng, n_queries=40):
    # Median time to answer one lap's Speed when that lap sits in a bigger block.
    blocks = []
    for g in group_laps(laps, laps_per_block):
        block, _ = encode_block(*merge(g), SHARED)
        start = 0
        for lap in g:
            blocks.append((block, start, start + len(lap.timestamps), lap))
            start += len(lap.timestamps)
    times = []
    for block, a, b, lap in rng.sample(blocks, min(n_queries, len(blocks))):
        t0 = time.perf_counter()
        _, values = decode_channel(block, "Speed")
        answer = values[a:b]
        times.append((time.perf_counter() - t0) * 1000)
        assert answer == lap.channels["Speed"]
    return statistics.median(times)


# 5: ablations ------------------------------------------------------------------

# helper function to calculate bucket cost.
def bucket_cost(dod):
    # Bits the timestamp encoder spends on one delta-of-delta value.
    if dod == 0:
        return 1
    for low, high, _prefix, prefix_len, width in BUCKETS:
        if low <= dod <= high:
            return prefix_len + width
    return 4 + 32

# helper function to calculate timestamp ablation.
def timestamp_ablation(laps):
    # Bits for timestamps with delta-of-delta (the paper) and with plain deltas.
    dod_bits = delta_bits = 0
    for lap in laps:
        ts = lap.timestamps
        dod_bits += 64
        delta_bits += 64
        prev_delta = 0
        for a, b in zip(ts, ts[1:]):
            delta = b - a
            dod_bits += bucket_cost(delta - prev_delta)
            delta_bits += bucket_cost(delta)  # same buckets, previous gap ignored
            prev_delta = delta
    return dod_bits, delta_bits

# helper function to calculate value bits.
def value_bits(laps, channel, reuse_window):
    total = 0
    for lap in laps:
        enc = ValueEncoder(reuse_window=reuse_window)
        for v in lap.channels[channel]:
            enc.add(v)
        total += enc.writer.bit_length
    return total


# 6: speed -------------------------------------------------------------------------

# helper function to calculate speed.
def speed(laps, meta, rng, n_queries=300):
    points = sum(len(lap.timestamps) for lap in laps) * len(laps[0].channels)

    t0 = time.perf_counter()
    blocks = [encode_block(lap.timestamps, lap.channels, SHARED)[0] for lap in laps]
    encode_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    for block in blocks:
        decode_block(block)
    decode_s = time.perf_counter() - t0

    stores = {fmt: Store.build(laps, meta, fmt) for fmt in (GORILLA, RAW)}
    channels = list(laps[0].channels)
    keys = [(lap.driver, lap.lap_number, rng.choice(channels)) for lap in rng.choices(laps, k=n_queries)]
    latency = {}
    for fmt, store in stores.items():
        times = []
        for key in keys:
            t1 = time.perf_counter()
            store.get(*key)
            times.append((time.perf_counter() - t1) * 1000)
        times.sort()
        latency[fmt] = (statistics.median(times), times[int(len(times) * 0.95)])
    return {
        "points": points,
        "encode_points_per_s": points / encode_s,
        "decode_points_per_s": points / decode_s,
        "query_median_ms": latency[GORILLA][0], "query_p95_ms": latency[GORILLA][1],
        "raw_query_median_ms": latency[RAW][0], "raw_query_p95_ms": latency[RAW][1],
    }


# Output ------------------------------------------------------------------------------

# helper function to write csv with header and rows (blocks)
def write_csv(name, header, rows):
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--timing-race", type=int, default=1,
                        help="race number (from the race menu) used for the timing experiments")
    parser.add_argument("--no-charts", action="store_true", help="write the CSV files only")
    args = parser.parse_args()

    datasets = list_datasets()
    if not datasets:
        raise SystemExit("No races found in data/.")
    os.makedirs(OUT_DIR, exist_ok=True)
    rng = random.Random(4660)
    if zstd_compress is None:
        print("zstd is not available, so the zstd columns will be 0 "
              "(use Python 3.14+ or pip install zstandard).")

    races = []
    for i, (path, meta) in enumerate(datasets, start=1):
        print(f"[{i}/{len(datasets)}] {short_name(meta)}: loading", end="", flush=True)
        _, laps = load_laps(path)
        print(", sizes", end="", flush=True)
        m = measure_race(laps)
        print(", block sizes", end="", flush=True)
        m["block_bytes"] = {k: block_size_bytes(laps, k) for k in BLOCK_SIZES}
        print(", ablations", end="", flush=True)
        m["dod_bits"], m["delta_bits"] = timestamp_ablation(laps)
        assert m["dod_bits"] == m["time_bits"], "timestamp bit count does not match the encoder"
        m["no_reuse_bits"] = {c: value_bits(laps, c, False) for c in laps[0].channels}
        m["meta"], m["name"] = meta, short_name(meta)
        if i == args.timing_race:
            print(", timing", end="", flush=True)
            m["speed"] = speed(laps, meta, rng)
            m["block_query_ms"] = {k: block_size_query_ms(laps, k, rng) for k in BLOCK_SIZES}
        races.append(m)
        print(" done")

    channels = list(races[0]["values"])
    timing = next(r for r in races if "speed" in r)
    total = lambda key: sum(r[key] for r in races)
    points_all = total("points")

    # Experiments

    # 1. compression per race
    fmt_cols = ["raw16", "raw_store", "gzip_lap", "zstd_lap", "gzip_race", "zstd_race",
                "gorilla_per_channel", "gorilla_shared"]
    rows = []
    for r in races + [dict({k: total(k) for k in fmt_cols + ["samples", "points"]}, name="All races")]:
        rows.append([r["name"], r["samples"], r["points"]]
                    + [f"{r[k] / r['points']:.3f}" for k in fmt_cols]
                    + [f"{r['raw16'] / r['gorilla_shared']:.1f}", f"{r['raw_store'] / r['gorilla_shared']:.1f}"])
    write_csv("1_compression.csv",
              ["race", "samples", "points"] + [f"{k}_bytes_per_point" for k in fmt_cols]
              + ["ratio_vs_raw16", "ratio_vs_raw_store"], rows)

    # 2. channels (all races together)
    def channel_totals(c):
        s = {case: {"count": sum(r["values"][c][case]["count"] for r in races),
                    "bits": sum(r["values"][c][case]["bits"] for r in races)} for case in ("first",) + CASES}
        n = sum(x["count"] for x in s.values())
        return s, n, sum(x["bits"] for x in s.values())

    rows, chan = [], {}
    for c in channels:
        s, n, bits = channel_totals(c)
        changed = n - s["first"]["count"]
        avg = lambda case: s[case]["bits"] / s[case]["count"] if s[case]["count"] else 0.0
        chan[c] = {"bits_per_value": bits / n, **{case: pct(s[case]["count"], changed) for case in CASES},
                   "avg_reuse": avg("reuse"), "avg_new": avg("new")}
        rows.append([c, n, f"{bits / n:.2f}"] + [f"{chan[c][case]:.1f}" for case in CASES]
                    + [f"{avg('reuse'):.1f}", f"{avg('new'):.1f}"])
    rows.append(["Paper (Facebook)", "", "", "51.0", "30.0", "19.0", "26.6", "36.9"])
    write_csv("2_channels.csv", ["channel", "values", "bits_per_value", "repeat_pct", "reuse_pct", "new_pct",
                                 "avg_bits_reuse", "avg_bits_new"], rows)

    # 3. timestamps
    rows = []
    for r in races:
        n = sum(r["time"].values())
        rows.append([r["name"], f"{r['time_bits'] / r['samples']:.2f}"] + [f"{pct(r['time'][b], n):.1f}" for b in BUCKET_NAMES])
    all_time = {b: sum(r["time"][b] for r in races) for b in BUCKET_NAMES}
    n_all = sum(all_time.values())
    ts_bits_per_sample = total("time_bits") / total("samples")
    rows.append(["All races", f"{ts_bits_per_sample:.2f}"] + [f"{pct(all_time[b], n_all):.1f}" for b in BUCKET_NAMES])
    write_csv("3_timestamps.csv", ["race", "bits_per_timestamp"] + [f"{b}_pct" for b in BUCKET_NAMES], rows)

    # 4. block size
    label = lambda k: "whole race" if k is None else str(k)
    block_rows = []
    for k in BLOCK_SIZES:
        size = sum(r["block_bytes"][k] for r in races)
        block_rows.append([label(k), f"{size / points_all:.3f}", f"{timing['block_query_ms'][k]:.2f}"])
    write_csv("4_block_size.csv", ["laps_per_block", "bytes_per_point_all_races",
                                   f"median_lap_query_ms_{timing['name'].replace(' ', '_')}"], block_rows)

    # 5. ablations
    reuse_rows = []
    for c in channels:
        with_reuse = sum(sum(r["values"][c][k]["bits"] for k in ("first",) + CASES) for r in races)
        without = sum(r["no_reuse_bits"][c] for r in races)
        n = channel_totals(c)[1]
        reuse_rows.append([c, f"{with_reuse / n:.2f}", f"{without / n:.2f}", f"{pct(without - with_reuse, without):.1f}"])
    dod_bits, delta_bits = total("dod_bits"), total("delta_bits")
    write_csv("5_ablations.csv", ["series", "bits_per_value_paper", "bits_per_value_without", "saving_pct"],
              [[f"{c} (window reuse)", *rest] for c, *rest in reuse_rows]
              + [["Timestamps (delta-of-delta vs plain delta)", f"{dod_bits / total('samples'):.2f}",
                  f"{delta_bits / total('samples'):.2f}", f"{pct(delta_bits - dod_bits, delta_bits):.1f}"]])

    # 6. speed
    sp = timing["speed"]
    write_csv("6_speed.csv", ["race", "points", "encode_points_per_s", "decode_points_per_s",
                              "query_median_ms", "query_p95_ms", "raw_query_median_ms", "raw_query_p95_ms"],
              [[timing["name"], sp["points"], f"{sp['encode_points_per_s']:.0f}", f"{sp['decode_points_per_s']:.0f}",
                f"{sp['query_median_ms']:.3f}", f"{sp['query_p95_ms']:.3f}",
                f"{sp['raw_query_median_ms']:.3f}", f"{sp['raw_query_p95_ms']:.3f}"]])

    # summary
    bpp = lambda key: total(key) / points_all
    lines = [
        f"Races: {len(races)}, samples: {total('samples'):,}, points: {points_all:,}",
        "",
        "Bytes per point (all races)        paper: 1.37",
        f"  raw (paper's baseline)           {RAW_BYTES_PER_POINT:.2f}",
        f"  uncompressed store               {bpp('raw_store'):.2f}",
        f"  gzip -9, per lap                 {bpp('gzip_lap'):.2f}",
        f"  zstd -19, per lap                {bpp('zstd_lap'):.2f}",
        f"  gzip -9, whole race              {bpp('gzip_race'):.2f}",
        f"  zstd -19, whole race             {bpp('zstd_race'):.2f}",
        f"  Gorilla, paper layout            {bpp('gorilla_per_channel'):.2f}",
        f"  Gorilla, shared timestamps       {bpp('gorilla_shared'):.2f}  "
        f"({RAW_BYTES_PER_POINT / bpp('gorilla_shared'):.1f}x vs raw, {total('raw_store') / total('gorilla_shared'):.1f}x vs uncompressed store)",
        "",
        "Values by channel: bits/value, repeat / reuse / new   paper: 51 / 30 / 19",
    ] + [f"  {c:<9} {chan[c]['bits_per_value']:5.2f}   {chan[c]['repeat']:4.1f} / {chan[c]['reuse']:4.1f} / {chan[c]['new']:4.1f}"
         for c in channels] + [
        "",
        f"Timestamps: {ts_bits_per_sample:.2f} bits each, {pct(all_time['zero'], n_all):.1f}% in the 1-bit case (paper: 96%)",
        "",
        "Block size (laps per block -> bytes/point, lap query ms):",
    ] + [f"  {a:<11} {b} B/pt, {c} ms" for a, b, c in block_rows] + [
        "",
        "Ablations:",
    ] + [f"  window reuse saves {row[3]}% on {row[0]}" for row in reuse_rows] + [
        f"  delta-of-delta saves {pct(delta_bits - dod_bits, delta_bits):.1f}% vs plain delta on timestamps",
        "",
        f"Speed ({timing['name']}): encode {sp['encode_points_per_s']:,.0f} points/s, "
        f"decode {sp['decode_points_per_s']:,.0f} points/s",
        f"  one-channel lap query: compressed {sp['query_median_ms']:.2f} ms median "
        f"({sp['query_p95_ms']:.2f} p95), uncompressed {sp['raw_query_median_ms']:.3f} ms",
    ]
    with open(os.path.join(OUT_DIR, "summary.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines))

    if not args.no_charts:
        from .charts import draw_all
        draw_all(OUT_DIR, races, channels, chan, all_time, block_rows, reuse_rows,
                 (dod_bits, delta_bits, total("samples")), timing["name"])
    print(f"\nWrote results to {os.path.relpath(OUT_DIR)}/")


if __name__ == "__main__":
    main()
