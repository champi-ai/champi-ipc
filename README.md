# champi-ipc

**Generic Shared Memory IPC Infrastructure for Python**

A lightweight, type-safe library for inter-process communication using shared memory and blinker signals.

## Features

-  **Generic Design** - Works with any signal type enum
-  **Type-Safe** - Full type hints and mypy support
-  **Low Latency** - Binary struct serialization
-  **Signal Loss Detection** - ACK-based tracking
-  **Thread-Safe** - FIFO queue for ordered processing
-  **Cleanup Utilities** - Automatic orphaned region cleanup
-  **CLI Tools** - status, cleanup commands
-  **Cross-Platform** - Linux, macOS, Windows

## Installation

```bash
pip install champi-ipc
```

Or with UV:
```bash
uv pip install champi-ipc
```

## Quick Start

### 1. Define Your Signal Types

```python
from enum import IntEnum
import struct

class MySignals(IntEnum):
    TEXT_MESSAGE = 1

# Define struct format
TEXT_STRUCT = struct.Struct("=QB256s")  # seq_num, signal_type, text

def pack_text(seq_num: int, text: str) -> bytes:
    text_bytes = text.encode()[:256].ljust(256, b'\x00')
    return TEXT_STRUCT.pack(seq_num, MySignals.TEXT_MESSAGE, text_bytes)

def unpack_text(data: bytes) -> dict:
    seq_num, signal_type, text_bytes = TEXT_STRUCT.unpack(data)
    return {"seq_num": seq_num, "text": text_bytes.rstrip(b'\x00').decode()}
```

### 2. Create Struct Registry

```python
from champi_ipc import StructRegistry

registry = StructRegistry()
registry.register(MySignals.TEXT_MESSAGE, TEXT_STRUCT.size, pack_text, unpack_text)
```

### 3. Producer Process (Writer)

```python
from champi_ipc import SharedMemoryManager, SignalProcessor
from blinker import signal

# Create memory manager
manager = SharedMemoryManager("my_app", MySignals, registry)
manager.create_regions()

# Create signal processor
processor = SignalProcessor(manager)

# Connect blinker signal
text_signal = signal('text-message')
processor.connect_signal(
    text_signal,
    MySignals.TEXT_MESSAGE,
    data_mapper=lambda text: {'text': text}
)

processor.start()

# Emit signals
text_signal.send(text="Hello from producer!")
```

### 4. Consumer Process (Reader)

```python
from champi_ipc import SharedMemoryManager, SignalReader

# Attach to existing regions
manager = SharedMemoryManager("my_app", MySignals, registry)
manager.attach_regions()

# Create reader
reader = SignalReader(manager)

# Register handler
def handle_text(signal_data):
    print(f"Received: {signal_data.data['text']}")

reader.register_handler(MySignals.TEXT_MESSAGE, handle_text)

# Poll loop (60 Hz)
reader.poll_loop(poll_rate_hz=60)
```

## CLI Commands

### Cleanup Orphaned Regions

```bash
champi-ipc cleanup --prefix my_app --signal-module my_app.signals.MySignals
```

### Show Region Status

```bash
champi-ipc status --prefix my_app
```

## Documentation

- See `examples/` for more detailed examples
- See `docs/` for API reference and migration guides

## License

MIT License - see LICENSE file

## Contributing

Contributions welcome! Built with blinker, loguru, and click.
