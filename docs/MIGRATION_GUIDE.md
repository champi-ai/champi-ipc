# Migration Guide

This guide walks through replacing the embedded IPC code in `champi-imgui` and
`champi-stt` with `champi-ipc`.

---

## Overview of changes

| Area | Before | After |
|------|--------|-------|
| Import paths | `mcp_champi.ipc_svc.*` / `champi_stt.assistant.ipc.*` | `champi_ipc` |
| Manager constructor | `SharedMemoryManager(name, signal_enum, struct_sizes_dict)` | `SharedMemoryManager(prefix, registry)` |
| Region lifecycle | `create_regions()` / `attach_regions()` (no args) | `create_regions(signal_types)` / `attach_regions(signal_types)` |
| Pack / unpack | Standalone functions or manager methods | Registered on `StructRegistry`, called via `registry.pack()` / `registry.unpack()` |
| Struct size map | Plain `dict[SignalType, int]` | `StructRegistry` |

---

## Step 1 — Add the dependency

In `pyproject.toml` add `champi-ipc` as a dependency:

```toml
[project]
dependencies = [
    "champi-ipc>=0.1.0",
]
```

With uv:

```bash
uv add "champi-ipc>=0.1.0"
```

---

## Step 2 — Define your signal enum

Keep (or create) a dedicated `signals.py` module in your project. Signal types
must be `IntEnum` subclasses:

```python
# my_app/signals.py
from enum import IntEnum

class MySignals(IntEnum):
    TEXT    = 1
    COUNTER = 2
    STATUS  = 3
```

If you already have this as part of the old embedded IPC code, you can keep it
in place and just change the import in the rest of your code.

---

## Step 3 — Create pack / unpack functions

Each signal type needs two functions:

- `pack_<name>(**kwargs) -> bytes` — serialise kwargs into a fixed-size byte
  string.
- `unpack_<name>(data: bytes) -> SignalData` — deserialise bytes back into a
  `SignalData` instance.

```python
# my_app/signal_codec.py
import struct
from champi_ipc import SignalData
from .signals import MySignals

TEXT_STRUCT = struct.Struct("=QB256s")   # seq_num (Q), signal_type (B), text (256s)

def pack_text(**kwargs: object) -> bytes:
    text = str(kwargs.get("text", ""))
    seq_num = int(kwargs["seq_num"])
    text_bytes = text.encode()[:256].ljust(256, b"\x00")
    return TEXT_STRUCT.pack(seq_num, MySignals.TEXT, text_bytes)

def unpack_text(data: bytes) -> SignalData:
    seq_num, sig_type, text_bytes = TEXT_STRUCT.unpack(data)
    return SignalData(
        signal_type=MySignals(sig_type),
        seq_num=seq_num,
        data={"text": text_bytes.rstrip(b"\x00").decode()},
    )
```

Key rules:

- Use a **fixed-size** `struct.Struct` — variable-length formats are not
  supported.
- The pack function receives keyword arguments forwarded from
  `SignalQueue.put()` / `SignalProcessor.connect_signal()`.
- The unpack function must accept exactly the bytes produced by pack.

---

## Step 4 — Set up StructRegistry

Create a factory that builds and returns a configured `StructRegistry`:

```python
# my_app/ipc_setup.py
from champi_ipc import StructRegistry
from .signals import MySignals
from .signal_codec import pack_text, unpack_text, TEXT_STRUCT

def create_registry() -> StructRegistry:
    registry: StructRegistry = StructRegistry()
    registry.register(
        MySignals.TEXT,
        TEXT_STRUCT.size,
        pack_text,
        unpack_text,
    )
    # Register remaining signal types here
    return registry
```

Both the producer and consumer processes must build the same registry before
opening the shared memory manager.

---

## Step 5 — Update SharedMemoryManager construction

**Before (`champi-imgui` / old embedded code):**

```python
from mcp_champi.ipc_svc.shared_memory import SharedMemoryManager
from mcp_champi.ipc_svc.champi_structs import ChampiSignals, STRUCT_SIZES

manager = SharedMemoryManager("champi", ChampiSignals, STRUCT_SIZES)
manager.create_regions()   # no arguments
```

**After (`champi-ipc`):**

```python
from champi_ipc import SharedMemoryManager
from .ipc_setup import create_registry
from .signals import MySignals

registry = create_registry()
manager = SharedMemoryManager("my_app", registry=registry)
manager.create_regions([MySignals.TEXT, MySignals.COUNTER])   # explicit list
```

