# Troubleshooting

Common issues encountered when running or developing with `champi-ipc`.

---

## FileExistsError / RegionExistsError on region creation

**Symptom**

```
FileExistsError: [Errno 17] File exists
```

or the library logs:

```
WARNING | Region 'my_app_sig_1' already exists — attaching instead
```

**Cause**

A previous producer process crashed or was killed before calling `cleanup()`,
leaving the shared memory region file in `/dev/shm`.

**Fix**

Run the cleanup CLI to remove orphaned regions:

```bash
# Preview what will be removed
champi-ipc cleanup --prefix my_app_ --dry-run

# Remove the regions
champi-ipc cleanup --prefix my_app_
```

Or remove manually on Linux:

```bash
ls /dev/shm/my_app_*
rm /dev/shm/my_app_*
```

**Prevention**

Always use `SharedMemoryManager` as a context manager or call `cleanup()` in a
`finally` block so regions are unlinked even when the process exits
unexpectedly:

```python
with SharedMemoryManager("my_app", registry=registry) as manager:
    manager.create_regions([MySignals.TEXT])
    run_application()
# cleanup() is always called here
```

---

## Region name conflicts between services

**Symptom**

One service accidentally reads data written by a different service, or
`attach_regions()` succeeds but returns garbage bytes.

**Cause**

Two services use the same `prefix` string in their `SharedMemoryManager`
constructor, so their region names collide.

**Fix**

Use a unique, service-specific prefix for every service:

```python
# champi-imgui
manager = SharedMemoryManager("imgui", registry=registry)

# champi-stt
manager = SharedMemoryManager("stt", registry=registry)
```

The resulting region names are `imgui_sig_1`, `stt_sig_1`, etc., and will
never collide.

You can verify which regions are currently active:

```bash
champi-ipc status --prefix imgui_
champi-ipc status --prefix stt_
```

---

## Signal loss warnings

**Symptom**

Log line such as:

```
WARNING | Potential signal loss for TEXT: ACK at seq 3, writing seq 9 (6 signals may be skipped)
```

**Cause**

The consumer is processing signals more slowly than the producer emits them.
`SignalProcessor` tracks the gap between the last written sequence number and
the last ACKed sequence number. When the gap exceeds `loss_threshold` (default
3) the warning is emitted.

This is expected under high load; it is informational, not fatal.

**Fixes**

1. **Increase consumer poll rate.**  Pass a higher `poll_rate_hz` to
   `SignalReader`:

   ```python
   reader = SignalReader(manager, poll_rate_hz=200.0)
   ```

2. **Slow down the producer.** If the consumer cannot keep up, reduce the
   emission rate or add back-pressure in the producer.

3. **Raise the loss threshold** if bursts are expected and occasional skips are
   acceptable:

   ```python
   processor = SignalProcessor(manager, loss_threshold=10)
   ```

4. **Profile the handler.** If the handler is slow, optimise it or move heavy
   work to a separate thread.

---

## --signal-module import failures (CLI cleanup)

**Symptom**

```
Error: cannot import module 'my_app.signals': No module named 'my_app'
```

**Cause**

The `--signal-module` option imports a Python module before running cleanup.
The module path must be importable from the current Python environment.

**Fix**

Make sure the package is installed or the working directory is on `sys.path`
before calling the CLI:

```bash
# If using uv
uv run champi-ipc cleanup --prefix my_app_ --signal-module my_app.signals

# Or activate the virtual environment first
source .venv/bin/activate
champi-ipc cleanup --prefix my_app_ --signal-module my_app.signals
```

If you do not need to trigger any import side-effects, omit `--signal-module`
entirely — it is optional:

```bash
champi-ipc cleanup --prefix my_app_
```

---

## macOS: list_regions and cleanup return empty results

**Symptom**

```
RuntimeWarning: Shared memory enumeration via /dev/shm is not available on this platform.
```

`champi-ipc status` and `champi-ipc cleanup` report no regions even though the
application is running.

**Cause**

macOS does not expose POSIX shared memory regions as files under `/dev/shm`.
The `list_regions()` and `cleanup_orphaned_regions()` functions require Linux.

**Workaround**

On macOS, use `get_region_info(name)` directly when the region name is known,
or use `ipcs -m` in the terminal to list shared memory segments:

```bash
ipcs -m
```

To manually unlink a region by name, write a short script:

```python
from multiprocessing.shared_memory import SharedMemory
shm = SharedMemory(name="my_app_sig_1", create=False)
shm.close()
shm.unlink()
```

---

## RegionNotFoundError on attach

**Symptom**

```
RegionNotFoundError: Shared memory region 'my_app_sig_1' does not exist
```

**Cause**

The consumer process called `attach_regions()` before the producer process
called `create_regions()`.

**Fix**

Start the producer before the consumer. In integration tests, add a short
retry loop:

```python
import time
from champi_ipc import RegionNotFoundError

for _ in range(10):
    try:
        manager.attach_regions([MySignals.TEXT])
        break
    except RegionNotFoundError:
        time.sleep(0.1)
else:
    raise RuntimeError("Producer did not create regions in time")
```

---

## Handler is never called

**Symptom**

`register_handler()` is called, the producer writes signals, but the handler
is never invoked.

**Checklist**

1. **Did you call `reader.start()` or use the context manager?** Without it the
   poll loop is not running.

2. **Did you attach the correct signal types?** The handler key must match the
   registered region. Check that `attach_regions([MySignals.TEXT])` was called
   for the same `signal_type` passed to `register_handler`.

3. **Are the region bytes actually changing?** `SignalReader` only dispatches
   when the raw bytes differ from the previous poll. If the producer writes the
   same payload every time the handler will not fire after the first delivery.

4. **Is the producer in the same process?** In testing scenarios, creating and
   attaching regions in the same process works but both `create_regions()` and
   `attach_regions()` must be called on separate `SharedMemoryManager`
   instances.

---

## Further reading

- [API reference](./API.md)
- [Migration guide](./MIGRATION_GUIDE.md)
- [Examples](../examples/)
