import multiprocessing
import os
import sys

# Packaged environment fixes - Top level to ensure all processes (parent/child) redirect logs
is_frozen = getattr(sys, 'frozen', False) or "__compiled__" in globals()

if is_frozen:
    try:
        _executable_dir = os.path.dirname(sys.executable)
        os.chdir(_executable_dir)
        sys.stderr = open("error.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = open("output.log", "a", encoding="utf-8", buffering=1)
    except Exception:
        pass

# Ensure sub-processes started via 'spawn' are intercepted before they reach main code
if __name__ == "__main__":
    multiprocessing.freeze_support()

    # Nuitka + spawn on Linux can sometimes skip freeze_support's exit if it's a resource_tracker.
    # We manually check sys.argv to see if this is a spawned child process or resource tracker.
    if is_frozen and any(arg in sys.argv for arg in ["--multiprocessing-fork", "-c"]):
        # This part should normally be handled by freeze_support(), 
        # but manual check helps if Nuitka/Python bootstrap is inconsistent.
        pass
    else:
        # Import App only in the main entry point to avoid overhead and double launches
        from src.ui.main_window import UmaExporterApp
        
        # Use 'spawn' to avoid GUI/OpenGL deadlocks in child processes on Linux
        try:
            multiprocessing.set_start_method('spawn', force=True)
        except RuntimeError:
            pass

        try:
            app = UmaExporterApp()
            app.run()
        except KeyboardInterrupt:
            print("\nExiting...")
        except Exception as e:
            print(f"Main App Error: {e}")
            import traceback
            traceback.print_exc()
