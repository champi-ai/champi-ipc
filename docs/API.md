# champi-ipc API Documentation

## Core Classes

### StructRegistry

Registry for mapping signal types to pack/unpack functions.

```python
from champi_ipc import StructRegistry

registry = StructRegistry()
```

#### Methods

**register(signal_type, struct_size, pack_func, unpack_func)**

Register a signal type with its pack/unpack functions.

- `signal_type`: Signal enum value
- `struct_size`: Size of packed struct in bytes
- `pack_func`: Function with signature `(seq_num: int, **kwargs) -> bytes`
- `unpack_func`: Function with signature `(data: bytes) -> SignalData`

```python
registry.register(MySignals.MESSAGE, 32, pack_message, unpack_message)
```

**pack(signal_type, seq_num, **kwargs) -> bytes**

Pack a signal into binary format.

```python
packed = registry.pack(MySignals.MESSAGE, seq_num=1, text="hello")
```

**unpack(signal_type, data) -> SignalData**

Unpack binary data into SignalData.

```python
signal_data = registry.unpack(MySignals.MESSAGE, packed)
```

**get_struct_size(signal_type) -> int**

Get the size of a signal type's struct.

```python
size = registry.get_struct_size(MySignals.MESSAGE)
```

---

### SignalData

Data class representing an unpacked signal.

```python
@dataclass
class SignalData:
    signal_type: SignalTypeProtocol
    seq_num: int
    data: dict[str, Any]
```

---

### SharedMemoryManager

Manages shared memory regions for IPC.

```python
from champi_ipc import SharedMemoryManager

manager = SharedMemoryManager(
    name_prefix="my_app",
    signal_type_enum=MySignals,
    struct_registry=registry
)
```

#### Methods

**create_regions()**

Create shared memory regions for all signal types (producer).

```python
manager.create_regions()
```

**attach_regions()**

Attach to existing shared memory regions (consumer).

```python
manager.attach_regions()
```

**write_signal(signal_type, data: bytes)**

Write packed signal data to shared memory.

```python
packed = registry.pack(MySignals.MESSAGE, 1, text="hello")
manager.write_signal(MySignals.MESSAGE, packed)
```

**read_signal(signal_type) -> bytes**

Read raw signal data from shared memory.

```python
raw_data = manager.read_signal(MySignals.MESSAGE)
signal_data = registry.unpack(MySignals.MESSAGE, raw_data)
```

**write_ack(signal_type, seq_num)**

Write ACK sequence number for signal loss detection.

```python
manager.write_ack(MySignals.MESSAGE, seq_num)
```

**read_ack(signal_type) -> int**

Read last ACKed sequence number.

```python
last_ack = manager.read_ack(MySignals.MESSAGE)
```

**cleanup()**

Clean up and unlink shared memory regions.

```python
manager.cleanup()
```

**Context Manager**

```python
with SharedMemoryManager("my_app", MySignals, registry) as manager:
    manager.create_regions()
    # Use manager...
# Automatic cleanup
```

---

### SignalQueue

Thread-safe FIFO queue for signals.

```python
from champi_ipc.core.signal_queue import SignalQueue

queue = SignalQueue(maxsize=100)
```

#### Methods

**put(signal_type, **kwargs) -> int**

Add signal to queue, returns sequence number.

```python
seq_num = queue.put(MySignals.MESSAGE, text="hello")
```

**get(timeout=None) -> Optional[SignalQueueItem]**

Get next signal from queue (blocks if empty).

```python
item = queue.get(timeout=1.0)
if item:
    print(f"Signal: {item.signal_type}, Seq: {item.seq_num}, Data: {item.data}")
```

**size() -> int**

Get current queue size.

```python
count = queue.size()
```

---

### SignalProcessor

Bridges blinker signals to shared memory.

```python
from champi_ipc import SignalProcessor

processor = SignalProcessor(memory_manager)
```

#### Methods

**connect_signal(signal, signal_type, data_mapper=None)**

Connect a blinker signal to the processor.

```python
from blinker import signal

msg_signal = signal("message")

# Simple connection
processor.connect_signal(msg_signal, MySignals.MESSAGE)

# With data mapper
processor.connect_signal(
    msg_signal,
    MySignals.MESSAGE,
    lambda text: {"text": text[:100]}  # Truncate
)
```

**start()**

Start processing signals in background thread.

```python
processor.start()
```

**stop()**

Stop processing signals.

```python
processor.stop()
```

---

### SignalReader

Reads signals from shared memory and dispatches to handlers.

```python
from champi_ipc import SignalReader

reader = SignalReader(memory_manager)
```

#### Methods

**register_handler(signal_type, handler)**

Register a handler function for a signal type.

```python
def handle_message(signal_data: SignalData):
    print(f"Text: {signal_data.data['text']}")

reader.register_handler(MySignals.MESSAGE, handle_message)
```

**poll_once()**

Poll all signal regions once and dispatch new signals.

```python
reader.poll_once()
```

**poll_loop(poll_rate_hz=60)**

Continuous polling loop.

