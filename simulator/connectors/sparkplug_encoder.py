"""
Minimal Sparkplug B protobuf encoder — no external protobuf dependency.

Encodes only the Payload/Metric subset needed for NBIRTH/DBIRTH/DDATA/NDEATH.
Wire format follows the Sparkplug B 3.0 spec (proto2 encoding).
"""

import struct
import time
from simulator.factory.base import Tag


class DataType:
    Int8 = 1
    Int16 = 2
    Int32 = 3
    Int64 = 4
    UInt8 = 5
    UInt16 = 6
    UInt32 = 7
    UInt64 = 8
    Float = 9
    Double = 10
    Boolean = 11
    String = 12
    DateTime = 13
    Text = 14


_TAG_DATATYPE: dict[str, int] = {
    "float": DataType.Double,
    "int": DataType.Int64,
    "bool": DataType.Boolean,
    "string": DataType.String,
}


# ---------------------------------------------------------------------------
# Low-level protobuf primitives
# ---------------------------------------------------------------------------

def _varint(value: int) -> bytes:
    out = []
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value & 0xFF)
    return bytes(out)


def _tag(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def _f_varint(field: int, value: int) -> bytes:
    return _tag(field, 0) + _varint(value)


def _f_fixed32(field: int, value: float) -> bytes:
    return _tag(field, 5) + struct.pack("<f", value)


def _f_fixed64(field: int, value: float) -> bytes:
    return _tag(field, 1) + struct.pack("<d", value)


def _f_string(field: int, value: str) -> bytes:
    enc = value.encode()
    return _tag(field, 2) + _varint(len(enc)) + enc


def _f_message(field: int, data: bytes) -> bytes:
    return _tag(field, 2) + _varint(len(data)) + data


# ---------------------------------------------------------------------------
# Metric encoder
# ---------------------------------------------------------------------------

def _encode_metric(name: str | None, datatype: int, value, timestamp: int) -> bytes:
    m = b""
    if name is not None:
        m += _f_string(1, name)           # name
    m += _f_varint(3, timestamp)          # timestamp
    m += _f_varint(4, datatype)           # datatype

    if datatype in (DataType.Int8, DataType.Int16, DataType.Int32,
                    DataType.UInt8, DataType.UInt16, DataType.UInt32):
        m += _f_varint(10, int(value) & 0xFFFF_FFFF)
    elif datatype in (DataType.Int64, DataType.UInt64, DataType.DateTime):
        m += _f_varint(11, int(value) & 0xFFFF_FFFF_FFFF_FFFF)
    elif datatype == DataType.Float:
        m += _f_fixed32(12, float(value))
    elif datatype == DataType.Double:
        m += _f_fixed64(13, float(value))
    elif datatype == DataType.Boolean:
        m += _f_varint(14, 1 if value else 0)
    elif datatype in (DataType.String, DataType.Text):
        m += _f_string(15, str(value))
    return m


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_payload(
    metrics: list[tuple],   # (name, datatype, value)
    seq: int,
    timestamp: int | None = None,
) -> bytes:
    if timestamp is None:
        timestamp = int(time.time() * 1000)

    payload = _f_varint(1, timestamp)   # Payload.timestamp

    for name, datatype, value in metrics:
        metric_bytes = _encode_metric(name, datatype, value, timestamp)
        payload += _f_message(2, metric_bytes)  # Payload.metrics (repeated)

    payload += _f_varint(3, seq % 256)  # Payload.seq
    return payload


def tag_to_metric(tag_name: str, tag: Tag) -> tuple:
    """Convert a simulator Tag to a (name, sparkplug_datatype, value) tuple."""
    return (tag_name, _TAG_DATATYPE.get(tag.datatype, DataType.Double), tag.value)
