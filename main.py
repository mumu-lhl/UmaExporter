import multiprocessing
import os
import sys

# Packaged environment fixes - Top level to ensure all processes (parent/child) redirect logs
# Supports both PyInstaller (sys.frozen) and Nuitka (__compiled__)
is_frozen = getattr(sys, 'frozen', False) or "__compiled__" in globals()

if is_frozen:

    try:
        # For Nuitka/PyInstaller, sys.executable is the path to the binary
        _executable_dir = os.path.dirname(sys.executable)
        os.chdir(_executable_dir)
        # Use append mode ('a') to prevent child processes from truncating the log
        # Use line buffering (buffering=1) for real-time log updates
        sys.stderr = open("error.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = open("output.log", "a", encoding="utf-8", buffering=1)
    except Exception:
        pass

from src.ui.main_window import UmaExporterApp


def main():
    # Essential for frozen executables using multiprocessing
    multiprocessing.freeze_support()

    # Use 'spawn' to avoid GUI/OpenGL deadlocks in child processes on Linux
    try:
        multiprocessing.set_start_method("spawn", force=True)
    except RuntimeError:
        pass

    try:
        app = UmaExporterApp()
        app.run()

    except KeyboardInterrupt:
        print("\nExiting...")


if __name__ == "__main__":
    main()
