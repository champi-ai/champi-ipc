# champi-ipc

[![CI](https://github.com/champi-ai/champi-ipc/actions/workflows/ci.yml/badge.svg)](https://github.com/champi-ai/champi-ipc/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/champi-ipc)](https://pypi.org/project/champi-ipc/)

Generic shared memory IPC infrastructure for multi-process Python applications.

## Overview

`champi-ipc` provides a reusable, type-safe library for inter-process communication built on POSIX shared memory and [blinker](https://github.com/pallets-eco/blinker) signals. It eliminates duplicated IPC boilerplate across services by offering a single, well-tested implementation.

## Features

- Generic design — works with any `IntEnum`-based signal type
- Full type hints and `mypy` support (PEP 561 compliant)
- ACK-based signal loss detection
- Thread-safe FIFO signal queue
- Cleanup utilities for orphaned shared memory regions
- CLI tools for status inspection and cleanup

## Requirements

- Python 3.12+
- Linux, macOS, or Windows

## Installation

```bash
pip install champi-ipc
```

Or with [uv](https://github.com/astral-sh/uv):

```bash
uv pip install champi-ipc
```

## Quick start

```python
from champi_ipc.base.protocols import SignalTypeProtocol
from champi_ipc.base.exceptions import IPCError
```

Full usage examples will be added as the library is built out across subsequent phases.

## Development

```bash
uv pip install -e ".[dev]"
uv run pytest
uv run ruff check src/
uv run mypy src/champi_ipc/
```

## License

MIT — see [LICENSE](LICENSE).
