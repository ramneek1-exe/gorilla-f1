import pandas as pd

from gorilla.ingest import split_into_laps, timedelta_to_ms


def ms(x):
    return pd.to_timedelta(x, unit="ms")


def fake_car_data():
    # Shaped like FastF1's session.car_data[...]: one row per sample.
    times = [1000, 1240, 1480, 1730, 1990, 2210, 2470, 2700, 2950]
    return pd.DataFrame({
        "SessionTime": [ms(t) for t in times],
        "Speed": [250, 255, 260, 262, 240, 200, 180, 185, 190],
        "RPM": [11000, 11100, 11200, 11250, 10800, 9800, 9500, 9600, 9700],
        "nGear": [7, 7, 7, 7, 6, 5, 4, 4, 4],
        "Throttle": [100, 100, 100, 100, 0, 0, 30, 60, 90],
        "Brake": [False, False, False, False, True, True, False, False, False],
        "DRS": [12, 12, 12, 12, 8, 8, 8, 8, 8],
    })


def fake_laps():
    return pd.DataFrame({
        "Driver": ["VER", "VER", "VER"],
        "DriverNumber": ["1", "1", "1"],
        "LapNumber": [1.0, 2.0, 3.0],
        "LapStartTime": [ms(1000), ms(1990), pd.NaT],   # lap 3 has no start time
        "Time": [ms(1990), ms(3000), ms(4000)],
    })


def test_samples_are_split_by_lap_boundaries():
    laps, rounded = split_into_laps(fake_car_data(), fake_laps(), "VER")
    assert [lap.lap_number for lap in laps] == [1, 2]   # lap 3 skipped
    assert laps[0].timestamps == [1000, 1240, 1480, 1730]   # 1990 starts lap 2
    assert laps[1].timestamps == [1990, 2210, 2470, 2700, 2950]
    assert rounded == 0
    assert all(lap.driver == "VER" for lap in laps)


def test_channels_become_floats_and_brake_becomes_0_or_1():
    laps, _ = split_into_laps(fake_car_data(), fake_laps(), "VER")
    lap2 = laps[1]
    assert lap2.channels["Brake"] == [1.0, 1.0, 0.0, 0.0, 0.0]
    assert lap2.channels["Speed"] == [240.0, 200.0, 180.0, 185.0, 190.0]
    assert all(isinstance(v, float) for values in lap2.channels.values() for v in values)
    assert list(lap2.channels) == ["Speed", "RPM", "nGear", "Throttle", "Brake", "DRS"]


def test_rounding_to_milliseconds_is_counted():
    series = pd.Series(pd.to_timedelta([1_000_000, 1_240_400], unit="us"))
    values, rounded = timedelta_to_ms(series)
    assert values == [1000, 1240]
    assert rounded == 1
