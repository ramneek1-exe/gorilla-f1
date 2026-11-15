from gorilla.block import SHARED, encode_block
from gorilla.ingest import LapData
from scripts.experiments import bucket_cost, group_laps, timestamp_ablation

from .test_block import fake_lap


def test_bucket_costs_match_the_paper():
    assert [bucket_cost(d) for d in (0, 64, -63, 65, 256, -256, 2048, 2049)] == [1, 9, 9, 12, 12, 16, 16, 36]


def test_ablation_count_matches_the_real_encoder():
    timestamps, channels = fake_lap()
    lap = LapData("VER", 1, timestamps, channels)
    dod_bits, delta_bits = timestamp_ablation([lap])
    _, stats = encode_block(timestamps, channels, SHARED)
    assert dod_bits == stats["streams"]["_time"]
    assert delta_bits > dod_bits


def test_group_laps_per_driver():
    laps = [LapData(d, n, [n], {"Speed": [1.0]}) for d in ("VER", "LEC") for n in range(1, 6)]
    groups = group_laps(laps, 2)
    assert [[(l.driver, l.lap_number) for l in g] for g in groups] == [
        [("VER", 1), ("VER", 2)], [("VER", 3), ("VER", 4)], [("VER", 5)],
        [("LEC", 1), ("LEC", 2)], [("LEC", 3), ("LEC", 4)], [("LEC", 5)]]
    assert [len(g) for g in group_laps(laps, None)] == [5, 5]
