"""Bit-level writer and reader.

Computers store data in whole bytes (8 bits), but Gorilla needs to write
fields of any width: a single 0 bit for a repeated value, 5 bits for a
leading-zero count, 7 bits for a small timestamp change, and so on.

BitWriter packs those fields back to back, crossing byte boundaries as
needed. BitReader reads them back in the same order. Bits are written
most significant bit (MSB) first, so the bytes read left to right in the same
order the fields were written.
"""


class BitWriter: #class to write bits
    def __init__(self): #initializes the writer
        self._buf = bytearray()  # finished, full bytes
        self._acc = 0            # bits waiting to fill the next byte
        self._nacc = 0           # how many bits are in _acc (always < 8 between calls)
        self.bit_length = 0      # total bits written, used to report exact sizes

    def write_bits(self, value, n): #writes n bits of value
        """Append the lowest n bits of value, most significant bit first."""
        if n == 0: #if n is 0, return
            return
        if n < 0 or n > 64: #if n is not between 0 and 64, raise an error
            raise ValueError(f"width must be between 0 and 64, got {n}")
        if value < 0 or value >> n: #if value is not between 0 and 2^n, raise an error
            raise ValueError(f"{value} does not fit in {n} bits")

        # Shift the new bits onto the right end of the accumulator.
        self._acc = (self._acc << n) | value
        self._nacc += n
        self.bit_length += n

        # Move every complete byte from the left end into the buffer.
        while self._nacc >= 8:
            self._nacc -= 8
            self._buf.append((self._acc >> self._nacc) & 0xFF)

        # Keep only the leftover bits that don't make a full byte yet.
        self._acc &= (1 << self._nacc) - 1

    def write_bit(self, bit): #writes a single bit
        self.write_bits(1 if bit else 0, 1)

    def to_bytes(self): #returns the bytes
        """Return everything written so far, padding the last byte with zeros."""
        out = bytearray(self._buf)
        if self._nacc:
            out.append((self._acc << (8 - self._nacc)) & 0xFF)
        return bytes(out)


class BitReader: #class to read bits
    def __init__(self, data, bit_length=None): #initializes the reader
        self._data = data
        self._idx = 0     # next byte to pull from data
        self._acc = 0     # bits pulled in but not read yet
        self._nacc = 0
        self.bits_read = 0
        # bit_length lets the reader ignore the zero padding in the last byte.
        self.bit_length = len(data) * 8 if bit_length is None else bit_length

    def read_bits(self, n): #reads n bits
        """Read the next n bits and return them as an unsigned integer."""
        if n == 0:
            return 0
        if self.bits_read + n > self.bit_length: #if n is greater than the remaining bits, raise an error
            raise EOFError("tried to read past the end of the bit stream")

        # Pull in whole bytes until there are enough bits buffered.
        while self._nacc < n:
            self._acc = (self._acc << 8) | self._data[self._idx]
            self._idx += 1
            self._nacc += 8

        # Take the n leftmost buffered bits.
        self._nacc -= n
        value = (self._acc >> self._nacc) & ((1 << n) - 1)
        self._acc &= (1 << self._nacc) - 1
        self.bits_read += n
        return value

    def read_bit(self): #reads a single bit
        return self.read_bits(1)
