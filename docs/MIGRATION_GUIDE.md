# Migration Guide: champi-ipc

This guide helps you migrate from the embedded IPC code in `champi` and `champi-stt` to the standalone `champi-ipc` library.

## Overview

The `champi-ipc` library extracts and generalizes the IPC (Inter-Process Communication) infrastructure that was duplicated across multiple services. The new library provides:

- **Generic design**: Works with any `IntEnum` signal types
- **Type safety**: Uses Python protocols and type hints
- **Flexibility**: Registry pattern for dynamic signal registration
- **CLI tools**: For debugging and managing shared memory regions

## Installation

```bash
pip install champi-ipc
```

Or with uv:
```bash
uv add champi-ipc
```

## Key Changes

### 1. Signal Queue

**Before** (champi):
```python
from mcp_champi.ipc_svc.signal_queue import SignalQueue

queue = SignalQueue()
```

**After** (champi-ipc):
```python
from champi_ipc import SignalQueue

queue = SignalQueue()
```

**Changes**:
- Import path changed
- No changes to API - fully compatible!

### 2. Shared Memory Manager

**Before** (champi):
```python
from mcp_champi.ipc_svc.shared_memory import SharedMemoryManager
from mcp_champi.ipc_svc.champi_structs import ChampiSignals, STRUCT_SIZES

manager = SharedMemoryManager("champi", ChampiSignals, STRUCT_SIZES)
```

**After** (champi-ipc):
```python
from champi_ipc import SharedMemoryManager, StructRegistry
from my_app.signals import MySignals

# Create registry
registry = StructRegistry()
registry.register(MySignals.SIGNAL_A, 32, pack_signal_a, unpack_signal_a)
registry.register(MySignals.SIGNAL_B, 64, pack_signal_b, unpack_signal_b)

# Create manager
manager = SharedMemoryManager("my_app", MySignals, registry)
```

**Changes**:
- **Generic design**: No longer hardcoded to ChampiSignals
- **StructRegistry**: New registry pattern for pack/unpack functions
- **Constructor**: Takes `(name_prefix, signal_enum, registry)` instead of `(name, signal_enum, struct_sizes)`

### 3. Signal Processor

**Before** (champi-stt):
```python
from champi_stt.assistant.ipc.signal_processor import SignalProcessor

processor = SignalProcessor(manager)
processor.connect_signal(my_signal, SignalTypes.TEXT, data_mapper)
```

**After** (champi-ipc):
```python
from champi_ipc import SignalProcessor

processor = SignalProcessor(manager)
processor.connect_signal(my_signal, MySignals.TEXT, data_mapper)
```

**Changes**:
- Import path changed
- API is compatible!

### 4. Signal Reader

**Before** (champi-stt):
```python
from champi_stt.assistant.ipc.signal_reader import SignalReader

reader = SignalReader(manager)
reader.register_handler(SignalTypes.TEXT, handle_text)
```

**After** (champi-ipc):
```python
from champi_ipc import SignalReader

reader = SignalReader(manager)
reader.register_handler(MySignals.TEXT, handle_text)
```

**Changes**:
- Import path changed
- API is compatible!

## Migration Steps

### Step 1: Define Your Signal Enum

```python
# signals.py
from enum import IntEnum

class MySignals(IntEnum):
    MESSAGE = 1
    COUNTER = 2
    STATUS = 3
```

### Step 2: Create Pack/Unpack Functions

```python
# signal_codec.py
import struct
from champi_ipc import SignalData

# Define structs
MESSAGE_STRUCT = struct.Struct("=QB256s")  # seq_num, signal_type, text

def pack_message(seq_num: int, **kwargs) -> bytes:
    text = kwargs.get("text", "")
    text_bytes = text.encode()[:256].ljust(256, b"\x00")
    return MESSAGE_STRUCT.pack(seq_num, MySignals.MESSAGE, text_bytes)

def unpack_message(data: bytes) -> SignalData:
    seq_num, signal_type, text_bytes = MESSAGE_STRUCT.unpack(data)
    return SignalData(
        signal_type=MySignals(signal_type),
        seq_num=seq_num,
        data={"text": text_bytes.rstrip(b"\x00").decode()},
    )
```