```python
# Poll at 60 Hz
reader.poll_loop(poll_rate_hz=60)

# Or manually:
while running:
    reader.poll_once()
    time.sleep(1.0 / 60)
```

---

## CLI Commands

### Status

Show status of shared memory regions.

```bash
champi-ipc status [OPTIONS]
```

**Options**:
- `--prefix TEXT`: Memory region prefix (default: champi_ipc)
- `--json`: Output in JSON format

**Examples**:
```bash
champi-ipc status --prefix my_app
champi-ipc status --prefix my_app --json
```

### Cleanup

Clean up orphaned shared memory regions.

```bash
champi-ipc cleanup [OPTIONS]
```

**Options**:
- `--prefix TEXT`: Memory region prefix (required)
- `--signal-module TEXT`: Python module path to signal enum (required)
- `--dry-run`: Show what would be cleaned without actually cleaning

**Examples**:
```bash
# Dry run
champi-ipc cleanup --prefix my_app --signal-module my_app.signals.MySignals --dry-run

# Actually clean
champi-ipc cleanup --prefix my_app --signal-module my_app.signals.MySignals
```

---

## Type Definitions

### SignalTypeProtocol

Protocol for signal type enums.

```python
@runtime_checkable
class SignalTypeProtocol(Protocol):
    name: str
    value: int
    def __int__(self) -> int: ...
```

Your signal enum should be an `IntEnum`:

```python
from enum import IntEnum

class MySignals(IntEnum):
    MESSAGE = 1
    COUNTER = 2
```

---

## Exceptions

### RegionNotFoundError

Raised when trying to attach to non-existent shared memory region.

```python
from champi_ipc.base.exceptions import RegionNotFoundError

try:
    manager.attach_regions()
except RegionNotFoundError:
    print("Regions not created yet - start producer first")
```

---

## Best Practices

### 1. Always Use Context Managers

```python
with SharedMemoryManager("my_app", MySignals, registry) as manager:
    manager.create_regions()
    # ...
# Automatic cleanup
```

### 2. Handle Signal Loss

The reader automatically detects signal loss and logs warnings. Monitor these logs:

```python
# Logged automatically when detected
# ⚠️  Signal loss detected for MESSAGE: expected seq 5, got 10 (5 signals missed)
```

### 3. Structure Your Packs Efficiently

Use fixed-size structs for predictable memory usage:

```python
# Good: Fixed size
MESSAGE_STRUCT = struct.Struct("=QB256s")  # Always 265 bytes

# Bad: Variable size
# Don't use variable-length formats
```

### 4. ACK After Processing

The reader automatically writes ACKs after successful handling:

```python
def handle_message(signal_data):
    process(signal_data)
    # ACK written automatically after handler returns
```

### 5. Error Handling in Handlers

Handler exceptions are caught and logged, but processing continues:

```python
def handle_message(signal_data):
    try:
        risky_operation(signal_data)
    except Exception as e:
        logger.error(f"Failed to process: {e}")
        # Don't re-raise - will be logged and processing continues
```

---

## Example: Complete Setup

```python
# signals.py
from enum import IntEnum

class MySignals(IntEnum):
    TEXT = 1
    NUMBER = 2

# codec.py
import struct
from champi_ipc import SignalData

TEXT_STRUCT = struct.Struct("=QB256s")
NUMBER_STRUCT = struct.Struct("=QBQ")

def pack_text(seq_num: int, **kwargs) -> bytes:
    text = kwargs.get("text", "")
    text_bytes = text.encode()[:256].ljust(256, b"\x00")
    return TEXT_STRUCT.pack(seq_num, MySignals.TEXT, text_bytes)

def unpack_text(data: bytes) -> SignalData:
    seq_num, sig_type, text_bytes = TEXT_STRUCT.unpack(data)
    return SignalData(
        signal_type=MySignals(sig_type),
        seq_num=seq_num,
        data={"text": text_bytes.rstrip(b"\x00").decode()}
    )

# setup.py
from champi_ipc import StructRegistry

def create_registry():
    registry = StructRegistry()
    registry.register(MySignals.TEXT, TEXT_STRUCT.size, pack_text, unpack_text)
    registry.register(MySignals.NUMBER, NUMBER_STRUCT.size, pack_number, unpack_number)
    return registry

# producer.py
from champi_ipc import SharedMemoryManager, SignalProcessor
from blinker import signal

registry = create_registry()

with SharedMemoryManager("my_app", MySignals, registry) as manager:
    manager.create_regions()
    
    processor = SignalProcessor(manager)
    
    text_signal = signal("text")
    processor.connect_signal(text_signal, MySignals.TEXT, lambda t: {"text": t})
    
    processor.start()
    text_signal.send(t="Hello")
    processor.stop()

# consumer.py
from champi_ipc import SharedMemoryManager, SignalReader

registry = create_registry()

with SharedMemoryManager("my_app", MySignals, registry) as manager:
    manager.attach_regions()
    
    reader = SignalReader(manager)
    reader.register_handler(MySignals.TEXT, lambda s: print(s.data["text"]))
    
    while True:
        reader.poll_once()
        time.sleep(0.016)  # ~60 Hz
```
