import os
import sys
import argparse

from src.core.utils import is_nuitka
from src.core.config import Config


def main():
    parser = argparse.ArgumentParser(description="Uma Musume Exporter")
    parser.add_argument("--f3d-viewer", action="store_true", help="Launch F3D viewer")
    parser.add_argument("--profile", action="store_true", help="Enable performance monitoring")
    
    args, unknown = parser.parse_known_args()

    # 1. HARD GUARD: Check for our custom viewer flag first.
    if args.f3d_viewer:
        from src.services.f3d.worker import launch_f3d_viewer_stdin

        try:
            launch_f3d_viewer_stdin()
        except KeyboardInterrupt:
            pass
        return

    # Set profile flag in config
    if args.profile:
        Config.PROFILE = True
        print("[INIT] Performance monitoring enabled.")

    # 2. Packaged environment fixes - Supports both PyInstaller (sys.frozen) and Nuitka
    is_frozen = getattr(sys, "frozen", False) or is_nuitka()

    if is_frozen:
        try:
            # Change to executable directory for relative paths (e.g., as_cli)
            _executable_dir = os.path.dirname(sys.executable)
            os.chdir(_executable_dir)
            
            # Only redirect logs if NOT profiling, so we can see output in console
            if not Config.PROFILE:
                sys.stderr = open("error.log", "a", encoding="utf-8", buffering=1)
                sys.stdout = open("output.log", "a", encoding="utf-8", buffering=1)
        except Exception:
            pass

    # Final guard before importing and running the App
    from src.ui.main_window import UmaExporterApp

    try:
        app = UmaExporterApp()
        app.run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Main App Error: {e}")
        if is_frozen:
            import traceback

            traceback.print_exc()


if __name__ == "__main__":
    main()
