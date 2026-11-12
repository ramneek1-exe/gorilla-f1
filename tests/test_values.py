import math
import random
import struct

from gorilla.bitio import BitReader
from gorilla.values import (
    ValueEncoder,
    decode_values,
    encode_values,
    float_to_bits,
)

# A synthetic 19-reading speed trace (km/h): corner exit, straight, braking.
# All values stay between 256 and 511, so only bit positions 12 to 19 (the
# top 8 mantissa bits) can change.
LAP = [262, 267, 272, 276, 280, 284, 290, 296, 300, 302, 302, 302, 303, 303,
       288, 274, 262, 258, 258]


def same_bits(a, b):
    """True if two floats are identical bit for bit (works for NaN and -0.0 too)."""
    return float_to_bits(a) == float_to_bits(b)


def test_lap_segment_cases_and_bit_costs():
    enc = ValueEncoder()
    cases, costs = [], []
    for v in LAP:
        before = enc.writer.bit_length
        counts_before = {k: s["count"] for k, s in enc.stats.items()}
        enc.add(v)
        cases.append(next(k for k, s in enc.stats.items() if s["count"] > counts_before[k]))
        costs.append(enc.writer.bit_length - before)

    assert cases == ["first", "new", "new", "reuse", "reuse", "reuse",
                     "new", "reuse", "reuse", "reuse", "repeat", "repeat",
                     "new", "repeat", "new", "new", "reuse", "reuse", "repeat"]
    assert costs == [64, 17, 18, 7, 7, 7, 18, 7, 7, 7, 1, 1, 14, 1, 17, 18, 7, 7, 1]
    assert enc.writer.bit_length == 226


def test_exact_bits_for_272_to_276():
    # 272 sets a window of bit positions 15 to 19 (15 leading, 44 trailing
    # zeros). 276 differs from 272 only at position 17, which is inside that
    # window, so the encoder writes 10 + 00100.
    data, n_bits, _ = encode_values([267, 272, 276])
    r = BitReader(data, n_bits)
    r.read_bits(64)                      # 267 in full
    r.read_bits(2 + 5 + 6 + 5)           # 272: 11 + header + 5 flip bits
    assert r.read_bits(2) == 0b10        # 276: reuse
    assert r.read_bits(5) == 0b00100     # only position 17 flipped
    assert r.bits_read == n_bits


def test_round_trip_lap():
    data, n_bits, _ = encode_values(LAP)
    assert decode_values(data, n_bits, len(LAP)) == [float(v) for v in LAP]


def test_round_trip_random_and_special_values():
    rng = random.Random(4660)
    values = [0.0, -0.0, 1.0, math.inf, -math.inf, math.nan, 5e-324, 1.7e308, -12.5]
    values += [rng.uniform(-1e6, 1e6) for _ in range(2000)]
    values += [struct.unpack(">d", rng.getrandbits(64).to_bytes(8, "big"))[0] for _ in range(2000)]
    data, n_bits, _ = encode_values(values)
    decoded = decode_values(data, n_bits, len(values))
    assert all(same_bits(a, b) for a, b in zip(values, decoded))


def test_length_64_window():
    # 0x8000...0001 ^ 0x0000...0000 flips the very first and very last bit,
    # so the meaningful length is 64, stored as 0 in the 6-bit field.
    a = struct.unpack(">d", (0).to_bytes(8, "big"))[0]
    b = struct.unpack(">d", (0x8000000000000001).to_bytes(8, "big"))[0]
    data, n_bits, stats = encode_values([a, b, a])
    assert stats["new"]["count"] == 1 and stats["reuse"]["count"] == 1
    assert all(same_bits(x, y) for x, y in zip([a, b, a], decode_values(data, n_bits, 3)))


def test_leading_zeros_are_capped_at_31():
    # 1.0 and the next float up differ only in the last bit: 63 leading zeros,
    # which doesn't fit in 5 bits, so the window starts at 31 instead.
    nxt = math.nextafter(1.0, 2.0)
    data, n_bits, _ = encode_values([1.0, nxt])
    r = BitReader(data, n_bits)
    r.read_bits(64)
    assert r.read_bits(2) == 0b11
    assert r.read_bits(5) == 31
    assert r.read_bits(6) == 33          # 64 - 31 leading - 0 trailing
    assert decode_values(data, n_bits, 2) == [1.0, nxt]


def test_throttle_style_data_is_mostly_repeats():
    throttle = [100] * 40 + [0] * 10 + [37, 62, 85, 100] + [100] * 40
    data, n_bits, stats = encode_values(throttle)
    assert stats["repeat"]["count"] >= 85
    assert n_bits < 64 * len(throttle) / 10   # better than 10x
    assert decode_values(data, n_bits, len(throttle)) == [float(v) for v in throttle]
