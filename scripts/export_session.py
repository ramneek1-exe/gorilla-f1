"""Download one session with FastF1 and save it to data/.

Usage (from the project folder):

    python -m scripts.export_session 2025 Monza R

Arguments are the season, the event name (or round number) and the session
("R" race, "Q" qualifying, "FP1", ...). This is the only script that needs
FastF1 and an F1 TV login. It prompts for the F1 account email and password
the first time; FastF1 then keeps a sign-in token outside this project.
Never put the password in any file in this repository.
"""

import argparse
import os

from gorilla.dataset import DATA_DIR, dataset_filename, load_laps, save_laps
from gorilla.ingest import load_session, session_laps
from gorilla.values import float_to_bits


def same_values(a, b):
    """Bit-for-bit comparison, so NaN and -0.0 are compared correctly too."""
    return len(a) == len(b) and all(float_to_bits(x) == float_to_bits(y) for x, y in zip(a, b))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("year", type=int)
    parser.add_argument("event")
    parser.add_argument("session")
    args = parser.parse_args()
    event = int(args.event) if args.event.isdigit() else args.event

    session = load_session(args.year, event, args.session)
    laps, rounded = session_laps(session)
    if not laps:
        raise SystemExit("No laps with car data found for this session.")
    if rounded:
        print(f"Warning: {rounded} timestamps were not whole milliseconds and were rounded.")

    meta = {"year": args.year, "event": str(session.event["EventName"]), "session": session.name}
    path = os.path.join(DATA_DIR, dataset_filename(meta["year"], meta["event"], meta["session"]))
    save_laps(path, laps, meta)

    # Read the file back and make sure nothing changed on the way to disk.
    _, reloaded = load_laps(path)
    same = len(reloaded) == len(laps) and all(
        a.driver == b.driver and a.lap_number == b.lap_number
        and a.timestamps == b.timestamps
        and a.channels.keys() == b.channels.keys()
        and all(same_values(a.channels[c], b.channels[c]) for c in a.channels)
        for a, b in zip(laps, reloaded)
    )
    if not same:
        raise SystemExit(f"Saved file {path} does not match the downloaded data.")

    samples = sum(len(lap.timestamps) for lap in laps)
    size_mb = os.path.getsize(path) / 1_000_000
    print(f"\nSaved {meta['year']} {meta['event']} ({meta['session']})")
    print(f"  {len({lap.driver for lap in laps})} drivers, {len(laps)} laps, {samples:,} samples")
    print(f"  {os.path.relpath(path)} ({size_mb:.1f} MB), verified")


if __name__ == "__main__":
    main()
