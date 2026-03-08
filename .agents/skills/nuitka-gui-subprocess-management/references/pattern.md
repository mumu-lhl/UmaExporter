# Nuitka Subprocess & stdin Communication Pattern

This pattern is the most robust way to handle child processes (like a 3D viewer or worker) in a Nuitka-packaged GUI application without triggering duplicate windows or deadlocks.

## 1. Main Entry Point Guard (`main.py`)

Child processes must be intercepted at the absolute top of `main()`, before any GUI libraries are imported.

```python
import sys
import multiprocessing

def main():
    # 1. HARD INTERCEPT: Check for custom CLI flag
    if "--worker-flag" in sys.argv:
        from my_package.worker import run_worker
        run_worker()
        return

    # 2. Standard multiprocessing support (fallback)
    multiprocessing.freeze_support()
    
    # 3. Guard against duplicate MainProcess
    if multiprocessing.current_process().name != "MainProcess":
        return

    # 4. Proceed to GUI initialization
    from my_package.ui import App
    App().run()
```

## 2. Worker Implementation (`worker.py`)

The worker should read commands from `sys.stdin` and use `select` or a timer to avoid blocking its own internal loop (e.g., a rendering loop).

```python
import sys
import os
import select

def run_worker():
    # Setup your engine/viewer here...
    
    def on_timer():
        # Non-blocking check for new data from parent
        if select.select([sys.stdin], [], [], 0)[0]:
            line = sys.stdin.readline()
            if not line or line.strip() == "STOP":
                return False # Exit loop
            # Process the data
            process_path(line.strip())
        return True

    # Start your event loop with on_timer as a callback
    start_event_loop(callback=on_timer)
```

## 3. Parent Spawning Logic (`ui.py`)

Launch the child using `subprocess.Popen` and communicate via `stdin`.

```python
import subprocess
import sys

def ensure_worker_running(self):
    if self.worker_process is None or self.worker_process.poll() is not None:
        executable = sys.executable
        args = [executable]
        
        # Source vs Frozen handling
        if not getattr(sys, "frozen", False) and "__compiled__" not in globals():
            args.append(os.path.abspath(sys.argv[0]))
            
        args.append("--worker-flag")

        self.worker_process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1, # Line buffered
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )

def send_to_worker(self, data):
    if self.worker_process:
        self.worker_process.stdin.write(f"{data}\n")
        self.worker_process.stdin.flush()
```
