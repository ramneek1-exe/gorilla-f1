"""Block format: one driver's telemetry for one lap, compressed.

The paper groups each time series into blocks that start with a full
timestamp and value, so every block can be decoded on its own. Here a block
holds every telemetry channel for one lap, in one of two layouts:

  shared       (our change) one timestamp stream for the whole block, plus
               one value-only stream per channel. In FastF1 car data every
               channel is sampled at the same moments, so the timestamps
               only need to be stored once.

  per-channel  (the paper's layout) one stream per channel, each holding
               interleaved (timestamp, value) pairs, exactly as Gorilla
               stores each of its series.

Byte layout:

    4 bytes   magic "GRB1"
    1 byte    layout (0 = shared, 1 = per-channel)
    4 bytes   number of samples
    1 byte    number of streams
    per stream:
        1 byte    name length
        n bytes   name (ASCII)
        4 bytes   length of the stream in bits
    the streams' bytes, one after another, in the same order

Because the header lists every stream's length, a reader can jump straight
to the streams it needs and skip the rest.
"""

import struct

from .bitio import BitReader, BitWriter
from .timestamps import TimestampDecoder, TimestampEncoder
from .values import ValueDecoder, ValueEncoder

MAGIC = b"GRB1"
SHARED = "shared"
PER_CHANNEL = "per-channel"
_LAYOUT_CODES = {SHARED: 0, PER_CHANNEL: 1}
_LAYOUT_NAMES = {code: name for name, code in _LAYOUT_CODES.items()}
TIME_STREAM = "_time"  # stream name used for shared timestamps


def encode_block(timestamps, channels, layout=SHARED):
    """Compressing one lap:

        timestamps: list of int milliseconds
        channels:   dict of channel name -> list of numbers (same length as timestamps)

    Returns (block bytes, stats), where stats holds the encoder statistics
    and bit counts used by the experiments.
    """
    count = len(timestamps)
    if count == 0:
        raise ValueError("a block needs at least one sample")
    for name, values in channels.items():
        if len(values) != count:
            raise ValueError(f"channel {name} has {len(values)} values, expected {count}")

    streams = []  # (name, BitWriter)
    stats = {"layout": layout, "count": count, "streams": {}, "values": {}, "time": None}

    if layout == SHARED:
        te = TimestampEncoder()
        for t in timestamps:
            te.add(t)
        streams.append((TIME_STREAM, te.writer))
        stats["time"] = te.stats
        for name, values in channels.items():
            ve = ValueEncoder()
            for v in values:
                ve.add(v)
            streams.append((name, ve.writer))
            stats["values"][name] = ve.stats

    elif layout == PER_CHANNEL:
        time_totals = None
        for name, values in channels.items():
            w = BitWriter()
            te, ve = TimestampEncoder(w), ValueEncoder(w)
            for t, v in zip(timestamps, values):  # interleave like the paper
                te.add(t)
                ve.add(v)
            streams.append((name, w))
            stats["values"][name] = ve.stats
            if time_totals is None:
                time_totals = dict(te.stats)
            else:
                for bucket, n in te.stats.items():
                    time_totals[bucket] += n
        stats["time"] = time_totals
    else:
        raise ValueError(f"unknown layout {layout!r}")

    header = bytearray(MAGIC)
    header += struct.pack(">BIB", _LAYOUT_CODES[layout], count, len(streams))
    body = bytearray()
    for name, w in streams:
        encoded = name.encode("ascii")
        header += struct.pack(">B", len(encoded)) + encoded + struct.pack(">I", w.bit_length)
        body += w.to_bytes()
        stats["streams"][name] = w.bit_length

    stats["header_bytes"] = len(header)
    stats["payload_bits"] = sum(stats["streams"].values())
    stats["total_bytes"] = len(header) + len(body)
    return bytes(header + body), stats


def read_header(data):
    """Parse a block header. Returns layout, count and each stream's location."""
    if data[:4] != MAGIC:
        raise ValueError("not a Gorilla block")
    layout_code, count, n_streams = struct.unpack_from(">BIB", data, 4)
    pos = 4 + struct.calcsize(">BIB")

    entries = []
    for _ in range(n_streams):
        (name_len,) = struct.unpack_from(">B", data, pos)
        pos += 1
        name = data[pos:pos + name_len].decode("ascii")
        pos += name_len
        (bit_length,) = struct.unpack_from(">I", data, pos)
        pos += 4
        entries.append((name, bit_length))

    streams = {}
    offset = pos  # streams start right after the header
    for name, bit_length in entries:
        n_bytes = (bit_length + 7) // 8
        streams[name] = (offset, bit_length)
        offset += n_bytes

    return {"layout": _LAYOUT_NAMES[layout_code], "count": count, "streams": streams}


def _reader(data, header, name):
    offset, bit_length = header["streams"][name]
    n_bytes = (bit_length + 7) // 8
    return BitReader(data[offset:offset + n_bytes], bit_length)


def _decode_shared_time(data, header):
    dec = TimestampDecoder(_reader(data, header, TIME_STREAM))
    return [dec.next() for _ in range(header["count"])]


def _decode_series(data, header, name):
    """Decode one channel. Returns (timestamps, values)."""
    count = header["count"]
    if header["layout"] == SHARED:
        timestamps = _decode_shared_time(data, header)
        dec = ValueDecoder(_reader(data, header, name))
        return timestamps, [dec.next() for _ in range(count)]

    r = _reader(data, header, name)
    td, vd = TimestampDecoder(r), ValueDecoder(r)
    timestamps, values = [], []
    for _ in range(count):
        timestamps.append(td.next())
        values.append(vd.next())
    return timestamps, values


def channel_names(header):
    return [name for name in header["streams"] if name != TIME_STREAM]


def decode_channel(data, name):
    """Decode only one channel (and the timestamps it needs) from a block."""
    header = read_header(data)
    if name not in header["streams"] or name == TIME_STREAM:
        raise KeyError(f"no channel {name!r} in this block")
    return _decode_series(data, header, name)


def decode_block(data):
    """Decode every channel. Returns (timestamps, {channel: values})."""
    header = read_header(data)
    channels, timestamps = {}, None
    for name in channel_names(header):
        timestamps, channels[name] = _decode_series(data, header, name)
    if timestamps is None:
        timestamps = _decode_shared_time(data, header)
    return timestamps, channels
