"""XOR value compression (Gorilla paper, Section 4.1.2).

Every value is a 64-bit float. Each new value is XORed with the previous one,
which leaves a 1 only in the bits that flipped. Then one of three things is
written:

    XOR is 0 (same value)                0                                   1 bit
    flips fit the remembered window      10 + bits inside the window        2 + window width
    flips need a new window              11 + 5-bit leading-zero count
                                            + 6-bit length + meaningful bits 13 + length

The "window" is the range of bit positions (leading and trailing zero counts)
from the last time a full header was written. Encoder and decoder both
remember it, so it only needs to be sent when it changes.

Two details from the paper's 5-bit and 6-bit header fields:
  * The leading-zero count must fit in 5 bits (0 to 31). If there are more
    than 31 leading zeros, we record 31; the extra zeros simply become part
    of the meaningful bits.
  * The length must fit in 6 bits (0 to 63), but a length of 64 is possible
    when the first and last bits both flip. A length of 0 can never happen
    (XOR is not 0 here), so 0 is used to mean 64.
"""

import struct

from .bitio import BitReader, BitWriter

MAX_LEADING = 31  # largest number a 5-bit field can hold


def float_to_bits(x):
    """The 64-bit IEEE 754 pattern of a float, as an unsigned integer."""
    return struct.unpack(">Q", struct.pack(">d", float(x)))[0]


def bits_to_float(b):
    return struct.unpack(">d", struct.pack(">Q", b))[0]


def leading_zeros(x):
    return 64 - x.bit_length()


def trailing_zeros(x):
    # x & -x keeps only the lowest 1 bit, so its position is the trailing-zero count.
    return (x & -x).bit_length() - 1


class ValueEncoder:
    def __init__(self, writer=None, reuse_window=True):
        """reuse_window=False always writes a new header (11). The output still
        decodes with ValueDecoder; it exists to measure what window reuse saves."""
        self.writer = writer if writer is not None else BitWriter()
        self.reuse_window = reuse_window
        self.count = 0
        # How often each case happens and how many bits it cost, for the experiments.
        self.stats = {case: {"count": 0, "bits": 0} for case in ("first", "repeat", "reuse", "new")}
        self._prev = None        # previous value's bit pattern
        self._win_leading = None  # remembered window, None until the first header
        self._win_trailing = None

    def add(self, value):
        w = self.writer
        bits_before = w.bit_length
        cur = float_to_bits(value)

        if self._prev is None:
            w.write_bits(cur, 64)
            case = "first"
        else:
            xor = cur ^ self._prev
            if xor == 0:
                w.write_bits(0, 1)
                case = "repeat"
            else:
                leading = min(leading_zeros(xor), MAX_LEADING)
                trailing = trailing_zeros(xor)

                fits = (self.reuse_window
                        and self._win_leading is not None
                        and leading >= self._win_leading
                        and trailing >= self._win_trailing)
                if fits:
                    # 10, then every bit inside the remembered window.
                    width = 64 - self._win_leading - self._win_trailing
                    w.write_bits(0b10, 2)
                    w.write_bits(xor >> self._win_trailing, width)
                    case = "reuse"
                else:
                    # 11, a new header, then only the meaningful bits.
                    length = 64 - leading - trailing
                    w.write_bits(0b11, 2)
                    w.write_bits(leading, 5)
                    w.write_bits(length % 64, 6)  # 64 is stored as 0
                    w.write_bits(xor >> trailing, length)
                    self._win_leading = leading
                    self._win_trailing = trailing
                    case = "new"

        self._prev = cur
        self.count += 1
        self.stats[case]["count"] += 1
        self.stats[case]["bits"] += w.bit_length - bits_before


class ValueDecoder:
    def __init__(self, reader):
        self.reader = reader
        self._prev = None
        self._win_leading = None
        self._win_trailing = None

    def next(self):
        r = self.reader
        if self._prev is None:
            cur = r.read_bits(64)
        elif r.read_bit() == 0:
            cur = self._prev                       # 0: same value
        else:
            if r.read_bit() == 1:                  # 11: read a new window
                self._win_leading = r.read_bits(5)
                length = r.read_bits(6) or 64      # 0 means 64
                self._win_trailing = 64 - self._win_leading - length
            # 10 or 11: read the bits inside the (possibly new) window.
            width = 64 - self._win_leading - self._win_trailing
            xor = r.read_bits(width) << self._win_trailing
            cur = self._prev ^ xor                 # flip those bits in the previous value
        self._prev = cur
        return bits_to_float(cur)


def encode_values(values):
    """Encode a list of numbers. Returns (bytes, bit_length, stats)."""
    enc = ValueEncoder()
    for v in values:
        enc.add(v)
    return enc.writer.to_bytes(), enc.writer.bit_length, enc.stats


def decode_values(data, bit_length, count):
    dec = ValueDecoder(BitReader(data, bit_length))
    return [dec.next() for _ in range(count)]
