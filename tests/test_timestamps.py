import random

import pytest

from gorilla.bitio import BitReader
from gorilla.timestamps import decode_timestamps, encode_timestamps


def bits_of(data, bit_length):
    """The stream as a string of 0s and 1s, without the padding."""
    r = BitReader(data, bit_length)
    return "".join(str(r.read_bit()) for _ in range(bit_length))


def test_regular_interval_costs_one_bit_per_reading():
    # Like the paper's data: a reading exactly every 60 seconds.
    ts = [1_000_000 + 60_000 * i for i in range(100)]
    data, n_bits, stats = encode_timestamps(ts)
    # 64 for the first, one bucket for the first delta, then 1 bit each.
    first_delta_bits = 36  # 60,000 ms needs the 32-bit bucket
    assert n_bits == 64 + first_delta_bits + 98
    assert stats["zero"] == 98
    assert decode_timestamps(data, n_bits, len(ts)) == ts


def test_exact_bits_for_f1_style_gaps():
    ts = [1000, 1240, 1480, 1500]
    data, n_bits, stats = encode_timestamps(ts)
    bits = bits_of(data, n_bits)

    assert bits[:64] == format(1000, "064b")  # first timestamp in full
    rest = bits[64:]
    # delta 240, dod 240   -> 9-bit bucket: 110 + (240 + 255 = 495)
    # delta 240, dod 0     -> 0
    # delta 20,  dod -220  -> 9-bit bucket: 110 + (-220 + 255 = 35)
    assert rest == "110" + format(495, "09b") + "0" + "110" + format(35, "09b")
    assert stats == {"zero": 1, "7-bit": 0, "9-bit": 2, "12-bit": 0, "32-bit": 0}


@pytest.mark.parametrize("dod, bucket", [
    (0, "zero"), (-63, "7-bit"), (64, "7-bit"), (65, "9-bit"), (-64, "9-bit"),
    (256, "9-bit"), (-256, "12-bit"), (2048, "12-bit"), (2049, "32-bit"),
    (-2048, "32-bit"),
])
def test_bucket_edges(dod, bucket):
    # Two readings set the previous delta to 1000 (that first delta lands in
    # the 12-bit bucket), then the third reading has the given dod.
    ts = [10_000, 11_000, 12_000 + dod]
    data, n_bits, stats = encode_timestamps(ts)
    expected = {name: 0 for name in stats}
    expected["12-bit"] += 1
    expected[bucket] += 1
    assert stats == expected
    assert decode_timestamps(data, n_bits, 3) == ts


def test_round_trip_jittery_samples():
    # Roughly 4 to 5 Hz with jitter and the occasional dropout, like FastF1.
    rng = random.Random(4660)
    ts, t = [], 3_600_000
    for _ in range(5000):
        t += rng.randint(1000, 5000) if rng.random() < 0.02 else rng.randint(180, 320)
        ts.append(t)
    data, n_bits, _ = encode_timestamps(ts)
    assert decode_timestamps(data, n_bits, len(ts)) == ts
    assert n_bits < 64 * len(ts) / 4  # far smaller than raw 64-bit timestamps


def test_timestamps_must_be_ints():
    with pytest.raises(TypeError):
        encode_timestamps([1.5, 2.5])
