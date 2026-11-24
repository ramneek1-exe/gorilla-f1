"""The storage layer: every lap of a race in one file, with an index.

Gorilla keeps its compressed blocks in memory and finds them through an
index on the series key. Here the key is (driver, lap): the index maps it to
the block's position in the file, so a query only touches the one block it
needs, and inside that block only the streams it needs.

File layout:

    4 bytes   magic "GST1"
    4 bytes   length of the JSON header in bytes
    n bytes   JSON header: race info, block format, and the index
              [[driver, lap, offset, length], ...]
    the blocks, one after another (offsets are counted from here)

Two block formats share this layout so they can be compared fairly:

    gorilla   blocks from block.py (compressed)
    raw       the same samples stored uncompressed: 8-byte timestamps and
              8-byte floats, i.e. the 16 bytes per point the paper starts from
"""

import json
import struct

from .block import SHARED, decode_block, decode_channel, decode_channels, encode_block

MAGIC = b"GST1"
GORILLA = "gorilla"
RAW = "raw"


# Uncompressed blocks --------------------------------------------------------

def encode_raw_block(timestamps, channels):
    """Store every value as-is: count, channel names, then plain arrays."""
    names = list(channels)
    count = len(timestamps)
    header = json.dumps(names).encode("ascii")
    out = bytearray(struct.pack(">II", count, len(header)) + header)
    out += struct.pack(f">{count}q", *timestamps)
    for name in names:
        out += struct.pack(f">{count}d", *channels[name])
    return bytes(out)

# Parse a raw block header; return (count, channel names, data start offset)
def _raw_layout(data):
    count, header_len = struct.unpack_from(">II", data, 0)
    names = json.loads(data[8:8 + header_len].decode("ascii"))
    start = 8 + header_len
    return count, names, start

# Decode a whole raw block; return (timestamps, {channel name: values}).
def decode_raw_block(data):
    count, names, start = _raw_layout(data)
    timestamps = list(struct.unpack_from(f">{count}q", data, start))
    channels, pos = {}, start + 8 * count
    for name in names:
        channels[name] = list(struct.unpack_from(f">{count}d", data, pos))
        pos += 8 * count
    return timestamps, channels

# Decode a single channel from a raw block.
def decode_raw_channel(data, name):
    count, names, start = _raw_layout(data)
    if name not in names:
        raise KeyError(f"no channel {name!r} in this block")
    timestamps = list(struct.unpack_from(f">{count}q", data, start))
    pos = start + 8 * count * (1 + names.index(name))
    return timestamps, list(struct.unpack_from(f">{count}d", data, pos))

# Decode multiple channels from a raw block.
def decode_raw_channels(data, names):
    count, all_names, start = _raw_layout(data)
    timestamps = list(struct.unpack_from(f">{count}q", data, start))
    channels = {}
    for name in names:
        if name not in all_names:
            raise KeyError(f"no channel {name!r} in this block")
        pos = start + 8 * count * (1 + all_names.index(name))
        channels[name] = list(struct.unpack_from(f">{count}d", data, pos))
    return timestamps, channels


# The store -------------------------------------------------------------------

# An in-memory store of one race, queried by (driver, lap).
class Store:

    def __init__(self, meta, block_format, index, blob):
        self.meta = meta
        self.block_format = block_format
        self._index = index      # (driver, lap) -> (offset, length)
        self._blob = blob        # all block bytes

    # building, saving, opening

    # Build a store from a sequence of laps.
    @classmethod
    def build(cls, laps, meta, block_format=GORILLA, layout=SHARED):
        index, blob = {}, bytearray()
        for lap in laps:
            if block_format == GORILLA:
                block, _ = encode_block(lap.timestamps, lap.channels, layout)
            elif block_format == RAW:
                block = encode_raw_block(lap.timestamps, lap.channels)
            else:
                raise ValueError(f"unknown block format {block_format!r}")
            index[(lap.driver, lap.lap_number)] = (len(blob), len(block))
            blob += block
        return cls(meta, block_format, index, bytes(blob))

    # Save the store to a file.
    def save(self, path):
        header = {
            "meta": self.meta,
            "format": self.block_format,
            "index": [[d, l, off, n] for (d, l), (off, n) in self._index.items()],
        }
        encoded = json.dumps(header).encode("utf-8")
        with open(path, "wb") as f:
            f.write(MAGIC + struct.pack(">I", len(encoded)) + encoded + self._blob)

    # Open a store from a file.
    @classmethod
    def open(cls, path):
        with open(path, "rb") as f:
            data = f.read()
        if data[:4] != MAGIC:
            raise ValueError(f"{path} is not a store file")
        (header_len,) = struct.unpack_from(">I", data, 4)
        header = json.loads(data[8:8 + header_len].decode("utf-8"))
        index = {(d, l): (off, n) for d, l, off, n in header["index"]}
        return cls(header["meta"], header["format"], index, data[8 + header_len:])

    # size

    def size_bytes(self):
        """Bytes used by the blocks (the index is the same size in every format)."""
        return len(self._blob)

    # what is in the store

    def drivers(self):
        return sorted({d for d, _ in self._index})

    def laps(self, driver):
        return sorted(l for d, l in self._index if d == driver)

    def channels(self):
        if not self._index:
            return []
        _, channels = self.get_lap(*next(iter(self._index)))
        return list(channels)

    # queries

    def _block(self, driver, lap):
        try:
            offset, length = self._index[(driver, lap)]
        except KeyError:
            raise KeyError(f"no data for driver {driver!r}, lap {lap}") from None
        return self._blob[offset:offset + length]

    def get(self, driver, lap, channel):
        """One channel for one lap. Returns (timestamps, values)."""
        block = self._block(driver, lap)
        if self.block_format == GORILLA:
            return decode_channel(block, channel)
        return decode_raw_channel(block, channel)

    def get_channels(self, driver, lap, channels):
        """Several channels for one lap. Returns (timestamps, {channel: values})."""
        block = self._block(driver, lap)
        if self.block_format == GORILLA:
            return decode_channels(block, channels)
        return decode_raw_channels(block, channels)

    def get_lap(self, driver, lap):
        """Every channel for one lap. Returns (timestamps, {channel: values})."""
        block = self._block(driver, lap)
        if self.block_format == GORILLA:
            return decode_block(block)
        return decode_raw_block(block)

    def get_range(self, driver, first_lap, last_lap, channel):
        """One channel over several laps, joined in order. Missing laps are skipped."""
        timestamps, values = [], []
        for lap in self.laps(driver):
            if first_lap <= lap <= last_lap:
                t, v = self.get(driver, lap, channel)
                timestamps += t
                values += v
        return timestamps, values

    def max_value(self, driver, lap, channel):
        """A simple aggregate, e.g. top speed on a lap. Returns (value, timestamp)."""
        timestamps, values = self.get(driver, lap, channel)
        i = max(range(len(values)), key=values.__getitem__)
        return values[i], timestamps[i]
