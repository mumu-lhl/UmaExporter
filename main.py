import multiprocessing
from src.ui.main_window import UmaExporterApp


def main():
    multiprocessing.freeze_support()

    import os
    import sys

    # Packaged environment fixes
    if getattr(sys, 'frozen', False):
        executable_dir = os.path.dirname(sys.executable)
        os.chdir(executable_dir)

        sys.stderr = open("error.log", "w", encoding="utf-8")
        sys.stdout = open("output.log", "w", encoding="utf-8")

    try:
        app = UmaExporterApp()
        app.run()

    except KeyboardInterrupt:
        print("\nExiting...")


if __name__ == "__main__":
    main()
