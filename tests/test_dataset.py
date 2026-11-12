import math

from gorilla.dataset import dataset_filename, list_datasets, load_laps, read_meta, save_laps
from gorilla.ingest import LapData
from gorilla.values import float_to_bits


def sample_laps():
    return [
        LapData("VER", 1, [1000, 1240, 1480],
                {"Speed": [250.0, 255.0, 0.1 + 0.2], "Brake": [0.0, 1.0, 1.0]}),
        LapData("VER", 2, [1720, 1960], {"Speed": [math.nan, -0.0], "Brake": [0.0, 0.0]}),
        LapData("LEC", 1, [990, 1230], {"Speed": [248.0, 1e-300], "Brake": [1.0, 0.0]}),
    ]


def test_filename():
    assert dataset_filename(2025, "Italian Grand Prix", "Race") == "2025_italian_grand_prix_race.csv.gz"
    assert dataset_filename(2024, "São Paulo Grand Prix", "Qualifying") == "2024_sao_paulo_grand_prix_qualifying.csv.gz"


def test_save_and_load_is_exact(tmp_path):
    path = tmp_path / "race.csv.gz"
    meta = {"year": 2025, "event": "Test Grand Prix", "session": "Race"}
    laps = sample_laps()
    save_laps(path, laps, meta)

    loaded_meta, loaded = load_laps(path)
    assert loaded_meta == meta
    assert [(l.driver, l.lap_number, l.timestamps) for l in loaded] == \
           [(l.driver, l.lap_number, l.timestamps) for l in laps]
    for a, b in zip(laps, loaded):
        for c in a.channels:
            # Bit-for-bit, so 0.1 + 0.2, NaN and -0.0 must all survive unchanged.
            assert [float_to_bits(x) for x in a.channels[c]] == [float_to_bits(x) for x in b.channels[c]]


def test_list_datasets_sorted_by_year_then_event(tmp_path):
    laps = sample_laps()
    for year, event in [(2025, "Monaco Grand Prix"), (2024, "Belgian Grand Prix"), (2025, "Italian Grand Prix")]:
        meta = {"year": year, "event": event, "session": "Race"}
        save_laps(tmp_path / dataset_filename(year, event, "Race"), laps, meta)
    (tmp_path / "notes.txt").write_text("not a dataset")

    found = list_datasets(tmp_path)
    assert [(m["year"], m["event"]) for _, m in found] == [
        (2024, "Belgian Grand Prix"), (2025, "Italian Grand Prix"), (2025, "Monaco Grand Prix")]
    assert read_meta(found[0][0])["event"] == "Belgian Grand Prix"
