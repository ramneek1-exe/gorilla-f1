"""Delta-of-delta timestamp compression (Gorilla paper, Section 4.1.1).

Timestamps are integer milliseconds. Instead of storing each timestamp,
we store how much the gap between readings changed:

    delta          = t[i] - t[i-1]
    delta_of_delta = delta - previous delta

If readings arrive at a steady rate, delta_of_delta is 0 and costs one bit.
Otherwise it goes into the smallest bucket that fits:

    delta_of_delta        written as                  total bits
    0                     0                            1
    -63 to 64             10   + 7 bits                9
    -255 to 256           110  + 9 bits                12
    -2047 to 2048         1110 + 12 bits               16
    anything else         1111 + 32 bits               36

Inside a bucket the value is stored with an offset so it is never negative:
for the 7-bit bucket we store (dod + 63), which turns -63..64 into 0..127.
The last bucket uses 32-bit two's complement.

Differences from the paper (explained in the report):
  * The paper's block header stores a 2-hour-aligned start time and writes
    the first timestamp as a 14-bit offset from it. F1 laps don't start on
    aligned boundaries, so we write the first timestamp in full (64 bits).
  * The paper writes the first delta in 14 bits. We send it through the
    normal buckets instead, treating the previous delta as 0. This never
    overflows and costs 12 bits for a typical 200 to 300 ms F1 gap.
"""

from .bitio import BitReader, BitWriter

# (lowest value, highest value, prefix bits, prefix length, payload width)
BUCKETS = [
    (-63, 64, 0b10, 2, 7),
    (-255, 256, 0b110, 3, 9),
    (-2047, 2048, 0b1110, 4, 12),
]
FALLBACK_PREFIX = 0b1111
FALLBACK_WIDTH = 32
FIRST_WIDTH = 64

# Names used in the stats, so experiments can count how often each case happens.
BUCKET_NAMES = ["zero", "7-bit", "9-bit", "12-bit", "32-bit"]


class TimestampEncoder:
    def __init__(self, writer=None):
        self.writer = writer if writer is not None else BitWriter()
        self.count = 0
        self.stats = {name: 0 for name in BUCKET_NAMES}
        self._prev_t = None
        self._prev_delta = 0

    def add(self, t):
        if not isinstance(t, int):
            raise TypeError(f"timestamps must be integer milliseconds, got {t!r}")
        w = self.writer

        if self._prev_t is None:
            if t < 0:
                raise ValueError("the first timestamp must not be negative")
            w.write_bits(t, FIRST_WIDTH)
        else:
            delta = t - self._prev_t
            dod = delta - self._prev_delta
            self._write_dod(dod)
            self._prev_delta = delta

        self._prev_t = t
        self.count += 1

    def _write_dod(self, dod):
        w = self.writer
        if dod == 0:
            w.write_bits(0, 1)
            self.stats["zero"] += 1
            return

        for i, (low, high, prefix, prefix_len, width) in enumerate(BUCKETS):
            if low <= dod <= high:
                w.write_bits(prefix, prefix_len)
                w.write_bits(dod - low, width)  # offset so the stored value is never negative
                self.stats[BUCKET_NAMES[i + 1]] += 1
                return

        if not -(2 ** 31) <= dod < 2 ** 31:
            raise ValueError(f"delta of delta {dod} ms does not fit in 32 bits")
        w.write_bits(FALLBACK_PREFIX, 4)
        w.write_bits(dod & 0xFFFFFFFF, FALLBACK_WIDTH)  # two's complement
        self.stats["32-bit"] += 1


class TimestampDecoder:
    def __init__(self, reader):
        self.reader = reader
        self._prev_t = None
        self._prev_delta = 0

    def next(self):
        r = self.reader
        if self._prev_t is None:
            t = r.read_bits(FIRST_WIDTH)
        else:
            delta = self._prev_delta + self._read_dod()
            t = self._prev_t + delta
            self._prev_delta = delta
        self._prev_t = t
        return t

    def _read_dod(self):
        r = self.reader
        if r.read_bit() == 0:
            return 0
        # Each extra 1 bit in the prefix moves to the next, wider bucket.
        for low, _high, _prefix, _prefix_len, width in BUCKETS:
            if r.read_bit() == 0:
                return r.read_bits(width) + low
        raw = r.read_bits(FALLBACK_WIDTH)
        return raw - (1 << 32) if raw >= 1 << 31 else raw


def encode_timestamps(timestamps):
    """Encode a list of int timestamps. Returns (bytes, bit_length, stats)."""
    enc = TimestampEncoder()
    for t in timestamps:
        enc.add(t)
    return enc.writer.to_bytes(), enc.writer.bit_length, enc.stats


def decode_timestamps(data, bit_length, count):
    dec = TimestampDecoder(BitReader(data, bit_length))
    return [dec.next() for _ in range(count)]