### Step 3: Create Registry

```python
# ipc_setup.py
from champi_ipc import StructRegistry
from .signals import MySignals
from .signal_codec import pack_message, unpack_message, MESSAGE_STRUCT

def create_registry():
    registry = StructRegistry()
    registry.register(
        MySignals.MESSAGE,
        MESSAGE_STRUCT.size,
        pack_message,
        unpack_message
    )
    # Register other signal types...
    return registry
```

### Step 4: Update Producer Code

```python
# producer.py
from blinker import signal
from champi_ipc import SharedMemoryManager, SignalProcessor
from .ipc_setup import create_registry
from .signals import MySignals

# Setup
registry = create_registry()
manager = SharedMemoryManager("my_app", MySignals, registry)
manager.create_regions()

processor = SignalProcessor(manager)

# Connect signals
msg_signal = signal("message")
processor.connect_signal(
    msg_signal,
    MySignals.MESSAGE,
    lambda text: {"text": text}
)

processor.start()

# Emit signals
msg_signal.send(text="Hello World")

# Cleanup
processor.stop()
manager.cleanup()
```

### Step 5: Update Consumer Code

```python
# consumer.py
from champi_ipc import SharedMemoryManager, SignalReader
from .ipc_setup import create_registry
from .signals import MySignals

# Setup
registry = create_registry()
manager = SharedMemoryManager("my_app", MySignals, registry)
manager.attach_regions()

reader = SignalReader(manager)

# Register handlers
def handle_message(signal_data):
    print(f"Received: {signal_data.data['text']}")

reader.register_handler(MySignals.MESSAGE, handle_message)

# Poll loop
while True:
    reader.poll_once()
    time.sleep(1.0 / 60)  # 60 Hz

# Cleanup
manager.cleanup()
```

## CLI Tools

The library includes CLI tools for debugging:

### Check Status

```bash
champi-ipc status --prefix my_app
champi-ipc status --prefix my_app --json
```

### Cleanup Orphaned Regions

```bash
# Dry run
champi-ipc cleanup --prefix my_app --signal-module my_app.signals.MySignals --dry-run

# Actually clean
champi-ipc cleanup --prefix my_app --signal-module my_app.signals.MySignals
```

## Breaking Changes

### StructRegistry Pattern

The biggest change is the introduction of `StructRegistry` to replace hardcoded struct dictionaries:

**Before**:
```python
STRUCT_SIZES = {
    ChampiSignals.TEXT: 264,
    ChampiSignals.AUDIO: 1024,
}

manager = SharedMemoryManager("champi", ChampiSignals, STRUCT_SIZES)
```

**After**:
```python
registry = StructRegistry()
registry.register(MySignals.TEXT, 264, pack_text, unpack_text)
registry.register(MySignals.AUDIO, 1024, pack_audio, unpack_audio)

manager = SharedMemoryManager("my_app", MySignals, registry)
```

### Pack/Unpack in Registry

Pack and unpack functions are now part of the registry instead of being methods on the manager:

**Before**:
```python
# Pack/unpack were separate utility functions
from champi_stt.assistant.ipc.structs import pack_text, unpack_text

packed = pack_text(seq_num, text="hello")
signal_data = unpack_text(packed)
```

**After**:
```python
# Pack/unpack are called through the registry
packed = registry.pack(MySignals.TEXT, seq_num, text="hello")
signal_data = registry.unpack(MySignals.TEXT, packed)
```

## Troubleshooting

### Import Errors

If you see import errors, make sure you've installed champi-ipc:
```bash
pip install champi-ipc
```

### Shared Memory Cleanup

If you encounter "File exists" errors, clean up orphaned regions:
```bash
champi-ipc cleanup --prefix my_app --signal-module my_app.signals.MySignals
```

### Signal Loss Warnings

The library automatically detects signal loss. If you see warnings:
1. Check your producer is not emitting too fast
2. Increase your consumer poll rate
3. Verify shared memory regions are accessible

## Complete Example

See `examples/basic_usage.py` for a complete working example of producer-consumer pattern.

## Support

For issues or questions:
- Check the [API documentation](./API.md)
- Review [examples](../examples/)
- File an issue on GitHub
