"""ACK frame helpers for shared memory signal-loss detection."""

import struct as _struct

# Native byte order, unsigned 64-bit integer: seq_num
ACK_STRUCT = _struct.Struct("=Q")


def pack_ack(seq: int) -> bytes:
    """Pack a sequence number into an ACK frame.

    Args:
        seq: Sequence number to acknowledge.  Valid range: 0 to 2**64-1.

    Returns:
        Eight bytes encoding *seq* in native byte order.
    """
    return ACK_STRUCT.pack(seq)


def unpack_ack(data: bytes) -> int:
    """Unpack an ACK frame to recover the sequence number.

    Args:
        data: Exactly ``get_ack_size()`` bytes as produced by :func:`pack_ack`.

    Returns:
        The sequence number encoded in *data*.
    """
    return int(ACK_STRUCT.unpack(data)[0])


def get_ack_size() -> int:
    """Return the fixed byte length of an ACK frame.

    Returns:
        Number of bytes in a packed ACK struct (always 8).
    """
    return ACK_STRUCT.size
