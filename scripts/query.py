"""Query a race through the compressed store.

Usage (from the project folder):

    python -m scripts.query

Pick a race, then ask for any driver, lap and one or more channels
(separated by spaces or commas, e.g. "Speed RPM Throttle"). Each answer is decoded
from the compressed store and checked against an uncompressed store of the
same data, and both lookups are timed.

The first time a race is opened its store is built and saved in results/,
so later runs open instantly.
"""

import os
import re
import statistics
import sys
import time

from gorilla.dataset import load_laps
from gorilla.store import GORILLA, RAW, Store

from .menu import choose_dataset, describe

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")
TIMING_RUNS = 30


def _can_print(text):
    try:
        text.encode(sys.stdout.encoding or "ascii")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


# Block characters for the one-line charts, or plain ASCII where the terminal
# cannot show them (some Windows setups).
SPARK = "▁▂▃▄▅▆▇█" if _can_print("▁▂▃▄▅▆▇█") else " .:-=+*#"


def open_stores(path, meta):
    """Open both stores for a race, building and saving them the first time."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    base = os.path.join(RESULTS_DIR, os.path.basename(path).replace(".csv.gz", ""))
    files = {GORILLA: base + ".gorilla.gstore", RAW: base + ".raw.gstore"}

    if all(os.path.exists(f) for f in files.values()):
        return {fmt: Store.open(f) for fmt, f in files.items()}

    print("Building the stores for this race (first time only) ...")
    _, laps = load_laps(path)
    stores = {}
    for fmt, file in files.items():
        start = time.perf_counter()
        stores[fmt] = Store.build(laps, meta, fmt)
        stores[fmt].save(file)
        print(f"  {fmt:<8} built in {time.perf_counter() - start:.1f} s")
    return stores


def sparkline(values, width=60):
    """A one-line chart of a series, squeezed to `width` characters."""
    if not values:
        return ""
    step = max(1, len(values) / width)
    picked = [values[int(i * step)] for i in range(min(width, len(values)))]
    low, high = min(picked), max(picked)
    if high == low:
        return SPARK[0] * len(picked)
    return "".join(SPARK[int((v - low) / (high - low) * (len(SPARK) - 1))] for v in picked)


def timed(fn, *args):
    """Median time of TIMING_RUNS calls, in milliseconds."""
    times = []
    for _ in range(TIMING_RUNS):
        start = time.perf_counter()
        fn(*args)
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times)


def ask(prompt, valid, show):
    """Ask until the answer is in `valid` (case-insensitive). Empty answer quits."""
    lookup = {str(v).lower(): v for v in valid}
    while True:
        answer = input(prompt).strip()
        if answer == "":
            return None
        if answer.lower() in lookup:
            return lookup[answer.lower()]
        print(f"  Not found. Options: {show}")


def ask_channels(channels):
    """Ask for one or more channels. Empty answer quits. Returns a list in the order given."""
    lookup = {c.lower(): c for c in channels}
    while True:
        answer = input(f"Channels ({', '.join(channels)}): ").strip()
        if answer == "":
            return None
        if answer.lower() == "all":
            return list(channels)
        wanted = [w for w in re.split(r"[\s,&+]+", answer) if w]
        unknown = [w for w in wanted if w.lower() not in lookup]
        if unknown:
            print(f"  Not found: {', '.join(unknown)}. Options: {', '.join(channels)}, or all")
            continue
        picked = []
        for w in wanted:
            if lookup[w.lower()] not in picked:
                picked.append(lookup[w.lower()])
        return picked


def main():
    path, meta = choose_dataset()
    stores = open_stores(path, meta)
    gorilla, raw = stores[GORILLA], stores[RAW]

    print(f"\n{describe(meta)}")
    print(f"  compressed store:   {gorilla.size_bytes():>12,} bytes")
    print(f"  uncompressed store: {raw.size_bytes():>12,} bytes "
          f"({raw.size_bytes() / gorilla.size_bytes():.1f}x larger)")

    drivers = gorilla.drivers()
    channels = gorilla.channels()
    print("\nPress Enter on an empty line to quit.")

    while True:
        print(f"\nDrivers: {', '.join(drivers)}")
        driver = ask("Driver: ", drivers, ", ".join(drivers))
        if driver is None:
            return
        laps = gorilla.laps(driver)
        lap = ask(f"Lap ({laps[0]}-{laps[-1]}): ", laps, f"laps {laps[0]} to {laps[-1]}")
        if lap is None:
            return
        wanted = ask_channels(channels)
        if wanted is None:
            return

        timestamps, values = gorilla.get_channels(driver, lap, wanted)
        same = (timestamps, values) == raw.get_channels(driver, lap, wanted)
        duration = (timestamps[-1] - timestamps[0]) / 1000

        print(f"\n{driver} lap {lap}: {len(timestamps)} samples over {duration:.1f} s")
        for name in wanted:
            v = values[name]
            top = max(range(len(v)), key=v.__getitem__)
            print(f"\n  {name}")
            print(f"  {sparkline(v)}")
            print(f"  min {min(v):g}, max {v[top]:g} "
                  f"(at {(timestamps[top] - timestamps[0]) / 1000:.1f} s into the lap), "
                  f"mean {statistics.fmean(v):.1f}")
        print(f"\n  matches the uncompressed store: {'yes' if same else 'NO'}")
        print(f"  lookup time for {len(wanted)} channel{'s' if len(wanted) > 1 else ''} "
              f"(median of {TIMING_RUNS}): "
              f"compressed {timed(gorilla.get_channels, driver, lap, wanted):.2f} ms, "
              f"uncompressed {timed(raw.get_channels, driver, lap, wanted):.2f} ms")


if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        print()
