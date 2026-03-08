import multiprocessing
import os
import sys

from src.utils import is_nuitka

# Fix archspec JSON discovery in Nuitka standalone builds.
# Must be set BEFORE importing any module that uses archspec.
if is_nuitka():
    _base_path = os.path.dirname(os.path.abspath(sys.argv[0]))
    _archspec_data = os.path.join(_base_path, "archspec", "json", "cpu")
    if os.path.exists(_archspec_data):
        os.environ["ARCHSPEC_CPU_DIR"] = _archspec_data

# Packaged environment fixes - Supports both PyInstaller (sys.frozen) and Nuitka (__compiled__)
is_frozen = getattr(sys, "frozen", False) or is_nuitka()

if is_frozen:
    try:
        _executable_dir = os.path.dirname(sys.executable)
        os.chdir(_executable_dir)
        # Append mode for logs
        sys.stderr = open("error.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = open("output.log", "a", encoding="utf-8", buffering=1)
    except Exception:
        pass

if __name__ == "__main__":
    # Essential for Windows standalone builds (Windows always uses 'spawn')
    multiprocessing.freeze_support()

    # Use 'spawn' to ensure sub-processes behave consistently across platforms (and with Nuitka)
    try:
        multiprocessing.set_start_method("spawn", force=True)
    except RuntimeError:
        pass

    # Import App here to ensure sub-processes (especially on Windows)
    # don't import the full UI logic unless they are the main process.
    from src.ui.main_window import UmaExporterApp

    try:
        app = UmaExporterApp()
        app.run()
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        print(f"Main App Error: {e}")
        if is_frozen:
            import traceback

            traceback.print_exc()