The `signal_type_enum` argument is gone. You pass the list of signal types
directly to `create_regions()` and `attach_regions()` instead.

---

## Step 6 — Update producer code

**Before (`champi-stt` / old embedded code):**

```python
from champi_stt.assistant.ipc.signal_processor import SignalProcessor

processor = SignalProcessor(manager)
processor.connect_signal(my_blinker_signal, SignalTypes.TEXT, data_mapper)
processor.start()
```

**After:**

```python
from champi_ipc import SignalProcessor

processor = SignalProcessor(manager)
processor.connect_signal(my_blinker_signal, MySignals.TEXT, data_mapper=data_mapper)
processor.start()
```

`SignalProcessor` is also a context manager:

```python
with SignalProcessor(manager) as processor:
    processor.connect_signal(sig, MySignals.TEXT, data_mapper=lambda text: {"text": text})
    sig.send(None, text="hello")
```

---

## Step 7 — Update consumer code

**Before (`champi-stt` / old embedded code):**

```python
from champi_stt.assistant.ipc.signal_reader import SignalReader

reader = SignalReader(manager)
reader.register_handler(SignalTypes.TEXT, handle_text)
# manual loop:
while True:
    reader.poll_once()
    time.sleep(1 / 60)
```

**After:**

```python
from champi_ipc import SignalReader

reader = SignalReader(manager, poll_rate_hz=60.0)
reader.register_handler(MySignals.TEXT, handle_text)
reader.start()   # background thread polls at 60 Hz
# ...
reader.stop()
```

Or via context manager:

```python
with SignalReader(manager, poll_rate_hz=60.0) as reader:
    reader.register_handler(MySignals.TEXT, handle_text)
    time.sleep(5.0)
```

Handler signature: the handler now receives **raw bytes**, not a `SignalData`
object. Call `registry.unpack()` inside the handler:

```python
def handle_text(raw: bytes) -> None:
    sd = registry.unpack(MySignals.TEXT, raw)
    print(sd.data["text"])
```

---

## Step 8 — Remove old IPC modules

Once all callers are updated, remove (or stop importing) the old embedded IPC
modules:

- `mcp_champi/ipc_svc/`
- `champi_stt/assistant/ipc/`

---

## Breaking changes summary

### Constructor signature changed

```python
# Old
SharedMemoryManager("champi", ChampiSignals, STRUCT_SIZES)

# New
SharedMemoryManager("my_app", registry=registry)
```

### create_regions / attach_regions require a signal list

```python
# Old
manager.create_regions()

# New
manager.create_regions([MySignals.TEXT, MySignals.COUNTER])
```

### StructRegistry replaces plain struct-size dicts

```python
# Old
STRUCT_SIZES = {ChampiSignals.TEXT: 264}
manager = SharedMemoryManager("champi", ChampiSignals, STRUCT_SIZES)

# New
registry = StructRegistry()
registry.register(MySignals.TEXT, 264, pack_text, unpack_text)
manager = SharedMemoryManager("my_app", registry=registry)
```

### registry.pack() signature changed

```python
# Old (protocols.py StructRegistry)
registry.pack(signal_type, seq_num=1, text="hello")

# New (base/struct_registry.py StructRegistry — the exported one)
registry.pack(signal_type, text="hello")
# seq_num is supplied by the caller inside pack_fn itself, not by the registry
```

### SignalReader handlers receive bytes, not SignalData

```python
# Old
def handle_text(signal_data: SignalData) -> None:
    print(signal_data.data["text"])

# New
def handle_text(raw: bytes) -> None:
    sd = registry.unpack(MySignals.TEXT, raw)
    print(sd.data["text"])
```

### poll_loop() no longer takes a poll_rate_hz argument

The poll rate is set on the constructor: `SignalReader(manager, poll_rate_hz=60.0)`.

---

## CLI tools after migration

Use the CLI to verify that regions are being created and to clean up orphaned
regions during development:

```bash
# Verify regions exist
champi-ipc status --prefix my_app_

# Clean up after a crashed producer
champi-ipc cleanup --prefix my_app_

# Dry run
champi-ipc cleanup --prefix my_app_ --dry-run
```

---

## Reference

- [API reference](./API.md)
- [Troubleshooting](./TROUBLESHOOTING.md)
- [Examples](../examples/)
