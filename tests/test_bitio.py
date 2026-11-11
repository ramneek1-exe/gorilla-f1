import random

import pytest

from gorilla.bitio import BitReader, BitWriter


def test_exact_bytes_for_a_new_window_header():
    # The control bit 1, then 10011 (19 leading zeros), then 000001 (length 1):
    # 1 10011 000001 -> 11001100 0001(0000 padding) -> 0xCC 0x10
    w = BitWriter()
    w.write_bits(0b1, 1)
    w.write_bits(0b10011, 5)
    w.write_bits(0b000001, 6)
    assert w.bit_length == 12
    assert w.to_bytes() == bytes([0xCC, 0x10])


def test_single_bits():
    w = BitWriter()
    for b in [1, 0, 1, 1, 0, 0, 0, 1, 1]:
        w.write_bit(b)
    assert w.to_bytes() == bytes([0b10110001, 0b10000000])


def test_round_trip_random_widths():
    rng = random.Random(4660)
    fields = []
    for _ in range(5000):
        n = rng.randint(1, 64)
        fields.append((rng.getrandbits(n), n))

    w = BitWriter()
    for value, n in fields:
        w.write_bits(value, n)

    r = BitReader(w.to_bytes(), w.bit_length)
    for value, n in fields:
        assert r.read_bits(n) == value
    assert r.bits_read == w.bit_length


def test_full_64_bit_value():
    w = BitWriter()
    w.write_bits(0x4072C00000000000, 64)  # 300.0 as a float64
    assert BitReader(w.to_bytes()).read_bits(64) == 0x4072C00000000000


def test_reading_past_the_end_fails():
    w = BitWriter()
    w.write_bits(0b101, 3)
    r = BitReader(w.to_bytes(), w.bit_length)
    r.read_bits(3)
    with pytest.raises(EOFError):
        r.read_bit()  # the padding bits must not be readable


def test_value_too_wide_is_rejected():
    with pytest.raises(ValueError):
        BitWriter().write_bits(8, 3)  # 8 is 1000, needs 4 bits
