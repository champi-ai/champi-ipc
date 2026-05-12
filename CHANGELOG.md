# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-10-19

### Added

- Initial release of champi-ipc library
- Core IPC infrastructure extracted from champi and champi-stt services
- Generic signal queue for thread-safe FIFO processing
- Shared memory manager with support for multiple signal types
- Signal processor for bridging blinker signals to shared memory
- Signal reader for consuming signals from shared memory
- Struct registry pattern for dynamic signal type registration
- ACK region support for signal loss detection
- CLI tools for debugging and managing shared memory regions:
  - `champi-ipc status` - Display status of shared memory regions
  - `champi-ipc cleanup` - Clean up orphaned shared memory regions
- Context manager support for automatic cleanup
- Type hints and protocols for type safety
- Comprehensive test suite (59% coverage, 43 tests)
- Integration tests for producer-consumer pattern
- Migration guide for existing services
- API documentation
- CI/CD workflow with GitHub Actions
- Example usage demonstrating producer-consumer pattern

### Features

- **Generic Design**: Works with any IntEnum signal types
- **Type Safe**: Uses Python protocols and TypeVar for compile-time type checking
- **Flexible**: Registry pattern allows dynamic signal registration
- **Robust**: Automatic signal loss detection and logging
- **Production Ready**: Comprehensive error handling and logging

### Dependencies

- loguru >= 0.7.0
- blinker >= 1.7.0
- click >= 8.1.0

[0.1.0]: https://github.com/yourusername/champi-ipc/releases/tag/v0.1.0
