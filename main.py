import multiprocessing
import os
import sys

# Packaged environment fixes - Supports both PyInstaller (sys.frozen) and Nuitka (__compiled__)
is_frozen = getattr(sys, "frozen", False) or "__compiled__" in globals()

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
