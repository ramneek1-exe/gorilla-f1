import random

import pytest

from gorilla.block import (
    PER_CHANNEL,
    SHARED,
    TIME_STREAM,
    decode_block,
    decode_channel,
    encode_block,
    read_header,
)


def fake_lap(n=400, seed=4660):
    """One lap of F1-like telemetry: jittery ~4 Hz timestamps and six channels."""
    rng = random.Random(seed)
    t, timestamps = 5_000_000, []
    speed, rpm, gear = 120.0, 9000.0, 3.0
    channels = {c: [] for c in ["Speed", "RPM", "nGear", "Throttle", "Brake", "DRS"]}
    for i in range(n):
        t += rng.randint(180, 320)
        timestamps.append(t)
        braking = 150 <= i % 200 < 170
        speed = max(70.0, min(330.0, speed + (-25 if braking else rng.randint(0, 4))))
        rpm = max(6000.0, min(12500.0, rpm + rng.randint(-150, 150)))
        if rng.random() < 0.03:
            gear = float(max(1, min(8, int(gear) + rng.choice([-1, 1]))))
        channels["Speed"].append(float(round(speed)))
        channels["RPM"].append(float(round(rpm)))
        channels["nGear"].append(gear)
        channels["Throttle"].append(0.0 if braking else 100.0)
        channels["Brake"].append(1.0 if braking else 0.0)
        channels["DRS"].append(12.0 if 40 <= i % 200 < 90 else 8.0)
    return timestamps, channels


@pytest.mark.parametrize("layout", [SHARED, PER_CHANNEL])
def test_round_trip(layout):
    timestamps, channels = fake_lap()
    block, _ = encode_block(timestamps, channels, layout)
    ts, decoded = decode_block(block)
    assert ts == timestamps
    assert decoded == channels


@pytest.mark.parametrize("layout", [SHARED, PER_CHANNEL])
def test_decode_one_channel(layout):
    timestamps, channels = fake_lap()
    block, _ = encode_block(timestamps, channels, layout)
    ts, speed = decode_channel(block, "Speed")
    assert ts == timestamps
    assert speed == channels["Speed"]
    with pytest.raises(KeyError):
        decode_channel(block, "Gearbox")


def test_header_lists_every_stream():
    timestamps, channels = fake_lap()
    block, stats = encode_block(timestamps, channels, SHARED)
    header = read_header(block)
    assert header["layout"] == SHARED
    assert header["count"] == len(timestamps)
    assert list(header["streams"]) == [TIME_STREAM] + list(channels)
    # The last stream ends exactly at the end of the block.
    offset, bits = list(header["streams"].values())[-1]
    assert offset + (bits + 7) // 8 == len(block) == stats["total_bytes"]


def test_shared_timestamps_are_smaller():
    timestamps, channels = fake_lap()
    shared, s1 = encode_block(timestamps, channels, SHARED)
    per_channel, s2 = encode_block(timestamps, channels, PER_CHANNEL)
    # Same value bits either way; the difference is 6 timestamp streams vs 1.
    assert len(shared) < len(per_channel)
    for c in channels:
        assert s1["values"][c] == s2["values"][c]


def test_block_much_smaller_than_raw():
    timestamps, channels = fake_lap()
    block, _ = encode_block(timestamps, channels, SHARED)
    raw = len(timestamps) * len(channels) * 16
    assert len(block) < raw / 5


def test_mismatched_lengths_rejected():
    with pytest.raises(ValueError):
        encode_block([1, 2, 3], {"Speed": [1.0, 2.0]})
