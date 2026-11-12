"""Load F1 car telemetry with FastF1 and split it into laps.

FastF1 is only used to download the data. Everything after that (turning it
into integer timestamps and float values, splitting by lap) is done here.

We use the raw car data (session.car_data), not FastF1's merged telemetry,
because the merged version interpolates values between samples and would
replace real readings with made-up ones.
"""

from dataclasses import dataclass, field
import os

import pandas as pd

# The car data channels, in the order they are stored in each block.
CHANNELS = ["Speed", "RPM", "nGear", "Throttle", "Brake", "DRS"]


@dataclass
class LapData:
    driver: str          # three-letter code, e.g. "VER"
    lap_number: int
    timestamps: list     # int milliseconds since the session started
    channels: dict = field(default_factory=dict)  # name -> list of floats


def timedelta_to_ms(series):
    """Convert a column of time offsets to integer milliseconds.

    Returns (list of ints, number of values that were not a whole millisecond
    and had to be rounded). The second number lets us report whether
    rounding to milliseconds lost anything.
    """
    micros = (series.dt.total_seconds() * 1_000_000).round()
    ms = (micros / 1000).round().astype("int64")
    not_whole = int((micros % 1000 != 0).sum())
    return ms.tolist(), not_whole


def _channel_values(frame, name):
    column = frame[name]
    if column.dtype == bool:
        return [1.0 if v else 0.0 for v in column]
    return [float(v) for v in column]


def split_into_laps(car_data, laps, driver):
    """Split one car's telemetry into laps.

    car_data: a car's DataFrame from session.car_data
    laps:     that driver's rows from session.laps
    driver:   the driver's three-letter code

    A sample belongs to a lap if LapStartTime <= SessionTime < Time (the
    lap's end). Laps without a start or end time are skipped.

    Returns (list of LapData, number of rounded timestamps).
    """
    channels = [c for c in CHANNELS if c in car_data.columns]
    result, rounded = [], 0

    for _, lap in laps.sort_values("LapNumber").iterrows():
        start, end = lap["LapStartTime"], lap["Time"]
        if pd.isna(start) or pd.isna(end) or pd.isna(lap["LapNumber"]):
            continue
        in_lap = car_data[(car_data["SessionTime"] >= start) & (car_data["SessionTime"] < end)]
        if len(in_lap) < 2:
            continue
        timestamps, n_rounded = timedelta_to_ms(in_lap["SessionTime"])
        rounded += n_rounded
        result.append(LapData(
            driver=driver,
            lap_number=int(lap["LapNumber"]),
            timestamps=timestamps,
            channels={c: _channel_values(in_lap, c) for c in channels},
        ))
    return result, rounded


def load_session(year, event, session_type, cache_dir="cache"):
    """Download (or read from the local cache) a session's laps and car data."""
    import fastf1  # imported here so the rest of the project works without it

    os.makedirs(cache_dir, exist_ok=True)
    fastf1.Cache.configure(cache_dir=cache_dir)
    session = fastf1.get_session(year, event, session_type)
    session.load(laps=True, telemetry=True, weather=False, messages=False)
    return session


def session_laps(session):
    """Every lap of every driver in a loaded session.

    Returns (list of LapData, number of rounded timestamps).
    """
    all_laps, rounded = [], 0
    for number, car_data in session.car_data.items():
        driver_laps = session.laps[session.laps["DriverNumber"] == number]
        if driver_laps.empty:
            continue
        driver = str(driver_laps["Driver"].iloc[0])
        laps, n_rounded = split_into_laps(car_data, driver_laps, driver)
        all_laps.extend(laps)
        rounded += n_rounded
    return all_laps, rounded
