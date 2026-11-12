"""Saved race datasets.

Downloading telemetry through FastF1 needs an F1 TV account, so each race is
downloaded once and saved as a plain data file in data/. Everything else in
the project (experiments, queries, the demo) reads these files, so it runs
offline and without any login.

File format: a gzip-compressed CSV.
  line 1:    # {"year": 2025, "event": "Italian Grand Prix", "session": "Race"}
  line 2:    driver,lap,time_ms,Speed,RPM,nGear,Throttle,Brake,DRS
  then one row per sample, ordered by driver, lap and time.

Values are written with repr(), which Python guarantees reads back as the
exact same float, so saving and loading never changes a value. gzip here is
only how the input data is stored on disk; it is not part of the system
being evaluated.
"""

import csv
import gzip
import json
import os
import re
import unicodedata

from .ingest import LapData

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def dataset_filename(year, event, session):
    """e.g. (2025, "Italian Grand Prix", "Race") -> "2025_italian_grand_prix_race.csv.gz"."""
    text = unicodedata.normalize("NFKD", f"{year} {event} {session}")
    text = text.encode("ascii", "ignore").decode("ascii")  # "São" -> "Sao"
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return f"{slug}.csv.gz"


def save_laps(path, laps, meta):
    """Write a list of LapData to a dataset file. meta is a small dict (year, event, session)."""
    if not laps:
        raise ValueError("no laps to save")
    channels = list(laps[0].channels)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with gzip.open(path, "wt", newline="", encoding="utf-8") as f:
        f.write("# " + json.dumps(meta) + "\n")
        writer = csv.writer(f)
        writer.writerow(["driver", "lap", "time_ms"] + channels)
        for lap in laps:
            columns = [lap.channels[c] for c in channels]
            for i, t in enumerate(lap.timestamps):
                writer.writerow([lap.driver, lap.lap_number, t] + [repr(col[i]) for col in columns])


def read_meta(path):
    """Read only the first line of a dataset file."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        first = f.readline()
    if not first.startswith("# "):
        raise ValueError(f"{path} is not a dataset file")
    return json.loads(first[2:])


def load_laps(path):
    """Read a dataset file. Returns (meta, list of LapData)."""
    with gzip.open(path, "rt", newline="", encoding="utf-8") as f:
        meta = json.loads(f.readline()[2:])
        reader = csv.reader(f)
        header = next(reader)
        channels = header[3:]
        laps, current = [], None
        for row in reader:
            driver, lap_number, t = row[0], int(row[1]), int(row[2])
            if current is None or current.driver != driver or current.lap_number != lap_number:
                current = LapData(driver, lap_number, [], {c: [] for c in channels})
                laps.append(current)
            current.timestamps.append(t)
            for c, v in zip(channels, row[3:]):
                current.channels[c].append(float(v))
    return meta, laps


def list_datasets(data_dir=DATA_DIR):
    """Every dataset in data_dir, sorted by year then event. Returns [(path, meta)]."""
    if not os.path.isdir(data_dir):
        return []
    found = []
    for name in os.listdir(data_dir):
        if name.endswith(".csv.gz"):
            path = os.path.join(data_dir, name)
            try:
                found.append((path, read_meta(path)))
            except (OSError, ValueError):
                continue
    return sorted(found, key=lambda item: (item[1].get("year", 0), item[1].get("event", "")))
