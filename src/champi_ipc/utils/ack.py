"""ACK (acknowledgment) utilities for signal loss detection.

ACK regions store the sequence number of the last successfully processed signal,
allowing the processor to detect when signals are dropped/skipped.
"""

import struct

# ACK struct: seq_num(Q) - just the sequence number (8 bytes unsigned long long)
ACK_STRUCT = struct.Struct("=Q")


def pack_ack(seq_num: int) -> bytes:
    """Pack ACK with sequence number.

    Args:
        seq_num: Sequence number to acknowledge

    Returns:
        Packed ACK data (8 bytes)

    Example:
        >>> data = pack_ack(42)
        >>> len(data)
        8
    """
    return ACK_STRUCT.pack(seq_num)


def unpack_ack(data: bytes) -> int:
    """Unpack ACK to get sequence number.

    Args:
        data: Packed ACK data (must be 8 bytes)

    Returns:
        Sequence number

    Example:
        >>> data = pack_ack(42)
        >>> unpack_ack(data)
        42
    """
    return ACK_STRUCT.unpack(data)[0]


def get_ack_size() -> int:
    """Get the size of ACK struct in bytes.

    Returns:
        Size in bytes (always 8)
    """
    return ACK_STRUCT.size
