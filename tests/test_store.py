import pytest

from gorilla.ingest import LapData
from gorilla.store import GORILLA, RAW, Store

from .test_block import fake_lap


def fake_race():
    laps = []
    for d, driver in enumerate(["VER", "LEC", "NOR"]):
        for lap in range(1, 6):
            timestamps, channels = fake_lap(n=120, seed=100 * d + lap)
            laps.append(LapData(driver, lap, timestamps, channels))
    return laps


META = {"year": 2025, "event": "Test Grand Prix", "session": "Race"}


@pytest.mark.parametrize("fmt", [GORILLA, RAW])
def test_queries_return_the_original_data(fmt, tmp_path):
    laps = fake_race()
    store = Store.build(laps, META, fmt)
    path = tmp_path / f"race.{fmt}.gstore"
    store.save(path)
    reopened = Store.open(path)

    for s in (store, reopened):
        assert s.meta == META
        assert s.drivers() == ["LEC", "NOR", "VER"]
        assert s.laps("VER") == [1, 2, 3, 4, 5]
        for lap in laps:
            assert s.get(lap.driver, lap.lap_number, "Speed") == (lap.timestamps, lap.channels["Speed"])
            assert s.get_lap(lap.driver, lap.lap_number) == (lap.timestamps, lap.channels)
            wanted = ["RPM", "Brake"]
            assert s.get_channels(lap.driver, lap.lap_number, wanted) == \
                (lap.timestamps, {c: lap.channels[c] for c in wanted})


def test_range_joins_laps_in_order():
    laps = fake_race()
    store = Store.build(laps, META)
    ts, values = store.get_range("LEC", 2, 4, "RPM")
    expected = [lap for lap in laps if lap.driver == "LEC" and 2 <= lap.lap_number <= 4]
    assert ts == [t for lap in expected for t in lap.timestamps]
    assert values == [v for lap in expected for v in lap.channels["RPM"]]


def test_max_value():
    laps = fake_race()
    store = Store.build(laps, META)
    lap = laps[0]
    value, t = store.max_value(lap.driver, lap.lap_number, "Speed")
    assert value == max(lap.channels["Speed"])
    assert lap.channels["Speed"][lap.timestamps.index(t)] == value


def test_compressed_store_is_smaller():
    laps = fake_race()
    assert Store.build(laps, META, GORILLA).size_bytes() * 5 < Store.build(laps, META, RAW).size_bytes()


def test_missing_lap_is_a_clear_error():
    store = Store.build(fake_race(), META)
    with pytest.raises(KeyError, match="lap 99"):
        store.get("VER", 99, "Speed")
