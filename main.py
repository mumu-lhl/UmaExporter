import os
import sys

from src.core.utils import is_nuitka

# Fix archspec JSON discovery in Nuitka standalone builds.
# Must be set BEFORE importing any module that uses archspec.
if is_nuitka():
    _base_path = os.path.dirname(os.path.abspath(sys.argv[0]))
    _archspec_data = os.path.join(_base_path, "archspec", "json", "cpu")
    if os.path.exists(_archspec_data):
        os.environ["ARCHSPEC_CPU_DIR"] = _archspec_data


def main():
    # 1. HARD GUARD: Check for our custom viewer flag first.
    # This is 100% reliable for child processes in all packaged environments.
    if "--f3d-viewer" in sys.argv:
        from src.services.f3d.worker import launch_f3d_viewer_stdin

        launch_f3d_viewer_stdin()
        return

    # 2. Packaged environment fixes - Supports both PyInstaller (sys.frozen) and Nuitka
    is_frozen = getattr(sys, "frozen", False) or is_nuitka()

    if is_frozen:
        try:
            # Change to executable directory for relative paths (e.g., as_cli)
            _executable_dir = os.path.dirname(sys.executable)
            os.chdir(_executable_dir)
            # Redirect logs in frozen builds
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
