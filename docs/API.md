# champi-ipc API Reference

Complete reference for all public symbols exported from `champi_ipc`.

---

## Table of contents

- [Core classes](#core-classes)
  - [SharedMemoryManager](#sharedmemorymanager)
  - [SignalProcessor](#signalprocessor)
  - [SignalReader](#signalreader)
  - [SignalQueue](#signalqueue)
  - [SignalQueueItem](#signalqueueitem)
- [Base types](#base-types)
  - [StructRegistry](#structregistry)
  - [SignalData](#signaldata)
  - [SignalTypeProtocol](#signaltypeprotocol)
- [Exceptions](#exceptions)
  - [IPCError](#ipcerror)
  - [RegionNotFoundError](#regionnotfounderror)
  - [RegionExistsError](#regionexistserror)
  - [SignalTypeNotRegisteredError](#signaltypenotregistererror)
- [Cleanup utilities](#cleanup-utilities)
  - [list\_regions](#list_regions)
  - [get\_region\_info](#get_region_info)
  - [cleanup\_orphaned\_regions](#cleanup_orphaned_regions)
  - [CleanupResult](#cleanupresult)
- [ACK utilities](#ack-utilities)
  - [pack\_ack / unpack\_ack / get\_ack\_size](#pack_ack--unpack_ack--get_ack_size)
  - [ACK\_STRUCT](#ack_struct)
- [CLI commands](#cli-commands)
  - [champi-ipc status](#champi-ipc-status)
  - [champi-ipc cleanup](#champi-ipc-cleanup)

---

## Core classes

### SharedMemoryManager

Manages named POSIX shared memory regions for inter-process communication.

Each logical channel consists of two regions:

- a **signal** region that stores an arbitrary packed struct, and
- an **ACK** region that holds a single `uint64` sequence counter.

The creator process calls `create_regions()` and is responsible for unlinking
regions on `cleanup()`. Attaching processes call `attach_regions()` and only
close (never unlink) on cleanup.

```python
from champi_ipc import SharedMemoryManager

manager = SharedMemoryManager(prefix="my_app", registry=registry)
```

#### Constructor

```python
SharedMemoryManager(prefix: str, registry: StructRegistry[S])
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `prefix` | `str` | Name prefix used for every shared memory region. |
| `registry` | `StructRegistry[S]` | Registry that maps signal types to their binary serialisation callables. |

#### Methods

**`create_regions(signal_types: list[S]) -> None`**

Create shared memory regions for each signal type in `signal_types`. Intended
for the producer process. If a region already exists it is attached rather than
created, and a warning is logged.

```python
manager.create_regions([MySignals.TEXT, MySignals.COUNTER])
```

**`attach_regions(signal_types: list[S]) -> None`**

Attach to existing shared memory regions created by another process. Intended
for the consumer process.

Raises `RegionNotFoundError` if a required region does not exist yet.

```python
manager.attach_regions([MySignals.TEXT, MySignals.COUNTER])
```

**`write_signal(signal_type: S, data: bytes) -> None`**

Write packed bytes into the signal region for `signal_type`. `data` must not
exceed the registered region size.

```python
packed = registry.pack(MySignals.TEXT, text="hello")
manager.write_signal(MySignals.TEXT, packed)
```

**`read_signal(signal_type: S) -> bytes`**

Read a snapshot of raw bytes from the signal region for `signal_type`.

```python
raw = manager.read_signal(MySignals.TEXT)
```

**`write_ack(signal_type: S, seq: int) -> None`**

Write an ACK sequence number to the ACK region for `signal_type`.

```python
manager.write_ack(MySignals.TEXT, seq_num)
```

**`read_ack(signal_type: S) -> int`**

Read the ACK sequence number from the ACK region for `signal_type`.

```python
last_ack = manager.read_ack(MySignals.TEXT)
```

**`cleanup() -> None`**

Close all regions and, if this process is the creator, unlink them from
`/dev/shm`. Safe to call multiple times.

```python
manager.cleanup()
```

#### Context manager

`SharedMemoryManager` implements `__enter__` / `__exit__` for automatic
cleanup:

```python
with SharedMemoryManager("my_app", registry=registry) as manager:
    manager.create_regions([MySignals.TEXT])
    # ...
# cleanup() is called automatically
```

---

### SignalProcessor

Bridges blinker `Signal` emissions to shared memory via a thread-safe FIFO
queue. A background thread continuously dequeues items and writes them to
shared memory. ACK-based signal-loss detection logs a warning whenever the
consumer falls more than `loss_threshold` sequence numbers behind.

```python
from champi_ipc import SignalProcessor

processor = SignalProcessor(memory_manager)
```

#### Constructor

```python
SignalProcessor(
    memory_manager: SharedMemoryManager[S],
    queue_maxsize: int = 100,
    loss_threshold: int = 3,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `memory_manager` | `SharedMemoryManager[S]` | — | Shared memory manager used for reads and writes. |
| `queue_maxsize` | `int` | `100` | Capacity of the internal signal queue. |
| `loss_threshold` | `int` | `3` | Un-ACKed sequence numbers that trigger a signal-loss warning. |

#### Methods

**`connect_signal(signal, signal_type, data_mapper=None) -> None`**

Subscribe a blinker signal so that each emission enqueues a work item.

| Parameter | Type | Description |
|-----------|------|-------------|
| `signal` | `blinker.Signal` | Blinker signal to connect. |
| `signal_type` | `S` | Target shared memory channel identifier. |
| `data_mapper` | `Callable[..., dict | None] \| None` | Optional callable that transforms raw `**kwargs` into the payload dict. Return `None` to discard an emission. |

```python
from blinker import signal as blinker_signal

text_sig = blinker_signal("text")

# Direct connection — kwargs are forwarded as-is
processor.connect_signal(text_sig, MySignals.TEXT)

# With a mapper — transform or filter kwargs
processor.connect_signal(
    text_sig,
    MySignals.TEXT,
    data_mapper=lambda text: {"text": text[:200]},
)
```

**`start() -> None`**

Start the background processing thread.

```python
processor.start()
```

**`stop() -> None`**

Stop the background thread and disconnect all signal handlers. Blocks until
the thread exits or a 2-second timeout elapses.

```python
processor.stop()
```

**`disconnect_all() -> None`**

Disconnect every registered signal handler without stopping the thread.

#### Context manager

```python
with SignalProcessor(manager) as processor:
    processor.connect_signal(sig, MySignals.TEXT)
    sig.send(text="hello")
# stop() called automatically
```

---

### SignalReader

Polls shared memory regions at a configurable rate and dispatches raw bytes to
registered handlers. Change-detection is byte-level: a handler is only called
when the region contents differ from the previous poll. After a handler returns
successfully an ACK is written back to the memory manager.

Handler exceptions are caught and logged; they never crash the poll loop.

```python
from champi_ipc import SignalReader

reader = SignalReader(memory_manager, poll_rate_hz=60.0)
```

#### Constructor

```python
SignalReader(
    memory_manager: SharedMemoryManager[S],
    poll_rate_hz: float = 100.0,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `memory_manager` | `SharedMemoryManager[S]` | — | An attached `SharedMemoryManager`. |
| `poll_rate_hz` | `float` | `100.0` | Polling frequency in Hz. |

#### Methods

**`register_handler(signal_type: S, handler: Callable[[bytes], None]) -> None`**

Register a callback for `signal_type`. The handler receives the raw bytes
payload.

```python
def handle_text(raw: bytes) -> None:
    signal_data = registry.unpack(MySignals.TEXT, raw)
    print(signal_data.data["text"])

reader.register_handler(MySignals.TEXT, handle_text)
```

**`poll_once() -> None`**

Read every registered region once and call the handler if the bytes have
changed since the last poll.

```python
reader.poll_once()
```

**`poll_loop() -> None`**

Run `poll_once()` in a loop at `poll_rate_hz`. Intended to be called in a
background thread. Exits when `stop()` is called.

**`start() -> None`**

Start the background polling thread. No-op if already running.

```python
reader.start()
```

**`stop() -> None`**

Signal the poll loop to exit and wait for the thread to finish.

```python
reader.stop()
```

#### Context manager

```python
with SignalReader(manager, poll_rate_hz=60.0) as reader:
    reader.register_handler(MySignals.TEXT, handle_text)
    # polling runs in background thread
# stop() called automatically
```

---

### SignalQueue

Thread-safe bounded FIFO queue for typed IPC signals. When the queue is full
(capacity = `maxsize`) the oldest item is silently dropped (ring-buffer
behaviour).

```python
from champi_ipc import SignalQueue

queue = SignalQueue(maxsize=100)
```

#### Constructor

```python
SignalQueue(maxsize: int = 100)
```

#### Methods

**`put(signal_type: S, **kwargs) -> int`**

Enqueue a signal item and return its monotonically increasing sequence number.

```python
seq = queue.put(MySignals.TEXT, text="hello")
```

**`get(timeout: float | None = None) -> SignalQueueItem[S] | None`**

Dequeue the oldest item, blocking until one is available. Returns `None` if
`timeout` elapses before an item arrives.

```python
item = queue.get(timeout=1.0)
if item is not None:
    print(item.signal_type, item.seq_num, item.data)
```

**`get_nowait() -> SignalQueueItem[S] | None`**

Dequeue the oldest item without blocking. Returns `None` if the queue is empty.

**`size() -> int`**

Return the current number of items in the queue.

**`clear() -> None`**

Remove all items from the queue.

---

### SignalQueueItem

A single entry held inside `SignalQueue`.

```python
@dataclass
class SignalQueueItem:
    signal_type: S
    seq_num: int
    data: dict[str, Any]  # populated from **kwargs passed to queue.put()
```

---

## Base types

### StructRegistry

Maps signal type enum values to their binary serialisation triple: a fixed byte
size, a pack callable, and an unpack callable.

```python
from champi_ipc import StructRegistry

registry = StructRegistry()
```

#### Methods

**`register(signal_type, size, pack_fn, unpack_fn) -> None`**

Register a signal type.

| Parameter | Type | Description |
|-----------|------|-------------|
| `signal_type` | `S` | Signal enum member to register. |
| `size` | `int` | Fixed byte length of a packed struct. |
| `pack_fn` | `Callable[..., bytes]` | Accepts arbitrary keyword arguments; returns packed bytes. |
| `unpack_fn` | `Callable[[bytes], object]` | Accepts bytes; returns an unpacked object. |

Raises `ValueError` if `signal_type` is already registered.

```python
registry.register(
    MySignals.TEXT,
    TEXT_STRUCT.size,
    pack_text,
    unpack_text,
)
```

**`get_size(signal_type: S) -> int`**

Return the packed byte size for `signal_type`.

Raises `SignalTypeNotRegisteredError` if not registered.

```python
size = registry.get_size(MySignals.TEXT)
```

**`pack(signal_type: S, **kwargs) -> bytes`**

Serialise data into bytes using the registered pack callable.

Raises `SignalTypeNotRegisteredError` if not registered.

```python
packed = registry.pack(MySignals.TEXT, text="hello")
```

**`unpack(signal_type: S, data: bytes) -> object`**

Deserialise bytes using the registered unpack callable.

Raises `SignalTypeNotRegisteredError` if not registered.

```python
result = registry.unpack(MySignals.TEXT, packed)
```

---

### SignalData

Data class returned by unpack callables when following the recommended pattern.
Not enforced by the library — your unpack callable may return any object.

```python
from champi_ipc import SignalData

@dataclass
class SignalData:
    signal_type: SignalTypeProtocol
    seq_num: int
    data: dict[str, Any]
```

---

### SignalTypeProtocol

Runtime-checkable protocol that any signal type enum must satisfy. Standard
`IntEnum` subclasses satisfy this protocol automatically.

```python
from champi_ipc import SignalTypeProtocol

@runtime_checkable
class SignalTypeProtocol(Protocol):
    name: str
    value: int
    def __int__(self) -> int: ...
```

Define your signal types as an `IntEnum`:

```python
from enum import IntEnum

class MySignals(IntEnum):
    TEXT = 1
    COUNTER = 2
    STATUS = 3
```

---

## Exceptions

All exceptions inherit from `IPCError`.

### IPCError

Base exception for all champi-ipc errors.

```python
from champi_ipc import IPCError
```

### RegionNotFoundError

Raised when attempting to attach to a shared memory region that does not exist.

```python
from champi_ipc import RegionNotFoundError

try:
    manager.attach_regions([MySignals.TEXT])
except RegionNotFoundError as exc:
    print(f"Region missing: {exc.name} — start the producer first")
```

### RegionExistsError

Raised when a region already exists and re-attaching it fails unexpectedly.

```python
from champi_ipc import RegionExistsError
```

### SignalTypeNotRegisteredError

Raised when a `StructRegistry` method is called with a signal type that has not
been registered.

```python
from champi_ipc import SignalTypeNotRegisteredError

try:
    registry.pack(MySignals.TEXT, text="hello")
except SignalTypeNotRegisteredError:
    print("Register the signal type first")
```

---

## Cleanup utilities

### list_regions

```python
from champi_ipc import list_regions

names: list[str] = list_regions(prefix="")
```

Return the names of all POSIX shared memory regions whose name starts with
`prefix`. Scans `/dev/shm` on Linux. On other platforms emits a
`RuntimeWarning` and returns an empty list.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `prefix` | `""` | Optional name prefix to filter by. Empty string lists every region. |

### get_region_info

```python
from champi_ipc import get_region_info

info: RegionInfo = get_region_info("my_app_sig_1")
```

Return size, mtime, and existence flag for a named shared memory region. On
Linux reads metadata from `/dev/shm/<name>`. On other platforms probes via
`multiprocessing.shared_memory.SharedMemory`; `mtime` is `None` in that case.

Raises `RegionNotFoundError` when no region with the given name exists.

`RegionInfo` is a `TypedDict`:

```python
class RegionInfo(TypedDict):
    name: str
    size: int
    mtime: float | None  # POSIX timestamp, or None on non-Linux
    exists: bool
```

### cleanup_orphaned_regions

```python
from champi_ipc import cleanup_orphaned_regions

result: CleanupResult = cleanup_orphaned_regions(prefix="my_app_")
```

Remove all POSIX shared memory regions whose name starts with `prefix`. Does
not check whether a region is still in use — callers must ensure no live
process holds the region open before calling.

On Linux unlinks entries in `/dev/shm` directly. On other platforms emits a
`RuntimeWarning` and returns an empty `CleanupResult`.

Raises `ValueError` when `prefix` is an empty string (safety guard against
accidentally removing unrelated system-wide regions).

### CleanupResult

```python
from champi_ipc import CleanupResult

@dataclass
class CleanupResult:
    removed: list[str]              # names successfully unlinked
    failed: dict[str, Exception]    # name -> exception for failures
```

---

## ACK utilities

### pack_ack / unpack_ack / get_ack_size

Low-level helpers used internally by `SharedMemoryManager` and `SignalReader`.
Exposed for advanced use cases.

```python
from champi_ipc import pack_ack, unpack_ack, get_ack_size

frame: bytes = pack_ack(seq=42)       # 8 bytes, native byte order
seq: int     = unpack_ack(frame)      # 42
size: int    = get_ack_size()         # 8
```

### ACK_STRUCT

The underlying `struct.Struct` instance: `Struct("=Q")` (native byte order,
unsigned 64-bit integer).

```python
from champi_ipc import ACK_STRUCT

print(ACK_STRUCT.size)   # 8
print(ACK_STRUCT.format) # =Q
```

---

## CLI commands

### champi-ipc status

Show active shared memory regions matching a prefix.

```
champi-ipc status [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--prefix TEXT` | `champi_` | Filter regions by name prefix. |
| `--json` | — | Output as a JSON array. |

**Examples**

```bash
champi-ipc status --prefix my_app
champi-ipc status --prefix my_app --json
```

Sample output:

```
NAME                  SIZE  LAST MODIFIED
------------------------------------------
my_app_ack_1          8.0 B  2026-05-11 14:23:01
my_app_ack_2          8.0 B  2026-05-11 14:23:01
my_app_sig_1        265.0 B  2026-05-11 14:23:02
my_app_sig_2         17.0 B  2026-05-11 14:23:01
```

---

### champi-ipc cleanup

Remove orphaned shared memory regions matching a prefix.

```
champi-ipc cleanup [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--prefix TEXT` | `champi_` | Name prefix of regions to remove. |
| `--signal-module TEXT` | — | Dotted module path to import before cleanup (optional). |
| `--dry-run` | — | List matching regions without removing them. |

**Examples**

```bash
# Preview what would be removed
champi-ipc cleanup --prefix my_app_ --dry-run

# Remove regions
champi-ipc cleanup --prefix my_app_

# Import a module first (e.g. to trigger any custom cleanup hooks)
champi-ipc cleanup --prefix my_app_ --signal-module my_app.signals
```

> **Note:** The `--signal-module` option accepts a plain module path
> (e.g. `my_app.signals`), not a dotted class path. The module is imported
> for its side-effects only.

---

## Complete example

```python
# signals.py
from enum import IntEnum

class MySignals(IntEnum):
    TEXT = 1
    COUNTER = 2


# codec.py
import struct
from champi_ipc import SignalData

TEXT_STRUCT = struct.Struct("=QB256s")      # seq_num, signal_type, text (265 bytes)
COUNTER_STRUCT = struct.Struct("=QBQ")      # seq_num, signal_type, value (17 bytes)


def pack_text(**kwargs: object) -> bytes:
    text = str(kwargs.get("text", ""))
    text_bytes = text.encode()[:256].ljust(256, b"\x00")
    return TEXT_STRUCT.pack(kwargs["seq_num"], MySignals.TEXT, text_bytes)


def unpack_text(data: bytes) -> SignalData:
    seq_num, sig_type, text_bytes = TEXT_STRUCT.unpack(data)
    return SignalData(
        signal_type=MySignals(sig_type),
        seq_num=seq_num,
        data={"text": text_bytes.rstrip(b"\x00").decode()},
    )


# ipc_setup.py
from champi_ipc import StructRegistry

def create_registry() -> StructRegistry:
    registry: StructRegistry = StructRegistry()
    registry.register(MySignals.TEXT, TEXT_STRUCT.size, pack_text, unpack_text)
    return registry


# producer.py
import time
from blinker import signal as blinker_signal
from champi_ipc import SharedMemoryManager, SignalProcessor

registry = create_registry()

with SharedMemoryManager("my_app", registry=registry) as manager:
    manager.create_regions([MySignals.TEXT])

    with SignalProcessor(manager) as processor:
        text_sig = blinker_signal("text")
        processor.connect_signal(
            text_sig, MySignals.TEXT, data_mapper=lambda text: {"text": text}
        )
        text_sig.send(None, text="Hello from producer")
        time.sleep(0.1)


# consumer.py
import time
from champi_ipc import SharedMemoryManager, SignalReader

registry = create_registry()

with SharedMemoryManager("my_app", registry=registry) as manager:
    manager.attach_regions([MySignals.TEXT])

    def handle_text(raw: bytes) -> None:
        sd = registry.unpack(MySignals.TEXT, raw)
        print(f"Received: {sd.data['text']}")  # type: ignore[union-attr]

    with SignalReader(manager, poll_rate_hz=60.0) as reader:
        reader.register_handler(MySignals.TEXT, handle_text)
        time.sleep(2.0)
```
