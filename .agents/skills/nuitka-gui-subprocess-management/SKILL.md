---
name: nuitka-gui-subprocess-management
description: Handles child process creation and communication in Nuitka-packaged GUI applications. Use when a standalone build spawns duplicate windows, freezes, or fails to initialize 3D/resource-heavy workers.
---

# Nuitka GUI Subprocess Management

Standard Python `multiprocessing` is fragile in standalone Nuitka builds. This skill implements a robust `subprocess` + `stdin` pattern that prevents duplicate GUI instances and deadlocks.

## Core Strategy

Instead of `multiprocessing.Process`, use `subprocess.Popen` to launch the current binary with a dedicated CLI flag. This ensures the child process skips all GUI initialization logic.

### 1. Intercepting the Child Process
Always check for a custom flag at the absolute start of `main()`. This is a 100% reliable guard against duplicate windows.

```python
def main():
    if "--my-worker-flag" in sys.argv:
        # Run worker logic directly and EXIT
        from my_app.worker import run_worker
        run_worker()
        return
```

### 2. Communicating via stdin
Use `stdin.write()` to send commands (like file paths or `STOP` signals) and `sys.stdin.readline()` in the child to receive them. This avoids shared-memory deadlocks and complex pipe handling.

### 3. Cleanup
Ensure the child process is terminated when the main GUI closes by sending a `"STOP"` command through `stdin` and calling `wait()`.

## Reference Implementation
See [pattern.md](references/pattern.md) for the complete boilerplate for `main.py`, the worker logic, and the UI-side spawning code.
