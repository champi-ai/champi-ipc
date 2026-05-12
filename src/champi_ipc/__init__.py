"""champi-ipc: Shared Memory IPC Infrastructure.

A generic, reusable library for inter-process communication using
shared memory and blinker signals.
"""

from champi_ipc.core.signal_queue import SignalQueue, SignalQueueItem

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "SignalQueue",
    "SignalQueueItem",
]
